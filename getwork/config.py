"""配置加载：companies.yaml（岗位来源）+ .env（SMTP 等凭据）。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

# getwork/ 的上一级即项目根，用它解析路径，避免依赖当前工作目录。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "companies.yaml"
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"

# 运行时由 add_source 工具追加/覆盖的来源，与手写的 companies.yaml 分开，
# 避免机器改写破坏手写注释。
CUSTOM_SOURCES_NAME = "sources.custom.yaml"

load_dotenv(PROJECT_ROOT / ".env")

VALID_STRATEGIES = ("platform", "static", "dynamic")

# 可由 CLI 参数 --config 覆盖，缺省用项目默认路径。
_CONFIG_PATH_OVERRIDE: Path | None = None


def set_config_path(path: str | Path | None) -> None:
    global _CONFIG_PATH_OVERRIDE
    _CONFIG_PATH_OVERRIDE = Path(path) if path else None


@dataclass
class Settings:
    output_dir: str = "data/output"
    timeouts_sec: dict = field(
        default_factory=lambda: {"request": 20, "page_load": 45, "login": 60}
    )
    browser: dict = field(
        default_factory=lambda: {"headless": True, "viewport": [1280, 900]}
    )


@dataclass
class Source:
    """一个岗位来源（一家公司/一个入口）。字段全部配置化，无硬编码。"""

    key: str
    name: str
    strategy: str = "static"  # platform | static | dynamic
    url: str = ""
    platform: str | None = None
    company_key: str | None = None
    needs_login: bool = False
    wait_for: str | None = None
    selectors: dict = field(default_factory=dict)
    api: dict = field(default_factory=dict)
    fields: dict = field(default_factory=dict)
    detail: dict | None = None
    login: dict | None = None

    def as_meta(self) -> dict:
        return {
            "key": self.key,
            "name": self.name,
            "strategy": self.strategy,
            "platform": self.platform,
            "company_key": self.company_key,
            "needs_login": self.needs_login,
            "url": self.url,
        }


class ConfigError(Exception):
    pass


class Config:
    def __init__(self, settings: Settings, sources: list[Source], path: Path):
        self.settings = settings
        self.sources = sources
        self.path = path
        self.sources_by_key = {s.key: s for s in sources}

    def get_source(self, key: str) -> Source | None:
        return self.sources_by_key.get(key)

    def data_dir(self) -> Path:
        return DEFAULT_DATA_DIR


def _parse_settings(raw: dict) -> Settings:
    s = Settings()
    s_raw = raw.get("settings") or {}
    s.output_dir = s_raw.get("output_dir", s.output_dir)
    if "timeouts_sec" in s_raw:
        s.timeouts_sec = {**s.timeouts_sec, **s_raw["timeouts_sec"]}
    if "browser" in s_raw:
        s.browser = {**s.browser, **s_raw["browser"]}
    return s


def _parse_source(raw: dict) -> Source:
    key = raw.get("key")
    if not key:
        raise ConfigError(f"source 缺少 key: {raw!r}")
    strategy = raw.get("strategy", "static")
    if strategy not in VALID_STRATEGIES:
        raise ConfigError(f"source {key}: 未知 strategy {strategy!r}（允许 {VALID_STRATEGIES}）")
    return Source(
        key=key,
        name=raw.get("name", key),
        strategy=strategy,
        url=raw.get("url", ""),
        platform=raw.get("platform"),
        company_key=raw.get("company_key"),
        needs_login=bool(raw.get("needs_login", False)),
        wait_for=raw.get("wait_for"),
        selectors=raw.get("selectors") or {},
        api=raw.get("api") or {},
        fields=raw.get("fields") or {},
        detail=raw.get("detail"),
        login=raw.get("login"),
    )


def load_config(path: str | Path | None = None) -> Config:
    """加载配置。配置文件缺失时返回空来源（工具仍可正常响应）。"""
    config_path = Path(path) if path else (_CONFIG_PATH_OVERRIDE or DEFAULT_CONFIG)
    if not config_path.exists():
        return Config(_parse_settings({}), [], config_path)

    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise ConfigError(f"解析 {config_path} 失败: {e}") from e

    settings = _parse_settings(raw)
    sources = _load_sources(raw, config_path.parent / CUSTOM_SOURCES_NAME)
    return Config(settings, sources, config_path)


def _load_sources(raw: dict, custom_path: Path) -> list[Source]:
    """companies.yaml 的来源 + 自定义来源（同名 key 覆盖）。"""
    srcs = [_parse_source(s) for s in raw.get("sources") or []]
    if custom_path.exists():
        try:
            custom = yaml.safe_load(custom_path.read_text(encoding="utf-8")) or []
        except yaml.YAMLError:
            return srcs
        if isinstance(custom, list):
            custom_keys = {
                c.get("key") for c in custom if isinstance(c, dict) and c.get("key")
            }
            srcs = [s for s in srcs if s.key not in custom_keys]
            srcs += [_parse_source(c) for c in custom if isinstance(c, dict)]
    return srcs


def add_source_entry(entry: dict) -> Source:
    """追加/覆盖一个来源到自定义文件（sources.custom.yaml），返回解析后的 Source。"""
    src = _parse_source(entry)
    custom_path = (_CONFIG_PATH_OVERRIDE or DEFAULT_CONFIG).parent / CUSTOM_SOURCES_NAME
    data: list[dict] = []
    if custom_path.exists():
        try:
            loaded = yaml.safe_load(custom_path.read_text(encoding="utf-8")) or []
        except yaml.YAMLError:
            loaded = []
        if isinstance(loaded, list):
            data = [d for d in loaded if isinstance(d, dict)]
    data = [d for d in data if d.get("key") != src.key]
    data.append(entry)
    custom_path.parent.mkdir(parents=True, exist_ok=True)
    custom_path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    return src


def resolve_output_dir(settings: Settings, data_dir: Path | None = None) -> Path:
    base = data_dir or DEFAULT_DATA_DIR
    p = Path(settings.output_dir)
    if not p.is_absolute():
        p = base / p
    p.mkdir(parents=True, exist_ok=True)
    return p
