"""Shared Nitter HTML timeline parser (all hosts)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import unescape
from urllib.parse import unquote, urljoin

try:
    from ...shared.utils import TweetItem, TweetMedia, format_tweet_published
except ImportError:  # pragma: no cover
    from shared.utils import TweetItem, TweetMedia, format_tweet_published

try:
    from ..network import is_safe_http_url
    from .query import normalize_query, query_kind
except ImportError:  # pragma: no cover
    from media_support.html_backend.query import normalize_query, query_kind
    from media_support.network import is_safe_http_url


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
    value = unescape(maybe_relative or "").strip()
    if not value:
        return ""
    if value.startswith("//"):
        return "https:" + value
    if value.startswith(("http://", "https://")):
        return value
    return urljoin(instance.rstrip("/") + "/", value.lstrip("/"))


_HTML_TAG_RE = re.compile(r"<!--.*?-->|<[^>]+>", re.DOTALL)
_HTML_VOID_TAGS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)


def _is_nested_media_section_start(token: str) -> bool:
    """Identify quote/article containers whose media is not author media."""
    if token.startswith("<!--") or re.match(r"<\s*/", token):
        return False
    class_match = re.search(
        r"\bclass\s*=\s*([\"'])(.*?)\1", token, re.IGNORECASE | re.DOTALL
    )
    if class_match:
        classes = {
            name.lower() for name in re.findall(r"[A-Za-z0-9_-]+", class_match.group(2))
        }
        if any(name == "quote" or name.startswith("quote-") for name in classes):
            return True
    href_match = re.search(
        r"\bhref\s*=\s*([\"'])(.*?)\1", token, re.IGNORECASE | re.DOTALL
    )
    if href_match:
        href = unescape(href_match.group(2))
        if re.search(r"(?:^|/)/?i/article(?:/|[?#]|$)", href, re.IGNORECASE):
            return True
    return False


def _is_outer_media_boundary_start(token: str) -> bool:
    """Recognize an outer attachment wrapper during malformed HTML recovery.

    A broken quote/article block can omit its closing tag.  Treating the rest
    of the timeline item as nested would hide a later author attachment.  In
    normal Nitter markup the author's attachments are wrapped by a plain
    ``attachments`` div, while quoted media uses a ``quote-*`` class, so this
    marker gives the tolerant scanner a conservative recovery point.
    """
    if token.startswith("<!--") or re.match(r"<\s*/", token):
        return False
    opening = re.match(r"<\s*([A-Za-z][\w:-]*)", token)
    if not opening or opening.group(1).lower() != "div":
        return False
    class_match = re.search(
        r"\bclass\s*=\s*([\"'])(.*?)\1", token, re.IGNORECASE | re.DOTALL
    )
    if not class_match:
        return False
    classes = {
        name.lower() for name in re.findall(r"[A-Za-z0-9_-]+", class_match.group(2))
    }
    return "attachments" in classes and not any(
        name == "quote" or name.startswith("quote-") for name in classes
    )


def _without_nested_media_sections(chunk: str) -> str:
    """Mask quote/Article blocks before scanning author attachments.

    Nitter renders quoted tweets as nested ``div`` trees. A flat regex over a
    whole timeline item cannot distinguish their media links from the outer
    tweet, so use a small tag stack to remove only those subtrees.
    """
    if not chunk:
        return ""
    stack: list[dict[str, object]] = []
    ranges: list[tuple[int, int]] = []
    for match in _HTML_TAG_RE.finditer(chunk):
        token = match.group(0)
        if token.startswith(("<!--", "<!")):
            continue

        # Recover from a missing quote/article closing tag before scanning a
        # subsequent outer attachment wrapper.  Without this boundary the
        # conservative end-of-chunk mask would hide valid author media.
        if stack and _is_outer_media_boundary_start(token):
            root_index = next(
                (index for index, entry in enumerate(stack) if entry.get("is_root")),
                None,
            )
            # An ``attachments`` wrapper nested under another quote/article
            # container (for example ``quote-media-container``) still belongs
            # to the quoted content. Only recover when the malformed root is
            # the direct open parent of the candidate outer wrapper.
            if root_index is not None and root_index == len(stack) - 1:
                root_start = stack[root_index].get("root_start")
                if isinstance(root_start, int) and root_start < match.start():
                    ranges.append((root_start, match.start()))
                del stack[root_index:]

        close = re.match(r"<\s*/\s*([A-Za-z][\w:-]*)", token)
        if close:
            tag = close.group(1).lower()
            found = None
            for index in range(len(stack) - 1, -1, -1):
                if stack[index]["tag"] == tag:
                    found = index
                    break
            if found is None:
                continue
            entry = stack[found]
            del stack[found:]
            root_start = entry.get("root_start")
            if entry.get("is_root") and isinstance(root_start, int):
                ranges.append((root_start, match.end()))
            continue

        opening = re.match(r"<\s*([A-Za-z][\w:-]*)", token)
        if not opening:
            continue
        tag = opening.group(1).lower()
        inherited = stack[-1].get("root_start") if stack else None
        is_root = inherited is None and _is_nested_media_section_start(token)
        root_start = match.start() if is_root else inherited
        self_closing = token.rstrip().endswith("/>") or tag in _HTML_VOID_TAGS
        entry = {"tag": tag, "root_start": root_start, "is_root": is_root}
        if not self_closing:
            stack.append(entry)
        elif is_root:
            ranges.append((match.start(), match.end()))

    end = len(chunk)
    for entry in stack:
        root_start = entry.get("root_start")
        if entry.get("is_root") and isinstance(root_start, int):
            ranges.append((root_start, end))
    if not ranges:
        return chunk
    masked = chunk
    for start, stop in sorted(ranges, reverse=True):
        masked = masked[:start] + masked[stop:]
    return masked


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
        r"(?:[?&]|amp;)cursor=([A-Za-z0-9_\-%=]+)",
    ):
        match = re.search(pat, html, re.IGNORECASE)
        if match:
            return unquote(match.group(1))
    return ""


def _extract_media(chunk: str, instance: str) -> list[TweetMedia]:
    media: list[TweetMedia] = []
    seen: set[str] = set()
    scan_chunk = _without_nested_media_sections(chunk)

    def add(kind: str, url: str) -> None:
        url = abs_url(instance, url)
        url = unescape(url).strip()
        if not url or url in seen:
            return
        if not is_safe_http_url(url, resolve_dns=False):
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
        scan_chunk,
        re.IGNORECASE,
    ):
        add("image", href[0] or href[1])
    for rel in re.findall(r'(?:href|src)="(/pic/orig/media[^"]+)"', scan_chunk):
        add("image", abs_url(instance, rel))
    if not any(m.is_image for m in media):
        for rel in re.findall(r'(?:href|src)="(/pic/media[^"]+)"', scan_chunk):
            add("image", abs_url(instance, rel))
    if 'class="attachments' in scan_chunk:
        idx = scan_chunk.find('class="attachments')
        scan = scan_chunk[idx : idx + 5000]
        for href in re.findall(r'href="(https://pbs\.twimg\.com/media/[^"]+)"', scan):
            add("image", href)
    for rel in re.findall(r'(?:href|src)="(/video/[^"]+)"', scan_chunk):
        add("video", abs_url(instance, rel))
    for href in re.findall(
        r'(?:href|src)="(https://video\.twimg\.com/[^"]+)"', scan_chunk
    ):
        add("video", href)
    return media


def _extract_tweet_text(chunk: str) -> str:
    """Pull main tweet body from a timeline-item chunk."""
    patterns = (
        r'(?s)<div class="tweet-content[^"]*"[^>]*>(.*?)</div>',
        r'(?s)<div class="tweet-content media-body"[^>]*>(.*?)</div>',
        r'(?s)<div class="tweet-body"[^>]*>.*?<div class="tweet-content[^"]*"[^>]*>(.*?)</div>',
    )
    for pat in patterns:
        match = re.search(pat, chunk, re.IGNORECASE)
        if not match:
            continue
        text = clean_html_text(match.group(1))
        if text:
            return text

    cleaned = re.sub(r"(?is)<script[^>]*>.*?</script>", "", chunk or "")
    cleaned = re.sub(r"(?is)<style[^>]*>.*?</style>", "", cleaned)
    cleaned = re.sub(
        r'(?is)<div class="quote(?:-tweet)?[^"]*"[^>]*>.*?</div>\s*</div>',
        "",
        cleaned,
    )
    text = clean_html_text(cleaned)
    lines_out = [ln.strip() for ln in text.splitlines() if ln.strip()]
    kept = []
    noise = {"retweet", "quote", "reply", "load more"}
    for ln in lines_out:
        low = ln.lower()
        if low in noise:
            continue
        if re.fullmatch(r"[@#]?\w{1,32}", ln) and not kept:
            continue
        if re.fullmatch(r"[\d,.]+[KMBkmb]?", ln):
            continue
        kept.append(ln)
    return chr(10).join(kept[:12]).strip()


def is_pure_retweet_chunk(chunk: str) -> bool:
    """Best-effort pure-retweet detection for Nitter HTML timeline items.

    Do not use footer action icons (icon-retweet) — every tweet has a retweet button.
    Prefer retweet-header / retweeted-by text in the region before tweet body.
    """
    if not chunk:
        return False
    # Nitter puts retweet-header *inside* tweet-body, before tweet-content.
    # Only cut at tweet-content (not tweet-body), else pure-RT headers are missed.
    low = chunk.lower()
    cut = len(chunk)
    for marker in (
        'class="tweet-content',
        "class='tweet-content",
    ):
        idx = low.find(marker)
        if idx != -1:
            cut = min(cut, idx)
    head = chunk[: min(cut, 2500)]

    if re.search(r'class="[^"]*retweet-header[^"]*"', head, re.IGNORECASE):
        return True
    if re.search(r"class='[^']*retweet-header[^']*'", head, re.IGNORECASE):
        return True
    if re.search(r"retweeted\s+by", head, re.IGNORECASE):
        return True
    return bool(re.search(r"(转推了|转推自)", head[:800]))


def parse_timeline_html(html: str, instance: str, *, source: str = "") -> TimelinePage:
    del source  # plugin TweetItem has no source field; keep API compatible
    if "timeline-item" not in html:
        return TimelinePage(tweets=[], next_cursor=extract_next_cursor(html))

    chunks = re.split(r'(?=<div class="timeline-item\b)', html)
    tweets: list[TweetItem] = []
    seen: set[str] = set()
    raw = 0
    for chunk in chunks:
        if "tweet-content" not in chunk and "tweet-body" not in chunk:
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
        text = _extract_tweet_text(chunk)
        dm = re.search(r'(?s)<span class="tweet-date">\s*<a[^>]*title="([^"]+)"', chunk)
        published = format_tweet_published(unescape(dm.group(1)) if dm else "")
        link = f"https://x.com/{user}/status/{sid}"
        tweets.append(
            TweetItem(
                text=text or "(无正文)",
                link=link,
                published=published,
                media=_extract_media(chunk, instance),
                is_retweet=is_pure_retweet_chunk(chunk),
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
    "is_pure_retweet_chunk",
    "normalize_query",
    "parse_timeline_html",
    "prefer_orig_pbs",
    "query_kind",
]
