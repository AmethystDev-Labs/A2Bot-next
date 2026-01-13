from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

# --- 可选依赖：curl_cffi（你指定要用） ---
try:
    from curl_cffi import requests as curl_requests  # type: ignore
except Exception:  # pragma: no cover
    curl_requests = None


def _parse_iso_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
        # 保证 tz-aware
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Provider:
    id: str
    name: str
    type: str
    model: str
    group: str
    endpoint: str

    latest_status: Optional[str] = None
    latest_latency_ms: Optional[int] = None
    latest_ping_latency_ms: Optional[int] = None
    latest_checked_at: Optional[datetime] = None
    latest_message: Optional[str] = None

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Provider":
        latest = d.get("latest") or {}
        return Provider(
            id=str(d.get("id", "")),
            name=str(d.get("name", "")),
            type=str(d.get("type", "")),
            model=str(d.get("model", "")),
            group=str(d.get("group", "")),
            endpoint=str(d.get("endpoint", "")),
            latest_status=(latest.get("status") if isinstance(latest, dict) else None),
            latest_latency_ms=(latest.get("latencyMs") if isinstance(latest, dict) else None),
            latest_ping_latency_ms=(latest.get("pingLatencyMs") if isinstance(latest, dict) else None),
            latest_checked_at=_parse_iso_dt(latest.get("checkedAt") if isinstance(latest, dict) else None),
            latest_message=(latest.get("message") if isinstance(latest, dict) else None),
        )


