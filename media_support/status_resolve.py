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
    from .video_probe import (
        coerce_duration_seconds,
        duration_from_mapping,
        extract_video_resolution,
    )
    from .xdown import XdownMediaCandidate
except ImportError:
    from media_support.html_backend.parser import prefer_pbs_quality
    from media_support.network import build_request_headers, safe_urlopen
    from media_support.status_link import StatusLink
    from media_support.video_probe import (
        coerce_duration_seconds,
        duration_from_mapping,
        extract_video_resolution,
    )
    from media_support.xdown import XdownMediaCandidate
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


def _append_media(
    bucket: list[TweetMedia],
    *,
    kind: str,
    url: str,
    duration_seconds: float | None = None,
    fallback_url: str = "",
) -> None:
    link = str(url or "").strip()
    if not link.startswith(("http://", "https://")):
        return
    if any(item.url == link for item in bucket):
        return
    bucket.append(
        TweetMedia(
            kind=kind,
            url=link,
            duration_seconds=duration_seconds,
            fallback_url=fallback_url,
        )
    )


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
    top_duration = coerce_duration_seconds(
        payload.get("duration") or payload.get("duration_seconds")
    )
    for item in items:
        if not isinstance(item, dict):
            continue
        kind = _kind_from_type(str(item.get("type") or "photo"))
        url = item.get("url") or item.get("thumbnail_url") or ""
        duration = (
            coerce_duration_seconds(
                item.get("duration") or item.get("duration_seconds")
            )
            or top_duration
        )
        if duration is None and item.get("duration_millis"):
            try:
                duration = float(item["duration_millis"]) / 1000.0
            except (TypeError, ValueError):
                pass
        if kind in {"video", "dynamic"}:
            # Prefer highest quality variants when present.
            variants = (
                item.get("variants")
                or item.get("formats")
                or (item.get("video_info") or {}).get("variants")
            )
            best = ""
            best_bitrate = -1
            if isinstance(variants, list):
                for variant in variants:
                    if not isinstance(variant, dict):
                        continue
                    vurl = str(variant.get("url") or variant.get("src") or "").strip()
                    if not vurl:
                        continue
                    content_type = str(variant.get("content_type") or "").lower()
                    if (
                        "mpegurl" in content_type
                        or vurl.endswith(".m3u8")
                        or ".m3u8?" in vurl
                    ):
                        continue
                    try:
                        bitrate = int(variant.get("bitrate") or 0)
                    except (TypeError, ValueError):
                        bitrate = 0
                    if bitrate >= best_bitrate:
                        best_bitrate = bitrate
                        best = vurl
            url = best or url
        _append_media(result, kind=kind, url=str(url), duration_seconds=duration)
    return result


