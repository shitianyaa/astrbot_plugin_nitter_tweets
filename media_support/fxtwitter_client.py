"""FxTwitter API client for timeline, search, and trends."""

from __future__ import annotations

import datetime as dt
import json
import logging
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request

try:
    from ..shared.utils import (
        TweetItem,
        format_tweet_published,
    )
    from .network import build_request_headers, safe_urlopen
    from .status_resolve import (
        _candidates_from_fxtwitter,
        _extract_status_text,
        _media_from_fxtwitter,
    )
except ImportError:
    from media_support.network import build_request_headers, safe_urlopen
    from media_support.status_resolve import (
        _candidates_from_fxtwitter,
        _extract_status_text,
        _media_from_fxtwitter,
    )
    from shared.utils import (
        TweetItem,
        format_tweet_published,
    )

logger = logging.getLogger("astrbot")

DEFAULT_FXTWITTER_BASE_URL = "https://api.fxtwitter.com"
MAX_RESPONSE_BYTES = 5_000_000


class FxTwitterError(RuntimeError):
    """Base exception for FxTwitter client errors."""


class FxTwitterNotFoundError(FxTwitterError):
    """Raised when FxTwitter returns 404 (e.g. search endpoint unavailable)."""


class FxTwitterClient:
    """Client for querying FxTwitter API v2 endpoints."""

    def __init__(
        self,
        base_url: str = DEFAULT_FXTWITTER_BASE_URL,
        timeout: float = 15.0,
    ):
        self.base_url = (base_url or DEFAULT_FXTWITTER_BASE_URL).rstrip("/")
        self.timeout = timeout

    def _fetch_json(self, url: str, *, timeout: float | None = None) -> dict[str, Any]:
        eff_timeout = self.timeout if timeout is None else timeout
        request = Request(
            url,
            headers=build_request_headers(accept="application/json,text/plain,*/*"),
            method="GET",
        )
        try:
            with safe_urlopen(request, timeout=eff_timeout) as response:
                status = int(getattr(response, "status", 0) or 0)
                if status == 404:
                    raise FxTwitterNotFoundError(
                        f"FxTwitter resource not found (404): {url}"
                    )
                if status >= 400:
                    raise FxTwitterError(f"FxTwitter HTTP error {status}")
                chunks: list[bytes] = []
                total = 0
                while True:
                    piece = response.read(64 * 1024)
                    if not piece:
                        break
                    total += len(piece)
                    if total > MAX_RESPONSE_BYTES:
                        raise FxTwitterError("FxTwitter response too large")
                    chunks.append(piece)
        except HTTPError as exc:
            if exc.code == 404:
                raise FxTwitterNotFoundError(
                    f"FxTwitter resource not found (404): {url}"
                ) from exc
            raise FxTwitterError(
                f"FxTwitter HTTP error {exc.code}: {exc.reason}"
            ) from exc
        except FxTwitterError:
            raise
        except Exception as exc:
            raise FxTwitterError(f"FxTwitter request failed: {exc}") from exc

        raw = b"".join(chunks)
        if not raw:
            raise FxTwitterError("empty response")
        try:
            data = json.loads(raw.decode("utf-8", errors="replace"))
        except Exception as exc:
            raise FxTwitterError(f"invalid json response: {exc}") from exc

        if not isinstance(data, dict):
            raise FxTwitterError("invalid json object")

        code = data.get("code")
        if code == 404:
            raise FxTwitterNotFoundError(
                f"FxTwitter returned code 404: {data.get('message', '')}"
            )
        if isinstance(code, int) and code >= 400:
            raise FxTwitterError(f"FxTwitter error {code}: {data.get('message', '')}")

        return data

    @staticmethod
    def _extract_cursor(data: dict[str, Any]) -> str | None:
        cursor = data.get("cursor")
        if isinstance(cursor, dict):
            bottom = cursor.get("bottom")
            return str(bottom).strip() if bottom else None
        if isinstance(cursor, str):
            c = cursor.strip()
            return c or None
        return None

    @staticmethod
    def _extract_results(data: dict[str, Any]) -> list[dict[str, Any]]:
        results = data.get("results")
        if isinstance(results, list):
            return [item for item in results if isinstance(item, dict)]
        tweets = data.get("tweets")
        if isinstance(tweets, list):
            return [item for item in tweets if isinstance(item, dict)]
        statuses = data.get("statuses")
        if isinstance(statuses, list):
            return [item for item in statuses if isinstance(item, dict)]
        return []

    def _tweet_from_payload(self, data: dict[str, Any]) -> TweetItem | None:
        tw = data.get("tweet") if isinstance(data.get("tweet"), dict) else None
        if tw is None:
            tw = data
        if not isinstance(tw, dict):
            return None

        author = tw.get("author") if isinstance(tw.get("author"), dict) else {}
        username = str(
            author.get("screen_name") or author.get("username") or ""
        ).lstrip("@")
        status_id = str(tw.get("id") or tw.get("id_str") or "").strip()

        text = _extract_status_text(tw)
        media = _media_from_fxtwitter(tw)
        candidates = _candidates_from_fxtwitter(tw)
        if not text and not media and not candidates:
            return None

        status_url = str(tw.get("url") or "").strip()
        if not status_url and username and status_id:
            status_url = f"https://x.com/{username}/status/{status_id}"
        elif not status_url and status_id:
            status_url = f"https://x.com/i/status/{status_id}"

        # Normalize published time
        raw_time = str(tw.get("created_at") or "").strip()
        if not raw_time and tw.get("created_timestamp"):
            try:
                ts = float(tw["created_timestamp"])
                raw_time = dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).strftime(
                    "%a %b %d %H:%M:%S +0000 %Y"
                )
            except (ValueError, TypeError, OSError):
                raw_time = ""
        published = format_tweet_published(raw_time)

        # Detect retweet
        is_retweet = bool(
            tw.get("reposted_by")
            or tw.get("retweeted_status")
            or tw.get("is_retweet")
            or tw.get("retweet")
        )

        return TweetItem(
            text=text,
            link=status_url,
            published=published,
            media=media,
            is_retweet=is_retweet,
            media_candidates=candidates,
        )

    def fetch_user_timeline(
        self,
        username: str,
        count: int = 10,
        skip_plain_text: bool = False,
        filter_reposts: bool = True,
        cursor: str | None = None,
        max_pages: int = 3,
        media_filter: str = "",
    ) -> tuple[list[TweetItem], str | None]:
        clean_user = username.strip().lstrip("@")
        if not clean_user:
            return [], None

        target_count = max(0, int(count))
        if target_count == 0:
            return [], None

        mf = str(media_filter or "").strip().lower()
        if mf == "video":
            skip_plain_text = True
        elif mf in ("image", "photo"):
            skip_plain_text = True

        # 转推守卫：仅当 skip_plain_text=True 且 filter_reposts=True 时允许调用 /media；
        # 若 filter_reposts=False，必须调用 /statuses 并在本地过滤纯文本，防止转推媒体丢失；
        if skip_plain_text and filter_reposts:
            endpoint = f"{self.base_url}/2/profile/{clean_user}/media"
        else:
            endpoint = f"{self.base_url}/2/profile/{clean_user}/statuses"

        if skip_plain_text:
            per_page = max(20, min(target_count * 2, 100))
        else:
            per_page = max(1, min(target_count, 100))

        pages_limit = max(1, int(max_pages or 3))
        accumulated: list[TweetItem] = []
        current_cursor = cursor
        pages_fetched = 0
        last_cursor = None
        cursor_stalled = False

        while len(accumulated) < target_count and pages_fetched < pages_limit:
            params: dict[str, Any] = {"count": per_page}
            if current_cursor:
                params["cursor"] = current_cursor

            url = f"{endpoint}?{urlencode(params)}"
            data = self._fetch_json(url)
            pages_fetched += 1

            last_cursor = self._extract_cursor(data)
            raw_results = self._extract_results(data)
            if not raw_results:
                break

            if not last_cursor or last_cursor == current_cursor:
                cursor_stalled = True
            elif current_cursor is None and last_cursor:
                # 初始页（未传入游标）拿到的游标若非空，继续下一页循环时若需要可作为 current_cursor
                pass

            for raw in raw_results:
                tweet = self._tweet_from_payload(raw)
                if tweet is None:
                    continue
                # 转推过滤
                if filter_reposts and tweet.is_retweet:
                    continue
                # 媒体类型过滤
                if mf == "video":
                    if not any(m.is_video for m in tweet.media):
                        continue
                elif mf in ("image", "photo"):
                    if not any(m.is_image for m in tweet.media):
                        continue
                elif skip_plain_text and not tweet.media:
                    continue
                accumulated.append(tweet)

            if cursor_stalled or len(accumulated) >= target_count:
                break
            current_cursor = last_cursor

        effective_cursor = None if (cursor_stalled or not last_cursor) else last_cursor
        return accumulated[:target_count], effective_cursor

    def search_tweets(
        self,
        query: str,
        count: int = 10,
        is_media: bool = False,
        cursor: str | None = None,
        feed: str = "latest",
    ) -> tuple[list[TweetItem], str | None]:
        q = query.strip()
        if not q:
            return [], None

        if is_media and "filter:media" not in q.lower():
            q = f"{q} filter:media".strip()

        params: dict[str, Any] = {
            "q": q,
            "feed": str(feed or "latest").strip().lower(),
            "count": max(1, min(count, 100)),
        }
        if cursor:
            params["cursor"] = cursor

        url = f"{self.base_url}/2/search?{urlencode(params)}"
        data = self._fetch_json(url)

        next_cursor = self._extract_cursor(data)
        raw_results = self._extract_results(data)

        tweets: list[TweetItem] = []
        for raw in raw_results:
            tweet = self._tweet_from_payload(raw)
            if tweet is None:
                continue
            if is_media and not tweet.media:
                continue
            tweets.append(tweet)

        return tweets[:count], next_cursor

    def fetch_trends(self, timeout: float = 10.0) -> list[dict]:
        url = f"{self.base_url}/2/trends"
        data = self._fetch_json(url, timeout=timeout)
        raw_trends = data.get("trends")
        if isinstance(raw_trends, list):
            return [t for t in raw_trends if isinstance(t, dict)]
        return []
