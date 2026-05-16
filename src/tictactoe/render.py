"""井字棋棋盘 PNG 渲染，输出 Base64 字符串。"""

from __future__ import annotations

import base64
import io
import re
from typing import Mapping

from PIL import Image, ImageDraw

# 画布与格子（3×3）
_SIZE = 300
_CELL = _SIZE // 3
_PAD = int(_CELL * 0.18)
_LINE_W = max(3, _SIZE // 100)

# 颜色
_BG = (248, 249, 250)
_GRID = (55, 65, 81)
_CIRCLE = (220, 53, 69)
_CROSS = (13, 110, 253)

_KEY_PATTERN = re.compile(r"^(\d):(\d)$")


def _normalize_icon(name: str) -> str | None:
    n = name.strip().lower()
    if n in ("circle", "o", "0"):
        return "circle"
    if n in ("cross", "x", "1"):
        return "cross"
    return None


def _parse_cell(key: str) -> tuple[int, int] | None:
    m = _KEY_PATTERN.match(key.strip())
    if not m:
        return None
    x, y = int(m.group(1)), int(m.group(2))
    if 0 <= x <= 2 and 0 <= y <= 2:
        return x, y
    return None


def _draw_grid(draw: ImageDraw.ImageDraw) -> None:
    for i in range(1, 3):
        p = i * _CELL
        draw.line([(p, 0), (p, _SIZE)], fill=_GRID, width=_LINE_W)
        draw.line([(0, p), (_SIZE, p)], fill=_GRID, width=_LINE_W)


def _cell_bbox(col: int, row: int) -> tuple[int, int, int, int]:
    x0 = col * _CELL + _PAD
    y0 = row * _CELL + _PAD
    x1 = (col + 1) * _CELL - _PAD
    y1 = (row + 1) * _CELL - _PAD
    return (x0, y0, x1, y1)


def _draw_circle(draw: ImageDraw.ImageDraw, col: int, row: int) -> None:
    draw.ellipse(_cell_bbox(col, row), outline=_CIRCLE, width=_LINE_W)


def _draw_cross(draw: ImageDraw.ImageDraw, col: int, row: int) -> None:
    x0, y0, x1, y1 = _cell_bbox(col, row)
    draw.line([(x0, y0), (x1, y1)], fill=_CROSS, width=_LINE_W)
    draw.line([(x0, y1), (x1, y0)], fill=_CROSS, width=_LINE_W)


def render_board_png_base64(state: Mapping[str, str]) -> str:
    """
    根据占位字典渲染 3×3 井字棋棋盘，返回 PNG 的 **纯 Base64** 字符串（无 data: 前缀）。

    :param state: 键为 ``\"x:y\"``（列、行，均为 0–2），值为图标类型，例如
        ``\"circle\"`` / ``\"cross\"``（也接受 ``o`` / ``x`` 等别名）。
    """
    img = Image.new("RGB", (_SIZE, _SIZE), _BG)
    draw = ImageDraw.Draw(img)
    _draw_grid(draw)

    for key, raw in state.items():
        pos = _parse_cell(key)
        if pos is None:
            continue
        col, row = pos
        kind = _normalize_icon(raw)
        if kind == "circle":
            _draw_circle(draw, col, row)
        elif kind == "cross":
            _draw_cross(draw, col, row)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def render_board_data_url(state: Mapping[str, str]) -> str:
    """同上，但返回 ``data:image/png;base64,...``，便于网页或部分客户端直接使用。"""
    b64 = render_board_png_base64(state)
    return f"data:image/png;base64,{b64}"


__all__ = ["render_board_png_base64", "render_board_data_url"]
