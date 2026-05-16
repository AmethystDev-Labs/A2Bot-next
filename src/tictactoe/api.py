"""
tictactoe_engine.py
====================
基于落点打分的井字棋 AI 决策模块（移植自 gofan-SiTu 的 C 语言实现）

公开接口
--------
next_move(context, self)  →  dict
    根据当前棋盘，计算 AI 最优落子。

    输入：
        context : dict[str, str]
            键 "x:y"（列:行，0-indexed），值为棋子类型（如 "circle"/"cross"）
        self : str
            AI 自身棋子类型

    返回：
        "position" : str | None   AI 落子坐标 "x:y"，无法落子时为 None
        "context"  : dict         落子后的完整棋盘
        "status"   : str          "ongoing" | "win" | "lose" | "draw"

board_status(context, tokens)  →  dict
    纯粹判断当前棋盘的胜负状态，不落子。

    输入：
        context : dict[str, str]
            当前棋盘
        tokens  : tuple[str, str] | list[str]
            棋盘上可能出现的两种棋子类型，顺序不影响结果
            例：("circle", "cross")

    返回：
        "status" : str          "ongoing" | "draw" | "finished"
        "winner" : str | None   获胜方棋子类型，无胜者时为 None
        "loser"  : str | None   落败方棋子类型，无败者时为 None

示例
----
>>> from tictactoe_engine import next_move, board_status
>>> result = next_move(
...     context={"0:0": "circle", "1:1": "circle"},
...     self="cross"
... )
>>> print(result["position"])           # e.g. "2:2"
>>> print(result["status"])             # "ongoing" / "win" / ...

>>> state = board_status(
...     context={"0:0": "cross", "1:0": "cross", "2:0": "cross"},
...     tokens=("circle", "cross")
... )
>>> print(state["status"])              # "finished"
>>> print(state["winner"])              # "cross"
>>> print(state["loser"])               # "circle"
"""

import random
from typing import Optional

# ── 常量 ──────────────────────────────────────────────────────────────────────

_N = 3  # 棋盘边长

# 打分表：两个同行/列/对角邻居字符的"类型值" → 分数
# 类型值 = 该行/列/对角三格字符之和 - 空格字符值（即去掉落点自身的空格贡献）
# 用整数编码：SELF=2, OPP=3, EMPTY=1
_SELF  = 2
_OPP   = 3
_EMPTY = 1

_SCORE_TABLE = {
    _SELF  + _SELF : 100,   # 己方已有 2 子 → 立刻可赢
    _OPP   + _OPP  : 50,    # 对方已有 2 子 → 必须阻截
    _SELF  + _EMPTY: 6,     # 己方 1 子 + 空
    _OPP   + _EMPTY: 4,     # 对方 1 子 + 空
    _EMPTY + _EMPTY: 2,     # 全空
    _SELF  + _OPP  : 1,     # 己我混杂 → 无意义方向
}


# ── 内部工具 ──────────────────────────────────────────────────────────────────

def _parse_board(context: dict, self_token: str, opp_token: str) -> list[list[int]]:
    """将 context 字典转成 3×3 整数矩阵（EMPTY/SELF/OPP）。"""
    board = [[_EMPTY] * _N for _ in range(_N)]
    for key, val in context.items():
        x_str, y_str = key.split(":")
        x, y = int(x_str), int(y_str)   # x=列, y=行
        if val == self_token:
            board[y][x] = _SELF
        elif val == opp_token:
            board[y][x] = _OPP
    return board


def _board_to_context(board: list[list[int]], self_token: str, opp_token: str) -> dict:
    """将 3×3 整数矩阵还原为 context 字典。"""
    ctx: dict[str, str] = {}
    for row in range(_N):
        for col in range(_N):
            v = board[row][col]
            if v == _SELF:
                ctx[f"{col}:{row}"] = self_token
            elif v == _OPP:
                ctx[f"{col}:{row}"] = opp_token
    return ctx


def _line_score(cells: list[int]) -> int:
    """给定一条线（3 格）的整数编码列表，返回该方向的得分。
    排除落点自身（空格 = EMPTY），对剩余两格求类型值。"""
    # 落点一定是 EMPTY（只在空格上评分），去掉其中一个 EMPTY
    type_val = sum(cells) - _EMPTY
    return _SCORE_TABLE.get(type_val, 0)


