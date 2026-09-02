"""Resolve a single public status into TweetItem via Fx/Vx/Syndication."""

from __future__ import annotations

import json
import logging
import time
from typing import Any
from urllib.request import Request

try:
    from ..shared.utils import TweetItem, TweetMedia, format_tweet_published
    from .html_backend.parser import prefer_pbs_quality
    from .network import build_request_headers, safe_urlopen
    from .status_link import StatusLink
except ImportError:
    from media_support.html_backend.parser import prefer_pbs_quality
    from media_support.network import build_request_headers, safe_urlopen
    from media_support.status_link import StatusLink
    from shared.utils import TweetItem, TweetMedia, format_tweet_published

logger = logging.getLogger("astrbot")

DEFAULT_TIMEOUT_SECONDS = 20.0
MAX_RESPONSE_BYTES = 1_500_000


class StatusResolveError(RuntimeError):
    """Raised when all status backends fail."""


def _kind_from_type(value: str) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"video", "gif", "animated_gif", "dynamic"}:
        return "dynamic" if raw in {"gif", "animated_gif", "dynamic"} else "video"
    return "image"


def _append_media(bucket: list[TweetMedia], *, kind: str, url: str) -> None:
    link = str(url or "").strip()
    if not link.startswith(("http://", "https://")):
        return
    if any(item.url == link for item in bucket):
        return
    bucket.append(TweetMedia(kind=kind, url=link))


