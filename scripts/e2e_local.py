"""本地端到端演示：登录 → 抓全部来源 → 汇总成 Markdown 简报 → 渲染 HTML+PNG。

真实邮件推送需在 .env 配置 SMTP 后，由 Agent 用 send_email 完成。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG = PROJECT_ROOT / "scripts" / "fixtures" / "companies.test.yaml"


async def call(session: ClientSession, name: str, args: dict) -> dict:
    res = await session.call_tool(name, args)
    text = "\n".join(
        c.text if hasattr(c, "text") else str(c) for c in res.content
    )
    return json.loads(text)


def build_briefing(jobs_by_source: dict[str, list]) -> str:
    lines = [
        "# 实习岗位日报（本地演示）",
        "",
        f"共抓取 {len(jobs_by_source)} 个来源，匹配岗位如下：",
        "",
    ]
    name_map = {"local-static": "本地测试(静态)", "local-platform": "本地测试(平台API)", "local-login": "本地测试(需登录)"}
    for src, jobs in jobs_by_source.items():
        lines.append(f"## {name_map.get(src, src)}（{len(jobs)} 条）")
        lines.append("")
        lines.append("| 岗位 | 地点 | 部门 | 发布日期 | 链接 |")
        lines.append("|---|---|---|---|---|")
        for j in jobs:
            lines.append(
                f"| {j['title']} | {j['location'] or '-'} | {j['department'] or '-'} "
                f"| {j['publish_date'] or '-'} | [{j['apply_url']}]({j['apply_url']}) |"
            )
        lines.append("")
    return "\n".join(lines)


async def main() -> None:
    server = StdioServerParameters(
        command="uv",
        args=["--directory", str(PROJECT_ROOT), "run", "python", "-m", "getwork", "--config", str(CONFIG)],
        env=None,
    )
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            await call(session, "login", {"source": "local-login", "username": "demo", "password": "secret"})
            jobs_by_source = {}
            for src in ("local-static", "local-platform", "local-login"):
                r = await call(session, "crawl_jobs", {"source": src})
                jobs_by_source[src] = r.get("jobs", [])
                print(f"{src}: status={r.get('status')} count={len(jobs_by_source[src])}")
            md = build_briefing(jobs_by_source)
            result = await call(session, "render_briefing", {"title": "实习岗位日报", "markdown": md})
            print("render_briefing:", json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
