"""Bounded, structured data returned to AstrBot LLM FunctionTools.

Treat all tweet text, trend labels and group names as UNTRUSTED data. Only
verified public X status URLs can be exported; Nitter instance URLs and
media download URLs must never enter the model-facing result.
"""

from __future__ import annotations

import json
import re
from typing import Any

MAX_TWEET_TEXT = 900
MAX_TOOL_TEXT = 16_000
_URL_RE = re.compile(r"^https://x\.com/[A-Za-z0-9_]{1,15}/status/\d+$")
_UMO_RE = re.compile(r"\b[A-Za-z0-9_.-]+:(?:GroupMessage|FriendMessage):[^\s<>\"']+")


def safe_label(value: object, *, max_chars: int = 160) -> str:
    """Remove controls, URLs, credentials and excessive text from metadata."""
    try:
        from ..shared.observability import (
            redact_instance_urls,
            sanitize_sensitive_text,
        )
    except ImportError:
        from shared.observability import redact_instance_urls, sanitize_sensitive_text

    cleaned = sanitize_sensitive_text(redact_instance_urls(str(value or "")))
    cleaned = _UMO_RE.sub("[会话标识]", cleaned)
    cleaned = "".join(
        char if char.isprintable() and char not in "\r\n\t" else " " for char in cleaned
    )
    return " ".join(cleaned.split())[:max_chars]


def tweet_to_data(tweet) -> dict[str, Any]:
    text = str(getattr(tweet, "text", "") or "")
    text_truncated = len(text) > MAX_TWEET_TEXT
    author = safe_label(getattr(tweet, "username", ""), max_chars=16)
    raw_url = str(getattr(tweet, "x_url", "") or "")
    public_url = raw_url if _URL_RE.fullmatch(raw_url) else ""
    kinds = []
    for media in getattr(tweet, "media", []) or []:
        if getattr(media, "is_video", False) and "video" not in kinds:
            kinds.append("video")
        elif getattr(media, "is_image", False) and "image" not in kinds:
            kinds.append("image")
    return {
        "author": author or None,
        "published": safe_label(getattr(tweet, "published", ""), max_chars=80) or None,
        "text": text[:MAX_TWEET_TEXT],
        "x_url": public_url or None,
        "media_types": kinds,
        "text_truncated": text_truncated,
    }


def trends_to_data(trends: list[dict]) -> list[dict[str, Any]]:
    output = []
    for item in trends[:25]:
        if not isinstance(item, dict):
            continue
        name = safe_label(item.get("name"), max_chars=100)
        if not name:
            continue
        rank = item.get("rank")
        output.append(
            {
                "name": name,
                "rank": rank if type(rank) is int and rank > 0 else None,
                "context": safe_label(item.get("context"), max_chars=120) or None,
            }
        )
    return output


def response_json(data: dict[str, Any]) -> str:
    """Return syntactically complete JSON even when items must be shortened."""
    result = dict(data)
    warnings = list(result.get("warnings") or [])
    result["warnings"] = warnings
    result.setdefault("truncated", False)
    serialized = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    if len(serialized) <= MAX_TOOL_TEXT:
        return serialized

    # For large subscriptions or long tweet payloads, reduce only leaf data,
    # not arbitrary byte slices that would break JSON or misreport item count.
    result["truncated"] = True
    if "结果过长，部分文本已截断" not in warnings:
        warnings.append("结果过长，部分文本已截断")
    items = result.get("items")
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                item["text"] = item["text"][:240]
                item["text_truncated"] = True
        serialized = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
        while len(serialized) > MAX_TOOL_TEXT and items:
            items.pop()
            result["returned_count"] = len(items)
            serialized = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    if len(serialized) > MAX_TOOL_TEXT and isinstance(result.get("entries"), list):
        entries = result["entries"]
        while len(serialized) > MAX_TOOL_TEXT and entries:
            entries.pop()
            serialized = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    if len(serialized) <= MAX_TOOL_TEXT:
        return serialized
    # Defensive final fallback: keep a valid, minimal envelope.
    return json.dumps(
        {
            "status": "partial",
            "kind": safe_label(result.get("kind")),
            "items": [],
            "returned_count": 0,
            "truncated": True,
            "warnings": ["结果超出长度限制"],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
