"""画像匹配版简报：抓全部岗位 → 按 profile 打分过滤 → 生成带匹配度的简报 → 渲染 → 发送。"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import yaml
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from getwork.match import filter_and_score, score_label
from getwork.models import JobRecord
SOURCES = ["tencent", "jd", "bytedance", "alibaba", "dewu", "xfusion"]
NAME = {"tencent": "腾讯", "jd": "京东", "bytedance": "字节跳动", "alibaba": "阿里巴巴", "dewu": "得物", "xfusion": "超聚变"}


def load_profile() -> dict:
    p = PROJECT_ROOT / "config" / "profile.yaml"
    if not p.exists():
        return {}
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return raw.get("profile") or {}


async def crawl(session: ClientSession, src: str) -> list[JobRecord]:
    res = await session.call_tool("crawl_jobs", {"source": src})
    text = "\n".join(c.text if hasattr(c, "text") else str(c) for c in res.content)
    data = json.loads(text)
    jobs = []
    for d in data.get("jobs", []):
        try:
            jobs.append(JobRecord(**{k: v for k, v in d.items() if k in JobRecord.__dataclass_fields__}))
        except Exception:
            continue
    return jobs


def build_briefing(matched_by_source: dict[str, list], profile: dict) -> str:
    total = sum(len(v) for v in matched_by_source.values())
    lines = ["# 实习岗位日报（匹配版）", ""]
    lines.append(f"> 按求职画像（{profile.get('direction', '')}：{'/'.join(profile.get('tech_stack', []))}）筛出 **{total} 条**相关岗位，每条附匹配度。")
    lines.append("")
    lines.append("## 总览")
    lines.append("")
    lines.append("| 公司 | 相关岗位数 | 最高匹配度 |")
    lines.append("|---|---|---|")
    for src, items in matched_by_source.items():
        top = max((i["score"] for i in items), default=0)
        lines.append(f"| {NAME.get(src, src)} | {len(items)} | {top} |")
    lines.append("")
    for src, items in matched_by_source.items():
        lines.append(f"## {NAME.get(src, src)}（相关 {len(items)} 条）")
        lines.append("")
        for it in items:
            j = it["job"]
            lines.append(f"### {j.title}　**匹配度 {it['score']}（{score_label(it['score'])}）**")
            lines.append("")
            lines.append(f"- **匹配理由**：{it['reason']}")
            req = (j.requirement or "").strip()
            if req:
                lines.append(f"- **要求**：{req}")
            loc = j.location or '-'
            typ = j.job_type or '-'
            date = j.publish_date or '-'
            lines.append(f"- 地点：{loc} · 类型：{typ} · 发布：{date}")
            lines.append(f"- [查看岗位详情]({j.apply_url or '#'})")
            lines.append("")
    return "\n".join(lines)


async def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    profile = load_profile()
    server = StdioServerParameters(command="uv", args=["run", "python", "-m", "getwork"], env=None)
    async with stdio_client(server) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            matched_by_source = {}
            for src in SOURCES:
                jobs = await crawl(s, src)
                matched = filter_and_score(jobs, profile)
                matched_by_source[src] = matched
                print(f"{src}: crawled={len(jobs)} matched={len(matched)}")
            md = build_briefing(matched_by_source, profile)
            info_res = await s.call_tool("render_briefing", {"title": "实习岗位日报（匹配版）", "markdown": md})
            info_text = "\n".join(c.text if hasattr(c, "text") else str(c) for c in info_res.content)
            info = json.loads(info_text)
            print("render:", info)
            html = Path("data/" + info["html_path"]).read_text(encoding="utf-8")
            send_res = await s.call_tool("send_email", {
                "to": profile.get("recipient_email") or "ryaovenking@henu.edu.cn",
                "subject": f"实习岗位日报·匹配版（{sum(len(v) for v in matched_by_source.values())} 条相关）",
                "html": html,
                "attachment_path": info["png_path"],
            })
            send_text = "\n".join(c.text if hasattr(c, "text") else str(c) for c in send_res.content)
            print("send:", send_text)


if __name__ == "__main__":
    asyncio.run(main())
