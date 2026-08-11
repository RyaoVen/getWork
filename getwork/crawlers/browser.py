"""dynamic 策略：JS 重页面用 Playwright 驱动浏览器；含登录与会话复用。"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from contextlib import asynccontextmanager
from typing import Any

from playwright.async_api import async_playwright

from ..config import Settings, Source
from ..models import JobRecord
from ..sessions import has_session, load_cookies, save_cookies
from .base import (
    CaptchaRequiredError,
    Crawler,
    InvalidCredentialsError,
    LoginRequiredError,
    UA,
    dig,
    job_from_fields,
    resolve_url,
)

log = logging.getLogger("getwork.browser")


@asynccontextmanager
async def _browser(settings: Settings, *, headless_override: bool | None = None):
    """打开一次性浏览器实例，用完即关。"""
    browser_cfg = settings.browser or {}
    headless = browser_cfg.get("headless", True)
    if headless_override is not None:
        headless = headless_override
    p = await async_playwright().start()
    browser = await p.chromium.launch(headless=headless)
    try:
        yield browser
    finally:
        await browser.close()
        await p.stop()


def _viewport(settings: Settings) -> dict:
    vp = (settings.browser or {}).get("viewport", [1280, 900])
    return {"width": int(vp[0]), "height": int(vp[1])}


class BrowserCrawler(Crawler):
    """按 source.selectors 在渲染后的 DOM 里抓取；需要登录时抛 LoginRequiredError。"""

    async def _fetch(self) -> list[JobRecord]:
        if self.source.needs_login and not has_session(self.source.key):
            raise LoginRequiredError(f"{self.source.name} 需要登录后才能抓取")

        jobs: list[JobRecord] = []
        timeout = int(self.settings.timeouts_sec.get("page_load", 45)) * 1000
        api = self.source.api
        captured: list[Any] = []

        def on_response(resp: Any) -> None:
            if not api:
                return
            match = api.get("response_match") or api.get("url")
            if match and match in resp.url:
                captured.append(resp)

        async with _browser(self.settings) as browser:
            context = await browser.new_context(
                viewport=_viewport(self.settings), user_agent=UA
            )
            cookies = load_cookies(self.source.key)
            if cookies:
                await context.add_cookies(cookies)
            page = await context.new_page()
            # 响应捕获模式需在导航前挂监听
            if api:
                page.on("response", on_response)

            await page.goto(self.source.url, wait_until="domcontentloaded", timeout=timeout)
            if await self._is_login_wall(page):
                raise LoginRequiredError(f"{self.source.name} 跳转到了登录页")

            # 配了 api 就走「捕获页面自身岗位 API 响应」；否则渲染 DOM 后按 selectors 抓
            if api:
                try:
                    await page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    pass
                return await self._parse_captured(captured, api)

            if self.source.wait_for:
                try:
                    await page.wait_for_selector(
                        self.source.wait_for, timeout=timeout
                    )
                except Exception:
                    pass

            list_sel = self.source.selectors.get("list")
            if list_sel:
                items = await page.locator(list_sel).all()
                for el in items:
                    job = await self._extract_item(el)
                    if job:
                        jobs.append(job)
        return jobs

    async def _parse_captured(self, captured: list[Any], api: dict) -> list[JobRecord]:
        """把页面自身收到的岗位 API 响应解析成岗位列表（规避签名/anti-bot）。"""
        data_path = api.get("data_path") or "data.list"
        total_path = api.get("total_path")
        seen: set[str] = set()
        jobs: list[JobRecord] = []
        for resp in captured:
            try:
                body = await resp.body()
            except Exception:
                continue
            try:
                data = json.loads(body.decode("utf-8"))
            except Exception:
                continue
            items = dig(data, data_path) or []
            if isinstance(items, dict):
                items = [items]
            for it in items:
                if not isinstance(it, dict):
                    continue
                job = job_from_fields(it, self.source)
                if not job:
                    continue
                key = (job.title, job.location)
                if key not in seen:
                    seen.add(key)
                    jobs.append(job)
            total = dig(data, total_path) if total_path else None
            if total is not None and len(jobs) >= int(total):
                break
        if not captured:
            log.warning("%s: 未捕获到匹配 response_match 的岗位 API 响应", self.source.key)
            return jobs
        return jobs

    async def _is_login_wall(self, page: Any) -> bool:
        login_cfg = self.source.login or {}
        wall_url = login_cfg.get("wall_url_contains")
        if wall_url and wall_url in (page.url or ""):
            return True
        wall_sel = login_cfg.get("wall_selector")
        if wall_sel:
            try:
                return await page.is_visible(wall_sel)
            except Exception:
                return False
        return False

    async def _extract_item(self, el: Any) -> JobRecord | None:
        s = self.source.selectors
        title = await _loc_value(el, s.get("title"))
        if not title:
            return None
        link = await _loc_value(el, s.get("link")) if s.get("link") else ""
        return JobRecord(
            title=title,
            company=self.source.name,
            source=self.source.key,
            location=await _loc_value(el, s.get("location")),
            department=await _loc_value(el, s.get("department")),
            job_type=await _loc_value(el, s.get("job_type")),
            publish_date=await _loc_value(el, s.get("publish_date")),
            deadline=await _loc_value(el, s.get("deadline")),
            description=await _loc_value(el, s.get("description")),
            apply_url=resolve_url(self.source.url, link),
        )


async def _loc_value(el: Any, spec: str | None) -> str | None:
    """取元素某子节点文本或属性，支持 "h3 a@href" 形式。"""
    if not spec:
        return None
    css, _, attr = spec.partition("@")
    loc = el.locator(css) if css else el
    try:
        if attr:
            v = await loc.get_attribute(attr)
        else:
            v = await loc.inner_text()
    except Exception:
        return None
    if isinstance(v, str):
        v = v.strip()
        return v or None
    return None


async def login_source(
    source: Source,
    settings: Settings,
    username: str,
    password: str,
    headed: bool = False,
) -> dict:
    """执行登录并持久化 cookie，返回过期时间。"""
    login_cfg = source.login or {}
    if not login_cfg:
        raise InvalidCredentialsError(f"{source.name} 未配置 login 参数")

    timeout = int(settings.timeouts_sec.get("login", 60)) * 1000
    login_url = login_cfg.get("url") or source.url
    u_sel = login_cfg.get("username_selector")
    p_sel = login_cfg.get("password_selector")
    sub_sel = login_cfg.get("submit_selector")
    if not (u_sel and p_sel and sub_sel):
        raise InvalidCredentialsError(f"{source.name} 的 login 配置缺少选择器")

    async with _browser(settings, headless_override=False if headed else None) as browser:
        context = await browser.new_context(viewport=_viewport(settings), user_agent=UA)
        cookies = load_cookies(source.key)
        if cookies:
            await context.add_cookies(cookies)
        page = await context.new_page()
        await page.goto(login_url, wait_until="domcontentloaded", timeout=timeout)

        await page.locator(u_sel).fill(username)
        await page.locator(p_sel).fill(password)
        await page.locator(sub_sel).click()

        success_check = login_cfg.get("success_check") or {}
        error_sel = login_cfg.get("error_selector")
        ok = await _wait_login_result(page, success_check, error_sel, timeout, headed)

        if not ok:
            if error_sel and page.locator(error_sel).count():
                msg = await page.locator(error_sel).inner_text()
                raise InvalidCredentialsError(msg.strip() or "账号或密码错误")
            if headed:
                raise InvalidCredentialsError("登录未成功，请检查账号密码")
            raise CaptchaRequiredError(
                "登录疑似触发验证码/滑块，请用 headed=true 重试并手动完成"
            )

        await _drain(page)
        jar = await context.cookies()
        save_cookies(source.key, jar)
        expires = _min_expiry(jar)
        return {"expires_at": expires}


async def _wait_login_result(
    page: Any, success_check: dict, error_sel: str | None, timeout_ms: int, headed: bool
) -> bool:
    """等待登录结果：命中 success_check 或出现 error_selector 即定论。"""
    s_type = success_check.get("type")
    s_value = success_check.get("value")
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        if s_type == "url_contains" and s_value and s_value in (page.url or ""):
            return True
        if s_type == "selector" and s_value:
            try:
                if await page.locator(s_value).count():
                    return True
            except Exception:
                pass
        if error_sel:
            try:
                if await page.locator(error_sel).count():
                    return False
            except Exception:
                pass
        await asyncio.sleep(0.5)
    return False


async def _drain(page: Any) -> None:
    """给页面路由/持久化一点时间，避免登录跳转未完成就收 cookie。"""
    try:
        await page.wait_for_load_state("networkidle", timeout=5000)
    except Exception:
        pass


def _min_expiry(cookies: list[dict]) -> str | None:
    exps = [c.get("expires", -1) for c in cookies if c.get("expires", -1) > 0]
    if not exps:
        return None
    import datetime

    return datetime.datetime.fromtimestamp(
        min(exps), datetime.timezone.utc
    ).isoformat()
