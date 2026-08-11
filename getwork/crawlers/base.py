"""爬虫基类与共享工具。"""

from __future__ import annotations

import datetime
from abc import ABC, abstractmethod
from typing import Any

from ..config import Settings, Source
from ..models import JobRecord

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


class LoginRequiredError(Exception):
    """页面需要登录才能抓取。"""


class InvalidCredentialsError(Exception):
    """登录失败：账号密码错误或被拒。"""


class CaptchaRequiredError(Exception):
    """登录触发验证码/滑块，需要人工介入。"""


class Crawler(ABC):
    """所有策略共有的接口。实现类只负责拿到归一化的 JobRecord 列表。"""

    def __init__(self, source: Source, settings: Settings):
        self.source = source
        self.settings = settings

    async def fetch(self, since_days: int | None = None) -> list[JobRecord]:
        jobs = await self._fetch()
        if since_days and since_days > 0:
            jobs = filter_by_since_days(jobs, since_days)
        return jobs

    @abstractmethod
    async def _fetch(self) -> list[JobRecord]:
        ...

    @property
    def timeout(self) -> float:
        return float(self.settings.timeouts_sec.get("request", 20))


def dig(obj: Any, dotted: str) -> Any:
    """按点分路径取 JSON 字段，如 "data.jobList[0]" 或 "data.jobList"（列表元素用遍历）。"""
    if not dotted:
        return None
    cur = obj
    for part in dotted.split("."):
        if cur is None:
            return None
        if isinstance(cur, list):
            results = []
            for item in cur:
                v = dig(item, part)
                if v is not None:
                    results.append(v)
            return results if results else None
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def first_text(value: Any) -> str | None:
    """把可能为 str/list/dict 的提取值压成单条字符串。"""
    if value is None:
        return None
    if isinstance(value, str):
        s = value.strip()
        return s or None
    if isinstance(value, list):
        for v in value:
            s = first_text(v)
            if s:
                return s
        return None
    if isinstance(value, dict):
        for k in ("name", "label", "value", "text"):
            if k in value:
                s = first_text(value[k])
                if s:
                    return s
        return None
    return str(value).strip()


def resolve_url(base: str, href: str | None) -> str:
    from urllib.parse import urljoin, urlparse

    if not href:
        return ""
    href = href.strip()
    if href.startswith(("javascript:", "mailto:", "#")):
        return ""
    if href.startswith("//"):
        return f"{urlparse(base).scheme}:{href}"
    return urljoin(base, href)


def filter_by_since_days(jobs: list[JobRecord], since_days: int) -> list[JobRecord]:
    """best-effort：能解析 publish_date 的按日期过滤；解析不了的保留（交给 Agent 判断）。"""
    if not since_days or since_days <= 0:
        return jobs

    cutoff = datetime.date.today() - datetime.timedelta(days=since_days)
    kept = []
    for j in jobs:
        date = _parse_date(j.publish_date)
        if date is None or date >= cutoff:
            kept.append(j)
    return kept


def _parse_date(s: str | None) -> datetime.date | None:
    if not s:
        return None
    s = s.strip()
    # ISO: 2026-08-11 或 2026-08-11 10:30
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None