def _text_from_structured_raw(value: Any) -> str:
    """Normalize Fx/Vx raw_text blobs; empty display_text_range => no body."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        rng = value.get("display_text_range")
        if isinstance(rng, (list, tuple)) and len(rng) >= 2:
            try:
                start = int(rng[0])
                end = int(rng[1])
            except (TypeError, ValueError):
                start = end = 0
            else:
                if end <= start:
                    return ""
                inner = value.get("text")
                if isinstance(inner, str) and inner:
                    return inner[start:end].strip() or inner.strip()
        inner = value.get("text")
        if isinstance(inner, str):
            return inner.strip()
        return ""
    return str(value).strip()


def _extract_status_text(payload: dict[str, Any]) -> str:
    """Prefer explicit ``text`` (even when empty); never str() a raw_text dict."""
    if "text" in payload:
        primary = payload.get("text")
        if isinstance(primary, str):
            # Empty string is a real media-only body; do not fall back to raw_text.
            return primary.strip()
        if isinstance(primary, dict):
            return _text_from_structured_raw(primary)
        if primary is not None:
            return str(primary).strip()
    if "raw_text" in payload:
        return _text_from_structured_raw(payload.get("raw_text"))
    return ""


def _media_from_fxtwitter(payload: dict[str, Any]) -> list[TweetMedia]:
    media_block = payload.get("media") or {}
    items = media_block.get("all") if isinstance(media_block, dict) else None
    if not isinstance(items, list):
        items = []
    result: list[TweetMedia] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        kind = _kind_from_type(str(item.get("type") or "photo"))
        url = item.get("url") or item.get("thumbnail_url") or ""
        if kind in {"video", "dynamic"}:
            # Prefer highest quality variants when present.
            variants = item.get("variants") or item.get("video_info", {}).get(
                "variants"
            )
            best = ""
            best_bitrate = -1
            if isinstance(variants, list):
                for variant in variants:
                    if not isinstance(variant, dict):
                        continue
                    vurl = str(variant.get("url") or "").strip()
                    if not vurl:
                        continue
                    try:
                        bitrate = int(variant.get("bitrate") or 0)
                    except (TypeError, ValueError):
                        bitrate = 0
                    if bitrate >= best_bitrate:
                        best_bitrate = bitrate
                        best = vurl
            url = best or url
        _append_media(result, kind=kind, url=str(url))
    return result


def _media_from_vxtwitter(payload: dict[str, Any]) -> list[TweetMedia]:
    result: list[TweetMedia] = []
    extended = payload.get("media_extended")
    if isinstance(extended, list):
        for item in extended:
            if not isinstance(item, dict):
                continue
            kind = _kind_from_type(str(item.get("type") or "image"))
            url = item.get("url") or item.get("thumbnail_url") or ""
            _append_media(result, kind=kind, url=str(url))
    if result:
        return result
    urls = payload.get("mediaURLs") or payload.get("media_urls") or []
    if isinstance(urls, list):
        for url in urls:
            _append_media(result, kind="image", url=str(url))
    return result


def _media_from_syndication(payload: dict[str, Any]) -> list[TweetMedia]:
    result: list[TweetMedia] = []
    photos = payload.get("photos") or []
    if isinstance(photos, list):
        for item in photos:
            if isinstance(item, dict):
                _append_media(
                    result,
                    kind="image",
                    url=str(item.get("url") or item.get("src") or ""),
                )
            else:
                _append_media(result, kind="image", url=str(item))
    video = payload.get("video")
    if isinstance(video, dict):
        variants = video.get("variants") or []
        best = ""
        best_bitrate = -1
        if isinstance(variants, list):
            for variant in variants:
                if not isinstance(variant, dict):
                    continue
                vurl = str(variant.get("src") or variant.get("url") or "").strip()
                if not vurl:
                    continue
                try:
                    bitrate = int(variant.get("bitrate") or 0)
                except (TypeError, ValueError):
                    bitrate = 0
                if bitrate >= best_bitrate:
                    best_bitrate = bitrate
                    best = vurl
        if best:
            kind = "dynamic" if "tweet_video_thumb" in str(video) else "video"
            # gif-like
            vtype = str(video.get("video_type") or video.get("type") or "").lower()
            if "gif" in vtype:
                kind = "dynamic"
            _append_media(result, kind=kind, url=best)
    return result


def _fetch_json(url: str, *, timeout: float) -> dict[str, Any]:
    request = Request(
        url,
        headers=build_request_headers(accept="application/json,text/plain,*/*"),
        method="GET",
    )
    with safe_urlopen(request, timeout=timeout) as response:
        status = int(getattr(response, "status", 0) or 0)
        if status and status >= 400:
            raise StatusResolveError(f"http {status}")
        chunks: list[bytes] = []
        total = 0
        while True:
            piece = response.read(64 * 1024)
            if not piece:
                break
            total += len(piece)
            if total > MAX_RESPONSE_BYTES:
                raise StatusResolveError("response too large")
            chunks.append(piece)
    raw = b"".join(chunks)
    if not raw:
        raise StatusResolveError("empty response")
    data = json.loads(raw.decode("utf-8", errors="replace"))
    if not isinstance(data, dict):
        raise StatusResolveError("invalid json object")
    return data


def _tweet_from_fx(link: StatusLink, data: dict[str, Any]) -> TweetItem | None:
    tw = data.get("tweet") if isinstance(data.get("tweet"), dict) else None
    if tw is None and data.get("text"):
        tw = data
    if not isinstance(tw, dict):
        return None
    author = tw.get("author") if isinstance(tw.get("author"), dict) else {}
    username = str(
        author.get("screen_name") or author.get("username") or link.username or ""
    ).lstrip("@")
    text = _extract_status_text(tw)
    status_url = str(tw.get("url") or link.canonical_url).strip()
    published = format_tweet_published(str(tw.get("created_at") or "").strip())
    media = _media_from_fxtwitter(tw)
    if not text and not media:
        return None
    if not status_url:
        status_url = link.canonical_url
    if username and "/status/" in status_url:
        # Prefer canonical with real author when present.
        status_url = f"https://x.com/{username}/status/{link.status_id}"
    return TweetItem(
        text=text,
        link=status_url,
        published=published,
        media=media,
    )


def _tweet_from_vx(link: StatusLink, data: dict[str, Any]) -> TweetItem | None:
    text = _extract_status_text(data)
    username = str(
        data.get("user_screen_name") or data.get("user_name") or link.username or ""
    ).lstrip("@")
    status_url = str(
        data.get("tweetURL") or data.get("url") or link.canonical_url
    ).strip()
    published = format_tweet_published(
        str(data.get("date") or data.get("created_at") or "").strip()
    )
    media = _media_from_vxtwitter(data)
    if not text and not media:
        return None
    if username:
        status_url = f"https://x.com/{username}/status/{link.status_id}"
    return TweetItem(
        text=text,
        link=status_url,
        published=published,
        media=media,
    )


def _tweet_from_syndication(link: StatusLink, data: dict[str, Any]) -> TweetItem | None:
    text = _extract_status_text(data)
    user = data.get("user") if isinstance(data.get("user"), dict) else {}
    username = str(user.get("screen_name") or link.username or "").lstrip("@")
    published = format_tweet_published(str(data.get("created_at") or "").strip())
    media = _media_from_syndication(data)
    if not text and not media:
        return None
    status_url = (
        f"https://x.com/{username}/status/{link.status_id}"
        if username
        else link.canonical_url
    )
    return TweetItem(
        text=text,
        link=status_url,
        published=published,
        media=media,
    )


def _apply_image_quality(tweet: TweetItem, quality: str) -> None:
    """Align Fx/Vx/Syndication image URLs with the configured quality tier.

    These backends hand back pbs.twimg.com links at whatever tier they chose
    (usually ``name=orig``), so without this the media_quality setting had no
    effect on the status route while HTML and xdown both honoured it.
    """
    tier = str(quality or "").strip().lower()
    if tier not in {"high", "medium", "low"}:
        tier = "high"
    for media in tweet.media:
        if getattr(media, "kind", "") != "image":
            continue
        media.url = prefer_pbs_quality(media.url, tier)


def resolve_status_tweet(
    link: StatusLink,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    media_quality: str = "high",
) -> TweetItem:
    """Resolve one status link; raise StatusResolveError on total failure."""
    user = link.username or "i"
    sid = link.status_id
    sources = [
        (
            "fxtwitter",
            f"https://api.fxtwitter.com/{user}/status/{sid}",
            _tweet_from_fx,
        ),
        (
            "vxtwitter",
            f"https://api.vxtwitter.com/{user}/status/{sid}",
            _tweet_from_vx,
        ),
        (
            "syndication",
            f"https://cdn.syndication.twimg.com/tweet-result?id={sid}&token=x",
            _tweet_from_syndication,
        ),
    ]
    errors: list[str] = []
    for name, url, builder in sources:
        started = time.perf_counter()
        try:
            payload = _fetch_json(url, timeout=timeout)
            tweet = builder(link, payload)
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            if tweet is None:
                errors.append(f"{name}: empty")
                logger.info(
                    "[NitterTweets] status resolve empty: source=%s status_id=%s elapsed_ms=%s",
                    name,
                    sid,
                    elapsed_ms,
                )
                continue
            _apply_image_quality(tweet, media_quality)
            logger.info(
                "[NitterTweets] status resolve ok: source=%s status_id=%s elapsed_ms=%s media=%s quality=%s",
                name,
                sid,
                elapsed_ms,
                len(tweet.media),
                media_quality,
            )
            return tweet
        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            errors.append(f"{name}: {type(exc).__name__}")
            logger.info(
                "[NitterTweets] status resolve fail: source=%s status_id=%s elapsed_ms=%s error=%s",
                name,
                sid,
                elapsed_ms,
                type(exc).__name__,
            )
    raise StatusResolveError("; ".join(errors) or "resolve failed")


async def resolve_status_tweet_async(
    link: StatusLink,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    media_quality: str = "high",
) -> TweetItem:
    import asyncio

    return await asyncio.to_thread(
        resolve_status_tweet, link, timeout=timeout, media_quality=media_quality
    )
