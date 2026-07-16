from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from typing import Any, cast

from nonebot import get_bot, get_driver, logger, on_command, require
from nonebot.adapters.onebot.v11 import (
    Bot as V11Bot,
    GROUP_ADMIN,
    GROUP_OWNER,
    GroupMessageEvent,
    Message,
)
from nonebot.params import CommandArg
from nonebot.permission import Permission, SUPERUSER
from nonebot.plugin import PluginMetadata

require("nonebot_plugin_apscheduler")
require("nonebot_plugin_localstore")

from nonebot_plugin_apscheduler import scheduler

from .client import (
    ALL_KNOWN_TYPES,
    DEFAULT_TYPES,
    ActivityEvent,
    HFFeedClient,
    HFFeedError,
)
from . import store

__plugin_meta__ = PluginMetadata(
    name="hf_feed",
    description="监控 HuggingFace Org/User Activity Feed",
    usage="hf:help",
)

MAIN_CMD = "hf"
PERM: Permission = GROUP_ADMIN | GROUP_OWNER | SUPERUSER

HELP_TEXT = f"""\
{MAIN_CMD}:help
{MAIN_CMD}:status
{MAIN_CMD}:add <account> [org|user] [types]
{MAIN_CMD}:rm <account>
{MAIN_CMD}:list
{MAIN_CMD}:get <account> [org|user] [n]

types 默认 {','.join(DEFAULT_TYPES)}
可选 {','.join(ALL_KNOWN_TYPES)}
"""

feed_client = HFFeedClient()
_poll_lock = asyncio.Lock()


def _parse_types(raw: str | None) -> list[str]:
    if not raw:
        return list(DEFAULT_TYPES)
    types = [part.strip().lower() for part in raw.replace("，", ",").split(",") if part.strip()]
    invalid = [t for t in types if t not in ALL_KNOWN_TYPES and t != "*"]
    if invalid:
        raise ValueError(f"未知类型：{', '.join(invalid)}")
    if "*" in types:
        return list(ALL_KNOWN_TYPES)
    return types


def _format_event(event: ActivityEvent) -> str:
    if event.url:
        return f"{event.summary()}\n{event.url}"
    return event.summary()


def _make_forward_nodes(bot: V11Bot, chunks: list[str], name: str = "HF Feed") -> list[dict[str, Any]]:
    return [
        {
            "type": "node",
            "data": {
                "name": name,
                "uin": str(bot.self_id),
                "content": chunk,
            },
        }
        for chunk in chunks
    ]


async def _send_forward(bot: V11Bot, group_id: int, chunks: list[str], name: str = "HF Feed") -> None:
    nodes = _make_forward_nodes(bot, chunks, name=name)
    await bot.call_api("send_group_forward_msg", group_id=group_id, messages=nodes)


async def _notify_groups(group_ids: list[int], text: str) -> None:
    try:
        bot = cast(V11Bot, get_bot())
    except Exception:
        logger.warning("hf_feed: no bot connected, skip notify")
        return
    for group_id in group_ids:
        try:
            await _send_forward(bot, group_id, [text])
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"hf_feed notify group {group_id} failed: {exc}")


async def _bootstrap_seen(name: str, kind: str | None) -> tuple[str, list[str], list[ActivityEvent]]:
    snap = await feed_client.resolve_and_fetch(name, kind)
    seen = [event.event_key for event in snap.activities]
    return snap.kind, seen, snap.activities


async def poll_once(force: bool = False) -> dict[str, int]:
    if not force and not store.is_enabled():
        return {"accounts": 0, "new": 0, "errors": 0}

    if _poll_lock.locked():
        return {"accounts": 0, "new": 0, "errors": 0, "skipped": 1}

    async with _poll_lock:
        watches = store.list_watches()
        stats = {"accounts": 0, "new": 0, "errors": 0}
        for key, item in watches.items():
            stats["accounts"] += 1
            name = item.get("name") or key
            kind = item.get("kind")
            allow = set(item.get("types") or DEFAULT_TYPES)
            seen = list(item.get("seen") or [])
            seen_set = set(seen)
            groups = list(item.get("groups") or [])
            try:
                snap = await feed_client.resolve_and_fetch(
                    name, kind if kind in ("org", "user") else None
                )
                current_keys = [event.event_key for event in snap.activities]

                # 无基线：只记 seen，不推送任何已有动态（含启动前历史）
                if not seen:
                    store.update_watch(
                        name,
                        kind=snap.kind,
                        seen=current_keys[:500],
                        last_check=datetime.now(timezone.utc).isoformat(),
                        last_error=None,
                        last_new=0,
                        bootstrapped=True,
                    )
                    logger.info(f"hf_feed bootstrap {name}: {len(current_keys)} events, no notify")
                    await asyncio.sleep(1.0)
                    continue

                fresh = [
                    event
                    for event in snap.activities
                    if event.event_key not in seen_set and event.type in allow
                ]
                # activities are newest-first; notify oldest-new first
                fresh.reverse()
                for event in fresh:
                    await _notify_groups(groups, _format_event(event))
                    await asyncio.sleep(0.3)

                merged: list[str] = []
                for event_key in current_keys + seen:
                    if event_key not in merged:
                        merged.append(event_key)
                store.update_watch(
                    name,
                    kind=snap.kind,
                    seen=merged[:500],
                    last_check=datetime.now(timezone.utc).isoformat(),
                    last_error=None,
                    last_new=len(fresh),
                    bootstrapped=True,
                )
                stats["new"] += len(fresh)
            except Exception as exc:  # noqa: BLE001
                stats["errors"] += 1
                store.update_watch(
                    name,
                    last_check=datetime.now(timezone.utc).isoformat(),
                    last_error=str(exc),
                )
                logger.warning(f"hf_feed poll {name} failed: {exc}")
            await asyncio.sleep(1.0)
        return stats