def _check_winner(board: list[list[int]]) -> Optional[int]:
    """检查是否有人获胜。返回 _SELF/_OPP，或 None（未分胜负）。"""
    lines: list[list[int]] = []
    # 行
    for r in range(_N):
        lines.append([board[r][c] for c in range(_N)])
    # 列
    for c in range(_N):
        lines.append([board[r][c] for r in range(_N)])
    # 正对角
    lines.append([board[i][i] for i in range(_N)])
    # 反对角
    lines.append([board[i][_N - 1 - i] for i in range(_N)])

    for line in lines:
        if line[0] == line[1] == line[2] and line[0] != _EMPTY:
            return line[0]
    return None


def _is_full(board: list[list[int]]) -> bool:
    return all(board[r][c] != _EMPTY for r in range(_N) for c in range(_N))


def _compute_move(board: list[list[int]]) -> Optional[int]:
    """
    遍历空格，计算每个落点的综合得分（行 + 列 + 正对角 + 反对角），
    返回得分最高的落点索引（row * N + col）；若棋盘已满返回 None。
    """
    best_score = -1
    best_idx: Optional[int] = None

    for idx in range(_N * _N):
        row, col = divmod(idx, _N)
        if board[row][col] != _EMPTY:
            continue

        # 行
        row_cells = [board[row][c] for c in range(_N)]
        s = _line_score(row_cells)

        # 列
        col_cells = [board[r][col] for r in range(_N)]
        s += _line_score(col_cells)

        # 正对角（仅当 row == col）
        if row == col:
            diag_cells = [board[i][i] for i in range(_N)]
            s += _line_score(diag_cells)

        # 反对角（仅当 row + col == N-1）
        if row + col == _N - 1:
            anti_cells = [board[i][_N - 1 - i] for i in range(_N)]
            s += _line_score(anti_cells)

        if s > best_score:
            best_score = s
            best_idx = idx
        elif s == best_score and random.random() < 0.5:
            best_idx = idx

    return best_idx


# ── 公开接口 ──────────────────────────────────────────────────────────────────

def next_move(context: dict[str, str], self: str) -> dict:
    """
    根据当前棋盘状态，计算 AI 的最优落子位置。

    Parameters
    ----------
    context : dict[str, str]
        当前棋盘，键 "x:y"（列:行，0-indexed），值为棋子类型。
    self : str
        AI 自身的棋子类型（"circle" 或 "cross"）。

    Returns
    -------
    dict with keys:
        "position" : str | None   AI 落子坐标 "x:y"，棋盘已满时为 None
        "context"  : dict         落子后的棋盘状态
        "status"   : str          "ongoing" | "win" | "lose" | "draw"
    """
    # 推断对手棋子类型
    all_tokens = set(context.values()) | {self}
    other_tokens = all_tokens - {self}
    if other_tokens:
        opp = next(iter(other_tokens))
    else:
        # 棋盘为空或只有己方棋子，给对手一个占位符
        opp = "cross" if self == "circle" else "circle"

    board = _parse_board(context, self, opp)

    # 先检查落子前是否已有胜负（理论上不应出现，但做防御）
    winner = _check_winner(board)
    if winner == _SELF:
        return {"position": None, "context": dict(context), "status": "win"}
    if winner == _OPP:
        return {"position": None, "context": dict(context), "status": "lose"}
    if _is_full(board):
        return {"position": None, "context": dict(context), "status": "draw"}

    # 计算最优落点
    idx = _compute_move(board)
    if idx is None:
        return {"position": None, "context": dict(context), "status": "draw"}

    row, col = divmod(idx, _N)
    board[row][col] = _SELF
    pos_str = f"{col}:{row}"

    # 落子后检查局面
    winner = _check_winner(board)
    new_ctx = _board_to_context(board, self, opp)

    if winner == _SELF:
        status = "win"
    elif winner == _OPP:
        status = "lose"
    elif _is_full(board):
        status = "draw"
    else:
        status = "ongoing"

    return {
        "position": pos_str,
        "context": new_ctx,
        "status": status,
    }


