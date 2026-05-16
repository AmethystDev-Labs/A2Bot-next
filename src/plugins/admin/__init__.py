from nonebot import on_request, on_command
from nonebot.adapters.onebot.v11 import Bot, GroupRequestEvent, GroupMessageEvent, Message, GROUP_ADMIN, GROUP_OWNER
from nonebot.permission import SUPERUSER
from nonebot.params import CommandArg, ArgPlainText
from .config import ConfigManager
# from nonebot.rule import is_type

group_req = on_request()

@group_req.handle()
async def handle_group_request(bot: Bot, event: GroupRequestEvent):
    # event.comment：验证信息
    # event.user_id：申请者 QQ
    # event.group_id：目标群号
    # event.sub_type：'add'（主动申请）或 'invite'（被邀请）

    userinfo = await bot.get_stranger_info(user_id=event.user_id)
    config = ConfigManager(group_id=event.group_id)

    if config.get("admin_enabled", False):
        required_level = config.get("required_level", 0)
        if userinfo.get("qqLevel", 0) >= required_level:
            await event.approve(bot)
        else:
            await event.reject(bot, reason=f"验证未通过，等级要求：{required_level}，你的等级：{userinfo.get('qqLevel', 0)}")

group_cmd = on_command("req", aliases={"入群设置"}, priority=5, permission=GROUP_ADMIN | GROUP_OWNER | SUPERUSER)
@group_cmd.handle()
async def _(bot: Bot, event: GroupMessageEvent, arg: Message = CommandArg()):
    config = ConfigManager(group_id=event.group_id)
    if not (arg_list := arg.extract_plain_text().strip().split()):
        await group_cmd.finish("请提供子命令，例如：req enable")

    match arg_list[0].lower():
        case "enable":
            config.set("admin_enabled", True)
            await group_cmd.finish("已启用入群验证")
        case "disable":
            config.set("admin_enabled", False)
            await group_cmd.finish("已禁用入群验证")
        case "status":
            status = config.get("admin_enabled", False)
            await group_cmd.finish(f"入群验证当前状态：{'启用' if status else '禁用'}")
        case "require_level":
            if len(arg_list) < 2 or not arg_list[1].isdigit():
                await group_cmd.finish("请提供有效的等级要求，例如：req require_level 3")
            level = int(arg_list[1])
            config.set("required_level", level)
            await group_cmd.finish(f"已设置入群验证等级要求为 {level}")
        case _:
            await group_cmd.finish("未知的子命令。可用子命令：enable, disable, status, require_level")