def _candidates_from_fxtwitter(payload: dict[str, Any]) -> list[XdownMediaCandidate]:
    media_block = payload.get("media") or {}
    items = media_block.get("all") if isinstance(media_block, dict) else None
    if not isinstance(items, list):
        items = []
    result: list[XdownMediaCandidate] = []
    top_duration = coerce_duration_seconds(
        payload.get("duration") or payload.get("duration_seconds")
    )
    for item in items:
        if not isinstance(item, dict):
            continue
        kind = _kind_from_type(str(item.get("type") or "photo"))
        if kind == "image":
            url = str(item.get("url") or item.get("thumbnail_url") or "").strip()
            if url:
                result.append(XdownMediaCandidate(kind="image", url=url))
            continue

        item_duration = (
            coerce_duration_seconds(
                item.get("duration") or item.get("duration_seconds")
            )
            or top_duration
        )
        if item_duration is None and item.get("duration_millis"):
            try:
                item_duration = float(item["duration_millis"]) / 1000.0
            except (TypeError, ValueError):
                pass

        variants = (
            item.get("variants")
            or item.get("formats")
            or (item.get("video_info") or {}).get("variants")
            or []
        )
        variant_candidates: list[XdownMediaCandidate] = []
        if isinstance(variants, list):
            seen_vurls: set[str] = set()
            for variant in variants:
                if not isinstance(variant, dict):
                    continue
                vurl = str(variant.get("url") or variant.get("src") or "").strip()
                if not vurl or vurl in seen_vurls:
                    continue
                content_type = str(variant.get("content_type") or "").lower()
                if (
                    "mpegurl" in content_type
                    or vurl.endswith(".m3u8")
                    or ".m3u8?" in vurl
                ):
                    continue
                seen_vurls.add(vurl)
                try:
                    bitrate = int(variant.get("bitrate") or 0)
                except (TypeError, ValueError):
                    bitrate = 0

                res = None
                if variant.get("resolution"):
                    try:
                        res = int(variant["resolution"])
                    except (TypeError, ValueError):
                        res = extract_video_resolution(str(variant["resolution"]), "")
                if res is None and variant.get("width") and variant.get("height"):
                    try:
                        w, h = int(variant["width"]), int(variant["height"])
                        if w > 0 and h > 0:
                            res = min(w, h)
                    except (TypeError, ValueError):
                        pass
                if res is None:
                    res = extract_video_resolution("", vurl)

                v_dur = coerce_duration_seconds(
                    variant.get("duration") or variant.get("duration_seconds")
                )
                dur = v_dur if v_dur is not None else item_duration

                size_bytes = None
                for skey in ("size_bytes", "filesize", "file_size", "size"):
                    if variant.get(skey):
                        try:
                            size_bytes = int(variant[skey])
                            break
                        except (TypeError, ValueError):
                            pass

                label = f"下载 MP4 ({res}p)" if res else "下载 MP4"
                variant_candidates.append(
                    XdownMediaCandidate(
                        kind=kind,
                        url=vurl,
                        label=label,
                        resolution=res,
                        duration_seconds=dur,
                        fallback_url="",
                        size_bytes=size_bytes,
                        bitrate=bitrate,
                    )
                )

        if variant_candidates:
            result.extend(variant_candidates)
        else:
            url = str(item.get("url") or item.get("thumbnail_url") or "").strip()
            if url:
                res = extract_video_resolution("", url)
                label = f"下载 MP4 ({res}p)" if res else "下载 MP4"
                result.append(
                    XdownMediaCandidate(
                        kind=kind,
                        url=url,
                        label=label,
                        resolution=res,
                        duration_seconds=item_duration,
                        fallback_url="",
                    )
                )
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
            duration = duration_from_mapping(item)
            _append_media(result, kind=kind, url=str(url), duration_seconds=duration)
    if result:
        return result
    urls = payload.get("mediaURLs") or payload.get("media_urls") or []
    if isinstance(urls, list):
        for url in urls:
            _append_media(result, kind="image", url=str(url))
    return result


def _candidates_from_vxtwitter(payload: dict[str, Any]) -> list[XdownMediaCandidate]:
    result: list[XdownMediaCandidate] = []
    extended = payload.get("media_extended")
    if isinstance(extended, list):
        for item in extended:
            if not isinstance(item, dict):
                continue
            kind = _kind_from_type(str(item.get("type") or "image"))
            url = str(item.get("url") or item.get("thumbnail_url") or "").strip()
            if not url:
                continue
            duration = duration_from_mapping(item)
            res = (
                extract_video_resolution("", url)
                if kind in {"video", "dynamic"}
                else None
            )
            result.append(
                XdownMediaCandidate(
                    kind=kind,
                    url=url,
                    label=f"下载 MP4 ({res}p)" if res else "",
                    resolution=res,
                    duration_seconds=duration,
                )
            )
    if result:
        return result
    urls = payload.get("mediaURLs") or payload.get("media_urls") or []
    if isinstance(urls, list):
        for url in urls:
            u = str(url).strip()
            if u:
                result.append(XdownMediaCandidate(kind="image", url=u))
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
        duration = duration_from_mapping(video)
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
            vtype = str(video.get("video_type") or video.get("type") or "").lower()
            if "gif" in vtype:
                kind = "dynamic"
            _append_media(result, kind=kind, url=best, duration_seconds=duration)
    return result


