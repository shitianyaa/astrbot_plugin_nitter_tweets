"""Classify ordinary Nitter HTML responses.

Only self-hosted instances are supported, so this module neither solves nor
detects third-party challenge pages (Anubis / Poast / Cloudflare). It looks at
Nitter's own error markup and page title, and otherwise lets real timeline
content decide.

Historically this file also carried Cloudflare heuristics inherited from the
public-instance era. Those matched generic English phrases anywhere in the
body, so an ordinary tweet containing "access denied" or "just a moment" —
or a CF beacon script injected into a perfectly healthy 200 response — made
the whole instance look broken and triggered rotation.
"""

from __future__ import annotations

import re

_TITLE_RE = re.compile(rb"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)

#: Nitter 自己渲染的错误容器。这是结构化标记，正文里不会偶然出现，
#: 因此可以压过 timeline 判定。
_STRUCTURAL_ERROR_MARKERS = (
    b'class="error-panel"',
    b"class='error-panel'",
)

#: 只在 <title> 里匹配。标题是页面自述的身份，短且不含用户内容；同样的词出现在
#: 推文正文里则完全正常，全文匹配会把正常时间线判成实例故障。
_TITLE_ERROR_PHRASES = (
    b"login",
    b"log in",
    b"sign in",
    b"maintenance",
    b"error",
    b"not found",
    b"unavailable",
    b"access denied",
)

_TIMELINE_MARKERS = (
    b'class="timeline"',
    b"class='timeline'",
    b'class="timeline-item"',
    b"class='timeline-item'",
    b'class="tweet-content"',
    b"class='tweet-content'",
    b'class="show-more"',
    b"class='show-more'",
)


def classify_page(body: bytes) -> str:
    """Return ``ok``, ``empty``, ``error`` or ``other`` for a response body."""
    if not body or not body.strip():
        return "empty"

    low = body.lower()
    if any(marker in low for marker in _STRUCTURAL_ERROR_MARKERS):
        return "error"
    title = _title_text(low)
    if title and any(phrase in title for phrase in _TITLE_ERROR_PHRASES):
        return "error"
    if any(marker in low for marker in _TIMELINE_MARKERS):
        return "ok"
    if b"<html" in low or b"<!doctype html" in low:
        return "other"
    return "error"


def _title_text(low: bytes) -> bytes:
    match = _TITLE_RE.search(low)
    return match.group(1) if match else b""
