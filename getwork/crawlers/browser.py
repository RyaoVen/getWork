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
    first_text,
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


async def _read_json(resp: Any) -> Any:
    """读取响应体并解析 JSON，失败返回 None。"""
    try:
        body = await resp.body()
    except Exception:
        return None
    try:
        return json.loads(body.decode("utf-8"))
    except Exception:
        return None


async def _page_fetch_json(page: Any, url: str, method: str, body_obj: dict, headers: dict) -> Any:
    """在页面上下文里 fetch，返回解析后的 JSON；非 JSON 时包成 {"__raw__": ...}。"""
    body_js = json.dumps(body_obj) if body_obj else "undefined"
    js = (
        "async () => {"
        f"const h = {json.dumps(headers)};"
        f"const r = await fetch({json.dumps(url)}, {{"
        f"method: {json.dumps(method)},"
        "headers: Object.assign({'Content-Type': 'application/json'}, h),"
        f"body: {body_js}"
        "});"
        "const t = await r.text();"
        "try { return JSON.parse(t); } catch { return { __raw__: t.slice(0, 300), __status__: r.status }; }"
        "}"
    )
    return await page.evaluate(js)


async def _replay_request(
    page: Any,
    req: dict,
    page_param: str,
    pg: int,
    page_size: int,
    page_size_key: str,
    paginate_in_body: bool,
    offset_mode: bool,
) -> Any:
    """按捕获到的原始请求重放下一页，替换分页参数。"""
    from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

    url = req.get("url", "")
    method = req.get("method", "GET").upper()
    # content-type 由 _page_fetch_json 统一设置，避免大小写重复头
    headers = {k: v for k, v in (req.get("headers") or {}).items() if k.lower() != "content-type"}
    val = (pg - 1) * page_size if offset_mode else pg

    if method in ("POST", "PUT", "PATCH") and paginate_in_body:
        body: dict = {}
        pd = req.get("post_data")
        if pd:
            try:
                parsed = json.loads(pd)
                if isinstance(parsed, dict):
                    body = parsed
            except Exception:
                pass
        body[page_param] = val
        body[page_size_key] = page_size
        return await _page_fetch_json(page, url, method, body, headers)

    u = urlparse(url)
    q = dict(parse_qsl(u.query))
    q[page_param] = str(val)
    q[page_size_key] = str(page_size)
    url2 = urlunparse(u._replace(query=urlencode(q)))
    return await _page_fetch_json(page, url2, method, {}, headers)


def _fmt_template(tpl: str, raw: dict) -> str:
    """把含 {字段} 的模板按 raw 字典填充；不含模板时原样返回。"""
    if not isinstance(tpl, str):
        return str(tpl)
    if "{" not in tpl:
        return tpl

    def repl(m: re.Match) -> str:
        v = dig(raw, m.group(1))
        return first_text(v) or ""

    return re.sub(r"\{([a-zA-Z0-9_.]+)\}", repl, tpl)


