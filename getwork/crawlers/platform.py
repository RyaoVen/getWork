"""platform 策略：校招统一平台（北森/Moka/大易/大街等）后端的 JSON API。

请求与字段提取全部配置化（source.api / source.fields），
接口变动时改 YAML 即可，不动代码。端点可在浏览器开发者工具 Network 里抓取。
"""

from __future__ import annotations

from typing import Any

import httpx

from ..models import JobRecord
from .base import Crawler, UA, dig, first_text, resolve_url


class PlatformCrawler(Crawler):
    MAX_PAGES = 50

    async def _fetch(self) -> list[JobRecord]:
        api = self.source.api
        url = api.get("url") or self.source.url
        method = (api.get("method") or "GET").upper()
        headers = dict(api.get("headers") or {})
        base_body = dict(api.get("body") or {})
        base_params = dict(api.get("params") or {})
        page_param = api.get("page_param")
        page_size = int(api.get("page_size") or 20)
        page_size_key = api.get("page_size_key") or "pageSize"
        body_page_key = api.get("body_page_key")  # 分页字段在 body 时指定，否则走 query
        paginate_in_body = bool(body_page_key)
        data_path = api.get("data_path", "data.list")
        total_path = api.get("total_path")

        jobs: list[JobRecord] = []
        page = 1
        async with httpx.AsyncClient(
            timeout=self.timeout, headers={"User-Agent": UA, **headers},
            follow_redirects=True,
        ) as client:
            while page <= self.MAX_PAGES:
                body = dict(base_body)
                params = dict(base_params)
                if page_param:
                    if paginate_in_body:
                        body[body_page_key] = page
                        body[page_size_key] = page_size
                    else:
                        params[page_param] = page
                        params[page_size_key] = page_size

                send_kwargs = {"params": params}
                if method in ("POST", "PUT", "PATCH"):
                    send_kwargs["json"] = body
                resp = await client.request(method, url, headers=headers, **send_kwargs)
                resp.raise_for_status()
                data = resp.json()

                items = dig(data, data_path) or []
                if isinstance(items, dict):
                    items = [items]
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    job = self._extract_item(it)
                    if job:
                        jobs.append(job)

                total = dig(data, total_path) if total_path else None
                if not items:
                    break
                if total is not None and len(jobs) >= int(total):
                    break
                page += 1

        return jobs

    def _extract_item(self, item: dict) -> JobRecord | None:
        fields = self.source.fields or {}
        title = first_text(dig(item, fields.get("title", "title")))
        if not title:
            return None
        href = first_text(dig(item, fields.get("apply_url"))) if fields.get("apply_url") else None
        return JobRecord(
            title=title,
            company=self.source.name,
            source=self.source.key,
            location=first_text(dig(item, fields["location"])) if fields.get("location") else None,
            department=first_text(dig(item, fields["department"])) if fields.get("department") else None,
            job_type=first_text(dig(item, fields["job_type"])) if fields.get("job_type") else None,
            publish_date=first_text(dig(item, fields["publish_date"])) if fields.get("publish_date") else None,
            deadline=first_text(dig(item, fields["deadline"])) if fields.get("deadline") else None,
            description=first_text(dig(item, fields["description"])) if fields.get("description") else None,
            apply_url=resolve_url(self.source.url, href),
            raw=item,
        )
