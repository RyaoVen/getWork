"""画像匹配：按求职画像给岗位算匹配度（0-100），过滤无关岗位。

分数逻辑：方向（后端/全栈/研发）为主，技术栈/关键词命中为加分，无关类别直接丢弃。
"""

from __future__ import annotations

from typing import Any

from .models import JobRecord

# 与研发方向无关的岗位类别（标题出现即视为不相关）
IRRELEVANT = [
    "运营", "市场", "销售", "商务", "客服", "人力", "HR", "财务", "会计",
    "设计", "UI", "视觉", "美术", "内容", "编辑", "审核", "法务",
    "产品经理", "项目管理", "行政", "秘书", "助教", "咨询", "投研",
]

# 研发方向岗位词（标题命中 → 加分）
BACKEND_HINTS = ["后端", "全栈", "服务端", "后端开发", "全栈开发", "中间件", "基础架构", "网关"]
DEV_HINTS = [
    "开发", "工程师", "研发", "工程", "技术", "前端", "客户端",
    "数据开发", "测试开发", "SRE", "DevOps", "平台", "数据库",
]


def _score(job: JobRecord, profile: dict) -> tuple[int, str, bool]:
    """返回 (分数, 理由, 是否保留)。"""
    title = job.title or ""
    text = " ".join(
        filter(None, [title, job.description, job.requirement, job.job_type, job.department])
    ).lower()
    score = 0
    hits: list[str] = []

    # 1. 方向匹配
    if any(h in title for h in BACKEND_HINTS):
        score += 45
        hits.append("后端/全栈方向")
    elif any(h in title for h in DEV_HINTS):
        score += 30
        hits.append("研发类岗位")

    # 2. 技术栈命中
    ts = profile.get("tech_stack") or []
    found = [t for t in ts if t.lower() in text]
    if found:
        score += min(30, 6 * len(found))
        hits.append("命中技术栈: " + ", ".join(found[:4]))

    # 3. 关键词命中
    kws = profile.get("keywords") or []
    found_kw = [k for k in kws if k.lower() in text]
    if found_kw:
        score += min(15, 3 * len(found_kw))
        hits.append("命中关键词: " + ", ".join(found_kw[:3]))

    # 4. 无关类别 → 丢弃（但「XX开发/XX工程师」是研发岗，不因运营/市场等词丢弃）
    is_dev_role = any(h in title for h in DEV_HINTS + BACKEND_HINTS)
    if not is_dev_role and any(ir in title for ir in IRRELEVANT):
        return 0, "非研发方向（运营/市场/产品等）", False

    if not hits:
        return 0, "与画像方向关联较弱", False

    threshold = int(profile.get("match_threshold") or 40)
    return min(100, score), "；".join(hits), score >= threshold


def filter_and_score(jobs: list[JobRecord], profile: dict) -> list[dict]:
    """给每个岗位算匹配度并过滤，返回 [{job, score, reason}]，按分数降序。"""
    out = []
    for j in jobs:
        score, reason, keep = _score(j, profile)
        if keep:
            out.append({"job": j, "score": score, "reason": reason})
    out.sort(key=lambda x: x["score"], reverse=True)
    return out


def score_label(score: int) -> str:
    if score >= 75:
        return "高"
    if score >= 55:
        return "中"
    return "低"
