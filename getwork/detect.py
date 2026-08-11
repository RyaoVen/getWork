"""来源策略探测：给 add_source 用的轻量判断（static / dynamic / platform）。

探测只是起点，结果建议用 crawl_jobs 验证；选择器/API 配置不准时由 Agent 补正。
"""

from __future__ import annotations

from urllib.parse import urlparse

import httpx

from .crawlers.base import UA

# 常见统一招聘平台域名：命中即按 platform（JSON API）处理。
KNOWN_PLATFORM_HOSTS = (
    "mokahr.com",      # Moka
    "hr-ideal.cn",     # 北森
    "dajie.com",       # 大街网
    "dayee.net",       # 大易
    "beisen.co",       # 北森海外
    "zhaopin.com",     # 智联
)

_SPA_MARKERS = (
    'id="app"',
    'id="root"',
    'id="__nuxt"',
    'id="__next"',
    'id="app-root"',
    '<div id="app">',
    '<div id="root">',
)


def _host_of(url: str) -> str:
    return (urlparse(url).netloc or "").lower().replace("www.", "")


async def detect_strategy(url: str) -> dict:
    """探测返回 {strategy, needs_login, reason}。异常时兜底为 static。"""
    host = _host_of(url)
    for p in KNOWN_PLATFORM_HOSTS:
        if p in host:
            return {
                "strategy": "platform",
                "needs_login": False,
                "reason": f"域名疑似 {p} 招聘平台，按 JSON API 处理",
            }
    try:
        async with httpx.AsyncClient(
            timeout=10, headers={"User-Agent": UA}, follow_redirects=True
        ) as client:
            resp = await client.get(url)
            text = resp.text or ""
    except Exception as e:
        return {
            "strategy": "static",
            "needs_login": False,
            "reason": f"探测失败({type(e).__name__})，默认静态页",
        }
    lower = text.lower()
    for marker in _SPA_MARKERS:
        if marker in lower:
            return {
                "strategy": "dynamic",
                "needs_login": False,
                "reason": "检测到 SPA 容器（JS 渲染），用 Playwright",
            }
    return {"strategy": "static", "needs_login": False, "reason": "普通 HTML，按静态页处理"}
