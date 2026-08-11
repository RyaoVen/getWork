"""简报管线：Markdown → HTML（Jinja2 模板）→ PNG（Playwright 整页截图）。"""

from __future__ import annotations

import datetime
import logging
from pathlib import Path

import markdown
from jinja2 import Environment, FileSystemLoader
from playwright.async_api import async_playwright

from .config import DEFAULT_DATA_DIR, PROJECT_ROOT

log = logging.getLogger("getwork.briefing")

TEMPLATES_DIR = PROJECT_ROOT / "getwork" / "templates"
_EXTENSIONS = ["tables", "fenced_code", "sane_lists", "nl2br"]


def _ts() -> str:
    return datetime.datetime.now().strftime("%Y%m%d-%H%M%S")


def _output_dir(output_dir: Path | None) -> Path:
    out = output_dir or (DEFAULT_DATA_DIR / "output")
    out = out if out.is_absolute() else DEFAULT_DATA_DIR / out
    out.mkdir(parents=True, exist_ok=True)
    return out


def render_html(markdown_text: str, title: str | None = None) -> tuple[str, str]:
    """把 Markdown 渲染成完整 HTML 字符串，返回 (html, file_stem)。"""
    body = markdown.markdown(markdown_text, extensions=_EXTENSIONS)
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    template = env.get_template("briefing.html.j2")
    html = template.render(
        title=title or "岗位简报",
        body=body,
        generated_at=datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
    )
    return html, f"briefing-{_ts()}"


async def screenshot_html(html_path: Path, output_dir: Path) -> Path:
    """用 headless Chromium 对 HTML 文件整页截图成 PNG。"""
    png_path = output_dir / f"{html_path.stem}.png"
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await browser.new_page(
                viewport={"width": 900, "height": 1400},
                device_scale_factor=2,
            )
            await page.goto(html_path.as_uri(), wait_until="networkidle")
            await page.screenshot(path=str(png_path), full_page=True)
        finally:
            await browser.close()
    return png_path


async def render_briefing(
    markdown_text: str,
    title: str | None = None,
    output_dir: Path | None = None,
) -> dict:
    """渲染简报，返回 {html_path, png_path}（相对 data/ 的路径）。"""
    out = _output_dir(output_dir)
    html, stem = render_html(markdown_text, title)
    html_path = out / f"{stem}.html"
    html_path.write_text(html, encoding="utf-8")
    try:
        png_path = await screenshot_html(html_path, out)
    except Exception:
        log.warning("PNG 截图失败，仅返回 HTML", exc_info=True)
        png_path = None
    return {
        "html_path": str(html_path.relative_to(DEFAULT_DATA_DIR)),
        "png_path": str(png_path.relative_to(DEFAULT_DATA_DIR)) if png_path else None,
    }
