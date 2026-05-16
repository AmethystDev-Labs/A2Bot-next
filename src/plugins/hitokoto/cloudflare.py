import httpx
from nonebot import get_driver
from pydantic import BaseModel
from types import SimpleNamespace


class CloudflareConfigError(Exception):
    pass


class CloudflareAPIError(Exception):
    pass


class CloudflareConfig(BaseModel):
    cloudflare_account_id: str
    cloudflare_api_token: str

def parse_env(path: str = ".env") -> SimpleNamespace:
    env = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, _, value = line.partition("=")
            key = key.strip().lower()
            value = value.strip().strip("\"'")
            if key:
                env[key] = value
    return SimpleNamespace(**env)


try:
    config = CloudflareConfig.model_validate(get_driver().config.model_dump())
except Exception as e:
    if config := parse_env(".env.prod"):
        try:
            config = CloudflareConfig.model_validate(vars(config))
        except Exception as e:
            raise CloudflareConfigError("从环境变量解析 Cloudflare 配置失败，请检查 .env.prod 文件格式")


async def get_browser_run_instance() -> str:
    aid = config.cloudflare_account_id
    token = config.cloudflare_api_token
    headers = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient() as client:
        # 1. 优先尝试获取现有的活跃会话（实现浏览器复用）
        try:
            session_response = await client.get(
                f"https://api.cloudflare.com/client/v4/accounts/{aid}/browser-rendering/devtools/session",
                headers=headers,
                timeout=10.0,
            )
            if session_response.is_success:
                session_data = session_response.json()
                # 兼容标准 Cloudflare 包装器格式 {"result": [...]} 或直接返回列表的格式
                sessions = session_data.get("result", []) if isinstance(session_data, dict) else session_data
                
                if isinstance(sessions, list) and len(sessions) > 0:
                    first_session = sessions[0]
                    if isinstance(first_session, dict):
                        # 获取会话 ID（兼容不同 SDK 版本的命名差异）
                        session_id = first_session.get("session_id") or first_session.get("sessionId") or first_session.get("id")
                        if session_id:
                            # 拼接复用该会话的 WebSocket 调试地址
                            return f"wss://api.cloudflare.com/client/v4/accounts/{aid}/browser-rendering/devtools/browser/{session_id}"
        except Exception:
            # 获取或解析活跃会话异常时，静默降级，继续走下方创建新实例的逻辑
            pass

        # 2. 如果没有可复用的活跃会话，则请求创建全新的浏览器会话
        try:
            response = await client.post(
                f"https://api.cloudflare.com/client/v4/accounts/{aid}/browser-rendering/devtools/browser",
                params={"keep_alive": 600000}, # 闲置超时保持 10 分钟
                headers=headers,
                timeout=30.0,
            )
        except httpx.TimeoutException as e:
            raise CloudflareAPIError("请求 Cloudflare API 超时") from e
        except httpx.RequestError as e:
            raise CloudflareAPIError(f"网络请求失败: {e}") from e

        if response.status_code == 401:
            raise CloudflareConfigError("API Token 无效或无权限，请检查 cloudflare_api_token")
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After", "未知")
            raise CloudflareAPIError(f"触发速率限制，请 {retry_after} 秒后重试")
        if not response.is_success:
            raise CloudflareAPIError(f"API 返回错误 {response.status_code}: {response.text}")

        result = response.json()
        cdp_address = result.get("webSocketDebuggerUrl")
        if not cdp_address:
            raise CloudflareAPIError(f"响应中缺少 webSocketDebuggerUrl，完整响应: {result}")
        return cdp_address