# -*- coding: utf-8 -*-
"""Shared Nitter HTML timeline parser (all hosts)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import unescape
from urllib.parse import unquote, urljoin

try:
    from ...shared.utils import TweetItem, TweetMedia
except ImportError:  # pragma: no cover
    from shared.utils import TweetItem, TweetMedia

try:
    from .query import normalize_query, query_kind
except ImportError:  # pragma: no cover
    from media_support.html_backend.query import normalize_query, query_kind


@dataclass(slots=True)
class TimelinePage:
    tweets: list[TweetItem]
    next_cursor: str = ""
    raw_item_count: int = 0


def clean_html_text(raw: str) -> str:
    text = re.sub(r"(?i)<br\s*/?>", "\n", raw or "")
    text = re.sub(r"(?s)<[^>]+>", "", text)
    text = unescape(text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def abs_url(instance: str, maybe_relative: str) -> str:
    value = (maybe_relative or "").strip()
    if not value:
        return ""
    if value.startswith("//"):
        return "https:" + value
    if value.startswith(("http://", "https://")):
        return value
    return urljoin(instance.rstrip("/") + "/", value.lstrip("/"))


def prefer_orig_pbs(url: str) -> str:
    if "pbs.twimg.com/media/" not in url:
        return url
    if "name=" in url:
        return re.sub(r"([?&])name=[^&]*", r"\1name=orig", url)
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}name=orig"


def extract_next_cursor(html: str) -> str:
    for pat in (
        r'class="show-more"[^>]*>\s*<a[^>]+href="[^"]*?cursor=([^"&#]+)',
        r'href="[^"]*?cursor=([^"&#]+)[^"]*"[^>]*>\s*Load more',
        r'(?:[?&]|amp;)cursor=([A-Za-z0-9_\-%=]+)',
    ):
        match = re.search(pat, html, re.I)
        if match:
            return unquote(match.group(1))
    return ""


def _extract_media(chunk: str, instance: str) -> list[TweetMedia]:
    media: list[TweetMedia] = []
    seen: set[str] = set()

    def add(kind: str, url: str) -> None:
        url = (url or "").strip()
        if not url or url in seen:
            return
        if "profile_images" in url or "profile_banners" in url:
            return
        if kind == "image" and (
            "video_thumb" in url or "amplify_video_thumb" in url or "emoji" in url
        ):
            return
        if kind == "image" and "pbs.twimg.com" in url:
            url = prefer_orig_pbs(url)
        seen.add(url)
        media.append(TweetMedia(kind=kind, url=url))

    for href in re.findall(
        r'class="still-image"[^>]*href="([^"]+)"|href="([^"]+)"[^>]*class="still-image"',
        chunk,
        re.I,
    ):
        add("image", href[0] or href[1])
    for rel in re.findall(r'(?:href|src)="(/pic/orig/media[^"]+)"', chunk):
        add("image", abs_url(instance, rel))
    if not any(m.is_image for m in media):
        for rel in re.findall(r'(?:href|src)="(/pic/media[^"]+)"', chunk):
            add("image", abs_url(instance, rel))
    if 'class="attachments' in chunk:
        idx = chunk.find('class="attachments')
        scan = chunk[idx : idx + 5000]
        for href in re.findall(
            r'href="(https://pbs\.twimg\.com/media/[^"]+)"', scan
        ):
            add("image", href)
    for rel in re.findall(r'(?:href|src)="(/video/[^"]+)"', chunk):
        add("video", abs_url(instance, rel))
    for href in re.findall(
        r'(?:href|src)="(https://video\.twimg\.com/[^"]+)"', chunk
    ):
        add("video", href)
    return media


def parse_timeline_html(html: str, instance: str, *, source: str = "") -> TimelinePage:
    del source  # plugin TweetItem has no source field; keep API compatible
    if "timeline-item" not in html:
        return TimelinePage(tweets=[], next_cursor=extract_next_cursor(html))

    chunks = re.split(r'(?=<div class="timeline-item\b)', html)
    tweets: list[TweetItem] = []
    seen: set[str] = set()
    raw = 0
    for chunk in chunks:
        if "tweet-content" not in chunk:
            continue
        sm = re.search(
            r'href="/(?P<user>[A-Za-z0-9_]+)/status(?:es)?/(?P<id>\d+)',
            chunk,
        )
        if not sm:
            continue
        raw += 1
        user, sid = sm.group("user"), sm.group("id")
        key = f"{user}:{sid}"
        if key in seen:
            continue
        seen.add(key)
        cm = re.search(
            r'(?s)<div class="tweet-content[^"]*"[^>]*>(.*?)</div>', chunk
        )
        text = clean_html_text(cm.group(1) if cm else "")
        dm = re.search(
            r'(?s)<span class="tweet-date">\s*<a[^>]*title="([^"]+)"', chunk
        )
        published = unescape(dm.group(1)) if dm else ""
        link = f"https://x.com/{user}/status/{sid}"
        tweets.append(
            TweetItem(
                text=text or "(无正文)",
                link=link,
                published=published,
                media=_extract_media(chunk, instance),
            )
        )
    return TimelinePage(
        tweets=tweets,
        next_cursor=extract_next_cursor(html),
        raw_item_count=raw,
    )


__all__ = [
    "TimelinePage",
    "abs_url",
    "clean_html_text",
    "extract_next_cursor",
    "normalize_query",
    "parse_timeline_html",
    "prefer_orig_pbs",
    "query_kind",
]
