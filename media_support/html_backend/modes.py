"""Classify ordinary Nitter HTML responses.

Public-instance challenge solvers intentionally do not live here. Self-hosted
instances are expected to expose their normal Nitter pages directly.
"""

from __future__ import annotations


def classify_page(body: bytes) -> str:
    """Return ``ok``, ``empty``, ``error`` or ``other`` for a response body."""
    if not body or not body.strip():
        return "empty"

    low = body.lower()
    # Gate/challenge markers win over timeline markers: a self-hosted
    # instance fronted by Cloudflare may serve an interstitial that still
    # contains timeline-like markup. Treating that as ``ok`` would make the
    # parser read an empty timeline as a legitimate "no tweets" instead of a
    # blocked page.
    error_markers = (
        b'class="error-panel"',
        b"class='error-panel'",
        b"this site is under maintenance",
        b"<title>login",
        b"cloudflare ray id",
        b"challenge-platform",
        b"just a moment",
        b"access denied",
    )
    if any(marker in low for marker in error_markers):
        return "error"
    has_timeline = any(
        marker in low
        for marker in (
            b'class="timeline"',
            b"class='timeline'",
            b'class="timeline-item"',
            b"class='timeline-item'",
            b'class="tweet-content"',
            b"class='tweet-content'",
            b'class="show-more"',
            b"class='show-more'",
        )
    )
    if has_timeline:
        return "ok"
    if b"<html" in low or b"<!doctype html" in low:
        return "other"
    return "error"
