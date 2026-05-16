from .render import render_board_data_url, render_board_png_base64
from .api import next_move, board_status
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message
from nonebot import on_command
from nonebot.params import CommandArg, ArgPlainText
from nonebot.matcher import Matcher

__all__ = ["render_board_png_base64", "render_board_data_url", "next_move", "board_status"]

temp_sessions = {}

tictactoe_command = on_command("tictactoe", aliases={"ttt"}, priority=5)
@tictactoe_command.handle()
async def _(bot: Bot, event: GroupMessageEvent, matcher: Matcher, args: Message = CommandArg()):
    if args.extract_plain_text():
        if event.user_id not in temp_sessions.keys(): # 判断用户是否已经有session
            temp_sessions[event.user_id] = {}
            

@tictactoe_command.got("first", prompt="是否先手，回复1确认，回复0后手，回复2退出")
async def if_first(event: GroupMessageEvent, matcher: Matcher, first: str = ArgPlainText()):
    if first == "1":
        await matcher.send("对局：用户先手")
        
    elif first == "0":
        await matcher.send("对局：电脑先手")
    elif first == "2":
        await matcher.send("对局已退出")
        temp_sessions.pop(event.user_id)
        return
    else:
        await matcher.reject("输入错误，请重新输入！")

@tictactoe_command.got("coord", prompt="输入坐标")
async def input_coord(event: GroupMessageEvent, matcher: Matcher, coord: str = ArgPlainText()):
    pass

        



"""
我在思考怎么做。。。。
official demo: 

@weather.handle()
async def handle_function(matcher: Matcher, args: Message = CommandArg()):
    if args.extract_plain_text():
        matcher.set_arg("location", args)

@weather.got("location", prompt="请输入地名")
async def got_location(location: str = ArgPlainText()):
    if location not in ["北京", "上海", "广州", "深圳"]:
        await weather.reject(f"你想查询的城市 {location} 暂不支持，请重新输入！")
    await weather.finish(f"今天{location}的天气是...")
"""