"""探测校招站点：抓渲染后的岗位标题 + 疑似岗位 API 请求，用于配置 companies.yaml。

用法：uv run python scripts/probe_sites.py [site索引或名]
"""

from __future__ import annotations

import asyncio
import re
import sys

from playwright.async_api import async_playwright

SITES = [
    ("美团", "https://zhaopin.meituan.com/web/campus"),
    ("腾讯", "https://join.qq.com/post.html?query=p_104"),
    ("拼多多", "https://careers.pddglobalhr.com/campus/intern"),
    ("京东", "https://campus.jd.com/#/jobs?selProjects=45"),
    ("字节", "https://jobs.bytedance.com/campus/position?keywords=&category=&location=&project=7194661644654577981%2C7194661126919358757&type=&job_hot_flag=&current=1&limit=10&functionCategory=&tag="),
    ("阿里", "https://campus-talent.alibaba.com/campus/position?batchId=100000560002"),
    ("同程", "https://mhr.ly.com/recruit/schoolPortal/#/postDelivery?srt=0.4871249267327028"),
    ("携程", "https://job.ctrip.com/#/campus/jobList"),
    ("得物", "https://campus.dewu.com/578078/position/list?keywords=&category=&location=&project=7623619302324226314%2C7309753987297167679&type=&job_hot_flag=&current=1&limit=10&functionCategory=&tag="),
    ("超聚变", "https://career.xfusion.com/OfficialPortal/#/traineeList"),
]

_JOB_TITLE_RE = re.compile(r"(前端|后端|算法|测试|开发|实习|工程师|产品|运营|数据|客户端|服务端|机器学习|大数据|运维|安全|AI|安卓|iOS|Java|Python|Go|C\+\+|机器学习)")

_JOBSEL = [
    "a[class*=position]", "a[class*=job]", "[class*=position-name]", "[class*=job-name]",
    "[class*=position-list] li", "[class*=job-list] li", "[class*=job-card]",
    "[class*=campus-job]", "ul li a[href*=job]", "ul li a[href*=position]",
]


async def probe(name: str, url: str) -> None:
    api_urls: list[str] = []
    p = await async_playwright().start()
    browser = await p.chromium.launch(headless=True)
    try:
        ctx = await browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36")
        page = await ctx.new_page()
        page.on("request", lambda req: api_urls.append(req.url) if req.resource_type in ("xhr", "fetch") else None)
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=25000)
        except Exception as e:
            print(f"[{name}] goto 失败: {type(e).__name__}")
            return
        # 等数据加载
        for _ in range(8):
            await page.wait_for_timeout(1200)
            txt = await page.evaluate("document.body ? document.body.innerText.slice(0, 20000) : ''")
            if "登录" not in txt and "验证" not in txt and len(txt) > 300:
                break
        txt = await page.evaluate("document.body ? document.body.innerText.slice(0, 40000) : ''")
        # 提取疑似岗位标题
        titles = []
        for line in txt.splitlines():
            line = line.strip()
            if 2 <= len(line) <= 30 and _JOB_TITLE_RE.search(line):
                if line not in titles:
                    titles.append(line)
        print(f"[{name}] DOM 岗位标题样例: {titles[:8]}")
        # 过滤疑似岗位 API
        cand = [u for u in api_urls if re.search(r"(position|job|campus|post|search|list|recruit|offer)", u, re.I)]
        seen = set()
        out = []
        for u in cand:
            base = re.sub(r"\?.*$", "", u)
            if base not in seen:
                seen.add(base); out.append(u[:150])
        print(f"[{name}] 疑似 API ({len(out)}):")
        for u in out[:8]:
            print(f"    {u}")
    finally:
        await browser.close()
        await p.stop()


async def main():
    if len(sys.argv) > 1:
        key = sys.argv[1]
        items = [s for s in SITES if key in s[0]]
        if not items:
            items = [SITES[int(key)]]
    else:
        items = SITES
    for name, url in items:
        print(f"===== {name} =====")
        await probe(name, url)


if __name__ == "__main__":
    asyncio.run(main())
