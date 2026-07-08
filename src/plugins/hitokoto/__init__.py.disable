from nonebot import on_notice
from nonebot.adapters.onebot.v11 import Bot, MessageSegment
from nonebot.adapters.onebot.v11.event import PokeNotifyEvent
import httpx
from .render import render_template_to_png

poke_handler = on_notice()

@poke_handler.handle()
async def handle_poke(bot: Bot, event: PokeNotifyEvent):
    # event.user_id   -> 发起戳一戳的人
    # event.target_id -> 被戳的人
    # event.self_id   -> 机器人自己的 QQ
    # event.group_id  -> 群号（私聊时无此字段）

    if event.target_id == event.self_id:
        # 被戳的是机器人自己
        async with httpx.AsyncClient() as client:
            hitokoto_result = await client.get("https://hitokoto.c0ffee.space/")
            hitokoto_result = hitokoto_result.json()
            await bot.send(event, message=f"『{hitokoto_result.get('hitokoto', '获取失败')}』 -- {hitokoto_result.get('from', '未知')}")
            image = await render_template_to_png(hitokoto_result.get('hitokoto', '获取失败'), hitokoto_result.get('from', '未知'))
            await bot.send(event, message=MessageSegment.image(image))