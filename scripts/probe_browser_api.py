"""验证「浏览器上下文内调岗位 API」方案：加载页面 → 用页面会话调 API → 看 JSON 结构。"""

from __future__ import annotations

import asyncio
import json

from playwright.async_api import async_playwright

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"

CASES = [
    ("腾讯", "https://join.qq.com/post.html?query=p_104", {
        "method": "POST",
        "url": "https://join.qq.com/api/v1/position/searchPosition",
        "body": {"pageSize": 5, "pageIndex": 1, "keywords": "", "recruitType": "1"},
    }),
    ("字节", "https://jobs.bytedance.com/campus/position", {
        "method": "GET",
        "url": "https://jobs.bytedance.com/api/v1/search/job/posts",
        "params": {"keyword": "", "limit": 5, "offset": 0, "subject_id_list": "7"},
    }),
]


async def main():
    p = await async_playwright().start()
    browser = await p.chromium.launch(headless=True)
    try:
        for name, page_url, api in CASES:
            print(f"===== {name} =====")
            ctx = await browser.new_context(user_agent=UA)
            page = await ctx.new_page()
            try:
                await page.goto(page_url, wait_until="domcontentloaded", timeout=25000)
                await page.wait_for_timeout(3000)
            except Exception as e:
                print("  goto:", type(e).__name__, e)
            # 用页面上下文调 API
            js = f"""
            async () => {{
                const opts = {json.dumps({k: v for k, v in api.items() if k != "url"}, ensure_ascii=False)};
                let url = {json.dumps(api["url"])};
                if (opts.params) {{
                    const qs = new URLSearchParams(opts.params).toString();
                    url += (url.includes("?") ? "&" : "?") + qs;
                }}
                const resp = await fetch(url, {{
                    method: opts.method || "GET",
                    headers: {{"Content-Type": "application/json"}},
                    body: opts.method === "POST" ? JSON.stringify(opts.body || {{}}) : undefined,
                }});
                const text = await resp.text();
                let data; try {{ data = JSON.parse(text); }} catch {{ data = text.slice(0,200); }}
                return {{ status: resp.status, type: typeof data === "string" ? "text" : "json", data }};
            }}
            """
            try:
                result = await page.evaluate(js)
                print("  status:", result.get("status"))
                d = result.get("data")
                if isinstance(d, dict):
                    print("  top_keys:", list(d.keys())[:10])
                    # find first list
                    def fl(x, dep=0):
                        if dep > 4: return None
                        if isinstance(x, list): return x
                        if isinstance(x, dict):
                            for v in x.values():
                                r = fl(v, dep+1)
                                if r: return r
                        return None
                    lst = fl(d)
                    if lst:
                        print("  list_len:", len(lst))
                        if lst and isinstance(lst[0], dict):
                            print("  first_keys:", list(lst[0].keys())[:14])
                            print("  sample:", json.dumps(lst[0], ensure_ascii=False)[:200])
                else:
                    print("  data:", str(d)[:160])
            except Exception as e:
                print("  evaluate FAIL:", type(e).__name__, e)
            await ctx.close()
    finally:
        await browser.close()
        await p.stop()


if __name__ == "__main__":
    asyncio.run(main())
