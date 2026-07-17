from __future__ import annotations

import hashlib
import html
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

ORG_ACTIVITY_URL = "https://huggingface.co/organizations/{name}/activity/all"
USER_ACTIVITY_URL = "https://huggingface.co/{name}/activity/all"

_ORG_PROPS_RE = re.compile(
    r'data-target="OrgProfile"\s+data-props="([^"]+)"'
)
_USER_PROPS_RE = re.compile(
    r'data-target="UserProfile"\s+data-props="([^"]+)"'
)

DEFAULT_TYPES = ("publish", "update", "collection", "paper")
ALL_KNOWN_TYPES = ("publish", "update", "collection", "paper", "discussion", "pr")


@dataclass(slots=True)
class ActivityEvent:
    event_key: str
    type: str
    time: str
    account: str
    kind: str
    user: str | None = None
    repo_id: str | None = None
    repo_type: str | None = None
    title: str | None = None
    url: str | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    def summary(self) -> str:
        target = self.repo_id or self.title or ""
        labels = {
            "publish": "发布",
            "update": "更新",
            "collection": "合集",
            "paper": "论文",
            "discussion": "讨论",
            "pr": "PR",
        }
        label = labels.get(self.type, self.type)
        if self.type in ("discussion", "pr") and self.title:
            return f"[{self.account}] {label} {target}\n{self.title}"
        if self.type in ("collection", "paper"):
            return f"[{self.account}] {label} {self.title or target}"
        if self.repo_type and target:
            return f"[{self.account}] {label} {self.repo_type} {target}"
        return f"[{self.account}] {label} {target}".rstrip()


@dataclass(slots=True)
class FeedSnapshot:
    account: str
    kind: str
    activities: list[ActivityEvent]
    cursor: str | None = None


class HFFeedError(Exception):
    pass


def _parse_props(html_text: str, kind: str) -> dict[str, Any]:
    pattern = _ORG_PROPS_RE if kind == "org" else _USER_PROPS_RE
    match = pattern.search(html_text)
    if not match:
        raise HFFeedError(f"page missing {kind} activity payload")
    try:
        return json.loads(html.unescape(match.group(1)))
    except json.JSONDecodeError as exc:
        raise HFFeedError(f"invalid {kind} activity json: {exc}") from exc


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _event_key(item: dict[str, Any], account: str) -> str:
    # 优先稳定字段；publish/update 通常没有 eventId
    if event_id := item.get("eventId"):
        return f"id:{event_id}"

    raw_type = str(item.get("type") or "unknown")
    if raw_type == "discussion":
        discussion = item.get("discussionData") or {}
        if discussion.get("isPullRequest"):
            raw_type = "pr"
        repo = discussion.get("repo") or {}
        repo_name = repo.get("name") or item.get("repoId") or ""
        num = discussion.get("num")
        if repo_name and num is not None:
            return f"{raw_type}:{repo_name}:{num}"

    if collection := item.get("collection") or {}:
        cid = collection.get("id") or collection.get("slug")
        if cid:
            return f"collection:{cid}"

    if paper := item.get("paper") or item.get("paperData") or {}:
        if isinstance(paper, dict):
            pid = paper.get("id") or paper.get("title")
            if pid:
                return f"paper:{pid}"

    repo_id = item.get("repoId") or ""
    if raw_type in ("publish", "update") and repo_id:
        # 同一 repo 的 update 用 lastModified/time 区分
        stamp = item.get("time") or ""
        repo_data = item.get("repoData") or {}
        if isinstance(repo_data, dict) and repo_data.get("lastModified"):
            stamp = str(repo_data.get("lastModified"))
        return f"{raw_type}:{repo_id}:{stamp}"

    digest = hashlib.sha1(
        json.dumps(
            {
                "t": item.get("type"),
                "time": item.get("time"),
                "repo": item.get("repoId"),
                "user": item.get("user"),
                "title": _event_title(item),
                "account": account,
            },
            sort_keys=True,
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()[:16]
    return f"h:{digest}"


def _event_title(item: dict[str, Any]) -> str | None:
    if discussion := item.get("discussionData"):
        return discussion.get("title")
    if collection := item.get("collection"):
        return collection.get("title")
    if paper := item.get("paper") or item.get("paperData"):
        if isinstance(paper, dict):
            return paper.get("title") or paper.get("id")
    if repo := item.get("repoData"):
        if isinstance(repo, dict):
            return repo.get("id")
    return item.get("repoId")


def _event_url(item: dict[str, Any], account: str) -> str | None:
    repo_id = item.get("repoId")
    repo_type = item.get("repoType")
    if repo_id and repo_type:
        base = {
            "model": "https://huggingface.co",
            "dataset": "https://huggingface.co/datasets",
            "space": "https://huggingface.co/spaces",
        }.get(str(repo_type), "https://huggingface.co")
        url = f"{base}/{repo_id}"
        if discussion := item.get("discussionData"):
            num = discussion.get("num")
            if num is not None:
                return f"{url}/discussions/{num}"
        return url
    if collection := item.get("collection"):
        if share := collection.get("shareUrl"):
            return share
        if slug := collection.get("slug"):
            return f"https://huggingface.co/collections/{slug}"
    return f"https://huggingface.co/{account}"


def _normalize_type(item: dict[str, Any]) -> str:
    raw_type = str(item.get("type") or "unknown")
    # HF 把 PR 也标成 discussion，真正标志在 isPullRequest
    if raw_type == "discussion":
        discussion = item.get("discussionData") or {}
        if discussion.get("isPullRequest"):
            return "pr"
    return raw_type


def normalize_activity(item: dict[str, Any], account: str, kind: str) -> ActivityEvent:
    return ActivityEvent(
        event_key=_event_key(item, account),
        type=_normalize_type(item),
        time=str(item.get("time") or ""),
        account=account,
        kind=kind,
        user=item.get("user"),
        repo_id=item.get("repoId"),
        repo_type=item.get("repoType"),
        title=_event_title(item),
        url=_event_url(item, account),
        raw=item,
    )


class HFFeedClient:
    def __init__(self, timeout: float = 30.0) -> None:
        self._timeout = timeout

    async def _get_html(self, url: str) -> str:
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
        }
        async with httpx.AsyncClient(
            timeout=self._timeout,
            follow_redirects=True,
            headers=headers,
        ) as client:
            resp = await client.get(url)
            if resp.status_code == 404:
                raise HFFeedError("account activity page not found")
            resp.raise_for_status()
            return resp.text

    async def fetch_kind(self, name: str, kind: str) -> FeedSnapshot:
        name = name.strip().strip("/")
        if not name:
            raise HFFeedError("empty account name")
        url = (ORG_ACTIVITY_URL if kind == "org" else USER_ACTIVITY_URL).format(name=name)
        html_text = await self._get_html(url)
        props = _parse_props(html_text, kind)
        activities = [
            normalize_activity(item, name, kind)
            for item in props.get("activities") or []
            if isinstance(item, dict)
        ]
        return FeedSnapshot(
            account=name,
            kind=kind,
            activities=activities,
            cursor=props.get("activityCursor"),
        )

    async def resolve_and_fetch(self, name: str, kind: str | None = None) -> FeedSnapshot:
        name = name.strip().strip("/")
        if kind in ("org", "user"):
            return await self.fetch_kind(name, kind)

        errors: list[str] = []
        for candidate in ("org", "user"):
            try:
                return await self.fetch_kind(name, candidate)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{candidate}: {exc}")
        raise HFFeedError("; ".join(errors) or f"cannot resolve account {name}")
