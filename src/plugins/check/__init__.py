"""
群验证码入群验证插件
使用 on_notice 检测入群事件 + on_message 接收验证答案
触发验证前会先检查机器人是否为该群管理员/群主（没有权限就无法踢人，验证没有意义）
配合内存字典维护验证状态，超时自动踢人
"""

import asyncio
import random
import time
from typing import Dict, Tuple

from nonebot import on_notice, on_message
from nonebot.adapters.onebot.v11 import (
    Bot,
    Message,
    MessageSegment,
    GroupMessageEvent,
    GroupIncreaseNoticeEvent,
)
from nonebot.rule import Rule

# ---------------------------------------------------------------------------
# 全局状态：key = (group_id, user_id) -> 验证信息
# ---------------------------------------------------------------------------
VERIFY_TIMEOUT = 60  # 验证超时时间（秒）
MAX_TRIES = 3        # 最大错误次数

pending: Dict[Tuple[int, int], dict] = {}


def gen_question():
    """生成一道简单的加减法题目"""
    a = random.randint(-100, 100)
    b = random.randint(-100, 100)
    op = random.randint(0, 1)
    if op == 0:
        return a, b, "+", a + b
    else:
        return a, b, "-", a - b


async def bot_is_admin_or_owner(bot: Bot, group_id: int) -> bool:
    """检查机器人在该群是否为管理员或群主"""
    try:
        info = await bot.get_group_member_info(
            group_id=group_id, user_id=int(bot.self_id), no_cache=True
        )
    except Exception:
        # 拿不到信息就保守地认为没有权限，避免误判导致后续踢人失败
        return False
    return info.get("role") in ("admin", "owner")


# ---------------------------------------------------------------------------
# 1. 入群通知：先检查权限，再发送题目，记录状态，启动超时踢人任务
# ---------------------------------------------------------------------------
handle_increase = on_notice(priority=10, block=False)


@handle_increase.handle()
async def on_group_increase(bot: Bot, event: GroupIncreaseNoticeEvent):
    if not isinstance(event, GroupIncreaseNoticeEvent):
        return

    group_id = event.group_id
    user_id = event.user_id
    key = (group_id, user_id)

    # 机器人没有管理员/群主权限就踢不了人，验证流程直接跳过，
    # 避免出现"验证失败但踢不掉人"的尴尬情况
    if not await bot_is_admin_or_owner(bot, group_id):
        return

    a, b, op_str, answer = gen_question()

    pending[key] = {
        "answer": answer,
        "count": 0,
        "created_at": time.time(),
    }

    await bot.send_group_msg(
        group_id=group_id,
        message=Message(
            [
                MessageSegment.at(user_id),
                MessageSegment.text(
                    f" 欢迎入群！请在 {VERIFY_TIMEOUT} 秒内回答问题以通过验证：\n"
                    f"{a} {op_str} {b} = ?"
                ),
            ]
        ),
    )

    # 启动超时任务：到时间还没验证通过就踢人
    asyncio.create_task(kick_if_timeout(bot, group_id, user_id))


async def kick_if_timeout(bot: Bot, group_id: int, user_id: int):
    key = (group_id, user_id)
    await asyncio.sleep(VERIFY_TIMEOUT)

    # 如果 key 还在，说明用户没有验证通过，超时踢人
    if key in pending:
        del pending[key]
        try:
            await bot.set_group_kick(group_id=group_id, user_id=user_id)
            await bot.send_group_msg(
                group_id=group_id,
                message=Message(
                    [
                        MessageSegment.at(user_id),
                        MessageSegment.text(" 验证超时，已被移出群聊"),
                    ]
                ),
            )
        except Exception:
            # 机器人权限可能在这期间被取消，或用户已经离开
            pass


# ---------------------------------------------------------------------------
# 2. 群消息：检查发送者是否在验证名单中，校验答案
# ---------------------------------------------------------------------------
def is_pending(event: GroupMessageEvent) -> bool:
    return (event.group_id, event.user_id) in pending


handle_answer = on_message(rule=Rule(is_pending), priority=5, block=True)


@handle_answer.handle()
async def on_answer(bot: Bot, event: GroupMessageEvent):
    group_id = event.group_id
    user_id = event.user_id
    key = (group_id, user_id)

    info = pending.get(key)
    if info is None:
        return

    text = event.get_plaintext().strip()

    try:
        user_answer = int(text)
    except ValueError:
        user_answer = None

    if user_answer is not None and user_answer == info["answer"]:
        del pending[key]
        await handle_answer.finish(
            Message(
                [
                    MessageSegment.at(user_id),
                    MessageSegment.text(" 答案正确，验证通过！"),
                ]
            )
        )
        return

    info["count"] += 1

    if info["count"] >= MAX_TRIES:
        del pending[key]
        try:
            await bot.set_group_kick(group_id=group_id, user_id=user_id)
        except Exception:
            pass
        await handle_answer.finish(
            Message(
                [
                    MessageSegment.at(user_id),
                    MessageSegment.text(" 错误次数过多，已被移出群聊"),
                ]
            )
        )
    else:
        remaining = MAX_TRIES - info["count"]
        await handle_answer.finish(
            Message(
                [
                    MessageSegment.at(user_id),
                    MessageSegment.text(f" 答案错误，请重新回答（剩余 {remaining} 次机会）"),
                ]
            )
        )