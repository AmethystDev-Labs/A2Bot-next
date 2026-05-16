"""
writer: Claude Sonnet 4.6

基于 nonebot-plugin-localstore 封装的 JSON 配置管理器
支持分群配置与全局配置
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import nonebot_plugin_localstore as store


class ConfigManager:
    """
    JSON 配置管理器，支持分群配置与全局配置。

    Usage::

        # 分群配置
        config = ConfigManager(group_id="123456")
        config.set("key", "value")
        val = config.get("key", default="fallback")

        # 全局配置
        global_config = ConfigManager(group_id=None)
        global_config.set("global_key", True)

        # 批量更新
        config.update({"a": 1, "b": 2})

        # 删除某项
        config.delete("key")

        # 获取全部配置
        all_cfg = config.all()

        # 重置（清空）配置
        config.reset()
    """

    _GLOBAL_FILENAME = "global_config.json"
    _GROUP_DIR = "groups"

    def __init__(self, group_id: str | int | None = None) -> None:
        """
        初始化配置管理器。

        :param group_id: 群号字符串或整数；传 None 表示全局配置。
        """
        self._group_id = str(group_id) if group_id is not None else None
        self._config_path = self._resolve_path()
        self._ensure_file()

    # ------------------------------------------------------------------
    # 路径解析
    # ------------------------------------------------------------------

    def _resolve_path(self) -> Path:
        """根据 group_id 决定配置文件路径。"""
        data_dir: Path = store.get_data_dir("config_manager")

        if self._group_id is None:
            return data_dir / self._GLOBAL_FILENAME
        else:
            group_dir = data_dir / self._GROUP_DIR
            group_dir.mkdir(parents=True, exist_ok=True)
            return group_dir / f"{self._group_id}.json"

    def _ensure_file(self) -> None:
        """若配置文件不存在则创建空 JSON 文件。"""
        if not self._config_path.exists():
            self._config_path.parent.mkdir(parents=True, exist_ok=True)
            self._write({})

    # ------------------------------------------------------------------
    # 底层读写
    # ------------------------------------------------------------------

    def _read(self) -> dict[str, Any]:
        """读取并解析 JSON 文件，容错处理损坏文件。"""
        try:
            text = self._config_path.read_text(encoding="utf-8")
            return json.loads(text) if text.strip() else {}
        except (json.JSONDecodeError, OSError):
            return {}

    def _write(self, data: dict[str, Any]) -> None:
        """将数据序列化写入 JSON 文件（带缩进，便于阅读）。"""
        self._config_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        """
        获取配置项。

        :param key: 配置键。
        :param default: 键不存在时返回的默认值，默认为 None。
        :return: 配置值或默认值。
        """
        return self._read().get(key, default)

    def set(self, key: str, value: Any) -> None:
        """
        设置（覆盖）单个配置项。

        :param key: 配置键。
        :param value: 配置值（须可被 JSON 序列化）。
        """
        data = self._read()
        data[key] = value
        self._write(data)

    def update(self, mapping: dict[str, Any]) -> None:
        """
        批量更新配置项（浅合并）。

        :param mapping: 要写入的键值对字典。
        """
        data = self._read()
        data.update(mapping)
        self._write(data)

    def delete(self, key: str) -> bool:
        """
        删除某个配置项。

        :param key: 要删除的键。
        :return: 键存在并成功删除返回 True，键不存在返回 False。
        """
        data = self._read()
        if key not in data:
            return False
        del data[key]
        self._write(data)
        return True

    def all(self) -> dict[str, Any]:
        """
        返回当前作用域的全部配置项（副本）。
        """
        return dict(self._read())

    def reset(self) -> None:
        """
        清空当前作用域的所有配置项（保留文件）。
        """
        self._write({})

    def setdefault(self, key: str, default: Any) -> Any:
        """
        若键不存在则写入默认值并返回；若已存在则直接返回现有值。

        :param key: 配置键。
        :param default: 默认值。
        :return: 最终的配置值。
        """
        data = self._read()
        if key not in data:
            data[key] = default
            self._write(data)
        return data[key]

    # ------------------------------------------------------------------
    # 便捷属性
    # ------------------------------------------------------------------

    @property
    def group_id(self) -> str | None:
        """当前配置作用域的 group_id（全局配置为 None）。"""
        return self._group_id

    @property
    def is_global(self) -> bool:
        """是否为全局配置。"""
        return self._group_id is None

    @property
    def config_path(self) -> Path:
        """当前配置文件的绝对路径。"""
        return self._config_path

    # ------------------------------------------------------------------
    # 魔术方法（支持字典风格访问）
    # ------------------------------------------------------------------

    def __getitem__(self, key: str) -> Any:
        data = self._read()
        if key not in data:
            raise KeyError(key)
        return data[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.set(key, value)

    def __delitem__(self, key: str) -> None:
        if not self.delete(key):
            raise KeyError(key)

    def __contains__(self, key: str) -> bool:
        return key in self._read()

    def __repr__(self) -> str:
        scope = f"group={self._group_id}" if self._group_id else "global"
        return f"ConfigManager({scope}, path={self._config_path})"