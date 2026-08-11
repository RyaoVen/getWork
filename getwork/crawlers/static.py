"""static 策略：普通 HTML 页面，httpx + BeautifulSoup + CSS 选择器。"""

from __future__ import annotations

from typing import Any

import httpx
from bs4 import BeautifulSoup

from ..models import JobRecord
from .base import Crawler, UA, resolve_url


class StaticCrawler(Crawler):
    """按 source.selectors 抓取静态页列表，支持翻页（next 链接）。"""

    MAX_PAGES = 50

    async def _fetch(self) -> list[JobRecord]:
        jobs: list[JobRecord] = []
        url: str | None = self.source.url
        page = 0
        async with httpx.AsyncClient(
            timeout=self.timeout, headers={"User-Agent": UA}, follow_redirects=True
        ) as client:
            while url and page < self.MAX_PAGES:
                soup = await self._fetch_soup(client, url)
                items = soup.select(self._sel("list") or "body > *")
                if not items:
                    break
                for item in items:
                    job = self._extract_item(item)
                    if job:
                        jobs.append(job)
                page += 1
                url = self._next_url(soup, url)
        return jobs

    async def _fetch_soup(self, client: httpx.AsyncClient, url: str) -> BeautifulSoup:
        resp = await client.get(url)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "lxml")

    def _sel(self, name: str) -> str | None:
        v = self.source.selectors.get(name)
        return v if isinstance(v, str) and v else None

    def _extract_item(self, item: Any) -> JobRecord | None:
        title = _select_text(item, self._sel("title"))
        if not title:
            return None
        link = _select_attr(item, self._sel("link"), "href") if self._sel("link") else ""
        apply_url = resolve_url(self.source.url, link)
        return JobRecord(
            title=title,
            company=self.source.name,
            source=self.source.key,
            location=_select_text(item, self._sel("location")),
            department=_select_text(item, self._sel("department")),
            job_type=_select_text(item, self._sel("job_type")),
            publish_date=_select_text(item, self._sel("publish_date")),
            deadline=_select_text(item, self._sel("deadline")),
            description=_select_text(item, self._sel("description")),
            apply_url=apply_url,
            raw={"html": str(item)[:2000]},
        )

    def _next_url(self, soup: BeautifulSoup, current: str) -> str | None:
        pag = self._sel("pagination")
        if not pag:
            return None
        node = soup.select_one(pag)
        if not node:
            return None
        href = node.get("href") if hasattr(node, "get") else None
        return resolve_url(current, href) if href else None


def _select_text(node: Any, css: str | None) -> str | None:
    if not css:
        return None
    el = node.select_one(css) if css else None
    return el.get_text(" ", strip=True) if el else None


def _select_attr(node: Any, css: str | None, attr: str) -> str | None:
    if not css:
        return None
    # 支持 "h3 a@href" 形式；若无 @ 则取节点本身属性
    sel, _, explicit_attr = css.partition("@")
    target_attr = explicit_attr or attr
    el = node.select_one(sel) if sel else node
    return el.get(target_attr) if el and hasattr(el, "get") else None
