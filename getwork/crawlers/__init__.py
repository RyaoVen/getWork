"""策略注册表：按 source.strategy 选择对应爬虫。"""

from __future__ import annotations

from ..config import Settings, Source
from .base import (
    CaptchaRequiredError,
    Crawler,
    InvalidCredentialsError,
    LoginRequiredError,
)
from .browser import BrowserCrawler
from .platform import PlatformCrawler
from .static import StaticCrawler

__all__ = [
    "Crawler",
    "LoginRequiredError",
    "InvalidCredentialsError",
    "CaptchaRequiredError",
    "get_crawler",
]


def get_crawler(source: Source, settings: Settings) -> Crawler:
    if source.strategy == "static":
        return StaticCrawler(source, settings)
    if source.strategy == "platform":
        return PlatformCrawler(source, settings)
    if source.strategy == "dynamic":
        return BrowserCrawler(source, settings)
    raise ValueError(f"未知 strategy: {source.strategy}")
