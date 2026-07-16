from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import nonebot_plugin_localstore as store

from .client import DEFAULT_TYPES

_SEEN_LIMIT = 500
_lock = threading.Lock()


def _path() -> Path:
    data_dir = store.get_plugin_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "watches.json"


def _default_data() -> dict[str, Any]:
    return {
        "enabled": True,
        "interval_minutes": 10,
        "watches": {},
    }


def load() -> dict[str, Any]:
    path = _path()
    with _lock:
        if not path.exists():
            data = _default_data()
            path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return data
        try:
            text = path.read_text(encoding="utf-8")
            data = json.loads(text) if text.strip() else _default_data()
        except (json.JSONDecodeError, OSError):
            data = _default_data()
        data.setdefault("enabled", True)
        data.setdefault("interval_minutes", 10)
        data.setdefault("watches", {})
        return data


def save(data: dict[str, Any]) -> None:
    path = _path()
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def list_watches() -> dict[str, dict[str, Any]]:
    return dict(load().get("watches") or {})


def get_watch(name: str) -> dict[str, Any] | None:
    return list_watches().get(name.lower())


def add_watch(
    name: str,
    *,
    kind: str,
    group_id: int,
    types: list[str] | None = None,
    seen: list[str] | None = None,
) -> dict[str, Any]:
    key = name.strip().lower()
    data = load()
    watches: dict[str, Any] = data.setdefault("watches", {})
    item = watches.get(key) or {
        "name": name.strip(),
        "kind": kind,
        "types": list(types or DEFAULT_TYPES),
        "groups": [],
        "seen": [],
        "bootstrapped": False,
        "last_check": None,
        "last_error": None,
        "last_new": 0,
    }
    item["name"] = name.strip()
    item["kind"] = kind
    if types is not None:
        item["types"] = list(types)
    groups = list(item.get("groups") or [])
    if group_id not in groups:
        groups.append(group_id)
    item["groups"] = groups
    if seen is not None:
        item["seen"] = list(seen)[-_SEEN_LIMIT:]
    watches[key] = item
    save(data)
    return item


def remove_watch(name: str, group_id: int | None = None) -> bool:
    key = name.strip().lower()
    data = load()
    watches: dict[str, Any] = data.setdefault("watches", {})
    item = watches.get(key)
    if not item:
        return False
    if group_id is None:
        del watches[key]
        save(data)
        return True
    groups = [g for g in (item.get("groups") or []) if g != group_id]
    if not groups:
        del watches[key]
    else:
        item["groups"] = groups
        watches[key] = item
    save(data)
    return True


def update_watch(name: str, **fields: Any) -> dict[str, Any] | None:
    key = name.strip().lower()
    data = load()
    watches: dict[str, Any] = data.setdefault("watches", {})
    item = watches.get(key)
    if not item:
        return None
    item.update(fields)
    if "seen" in fields and isinstance(item.get("seen"), list):
        item["seen"] = item["seen"][-_SEEN_LIMIT:]
    watches[key] = item
    save(data)
    return item


def set_enabled(enabled: bool) -> None:
    data = load()
    data["enabled"] = enabled
    save(data)


def is_enabled() -> bool:
    return bool(load().get("enabled", True))


def interval_minutes() -> int:
    try:
        value = int(load().get("interval_minutes", 10))
    except (TypeError, ValueError):
        value = 10
    return max(5, value)