def board_status(
    context: dict[str, str],
    tokens: tuple[str, str] | list[str],
) -> dict:
    """
    判断当前棋盘的胜负状态，不进行任何落子操作。

    Parameters
    ----------
    context : dict[str, str]
        当前棋盘，键 "x:y"（列:行，0-indexed），值为棋子类型字符串。
    tokens : tuple[str, str] | list[str]
        棋盘上两种棋子类型，例如 ("circle", "cross")。
        顺序不影响结果。

    Returns
    -------
    dict with keys:
        "status" : str
            "ongoing"  — 游戏尚未结束，棋盘仍有空格且无人获胜
            "draw"     — 棋盘已满且无人获胜
            "finished" — 已有一方获胜
        "winner" : str | None
            获胜方的棋子类型；无胜者时为 None
        "loser"  : str | None
            落败方的棋子类型；无败者时为 None
    """
    if len(tokens) != 2:
        raise ValueError("tokens 必须恰好包含两种棋子类型")

    token_a, token_b = tokens[0], tokens[1]

    # 用通用整数编码解析棋盘：token_a=2, token_b=3, 空=1
    board: list[list[int]] = [[_EMPTY] * _N for _ in range(_N)]
    for key, val in context.items():
        x_str, y_str = key.split(":")
        x, y = int(x_str), int(y_str)
        if val == token_a:
            board[y][x] = _SELF        # 2
        elif val == token_b:
            board[y][x] = _OPP         # 3

    # 检查所有连线
    lines: list[list[int]] = []
    for r in range(_N):
        lines.append([board[r][c] for c in range(_N)])
    for c in range(_N):
        lines.append([board[r][c] for r in range(_N)])
    lines.append([board[i][i]           for i in range(_N)])
    lines.append([board[i][_N - 1 - i]  for i in range(_N)])

    winning_code: Optional[int] = None
    for line in lines:
        if line[0] == line[1] == line[2] and line[0] != _EMPTY:
            winning_code = line[0]
            break

    if winning_code is not None:
        # 将内部编码还原为棋子类型字符串
        winner = token_a if winning_code == _SELF else token_b
        loser  = token_b if winning_code == _SELF else token_a
        return {"status": "finished", "winner": winner, "loser": loser}

    if _is_full(board):
        return {"status": "draw", "winner": None, "loser": None}

    return {"status": "ongoing", "winner": None, "loser": None}


# ── 简单自测 ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("─" * 40)
    print("board_status 测试")
    print("─" * 40)

    # cross 横排获胜
    s = board_status(
        context={"0:0": "cross", "1:0": "cross", "2:0": "cross", "0:1": "circle"},
        tokens=("circle", "cross"),
    )
    print(f"横排获胜  → status={s['status']}, winner={s['winner']}, loser={s['loser']}")

    # circle 对角获胜
    s = board_status(
        context={"0:0": "circle", "1:1": "circle", "2:2": "circle",
                 "1:0": "cross",  "2:0": "cross"},
        tokens=("circle", "cross"),
    )
    print(f"对角获胜  → status={s['status']}, winner={s['winner']}, loser={s['loser']}")

    # 平局
    s = board_status(
        context={
            "0:0": "cross",  "1:0": "circle", "2:0": "cross",
            "0:1": "circle", "1:1": "cross",  "2:1": "circle",
            "0:2": "circle", "1:2": "cross",  "2:2": "circle",
        },
        tokens=("circle", "cross"),
    )
    print(f"平局      → status={s['status']}, winner={s['winner']}, loser={s['loser']}")

    # 进行中
    s = board_status(
        context={"0:0": "cross", "1:1": "circle"},
        tokens=("circle", "cross"),
    )
    print(f"进行中    → status={s['status']}, winner={s['winner']}, loser={s['loser']}")

    print()
    print("─" * 40)
    print("next_move 测试")
    print("─" * 40)
    # 场景 1：空棋盘，AI 先手
    r = next_move(context={}, self="cross")
    print("空棋盘    →", f"落子={r['position']}, 状态={r['status']}")

    # 场景 2：AI 即将赢（还差一步）
    ctx = {
        "0:0": "cross", "1:0": "cross",
        "0:1": "circle", "1:1": "circle",
    }
    r = next_move(context=ctx, self="cross")
    print("即将获胜  →", f"落子={r['position']}, 状态={r['status']}")

    # 场景 3：必须防守
    ctx = {
        "0:0": "circle", "1:0": "circle",
        "0:1": "cross",
    }
    r = next_move(context=ctx, self="cross")
    print("必须防守  →", f"落子={r['position']}, 状态={r['status']}")