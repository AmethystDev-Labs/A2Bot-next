from . import lib
from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message
from nonebot.params import CommandArg

# General Gmail command
gen_email = on_command("gmail", aliases={"临时邮箱", "tempmail", "tm"}, priority=10)

@gen_email.handle()
async def _(bot: Bot, event: GroupMessageEvent, args: Message = CommandArg()):
    if args:
        gen_email.finish(f"Error: Not support args {args}")
    mail_client = lib.AsyncTempGmail()
    mail = await mail_client.generate_email()
    await gen_email.finish(f"Generated temporary Gmail address: {mail}\nIf you want receive email box, please send \"/mailbox {mail}\"")

mailbox = on_command("mailbox", aliases={"收信箱"}, priority=10)
@mailbox.handle()
async def _(bot: Bot, event: GroupMessageEvent, args: Message = CommandArg()):
    if not args:
        await mailbox.finish("Error: Please provide a temporary Gmail address.")
    mail_address = args.extract_plain_text().strip()
    mail_client = lib.AsyncTempGmail()
    emails = await mail_client.get_message_list(mail_address)
    if not emails:
        await mailbox.finish(f"No emails found for {mail_address}.")
    response = f"Emails for {mail_address}:\n"
    for idx, email in enumerate(emails, 1):
        response += f"{idx}. From: {email['from']}, Subject: {email['subject']}\n"
    await mailbox.finish(response)
