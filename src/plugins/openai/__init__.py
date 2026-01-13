import base64
import json
import os

import httpx
import anyio
from nonebot import on_command, on_message
from nonebot.adapters.onebot.v11 import Bot, Message, MessageEvent
from nonebot.log import logger
from nonebot.params import CommandArg
from nonebot.rule import to_me
from nonebot import get_driver

config = get_driver().config

CONTEXT_DIR = os.path.join(os.getcwd(), "data", "openai")
USER_SETTINGS_DIR = os.path.join(CONTEXT_DIR, "users")
MAX_CONTEXT_MESSAGES = 20
_http_client: httpx.AsyncClient | None = None


@get_driver().on_startup
async def _init_http_client() -> None:
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(timeout=30)


@get_driver().on_shutdown
async def _close_http_client() -> None:
    global _http_client
    if _http_client is not None:
        await _http_client.aclose()
        _http_client = None


def _get_openai_config() -> tuple[str, str, str]:
    api_key = config.openai_api_key
    base_url = config.openai_base_url
    model = config.openai_model
    return api_key, base_url, model


def _get_prompt_file_path() -> str | None:
    prompt_file = getattr(config, "prompt_file", None)
    if not prompt_file:
        return None
    if os.path.isabs(prompt_file):
        return prompt_file
    return os.path.join(os.getcwd(), prompt_file)


async def _read_text(path: str) -> str:
    def _read() -> str:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    return await anyio.to_thread.run_sync(_read)


async def _read_json(path: str):
    def _read():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    return await anyio.to_thread.run_sync(_read)


async def _write_json(path: str, data) -> None:
    def _write() -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    await anyio.to_thread.run_sync(_write)


async def _load_prompt_message() -> dict | None:
    path = _get_prompt_file_path()
    if not path:
        return None
    if not os.path.exists(path):
        logger.warning("Prompt file not found: %s", path)
        return None
    try:
        content = (await _read_text(path)).strip()
        if not content:
            return None
        return {"role": "system", "content": content}
    except Exception as exc:
        logger.exception("Failed to load prompt file: %s", exc)
        return None


def _get_session_id(event: MessageEvent) -> str:
    user_id = event.get_user_id()
    group_id = getattr(event, "group_id", None)
    if group_id:
        return f"{group_id}_{user_id}"
    return f"{user_id}"


def _get_user_settings_path(event: MessageEvent) -> str:
    user_id = event.get_user_id()
    return os.path.join(USER_SETTINGS_DIR, f"{user_id}.json")


async def _load_user_settings(event: MessageEvent) -> dict:
    path = _get_user_settings_path(event)
    if not os.path.exists(path):
        return {}
    try:
        data = await _read_json(path)
        if isinstance(data, dict):
            return data
        logger.warning("Invalid user settings format in %s", path)
    except Exception as exc:
        logger.exception("Failed to load user settings: %s", exc)
    return {}


async def _save_user_settings(event: MessageEvent, settings: dict) -> None:
    os.makedirs(USER_SETTINGS_DIR, exist_ok=True)
    path = _get_user_settings_path(event)
    try:
        await _write_json(path, settings)
    except Exception as exc:
        logger.exception("Failed to save user settings: %s", exc)


async def _get_user_model(event: MessageEvent) -> str:
    settings = await _load_user_settings(event)
    model = settings.get("model")
    if isinstance(model, str) and model:
        return model
    return config.openai_model


async def _set_user_model(event: MessageEvent, model: str) -> None:
    settings = await _load_user_settings(event)
    settings["model"] = model
    await _save_user_settings(event, settings)


def _get_context_path(event: MessageEvent) -> str:
    session_id = _get_session_id(event)
    return os.path.join(CONTEXT_DIR, f"{session_id}.json")