class LinuxDoStatusClient:
    """
    SDK-ish client for https://check.linux.do/api/v1/status

    - 数值/元数据：用属性 .total .operational .generatedAt ...
    - 列表/字典：用方法 getAllGroups() / getOfflineModels() ...
    """

    DEFAULT_URL = "https://check.linux.do/api/v1/status"

    # 你之前定义的概念我保留，并做了可调的集合
    DEGRADED_STATUSES: Set[str] = {"degraded"}
    # “离线”通常你会想把这些算进去；另外 error 不在 summary 里时会单独暴露 .error
    OFFLINE_STATUSES: Set[str] = {"failed", "validationfailed", "maintenance"}

    def __init__(
        self,
        url: str = DEFAULT_URL,
        timeout_s: float = 15.0,
        impersonate: str = "chrome",
        auto_refresh: bool = True,
        data: Optional[Dict[str, Any]] = None,
    ):
        self._url = url
        self._timeout_s = timeout_s
        self._impersonate = impersonate

        self._raw: Dict[str, Any] = {}
        self._providers: List[Provider] = []
        self._providers_raw_by_id: Dict[str, Dict[str, Any]] = {}
        self._fetched_at: Optional[datetime] = None

        if data is not None:
            self._load(data)
        elif auto_refresh:
            self.refresh()

    # -----------------------
    # 网络 / 载入
    # -----------------------
    def refresh(self) -> "LinuxDoStatusClient":
        if curl_requests is None:
            raise RuntimeError(
                "curl_cffi 未安装。请先 pip install curl-cffi\n"
                "或把 data=... 传进来离线使用。"
            )

        r = curl_requests.get(
            self._url,
            timeout=self._timeout_s,
            impersonate=self._impersonate,  # chrome impersonate
            headers={"accept": "application/json", "cache-control": "no-cache"},
        )
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, dict):
            raise ValueError("API response must be a JSON object")

        self._load(data)
        return self

    def refreshIfNeeded(self) -> "LinuxDoStatusClient":
        """按 metadata.pollIntervalMs 判断是否过期；过期才 refresh。"""
        if self.isStale:
            return self.refresh()
        return self

    def _load(self, data: Dict[str, Any]) -> None:
        self._raw = data

        providers = data.get("providers", [])
        if not isinstance(providers, list):
            raise ValueError('response["providers"] must be a list')

        self._providers_raw_by_id = {
            str(p.get("id", "")): p for p in providers if isinstance(p, dict) and p.get("id")
        }
        self._providers = [Provider.from_dict(p) for p in providers if isinstance(p, dict)]
        self._fetched_at = _now_utc()

    # -----------------------
    # SDK 属性：summary / metadata
    # -----------------------
    @property
    def total(self) -> int:
        v = (self._raw.get("summary") or {}).get("total")
        return v if isinstance(v, int) else len(self._providers)

    @property
    def operational(self) -> int:
        v = (self._raw.get("summary") or {}).get("operational")
        if isinstance(v, int):
            return v
        return self.statusCounts.get("operational", 0)

    @property
    def degraded(self) -> int:
        v = (self._raw.get("summary") or {}).get("degraded")
        if isinstance(v, int):
            return v
        return self.statusCounts.get("degraded", 0)

    @property
    def failed(self) -> int:
        v = (self._raw.get("summary") or {}).get("failed")
        if isinstance(v, int):
            return v
        return self.statusCounts.get("failed", 0)

    @property
    def validationFailed(self) -> int:
        v = (self._raw.get("summary") or {}).get("validationFailed")
        if isinstance(v, int):
            return v
        return self.statusCounts.get("validationfailed", 0)

    @property
    def maintenance(self) -> int:
        v = (self._raw.get("summary") or {}).get("maintenance")
        if isinstance(v, int):
            return v
        return self.statusCounts.get("maintenance", 0)

    @property
    def avgLatencyMs(self) -> Optional[int]:
        v = (self._raw.get("summary") or {}).get("avgLatencyMs")
        return v if isinstance(v, int) else None

    @property
    def generatedAt(self) -> Optional[datetime]:
        dt = (self._raw.get("metadata") or {}).get("generatedAt")
        return _parse_iso_dt(dt if isinstance(dt, str) else None)

    @property
    def generatedAtString(self) -> Optional[str]:
        s = (self._raw.get("metadata") or {}).get("generatedAt")
        return s if isinstance(s, str) else None

    @property
    def pollIntervalMs(self) -> Optional[int]:
        v = (self._raw.get("metadata") or {}).get("pollIntervalMs")
        return v if isinstance(v, int) else None

    @property
    def pollIntervalLabel(self) -> Optional[str]:
        v = (self._raw.get("metadata") or {}).get("pollIntervalLabel")
        return v if isinstance(v, str) else None

    @property
    def fetchedAt(self) -> Optional[datetime]:
        """本地拉取时间（不是接口 generatedAt）。"""
        return self._fetched_at

    @property
    def isStale(self) -> bool:
        """
        依据 generatedAt + pollIntervalMs 判断是否过期：
        - 没 metadata 就当 stale（更安全）
        """
        gen = self.generatedAt
        interval = self.pollIntervalMs
        if gen is None or interval is None:
            return True
        return (_now_utc() - gen).total_seconds() * 1000 > interval

    # -----------------------
    # 扩展：状态统计 & “error”这种 summary 没给的状态
    # -----------------------
    @property
    def statusCounts(self) -> Dict[str, int]:
        """
        从 providers.latest.status 直接统计（比 summary 更“全”）
        例如：operational / degraded / error / failed / ...
        """
        counts: Dict[str, int] = {}
        for p in self._providers:
            k = (p.latest_status or "unknown").strip().lower()
            counts[k] = counts.get(k, 0) + 1
        return counts

    @property
    def error(self) -> int:
        """接口 summary 里不一定有 error，这里从 providers 计算。"""
        return self.statusCounts.get("error", 0)

    @property
    def offline(self) -> int:
        """
        “离线”综合数：failed + validationFailed + maintenance + error
        （你也可以按自己口味改 OFFLINE_STATUSES / 规则）
        """
        return self.failed + self.validationFailed + self.maintenance + self.error

    # -----------------------
    # SDK 方法：group/model/provider 查询
    # -----------------------
    def providers(self) -> List[Provider]:
        return list(self._providers)

    def getProvider(self, key: str) -> Optional[Provider]:
        """按 id 或 name 精确匹配（大小写不敏感）。"""
        k = key.strip().lower()
        for p in self._providers:
            if p.id.lower() == k or p.name.lower() == k:
                return p
        return None

    def __getitem__(self, key: str) -> Provider:
        p = self.getProvider(key)
        if p is None:
            raise KeyError(f"provider not found: {key}")
        return p

    def getProviderRaw(self, provider_id: str) -> Optional[Dict[str, Any]]:
        """拿原始 provider dict（含 statistics / timeline）。"""
        return self._providers_raw_by_id.get(provider_id)

    def getAllGroups(self) -> List[str]:
        groups = {p.group for p in self._providers if p.group}
        return sorted(groups)

    def getAllTypes(self) -> List[str]:
        types_ = {p.type for p in self._providers if p.type}
        return sorted(types_)

    def getAllModels(self, by_group: bool = True) -> Dict[str, List[str]] | List[str]:
        if not by_group:
            models = {p.model for p in self._providers if p.model}
            return sorted(models)

        m: Dict[str, Set[str]] = {}
        for p in self._providers:
            if p.group and p.model:
                m.setdefault(p.group, set()).add(p.model)
        return {g: sorted(models) for g, models in sorted(m.items(), key=lambda x: x[0].lower())}

    def getModelsByGroup(self, group: str) -> List[str]:
        g = group.strip().lower()
        models = {p.model for p in self._providers if p.group.lower() == g and p.model}
        return sorted(models)

    def getProvidersByGroup(self, group: str) -> List[Provider]:
        g = group.strip().lower()
        return [p for p in self._providers if p.group.lower() == g]

    def getProvidersByModel(self, model: str) -> List[Provider]:
        m = model.strip().lower()
        return [p for p in self._providers if p.model.lower() == m]

    def getProvidersByStatus(self, status: str) -> List[Provider]:
        s = status.strip().lower()
        return [p for p in self._providers if (p.latest_status or "").lower() == s]

    # -----------------------
    # 你要的：离线/降级 models（保持原来的返回风格）
    # -----------------------
    def getDegradedModels(self, by_group: bool = True) -> Dict[str, List[str]] | List[str]:
        return self._models_by_status(self.DEGRADED_STATUSES, by_group=by_group)

    def getOfflineModels(self, by_group: bool = True) -> Dict[str, List[str]] | List[str]:
        # offline = OFFLINE_STATUSES + {"error"}（更符合你想要的直觉）
        statuses = set(self.OFFLINE_STATUSES) | {"error"}
        return self._models_by_status(statuses, by_group=by_group)

    def _models_by_status(self, statuses: Set[str], by_group: bool) -> Dict[str, List[str]] | List[str]:
        statuses_l = {s.lower() for s in statuses}

        def hit(p: Provider) -> bool:
            return (p.latest_status or "").lower() in statuses_l

        if not by_group:
            models = {p.model for p in self._providers if p.model and hit(p)}
            return sorted(models)

        m: Dict[str, Set[str]] = {}
        for p in self._providers:
            if p.group and p.model and hit(p):
                m.setdefault(p.group, set()).add(p.model)

        return {g: sorted(models) for g, models in sorted(m.items(), key=lambda x: x[0].lower())}

    # -----------------------
    # 额外：快/慢、分组汇总（很 SDK 常用）
    # -----------------------
    def getFastestProviders(self, n: int = 5) -> List[Provider]:
        def key(p: Provider) -> Tuple[int, int]:
            return (0 if p.latest_latency_ms is not None else 1, p.latest_latency_ms or 10**18)

        return sorted(self._providers, key=key)[: max(0, int(n))]

    def getSlowestProviders(self, n: int = 5) -> List[Provider]:
        def key(p: Provider) -> Tuple[int, int]:
            return (0 if p.latest_latency_ms is not None else 1, -(p.latest_latency_ms or -10**18))

        return sorted(self._providers, key=key)[: max(0, int(n))]

    def getGroupSummary(self) -> Dict[str, Dict[str, int]]:
        """
        返回：
        {
          "Packy": {"total": 10, "operational": 8, "degraded": 1, "error": 1, ...},
          ...
        }
        """
        out: Dict[str, Dict[str, int]] = {}
        for p in self._providers:
            g = p.group or "unknown"
            st = (p.latest_status or "unknown").lower()
            out.setdefault(g, {"total": 0})
            out[g]["total"] += 1
            out[g][st] = out[g].get(st, 0) + 1
        # 排序输出（可读性更像 SDK）
        return {g: out[g] for g in sorted(out.keys(), key=lambda x: x.lower())}

    # -----------------------
    # 原始数据（调试用）
    # -----------------------
    def raw(self) -> Dict[str, Any]:
        return dict(self._raw)