cmd_help = on_command(f"{MAIN_CMD}:help", aliases={"hf:帮助"}, priority=5, block=True, permission=PERM)


@cmd_help.handle()
async def handle_help():
    await cmd_help.finish(HELP_TEXT)


cmd_status = on_command(f"{MAIN_CMD}:status", aliases={"hf:状态"}, priority=5, block=True, permission=PERM)


@cmd_status.handle()
async def handle_status(event: GroupMessageEvent):
    watches = [
        item
        for item in store.list_watches().values()
        if event.group_id in (item.get("groups") or [])
    ]
    lines = [
        f"轮询：{'开' if store.is_enabled() else '关'} / {store.interval_minutes()}min",
        f"本群：{len(watches)}",
    ]
    for item in watches[:10]:
        mark = " !" if item.get("last_error") else ""
        lines.append(f"- {item.get('name')}{mark}")
    await cmd_status.finish("\n".join(lines))


cmd_add = on_command(f"{MAIN_CMD}:add", aliases={"hf:watch"}, priority=5, block=True, permission=PERM)


@cmd_add.handle()
async def handle_add(event: GroupMessageEvent, args: Message = CommandArg()):
    parts = args.extract_plain_text().strip().split()
    if not parts:
        await cmd_add.finish(f"{MAIN_CMD}:add <account> [org|user] [types]")

    name = parts[0].strip().strip("/")
    kind_arg: str | None = None
    types_arg: str | None = None
    for part in parts[1:]:
        low = part.lower()
        if low in ("org", "user", "auto"):
            kind_arg = None if low == "auto" else low
        else:
            types_arg = part

    try:
        types = _parse_types(types_arg)
    except ValueError as exc:
        await cmd_add.finish(str(exc))

    existing = store.get_watch(name)
    if existing:
        store.add_watch(
            existing.get("name") or name,
            kind=existing.get("kind") or kind_arg or "org",
            group_id=event.group_id,
            types=types,
        )
        await cmd_add.finish(f"已添加 {existing.get('name') or name}")

    try:
        kind, seen, _activities = await _bootstrap_seen(name, kind_arg)
    except HFFeedError as exc:
        await cmd_add.finish(f"失败：{exc}")
    except Exception as exc:  # noqa: BLE001
        await cmd_add.finish(f"失败：{exc}")

    store.add_watch(
        name,
        kind=kind,
        group_id=event.group_id,
        types=types,
        seen=seen,
    )
    store.update_watch(name, bootstrapped=True)
    await cmd_add.finish(f"已添加 {name}")


cmd_rm = on_command(
    f"{MAIN_CMD}:rm",
    aliases={"hf:remove", "hf:del", "hf:unwatch"},
    priority=5, block=True, permission=PERM,
)


@cmd_rm.handle()
async def handle_rm(event: GroupMessageEvent, args: Message = CommandArg()):
    name = args.extract_plain_text().strip().split()
    if not name:
        await cmd_rm.finish(f"{MAIN_CMD}:rm <account>")
    account = name[0].strip().strip("/")
    ok = store.remove_watch(account, group_id=event.group_id)
    if not ok:
        await cmd_rm.finish(f"未监控 {account}")
    await cmd_rm.finish(f"已移除 {account}")


cmd_list = on_command(f"{MAIN_CMD}:list", aliases={"hf:ls"}, priority=5, block=True, permission=PERM)


@cmd_list.handle()
async def handle_list(event: GroupMessageEvent):
    watches = [
        item
        for item in store.list_watches().values()
        if event.group_id in (item.get("groups") or [])
    ]
    if not watches:
        await cmd_list.finish("无")
    await cmd_list.finish("\n".join(str(item.get("name")) for item in watches))


cmd_get = on_command(f"{MAIN_CMD}:get", priority=5, block=True, permission=PERM)


@cmd_get.handle()
async def handle_get(bot: V11Bot, event: GroupMessageEvent, args: Message = CommandArg()):
    parts = args.extract_plain_text().strip().split()
    if not parts:
        await cmd_get.finish(f"{MAIN_CMD}:get <account> [org|user] [n]")

    name = parts[0].strip().strip("/")
    kind_arg: str | None = None
    limit = 5
    for part in parts[1:]:
        low = part.lower()
        if low in ("org", "user"):
            kind_arg = low
        elif low.isdigit():
            limit = max(1, min(int(low), 20))

    try:
        snap = await feed_client.resolve_and_fetch(name, kind_arg)
    except HFFeedError as exc:
        await cmd_get.finish(f"失败：{exc}")
    except Exception as exc:  # noqa: BLE001
        await cmd_get.finish(f"失败：{exc}")

    if not snap.activities:
        await cmd_get.finish("无")

    chunks = [_format_event(ev) for ev in snap.activities[:limit]]
    try:
        await _send_forward(bot, event.group_id, chunks, name=f"HF {name}")
    except Exception as exc:  # noqa: BLE001
        await cmd_get.finish(f"失败：{exc}")
    await cmd_get.finish()


async def _scheduled_poll():
    try:
        stats = await poll_once()
        if stats.get("new") or stats.get("errors"):
            logger.info(f"hf_feed poll: {stats}")
    except Exception as exc:  # noqa: BLE001
        logger.exception(f"hf_feed scheduled poll failed: {exc}")


@get_driver().on_startup
async def _on_startup():
    if not scheduler.get_job("hf_feed_poll"):
        scheduler.add_job(
            _scheduled_poll,
            "interval",
            minutes=store.interval_minutes(),
            id="hf_feed_poll",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
    logger.info("hf_feed plugin loaded")
