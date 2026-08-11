"""真实端到端：抓 6 家校招站 → 汇总简报 → 渲染 → 邮件推送。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

SOURCES = ["tencent", "jd", "bytedance", "alibaba", "dewu", "xfusion"]
NAME = {"tencent": "腾讯", "jd": "京东", "bytedance": "字节跳动", "alibaba": "阿里巴巴", "dewu": "得物", "xfusion": "超聚变"}


async def call(session: ClientSession, name: str, args: dict) -> dict:
    res = await session.call_tool(name, args)
    text = "\n".join(c.text if hasattr(c, "text") else str(c) for c in res.content)
    return json.loads(text)


def build_briefing(jobs_by_source: dict[str, list]) -> str:
    def excerpt(s, n=110):
        if not s:
            return None
        s = " ".join(s.split())
        return s if len(s) <= n else s[:n] + "…"

    lines = ["# 实习岗位日报", "", f"> 由 getWork 自动抓取生成 · 覆盖 {len(jobs_by_source)} 家公司", ""]
    lines.append("## 总览")
    lines.append("")
    lines.append("| 公司 | 岗位数 | 示例岗位 |")
    lines.append("|---|---|---|")
    for src, jobs in jobs_by_source.items():
        sample = jobs[0]["title"] if jobs else "-"
        lines.append(f"| {NAME.get(src, src)} | {len(jobs)} | {sample} |")
    lines.append("")
    for src, jobs in jobs_by_source.items():
        lines.append(f"## {NAME.get(src, src)}（{len(jobs)} 条）")
        lines.append("")
        for j in jobs[:5]:
            lines.append(f"### {j['title']}")
            lines.append("")
            req = excerpt(j.get('requirement')) or excerpt(j.get('description'))
            if req:
                lines.append(f"- **要求**：{req}")
            loc = j.get('location') or '-'
            typ = j.get('job_type') or '-'
            date = j.get('publish_date') or '-'
            lines.append(f"- 地点：{loc} · 类型：{typ} · 发布：{date}")
            lines.append(f"- [查看岗位详情]({j.get('apply_url') or '#'})")
            if not j.get('requirement'):
                lines.append(f"> 官网未提供岗位要求，建议点上方链接到详情页查看。")
            lines.append("")
    return "\n".join(lines)


async def main():
    server = StdioServerParameters(command="uv", args=["run", "python", "-m", "getwork"], env=None)
    async with stdio_client(server) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            jobs_by_source = {}
            total = 0
            for src in SOURCES:
                r = await call(s, "crawl_jobs", {"source": src})
                jobs = r.get("jobs", [])
                jobs_by_source[src] = jobs
                total += len(jobs)
                print(f"{src}: status={r.get('status')} count={len(jobs)}")
            md = build_briefing(jobs_by_source)
            info = await call(s, "render_briefing", {"title": "实习岗位日报", "markdown": md})
            print("render:", info)
            res = await call(s, "send_email", {
                "to": "ryaovenking@henu.edu.cn",
                "subject": f"实习岗位日报（{total} 条）",
                "html": Path("data/" + info["html_path"]).read_text(encoding="utf-8"),
                "attachment_path": info["png_path"],
            })
            print("send:", json.dumps(res, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
