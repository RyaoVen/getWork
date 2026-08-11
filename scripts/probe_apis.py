"""探测各校招站岗位 API 是否可直接访问（无需登录/csrf），返回响应结构与首条字段。"""

from __future__ import annotations

import asyncio
import json

import httpx

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"

APIS = [
    ("腾讯", "GET", "https://join.qq.com/api/v1/position/searchPosition", None, "https://join.qq.com"),
    ("拼多多", "GET", "https://careers.pddglobalhr.com/api/careers/api/recruit/position/train/list", None, "https://careers.pddglobalhr.com"),
    ("京东", "POST", "https://campus.jd.com/api/wx/position/page", {"type": "present", "pageNo": 1, "pageSize": 10}, "https://campus.jd.com"),
    ("字节", "GET", "https://jobs.bytedance.com/api/v1/search/job/posts", {"keyword": "", "limit": 10, "offset": 0}, "https://jobs.bytedance.com"),
    ("阿里", "GET", "https://campus-talent.alibaba.com/position/search", {"pageSize": 10, "pageNo": 1}, "https://campus-talent.alibaba.com"),
    ("同程", "GET", "https://mhr.ly.com/recruit/ats/portal/schoolJob", None, "https://mhr.ly.com"),
    ("得物", "GET", "https://campus.dewu.com/api/v1/search/job/posts", {"keyword": "", "limit": 10, "offset": 0}, "https://campus.dewu.com"),
    ("超聚变", "GET", "https://apig.xfusion.com/api/xJob/xjobpostdeliver/osPostpagelist", {"pageSize": 10, "curPage": 1, "X-HW-ID": "aa7ff6cd1d724291a2bf569e7dd29fb0"}, "https://career.xfusion.com"),
]


async def probe(client: httpx.AsyncClient, name: str, method: str, url: str, body, ref: str):
    headers = {"User-Agent": UA, "Referer": ref, "Accept": "application/json"}
    try:
        if method == "POST":
            r = await client.post(url, json=body or {}, headers=headers)
        else:
            r = await client.get(url, params=body, headers=headers)
        ct = r.headers.get("content-type", "")
        if "json" not in ct:
            print(f"[{name}] {r.status_code} content-type={ct} text={r.text[:80]!r}")
            return
        try:
            data = r.json()
        except Exception:
            print(f"[{name}] {r.status_code} 非JSON: {r.text[:80]!r}")
            return
        print(f"[{name}] {r.status_code} top_keys={list(data.keys())[:8]}")
        # 找列表
        def first_list(d, depth=0):
            if depth > 4:
                return None
            if isinstance(d, list):
                return d
            if isinstance(d, dict):
                for v in d.values():
                    r_ = first_list(v, depth + 1)
                    if r_:
                        return r_
            return None
        lst = first_list(data)
        if lst and isinstance(lst, list) and lst:
            item = lst[0] if isinstance(lst[0], dict) else {"_": lst[0]}
            print(f"    list_len={len(lst)} first_item_keys={list(item.keys())[:12]}")
        else:
            print(f"    (无列表) body={json.dumps(data, ensure_ascii=False)[:160]}")
    except Exception as e:
        print(f"[{name}] FAIL {type(e).__name__} {str(e)[:80]}")


async def main():
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        for name, method, url, body, ref in APIS:
            await probe(client, name, method, url, body, ref)


if __name__ == "__main__":
    asyncio.run(main())
