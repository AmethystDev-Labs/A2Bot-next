from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set
import json

# 你指定要用 curl_cffi/chrome
try:
    from curl_cffi import requests as curl_requests  # type: ignore
except Exception:  # pragma: no cover
    curl_requests = None


@dataclass(frozen=True)
class NodeStat:
    id: int
    node_name: str
    nodegroup: str
    state: str  # online / offline / ...
    cur_counts: Optional[int] = None
    client_counts: Optional[int] = None
    tunnel_counts: Optional[int] = None

    cpu_usage: Optional[float] = None
    bandwidth_usage_percent: Optional[float] = None
    current_upload_usage_percent: Optional[float] = None

    total_traffic_in: Optional[int] = None
    total_traffic_out: Optional[int] = None

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "NodeStat":
        return NodeStat(
            id=int(d.get("id", 0)),
            node_name=str(d.get("node_name", "")),
            nodegroup=str(d.get("nodegroup", "")),
            state=str(d.get("state", "")),
            cur_counts=(d.get("cur_counts") if isinstance(d.get("cur_counts"), int) else None),
            client_counts=(d.get("client_counts") if isinstance(d.get("client_counts"), int) else None),
            tunnel_counts=(d.get("tunnel_counts") if isinstance(d.get("tunnel_counts"), int) else None),
            cpu_usage=(d.get("cpu_usage") if isinstance(d.get("cpu_usage"), (int, float)) else None),
            bandwidth_usage_percent=(
                d.get("bandwidth_usage_percent")
                if isinstance(d.get("bandwidth_usage_percent"), (int, float))
                else None
            ),
            current_upload_usage_percent=(
                d.get("current_upload_usage_percent")
                if isinstance(d.get("current_upload_usage_percent"), (int, float))
                else None
            ),
            total_traffic_in=(d.get("total_traffic_in") if isinstance(d.get("total_traffic_in"), int) else None),
            total_traffic_out=(d.get("total_traffic_out") if isinstance(d.get("total_traffic_out"), int) else None),
        )


class Client:
    """
    chmlfrp status sdk (ONLY status api)

    用法：
        from chmlfrp import Client
        c = Client().refresh()

        print(c.total, c.online, c.offline)
        print(c.msg, c.code, c.state)
        print(c.getAllGroups())
        print([n.node_name for n in c.getOfflineNodes()])
    """

    DEFAULT_URL = "https://cf-v2.uapis.cn/node_stats"

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
        self._nodes: List[NodeStat] = []

        if data is not None:
            self._load(data)
        elif auto_refresh:
            self.refresh()

    # -----------------------
    # fetch / load
    # -----------------------
    def refresh(self) -> "Client":
        if curl_requests is None:
            raise RuntimeError("curl_cffi 未安装。请先 pip install curl-cffi")

        r = curl_requests.get(
            self._url,
            timeout=self._timeout_s,
            impersonate=self._impersonate,
            headers={"accept": "application/json", "cache-control": "no-cache"},
        )
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, dict):
            raise ValueError("API response must be a JSON object")

        self._load(data)
        return self

    def _load(self, data: Dict[str, Any]) -> None:
        self._raw = data

        arr = data.get("data", [])
        if not isinstance(arr, list):
            raise ValueError('response["data"] must be a list')

        self._nodes = [NodeStat.from_dict(x) for x in arr if isinstance(x, dict)]

    # -----------------------
    # sdk-ish properties
    # -----------------------
    @property
    def msg(self) -> Optional[str]:
        v = self._raw.get("msg")
        return v if isinstance(v, str) else None

    @property
    def code(self) -> Optional[int]:
        v = self._raw.get("code")
        return v if isinstance(v, int) else None

    @property
    def state(self) -> Optional[str]:
        v = self._raw.get("state")
        return v if isinstance(v, str) else None

    @property
    def total(self) -> int:
        return len(self._nodes)

    @property
    def online(self) -> int:
        return sum(1 for n in self._nodes if n.state.lower() == "online")

    @property
    def offline(self) -> int:
        # 不是 online 都算 offline（更实用）
        return self.total - self.online

    # -----------------------
    # sdk-ish getters
    # -----------------------
    def nodes(self) -> List[NodeStat]:
        return list(self._nodes)

    def getAllGroups(self) -> List[str]:
        groups: Set[str] = {n.nodegroup for n in self._nodes if n.nodegroup}
        return sorted(groups)

    def getNodesByGroup(self, group: str) -> List[NodeStat]:
        g = group.strip().lower()
        return [n for n in self._nodes if n.nodegroup.lower() == g]

    def getNodesByState(self, state: str) -> List[NodeStat]:
        s = state.strip().lower()
        return [n for n in self._nodes if n.state.lower() == s]

    def getOnlineNodes(self) -> List[NodeStat]:
        return self.getNodesByState("online")

    def getOfflineNodes(self) -> List[NodeStat]:
        # 不是 online 都算 offline
        return [n for n in self._nodes if n.state.lower() != "online"]

    def raw(self) -> Dict[str, Any]:
        return dict(self._raw)