class BrowserCrawler(Crawler):
    """按 source.selectors 在渲染后的 DOM 里抓取；需要登录时抛 LoginRequiredError。"""

    async def _fetch(self) -> list[JobRecord]:
        if self.source.needs_login and not has_session(self.source.key):
            raise LoginRequiredError(f"{self.source.name} 需要登录后才能抓取")

        jobs: list[JobRecord] = []
        timeout = int(self.settings.timeouts_sec.get("page_load", 45)) * 1000
        api = self.source.api
        captured: list[Any] = []
        first_req: dict | None = None

        def match_url(u: str) -> bool:
            if not api:
                return False
            m = api.get("response_match") or api.get("url")
            return bool(m and m in u)

        def on_response(resp: Any) -> None:
            nonlocal first_req
            if not match_url(resp.url):
                return
            captured.append(resp)
            if first_req is None:
                req = resp.request
                first_req = {
                    "url": req.url,
                    "method": req.method,
                    "headers": {
                        k: v for k, v in req.headers.items()
                        if k.lower() not in ("content-length", "content-type", "cookie")
                    },
                    "post_data": req.post_data,
                }

        async with _browser(self.settings) as browser:
            context = await browser.new_context(
                viewport=_viewport(self.settings), user_agent=UA
            )
            cookies = load_cookies(self.source.key)
            if cookies:
                await context.add_cookies(cookies)
            page = await context.new_page()
            # 捕获模式需在导航前挂监听
            if api:
                page.on("response", on_response)

            await page.goto(self.source.url, wait_until="domcontentloaded", timeout=timeout)
            if await self._is_login_wall(page):
                raise LoginRequiredError(f"{self.source.name} 跳转到了登录页")

            # 配了 api 就走「捕获页面自身岗位 API 响应 + 翻页重放」；否则渲染 DOM 后按 selectors 抓
            if api:
                try:
                    await page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    pass
                jobs = await self._parse_captured(page, captured, api, first_req)
                if self.source.detail:
                    jobs = await self._enrich_details(page, jobs, self.source.detail)
                return jobs

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

    async def _parse_captured(
        self, page: Any, captured: list[Any], api: dict, first_req: dict | None
    ) -> list[JobRecord]:
        """解析页面自身收到的岗位 API 响应；滚动/点下一页触发页面自己加载更多。"""
        data_path = api.get("data_path") or "data.list"
        total_path = api.get("total_path")
        seen: set[tuple] = set()
        jobs: list[JobRecord] = []
        idx = 0

        async def drain() -> int:
            nonlocal idx
            added = 0
            while idx < len(captured):
                data = await _read_json(captured[idx])
                idx += 1
                if data is not None:
                    added += self._consume_items(data, data_path, total_path, seen, jobs)
            return added

        await drain()
        if not captured:
            log.warning("%s: 未捕获到匹配 response_match 的岗位 API 响应", self.source.key)
            return jobs

        # 滚动触发懒加载
        for _ in range(int(api.get("scroll_more") or 0)):
            added = await drain()
            if added == 0:
                break
            try:
                await page.mouse.wheel(0, 8000)
            except Exception:
                break
            await page.wait_for_timeout(1500)

        # 点击「下一页」按钮翻页
        sel = api.get("load_more_selector")
        if sel:
            for _ in range(int(api.get("load_more_rounds") or 5)):
                btn = page.locator(sel).first
                try:
                    if await btn.count() == 0:
                        break
                    cls = (await btn.get_attribute("class")) or ""
                    if "disabled" in cls or await btn.get_attribute("disabled") is not None:
                        break
                    await btn.click(timeout=5000)
                except Exception:
                    break
                await page.wait_for_timeout(1500)
                if await drain() == 0:
                    await page.wait_for_timeout(1200)
                    if await drain() == 0:
                        break

        # 翻页重放（配置了 page_param 才启用）
        if api.get("page_param") and first_req:
            try:
                await self._paginate(page, api, first_req, seen, jobs)
            except Exception:
                log.exception("%s: 翻页重放失败，仅保留已捕获页", self.source.key)
        return jobs

    def _consume_items(
        self, data: Any, data_path: str, total_path: str | None,
        seen: set[tuple], jobs: list[JobRecord],
    ) -> int:
        items = dig(data, data_path) or []
        if isinstance(items, dict):
            items = [items]
        added = 0
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
                added += 1
        return added

    async def _paginate(
        self, page: Any, api: dict, first_req: dict, seen: set[tuple], jobs: list[JobRecord]
    ) -> None:
        page_param = api.get("page_param")
        page_size = int(api.get("page_size") or 20)
        page_size_key = api.get("page_size_key") or "pageSize"
        paginate_in_body = bool(api.get("paginate_in_body"))
        offset_mode = bool(api.get("offset_mode"))
        max_pages = int(api.get("max_pages") or 20)
        data_path = api.get("data_path") or "data.list"
        total_path = api.get("total_path")
        pg = 2
        while pg <= max_pages:
            data = await _replay_request(
                page, first_req, page_param, pg, page_size, page_size_key,
                paginate_in_body, offset_mode,
            )
            if data is None or (isinstance(data, dict) and "__raw__" in data):
                break
            added = self._consume_items(data, data_path, total_path, seen, jobs)
            if added == 0:
                break
            total = dig(data, total_path) if total_path else None
            if total is not None and len(jobs) >= int(total):
                break
            pg += 1

    async def _enrich_details(self, page: Any, jobs: list[JobRecord], cfg: dict) -> list[JobRecord]:
        """逐岗位调详情接口，补全 description/requirement/location（列表 API 不含详情时用）。"""
        url_tpl = cfg.get("url")
        if not url_tpl:
            return jobs
        method = (cfg.get("method") or "GET").upper()
        body_tpl = cfg.get("body") or {}
        data_path = cfg.get("data_path")
        fields = cfg.get("fields") or {}
        throttle = float(cfg.get("throttle") or 0.2)
        for job in jobs:
            raw = job.raw or {}
            url = _fmt_template(url_tpl, raw)
            if not url:
                continue
            body = {k: _fmt_template(v, raw) for k, v in body_tpl.items()} if body_tpl else {}
            data = await _page_fetch_json(page, url, method, body, {})
            if isinstance(data, dict) and "__raw__" in data:
                continue
            detail = dig(data, data_path) if data_path else data
            if not isinstance(detail, dict):
                detail = data
            if not isinstance(detail, dict):
                continue
            if fields.get("description"):
                v = first_text(dig(detail, fields["description"]))
                if v:
                    job.description = v
            if fields.get("requirement"):
                v = first_text(dig(detail, fields["requirement"]))
                if v:
                    job.requirement = v
            if fields.get("location"):
                v = first_text(dig(detail, fields["location"]))
                if v:
                    job.location = v
            if throttle:
                await page.wait_for_timeout(int(throttle * 1000))
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