async def _load_context(event: MessageEvent) -> list[dict]:
    path = _get_context_path(event)
    if not os.path.exists(path):
        return []
    try:
        data = await _read_json(path)
        if isinstance(data, list):
            return data
        logger.warning("Invalid context format in %s", path)
    except Exception as exc:
        logger.exception("Failed to load context: %s", exc)
    return []


async def _save_context(event: MessageEvent, messages: list[dict]) -> None:
    os.makedirs(CONTEXT_DIR, exist_ok=True)
    path = _get_context_path(event)
    try:
        await _write_json(path, messages)
    except Exception as exc:
        logger.exception("Failed to save context: %s", exc)


async def _call_openai(messages: list[dict], model: str) -> str:
    api_key, base_url, _ = _get_openai_config()
    if not api_key:
        return "缺少 OPENAI_API_KEY 配置。"
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}"}
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.7,
    }
    try:
        if _http_client is None:
            await _init_http_client()
        resp = await _http_client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()
    except httpx.HTTPStatusError as exc:
        response = exc.response
        body = response.text
        if len(body) > 1000:
            body = body[:1000] + "..."
        logger.error(
            "OpenAI request failed: %s %s; body=%s",
            response.status_code,
            response.reason_phrase,
            body,
        )
        return f"上游返回错误 {response.status_code}，请稍后再试。"
    except Exception as exc:
        logger.exception("OpenAI request failed: %s", exc)
        return "请求 OpenAI 失败，请稍后再试。"


def _infer_image_mime(file_value: str) -> str:
    lowered = file_value.lower()
    if lowered.endswith(".jpg") or lowered.endswith(".jpeg"):
        return "image/jpeg"
    if lowered.endswith(".gif"):
        return "image/gif"
    if lowered.endswith(".webp"):
        return "image/webp"
    return "image/png"


def _normalize_image_data_url(
    file_value: str,
    base64_value: str,
    mime: str | None = None,
) -> str:
    if base64_value.startswith("data:image/"):
        return base64_value
    mime_value = mime or _infer_image_mime(file_value)
    return f"data:{mime_value};base64,{base64_value}"


async def _fetch_image_base64(url: str) -> tuple[str | None, str | None]:
    if _http_client is None:
        await _init_http_client()
    assert _http_client is not None
    resp = await _http_client.get(url)
    resp.raise_for_status()
    content_type = resp.headers.get("content-type", "").split(";", 1)[0].strip()
    encoded = base64.b64encode(resp.content).decode("ascii")
    return encoded, content_type or None


async def _build_image_part(segment) -> dict | None:
    file_value = segment.data.get("file", "") or ""
    base64_value = segment.data.get("base64", "") or ""

    if not base64_value and file_value.startswith("base64://"):
        base64_value = file_value[len("base64://") :]

    if base64_value:
        url = _normalize_image_data_url(file_value, base64_value)
        return {"type": "image_url", "image_url": {"url": url}}

    url_value = segment.data.get("url", "") or ""
    if not url_value:
        return None
    try:
        fetched_base64, mime = await _fetch_image_base64(url_value)
    except Exception as exc:
        logger.warning("Failed to fetch image url %s: %s", url_value, exc)
        return None
    if not fetched_base64:
        return None
    url = _normalize_image_data_url(url_value, fetched_base64, mime=mime)
    return {"type": "image_url", "image_url": {"url": url}}


async def _build_user_message(message: Message) -> dict | None:
    parts: list[dict] = []
    text_buffer: list[str] = []

    def _flush_text() -> None:
        if not text_buffer:
            return
        text = "".join(text_buffer).strip()
        text_buffer.clear()
        if text:
            parts.append({"type": "text", "text": text})

    for segment in message:
        if segment.type == "text":
            text_buffer.append(segment.data.get("text", ""))
            continue
        if segment.type != "image":
            continue
        _flush_text()
        image_part = await _build_image_part(segment)
        if image_part:
            parts.append(image_part)

    _flush_text()
    if not parts:
        return None
    if len(parts) == 1 and parts[0]["type"] == "text":
        return {"role": "user", "content": parts[0]["text"]}
    return {"role": "user", "content": parts}