def _candidates_from_syndication(
    payload: dict[str, Any],
) -> list[XdownMediaCandidate]:
    result: list[XdownMediaCandidate] = []
    photos = payload.get("photos") or []
    if isinstance(photos, list):
        for item in photos:
            if isinstance(item, dict):
                url = str(item.get("url") or item.get("src") or "").strip()
            else:
                url = str(item).strip()
            if url:
                result.append(XdownMediaCandidate(kind="image", url=url))
    video = payload.get("video")
    if isinstance(video, dict):
        duration = duration_from_mapping(video)
        kind = "dynamic" if "tweet_video_thumb" in str(video) else "video"
        vtype = str(video.get("video_type") or video.get("type") or "").lower()
        if "gif" in vtype:
            kind = "dynamic"
        variants = video.get("variants") or []
        variant_candidates: list[XdownMediaCandidate] = []
        if isinstance(variants, list):
            for variant in variants:
                if not isinstance(variant, dict):
                    continue
                vurl = str(variant.get("src") or variant.get("url") or "").strip()
                if not vurl:
                    continue
                content_type = str(variant.get("content_type") or "").lower()
                if (
                    "mpegurl" in content_type
                    or vurl.endswith(".m3u8")
                    or ".m3u8?" in vurl
                ):
                    continue
                try:
                    bitrate = int(variant.get("bitrate") or 0)
                except (TypeError, ValueError):
                    bitrate = 0
                res = extract_video_resolution("", vurl)
                label = f"下载 MP4 ({res}p)" if res else "下载 MP4"
                variant_candidates.append(
                    XdownMediaCandidate(
                        kind=kind,
                        url=vurl,
                        label=label,
                        resolution=res,
                        duration_seconds=duration,
                        bitrate=bitrate,
                    )
                )
        if variant_candidates:
            result.extend(variant_candidates)
        else:
            url = str(video.get("url") or video.get("src") or "").strip()
            if url:
                res = extract_video_resolution("", url)
                result.append(
                    XdownMediaCandidate(
                        kind=kind,
                        url=url,
                        label=f"下载 MP4 ({res}p)" if res else "下载 MP4",
                        resolution=res,
                        duration_seconds=duration,
                    )
                )
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
    candidates = _candidates_from_fxtwitter(tw)
    if not text and not media and not candidates:
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
        media_candidates=candidates,
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
    candidates = _candidates_from_vxtwitter(data)
    if not text and not media and not candidates:
        return None
    if username:
        status_url = f"https://x.com/{username}/status/{link.status_id}"
    return TweetItem(
        text=text,
        link=status_url,
        published=published,
        media=media,
        media_candidates=candidates,
    )


def _tweet_from_syndication(link: StatusLink, data: dict[str, Any]) -> TweetItem | None:
    text = _extract_status_text(data)
    user = data.get("user") if isinstance(data.get("user"), dict) else {}
    username = str(user.get("screen_name") or link.username or "").lstrip("@")
    published = format_tweet_published(str(data.get("created_at") or "").strip())
    media = _media_from_syndication(data)
    candidates = _candidates_from_syndication(data)
    if not text and not media and not candidates:
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
        media_candidates=candidates,
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
    for cand in getattr(tweet, "media_candidates", []):
        if getattr(cand, "kind", "") == "image":
            cand.url = prefer_pbs_quality(cand.url, tier)


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
                    f"[NitterTweets] 链接解析为空: source={name}, "
                    f"status_id={sid}, elapsed_ms={elapsed_ms}"
                )
                continue
            _apply_image_quality(tweet, media_quality)
            logger.info(
                f"[NitterTweets] 链接解析成功: source={name}, "
                f"status_id={sid}, elapsed_ms={elapsed_ms}, "
                f"media={len(tweet.media)}, quality={media_quality}"
            )
            return tweet
        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            errors.append(f"{name}: {type(exc).__name__}")
            logger.info(
                f"[NitterTweets] 链接解析失败: source={name}, "
                f"status_id={sid}, elapsed_ms={elapsed_ms}, "
                f"error={type(exc).__name__}"
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
