import httpx
from nonebot import require, get_driver, get_bot
from nonebot.log import logger
from nonebot.adapters.onebot.v11 import MessageSegment

# 确保已加载定时任务插件
require("nonebot_plugin_apscheduler")
from nonebot_plugin_apscheduler import scheduler

LAST_MODELS = []
driver = get_driver()
config = driver.config
# 优先从配置读取，设置默认值
OPENAI_BASE_URL = getattr(config, "openai_base_url", "https://api.openai.com/v1")
NOTICE_GROUP = getattr(config, "models_notice_group", None)
OPENAI_API_KEY = getattr(config, "openai_api_key", None)    
if not OPENAI_API_KEY or not NOTICE_GROUP:
    logger.error("未配置 API Key 或 通知群，请在配置文件中添加 openai_api_key 和 models_notice_group")
    raise ValueError("API Key 或 通知群 未配置")

@scheduler.scheduled_job("cron", minute="*", id="job_0")
async def get_models():
    global LAST_MODELS
    
    # 1. 动态获取 Bot 实例
    try:
        bot = get_bot()
    except ValueError:
        # 当前没有 Bot 连接
        return

    try:
        async with httpx.AsyncClient(timeout=10.0, headers={"Authorization": f"Bearer {OPENAI_API_KEY}"}) as client:
            resp = await client.get(f"{OPENAI_BASE_URL}/models")
            resp.raise_for_status()
            data = resp.json().get("data", [])
            current_models = sorted([m["id"] for m in data])

            # 2. 首次运行初始化，不发送通知
            if not LAST_MODELS:
                LAST_MODELS = current_models
                logger.info("模型监控初始化完成")
                return

            # 3. 对比差异
            if current_models != LAST_MODELS:
                added = set(current_models) - set(LAST_MODELS)
                removed = set(LAST_MODELS) - set(current_models)
                
                LAST_MODELS = current_models
                
                msg = "🚀 模型变动通知\n"
                if added:
                    msg += f"\n+ 新增模型：\n" + "\n".join(added)
                if removed:
                    msg += f"\n\n- 移除模型：\n" + "\n".join(removed)
                
                # 4. 发送通知到指定群
                if NOTICE_GROUP:
                    await bot.send_group_msg(group_id=NOTICE_GROUP, message=msg)
                logger.info("模型状态已通知")
                
    except Exception as e:
        logger.error(f"监控模型时发生错误: {e}")