async def _build_messages(history: list[dict], user_message: dict) -> list[dict]:
    messages = []
    prompt_msg = await _load_prompt_message()
    if prompt_msg:
        messages.append(prompt_msg)
    messages.extend(history)
    messages.append(user_message)
    return messages


def _infer_model_features(model_id: str) -> list[str]:
    lowered = model_id.lower()
    features = ["文本"]
    if "vision" in lowered or "gpt-4o" in lowered:
        features.append("视觉")
    if lowered.startswith("o1") or "reason" in lowered:
        features.append("思考")
    return features


async def _fetch_models() -> list[dict]:
    api_key, base_url, _ = _get_openai_config()
    if not api_key:
        return []
    url = f"{base_url.rstrip('/')}/models"
    headers = {"Authorization": f"Bearer {api_key}"}
    if _http_client is None:
        await _init_http_client()
    assert _http_client is not None
    resp = await _http_client.get(url, headers=headers)
    resp.raise_for_status()
    data = resp.json()
    models = data.get("data", [])
    if isinstance(models, list):
        return models
    return []


async def _send_model_list(bot: Bot, event: MessageEvent) -> None:
    try:
        models = await _fetch_models()
    except Exception as exc:
        logger.exception("Fetch models failed: %s", exc)
        await model_cmd.finish("获取模型列表失败，请稍后再试。")
        return
    if not models:
        await model_cmd.finish("未获取到模型列表。")
        return
    entries = []
    for item in models:
        model_id = item.get("id")
        if not model_id:
            continue
        features = "、".join(_infer_model_features(model_id))
        entries.append(f"{model_id}\n特性: {features}")
    entries.sort()
    nodes = []
    for entry in entries:
        nodes.append(
            {
                "type": "node",
                "data": {
                    "name": "A2Bot",
                    "uin": str(bot.self_id),
                    "content": entry,
                },
            }
        )
    group_id = getattr(event, "group_id", None)
    if group_id:
        await bot.call_api("send_group_forward_msg", group_id=group_id, messages=nodes)
        await model_cmd.finish("模型列表已发送。")
    else:
        text = "\n\n".join(entries)
        await model_cmd.finish(text)


chat = on_command("chat", priority=10)
model_cmd = on_command("model", priority=10)
tome = on_message(rule=to_me(), priority=10)


@chat.handle()
async def _(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    user_message = await _build_user_message(args)
    if not user_message:
        await chat.finish("请提供内容。用法: /chat 你好")
    history = await _load_context(event)
    messages = await _build_messages(history, user_message)
    model = await _get_user_model(event)
    reply = await _call_openai(messages, model)
    if reply:
        history.append(user_message)
        history.append({"role": "assistant", "content": reply})
        if len(history) > MAX_CONTEXT_MESSAGES:
            history = history[-MAX_CONTEXT_MESSAGES:]
        await _save_context(event, history)
    await chat.finish(reply)


@model_cmd.handle()
async def _(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    text = args.extract_plain_text().strip()
    if not text:
        await _send_model_list(bot, event)
        return
    await _set_user_model(event, text)
    await model_cmd.finish(f"已切换到模型: {text}")


@tome.handle()
async def _(bot: Bot, event: MessageEvent):
    user_message = await _build_user_message(event.message)
    if not user_message:
        return
    history = await _load_context(event)
    messages = await _build_messages(history, user_message)
    model = await _get_user_model(event)
    reply = await _call_openai(messages, model)
    if reply:
        history.append(user_message)
        history.append({"role": "assistant", "content": reply})
        if len(history) > MAX_CONTEXT_MESSAGES:
            history = history[-MAX_CONTEXT_MESSAGES:]
        await _save_context(event, history)
    await tome.finish(reply)
