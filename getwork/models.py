"""统一岗位模型。所有爬虫策略都归一化到 JobRecord，Agent 拿到的 JSON 一致。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class JobRecord:
    """一条归一化的岗位记录。"""

    title: str
    company: str
    source: str
    location: str | None = None
    department: str | None = None
    job_type: str | None = None
    publish_date: str | None = None
    deadline: str | None = None
    apply_url: str = ""
    description: str | None = None
    raw: dict = field(default_factory=dict)

    def to_dict(self, include_raw: bool = False) -> dict:
        d = asdict(self)
        if not include_raw:
            d.pop("raw", None)
        return d


def to_dicts(jobs: list[JobRecord], include_raw: bool = False) -> list[dict]:
    return [j.to_dict(include_raw=include_raw) for j in jobs]
