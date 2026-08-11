"""MCP server 入口：注册 getWork 全部工具（stdio 传输）。"""

from __future__ import annotations

import datetime
import logging
from pathlib import Path

from mcp.server import MCPServer

from . import __version__
from .briefing import render_briefing as _render_briefing
from .config import DEFAULT_DATA_DIR, ConfigError, load_config
from .crawlers import (
    CaptchaRequiredError,
    InvalidCredentialsError,
    LoginRequiredError,
    get_crawler,
)
from .crawlers.browser import login_source
from .mailer import (
    MailAuthError,
    Mailer,
    MailerConfigError,
    MailSendError,
    send_email as _send_email,
)
from .models import to_dicts
from . import sessions

log = logging.getLogger("getwork.server")

server = MCPServer(
    "getwork",
    version=__version__,
    instructions=(
        "getWork MCP：抓取公司校招/实习岗位、渲染简报、邮件推送。"
        "典型流程：list_sources → crawl_jobs（遇 login_required 则 login 后重试）"
        "→ 整理 Markdown → render_briefing → send_email。"
        "SMTP 未配置时 send_email 会返回 not_configured，可让用户填写 .env。"
    ),
)


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _resolve_data_path(p: str) -> Path:
    path = Path(p)
    return path if path.is_absolute() else DEFAULT_DATA_DIR / path


def _source_missing(source: str) -> dict:
    return {
        "status": "error",
        "reason": "unknown_source",
        "message": f"未知来源 {source!r}，先用 list_sources 查看可用来源",
    }


@server.tool()
async def list_sources() -> dict:
    """列出已配置的岗位来源（公司/入口）及其策略与登录需求。"""
    try:
        cfg = load_config()
    except ConfigError as e:
        return {"status": "error", "reason": "config_error", "message": str(e)}
    return {
        "status": "ok",
        "sources": [s.as_meta() for s in cfg.sources],
        "config_path": str(cfg.path),
    }


@server.tool()
async def crawl_jobs(source: str, since_days: int = 0) -> dict:
    """抓取指定来源的岗位列表。需要登录时返回 login_required。

    Args:
        source: 来源 key（list_sources 可见）
        since_days: 只看最近 N 天发布的岗位（0 表示全部）
    """
    try:
        cfg = load_config()
    except ConfigError as e:
        return {"status": "error", "reason": "config_error", "message": str(e)}
    s = cfg.get_source(source)
    if not s:
        return _source_missing(source)
    try:
        crawler = get_crawler(s, cfg.settings)
        jobs = await crawler.fetch(since_days or None)
    except LoginRequiredError as e:
        return {
            "status": "login_required",
            "source": source,
            "message": str(e),
            "hint": "调用 login 传入该来源的账号密码，成功后重试 crawl_jobs",
        }
    except Exception as e:
        log.exception("crawl %s failed", source)
        return {"status": "error", "reason": "crawl_failed", "message": str(e)}
    return {
        "status": "ok",
        "source": source,
        "fetched_at": _now_iso(),
        "count": len(jobs),
        "jobs": to_dicts(jobs),
    }


@server.tool()
async def login(source: str, username: str, password: str, headed: bool = False) -> dict:
    """登录需要账号的来源（仅 dynamic 策略）。密码只用于本次登录，不落盘。

    Args:
        source: 来源 key
        username: 账号
        password: 密码（由 Agent 向用户询问后传入）
        headed: 是否弹出真实浏览器窗口（遇验证码/滑块时用 True 让用户手动完成）
    """
    try:
        cfg = load_config()
    except ConfigError as e:
        return {"status": "error", "reason": "config_error", "message": str(e)}
    s = cfg.get_source(source)
    if not s:
        return _source_missing(source)
    if s.strategy != "dynamic":
        return {
            "status": "error",
            "reason": "unsupported",
            "message": f"{source} 是 {s.strategy} 策略，无需/不支持账号登录",
        }
    try:
        result = await login_source(s, cfg.settings, username, password, headed=headed)
    except InvalidCredentialsError as e:
        return {"status": "error", "reason": "invalid_credentials", "message": str(e)}
    except CaptchaRequiredError as e:
        return {"status": "error", "reason": "captcha_required", "message": str(e)}
    except Exception as e:
        log.exception("login %s failed", source)
        return {"status": "error", "reason": "login_failed", "message": str(e)}
    return {"status": "ok", "source": source, "expires_at": result.get("expires_at")}


@server.tool()
async def logout(source: str) -> dict:
    """清除指定来源已保存的登录会话（cookie）。"""
    cleared = sessions.clear_cookies(source)
    return {"status": "ok", "source": source, "cleared": cleared}


@server.tool()
async def render_briefing(markdown: str, title: str | None = None) -> dict:
    """把 Agent 写好的 Markdown 简报渲染成 HTML 邮件正文 + PNG 长图。

    Args:
        markdown: 简报的 Markdown 内容（建议含表格）
        title: 简报标题（可选）
    """
    try:
        result = await _render_briefing(markdown, title)
    except Exception as e:
        log.exception("render_briefing failed")
        return {"status": "error", "reason": "render_failed", "message": str(e)}
    return {"status": "ok", **result}


@server.tool()
async def send_email(
    to: str | None = None,
    subject: str = "",
    html: str = "",
    attachment_path: str | None = None,
) -> dict:
    """发送邮件（HTML 正文 + 可选 PNG 附件）。

    Args:
        to: 收件邮箱；不传时用 .env 的 SMTP_TO
        subject: 主题
        html: HTML 正文
        attachment_path: 附件路径（render_briefing 返回的 png_path）
    """
    mailer = Mailer()
    recipient = to or mailer.default_to
    if not recipient:
        return {
            "status": "error",
            "reason": "missing_recipient",
            "message": "未指定收件人，且 .env 未配置 SMTP_TO",
        }
    if not subject or not html:
        return {
            "status": "error",
            "reason": "missing_content",
            "message": "subject 和 html 均不能为空",
        }
    att = _resolve_data_path(attachment_path) if attachment_path else None
    try:
        _send_email(recipient, subject, html, att, mailer=mailer)
    except MailerConfigError as e:
        return {
            "status": "error",
            "reason": "not_configured",
            "message": f"{e}（也可直接告诉用户补充 .env）",
        }
    except MailAuthError as e:
        return {"status": "error", "reason": "auth_failed", "message": str(e)}
    except MailSendError as e:
        return {"status": "error", "reason": "smtp_error", "message": str(e)}
    return {"status": "ok", "to": recipient, "attachment": str(att) if att else None}
