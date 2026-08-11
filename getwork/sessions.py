"""会话 cookie jar：按来源持久化 Playwright cookie，只存 cookie 不存密码。"""

from __future__ import annotations

import json
import time
from pathlib import Path

from .config import DEFAULT_DATA_DIR

SESSIONS_DIR = DEFAULT_DATA_DIR / "sessions"


def _jar_path(source_key: str) -> Path:
    return SESSIONS_DIR / f"{source_key}.json"


def _load_all(source_key: str) -> list[dict]:
    p = _jar_path(source_key)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return data if isinstance(data, list) else []


def save_cookies(source_key: str, cookies: list[dict]) -> None:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    _jar_path(source_key).write_text(
        json.dumps(cookies, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def load_cookies(source_key: str) -> list[dict]:
    """读取未过期的 cookie（expires=-1 表示会话级，视为有效）。"""
    now = time.time()
    fresh = []
    for c in _load_all(source_key):
        exp = c.get("expires", -1)
        if exp == -1 or exp > now:
            fresh.append(c)
    return fresh


def has_session(source_key: str) -> bool:
    return bool(load_cookies(source_key))


def clear_cookies(source_key: str) -> bool:
    p = _jar_path(source_key)
    if p.exists():
        p.unlink()
        return True
    return False
