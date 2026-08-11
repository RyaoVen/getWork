"""批量探测各校招站岗位 API 的响应结构：data_path + 字段名。"""

from __future__ import annotations

import asyncio
import json

from playwright.async_api import async_playwright

SITES = [
    ("美团", "https://zhaopin.meituan.com/web/campus", "recruit"),
    ("腾讯", "https://join.qq.com/post.html?query=p_104", "searchPosition"),
    ("拼多多", "https://careers.pddglobalhr.com/campus/intern", "position/train/list"),
    ("京东", "https://campus.jd.com/#/jobs?selProjects=45", "position/page"),
    ("字节", "https://jobs.bytedance.com/campus/position", "search/job/posts"),
    ("阿里", "https://campus-talent.alibaba.com/campus/position", "position/search"),
    ("同程", "https://mhr.ly.com/recruit/schoolPortal/#/postDelivery?srt=0.48", "schoolJob"),
    ("得物", "https://campus.dewu.com/578078/position/list", "search/job/posts"),
    ("超聚变", "https://career.xfusion.com/OfficialPortal/#/traineeList", "osPostpagelist"),
]


def find_lists(d, prefix="", depth=0):
    """返回 [(path, list)] 的路径，尽量找含岗位的列表。"""
    out = []
    if depth > 6:
        return out
    if isinstance(d, dict):
        for k, v in d.items():
            if isinstance(v, list):
                out.append((f"{prefix}.{k}", v))
            elif isinstance(v, dict):
                out.extend(find_lists(v, f"{prefix}.{k}", depth + 1))
    return out


async def probe(name, url, match):
    p = await async_playwright().start()
    b = await p.chromium.launch(headless=True)
    ctx = await b.new_context(user_agent="Mozilla/5.0")
    page = await ctx.new_page()
    bodies = []
    page.on("response", lambda r: bodies.append(r) if match and match in r.url else None)
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=25000)
        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
    except Exception as e:
        print(f"[{name}] goto失败 {type(e).__name__}")
        await b.close(); await p.stop(); return
    print(f"===== {name} (match={match}) =====")
    for r in bodies:
        try:
            data = json.loads((await r.body()).decode("utf-8"))
        except Exception:
            continue
        for path, lst in find_lists(data)[:4]:
            if not lst:
                continue
            first = lst[0]
            if isinstance(first, dict):
                sample = {k: (str(v)[:18]) for k, v in list(first.items())[:14]}
                print(f"  {path}: len={len(lst)}")
                print(f"    fields: {json.dumps(sample, ensure_ascii=False)}")
            else:
                print(f"  {path}: len={len(lst)} (非对象列表)")
    if not bodies:
        print("  (未捕获到匹配响应)")
    await b.close(); await p.stop()


async def main():
    for name, url, match in SITES:
        await probe(name, url, match)


if __name__ == "__main__":
    asyncio.run(main())
