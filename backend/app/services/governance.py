from __future__ import annotations

import re
from typing import Any

from fastapi import HTTPException


INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions?", re.I),
    re.compile(r"reveal\s+(the\s+)?system\s+prompt", re.I),
    re.compile(r"忽略.{0,12}(之前|以上|系统).{0,12}(指令|规则|提示)"),
    re.compile(r"(泄露|输出|显示).{0,12}(系统提示词|system prompt|开发者指令)", re.I),
    re.compile(r"绕过.{0,8}(权限|安全|访问控制)"),
]


def validate_user_query(query: str, settings: dict[str, Any]) -> None:
    if not settings.get("prompt_injection_filter", True):
        return
    if any(pattern.search(query) for pattern in INJECTION_PATTERNS):
        raise HTTPException(status_code=400, detail="问题包含可能改变系统规则的指令，已被安全策略拦截")


def filter_sensitive_output(text: str, settings: dict[str, Any]) -> tuple[str, int]:
    filtered = text
    matches = 0
    words = sorted(
        {word.strip() for word in settings.get("sensitive_words", []) if word.strip()},
        key=len,
        reverse=True,
    )
    for word in words:
        count = filtered.lower().count(word.lower())
        if count:
            filtered = re.sub(re.escape(word), "[已过滤]", filtered, flags=re.I)
            matches += count
    return filtered, matches
