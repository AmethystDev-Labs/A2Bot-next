import sys
from pathlib import Path

if __name__ == "__main__":
    # 将项目根目录加入 sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from src.plugins.hitokoto import cloudflare
else:
    from . import cloudflare

import base64
from html import escape
from typing import Literal

import playwright.async_api as pw
from nonebot import get_driver
from pydantic import BaseModel

with open("src/plugins/hitokoto/template.html", "r", encoding="utf-8") as f:
    HTML_TEMPLATE = f.read()


class RenderConfig(BaseModel):
    render_method: Literal["cloudflare", "local"] = "local"
    cloudflare_api_token: str | None = None


_config: RenderConfig | None = None


def _get_config() -> RenderConfig:
    global _config
    if _config is None:
        _config = RenderConfig.model_validate(get_driver().config.model_dump())
    return _config


async def render_template_to_png(hitokoto: str, source: str) -> str:
    config = _get_config()
    html = HTML_TEMPLATE.replace("%%HITOKOTO%%", escape(hitokoto)).replace(
        "%%FROM%%", escape(source)
    )

    async with pw.async_playwright() as p:
        if config.render_method == "cloudflare":
            cdp_address = await cloudflare.get_browser_run_instance()
            browser = await p.chromium.connect_over_cdp(cdp_address, headers={"Authorization": f"Bearer {config.cloudflare_api_token}"})
        else:
            browser = await p.chromium.launch()

        try:
            page = await browser.new_page()
            await page.set_content(html)
            screenshot = await page.screenshot(full_page=True)
        finally:
            await browser.close()

    return "data:image/png;base64," + base64.b64encode(screenshot).decode("utf-8")


if __name__ == "__main__":
    import asyncio

    _config = RenderConfig()

    hitokoto = "人生苦短，及时行乐。"
    source = "一言"
    png_data_url = asyncio.run(render_template_to_png(hitokoto, source))
    with open("output.b64", "w", encoding="utf-8") as f:
        f.write(png_data_url)
