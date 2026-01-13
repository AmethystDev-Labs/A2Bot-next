from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message, MessageSegment
from nonebot.params import CommandArg
from nonebot import get_driver

import httpx

config = get_driver().config

renew = on_command("renew", aliases={"续期"}, priority=10)
@renew.handle()
async def _(bot: Bot, event: GroupMessageEvent, args: Message = CommandArg()):
    if args:
        await renew.finish("请不要在命令中添加参数。关于本插件：本插件是用于修复Gemini Business的无可用账户问题，如果遇到此错误，请使用此命令续期。")
    
    api_url = config.toapi_url
    api_key = config.toapi_key

    headers = {
        "X-Api-Key": api_key
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{api_url}/task/create_account", headers=headers)

    await renew.finish(f"已发送续期请求，请等待3-5分钟后尝试请求API。taskID: {resp.json()['task_id']}")

query_task = on_command("query_task", aliases={"查询任务"}, priority=10)
@query_task.handle()
async def _(bot: Bot, event: GroupMessageEvent, args: Message = CommandArg()):
    if not args:
        await query_task.finish("请提供taskID。")
    api_url = config.toapi_url
    api_key = config.toapi_key

    headers = {
        "X-Api-Key": api_key
    }

    payload = {
        "task_id": args.extract_plain_text()
    }

    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{api_url}/task/status", headers=headers, params=payload)

    await query_task.finish(f"任务状态：{resp.json()['status']}")