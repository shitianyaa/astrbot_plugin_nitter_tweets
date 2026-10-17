"""Fx/Nitter backend selection and scheduler scan adapters.

No sender, translation or database interactions live here. The authoritative
RSS/HTML pagination, instance rotation and watermark scan remain in the
existing Nitter client rather than being reimplemented.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

try:
    from ..media_support.html_backend.query import MAX_QUERY_LENGTH
except ImportError:
    from media_support.html_backend.query import MAX_QUERY_LENGTH

from .models import (
    FetchOutcome,
    FetchStatus,
    SearchQuery,
    TimelineQuery,
    TrendQuery,
    fetch_error,
    outcome_from_tweets,
)


class QueryBackends:
    def __init__(self, nitter, fxtwitter=None, *, fetch_backend: str = "mix"):
        mode = str(fetch_backend or "mix").strip().lower()
        if mode not in {"mix", "nitter", "fx"}:
            raise ValueError("fetch_backend must be mix, nitter or fx")
        self.nitter = nitter
        self.fx = fxtwitter
        self.mode = mode

    @staticmethod
    def _check_limit(value: int) -> None:
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError("limit must be a positive integer")

    @staticmethod
    def _check_media_type(value: str) -> str:
        media_type = str(value or "").strip().lower()
        if media_type not in ("", "image", "video"):
            raise ValueError("media_type must be image or video")
        return media_type

    @staticmethod
    def _filter_media(tweets, *, media_type: str = "", media_only: bool = False):
        records = list(tweets or [])
        if media_type == "video":
            kept = [
                tweet
                for tweet in records
                if any(media.is_video for media in tweet.media)
            ]
        elif media_type == "image":
            kept = [
                tweet
                for tweet in records
                if any(media.is_image for media in tweet.media)
            ]
        elif media_only:
            kept = [tweet for tweet in records if tweet.media]
        else:
            kept = records
        return kept, len(records) - len(kept)

    @staticmethod
    def _search_term(query: str, *, media_only: bool) -> str:
        term = str(query or "").strip()
        if not term:
            raise ValueError("query cannot be empty")
        if len(term) > MAX_QUERY_LENGTH:
            raise ValueError("query exceeds MAX_QUERY_LENGTH")
        if media_only and "filter:media" not in term.lower():
            term = f"{term} filter:media"
            if len(term) > MAX_QUERY_LENGTH:
                raise ValueError("media query exceeds MAX_QUERY_LENGTH")
        return term

    @asynccontextmanager
    async def _host_skip(self):
        """Ensure run-host ContextVar is always paired even on cancellation."""
        begin = getattr(self.nitter, "begin_run_host_skip", None)
        end = getattr(self.nitter, "end_run_host_skip", None)
        enabled = callable(begin) and callable(end)
        if enabled:
            begin()
        try:
            yield
        finally:
            if enabled:
                end()

    async def fetch_timeline(self, request: TimelineQuery) -> FetchOutcome:
        self._check_limit(request.limit)
        media_filter = self._check_media_type(request.media_filter)
        if request.max_pages < 1:
            raise ValueError("max_pages must be positive")
        attempts: list[str] = []

        if self.mode == "fx" and self.fx is None:
            return fetch_error(
                "timeline",
                backend="fx",
                source=request.username,
            )
        if self.mode in ("mix", "fx") and self.fx is not None:
            fetch_kwargs = dict(
                count=request.limit,
                skip_plain_text=request.skip_plain_text or bool(media_filter),
                filter_reposts=request.filter_reposts,
                max_pages=request.max_pages,
            )
            if media_filter:
                fetch_kwargs["media_filter"] = media_filter
            try:
                tweets, cursor = await asyncio.to_thread(
                    self.fx.fetch_user_timeline,
                    request.username,
                    **fetch_kwargs,
                )
            except Exception as exc:
                attempts.append("FxTwitter=失败")
                if self.mode == "fx":
                    return fetch_error(
                        "timeline",
                        backend="fx",
                        source=request.username,
                        exception=exc,
                        host_attempts=attempts,
                    )
            else:
                return outcome_from_tweets(
                    "timeline",
                    tweets,
                    backend="fx",
                    instance="FxTwitter",
                    source=request.username,
                    cursor=cursor,
                    host_attempts=["FxTwitter=成功"],
                )

        if self.nitter is None:
            return fetch_error(
                "timeline",
                backend="nitter",
                source=request.username,
                host_attempts=attempts,
            )
        try:
            async with self._host_skip():
                instance, records = await self.nitter.fetch_user(
                    request.username,
                    request.limit,
                    filter_reposts=request.filter_reposts,
                    skip_plain_text=request.skip_plain_text or bool(media_filter),
                )
        except Exception as exc:
            return fetch_error(
                "timeline",
                backend="nitter",
                source=request.username,
                exception=exc,
                host_attempts=[*attempts, "Nitter=失败"],
            )
        records, filtered = self._filter_media(
            records,
            media_type=media_filter,
        )
        return outcome_from_tweets(
            "timeline",
            records,
            backend="nitter",
            instance=instance,
            source=request.username,
            raw_item_count=len(records) + filtered,
            plain_text_filtered=filtered,
            host_attempts=[*attempts, "Nitter=成功"],
        )

    async def search(self, request: SearchQuery) -> FetchOutcome:
        self._check_limit(request.limit)
        if request.sort not in ("latest", "top"):
            raise ValueError("sort must be latest or top")
        media_type = self._check_media_type(request.media_type)
        media_only = bool(request.is_media or media_type)
        effective_query = self._search_term(
            request.query,
            media_only=media_only,
        )
        if request.max_pages < 1:
            raise ValueError("max_pages must be positive")
        attempts: list[str] = []

        if self.mode == "fx" and self.fx is None:
            return fetch_error(
                "search",
                backend="fx",
                source=request.query,
            )
        if self.mode in ("mix", "fx") and self.fx is not None:
            try:
                tweets, cursor = await asyncio.to_thread(
                    self.fx.search_tweets,
                    request.query,
                    count=request.limit,
                    is_media=media_only,
                    feed=request.sort,
                )
            except Exception as exc:
                attempts.append("FxTwitter=失败")
                if self.mode == "fx":
                    return fetch_error(
                        "search",
                        backend="fx",
                        source=request.query,
                        exception=exc,
                        host_attempts=attempts,
                    )
            else:
                kept, filtered = self._filter_media(
                    tweets,
                    media_type=media_type,
                    media_only=media_only,
                )
                return outcome_from_tweets(
                    "search",
                    kept,
                    backend="fx",
                    instance="FxTwitter",
                    source=request.query,
                    cursor=cursor,
                    raw_item_count=len(tweets),
                    plain_text_filtered=filtered,
                    host_attempts=["FxTwitter=成功"],
                )

        if self.nitter is None:
            return fetch_error(
                "search",
                backend="nitter",
                source=request.query,
                host_attempts=attempts,
            )
        try:
            async with self._host_skip():
                instance, fetched = await asyncio.to_thread(
                    self.nitter.search,
                    effective_query,
                    request.limit,
                    max_pages=request.max_pages,
                    sort=request.sort,
                )
        except Exception as exc:
            return fetch_error(
                "search",
                backend="nitter",
                source=request.query,
                exception=exc,
                host_attempts=[*attempts, "Nitter=失败"],
            )

        kept, filtered = self._filter_media(
            fetched,
            media_type=media_type,
            media_only=media_only,
        )
        return outcome_from_tweets(
            "search",
            kept,
            backend="nitter",
            instance=instance,
            source=request.query,
            scan_complete=getattr(fetched, "scan_complete", True),
            raw_item_count=getattr(fetched, "raw_item_count", len(fetched)),
            retweet_filtered=getattr(fetched, "retweet_filtered", 0),
            plain_text_filtered=filtered,
            anchor_status_ids=getattr(fetched, "anchor_status_ids", None),
            host_attempts=[
                *attempts,
                *(getattr(fetched, "host_attempts", []) or ["Nitter=成功"]),
            ],
        )

    async def trends(self, _request: TrendQuery) -> FetchOutcome:
        if self.fx is None:
            return fetch_error("trends", backend="fx", source="trends")
        try:
            trends = await asyncio.to_thread(self.fx.fetch_trends)
        except Exception as exc:
            return fetch_error(
                "trends",
                backend="fx",
                source="trends",
                exception=exc,
            )
        return FetchOutcome(
            kind="trends",
            status=FetchStatus.SUCCESS if trends else FetchStatus.EMPTY,
            trends=list(trends or []),
            backend="fx",
            source="trends",
            host_attempts=["FxTwitter=成功"],
        )

    async def scan_timeline(
        self,
        username: str,
        anchor_ids: list[str] | None,
        *,
        skip_plain_text: bool = False,
        filter_reposts: bool = True,
    ) -> FetchOutcome:
        if self.nitter is None:
            return fetch_error("timeline", backend="nitter", source=username)
        media_path = f"{username}/media" if skip_plain_text and filter_reposts else ""
        try:
            async with self._host_skip():
                instance, scan = await self.nitter.fetch_tweets_for_scheduler(
                    username,
                    anchor_ids,
                    skip_plain_text=skip_plain_text,
                    filter_reposts=filter_reposts,
                    path_override=media_path,
                )
        except Exception as exc:
            return fetch_error(
                "timeline",
                backend="nitter",
                source=username,
                exception=exc,
            )
        return self._from_scheduler_scan("timeline", username, instance, scan)

    @staticmethod
    def _from_scheduler_scan(
        kind: str,
        source: str,
        instance: str,
        scan,
    ) -> FetchOutcome:
        return outcome_from_tweets(
            kind,
            scan.tweets,
            backend="nitter",
            instance=instance,
            source=source,
            scan_complete=scan.complete,
            scanned_status_ids=scan.scanned_status_ids,
            anchor_status_ids=scan.anchor_status_ids,
            latest_status_id=scan.latest_status_id,
            plain_text_filtered=scan.plain_text_filtered,
            retweet_filtered=getattr(scan, "reposts_filtered", 0),
            reached_watermark=getattr(scan, "reached_watermark", False),
            host_attempts=["Nitter=成功"],
        )

    async def scan_search(
        self,
        query: str,
        limit: int,
        *,
        anchor_ids: list[str] | None = None,
        kind: str = "tag",
        skip_plain_text: bool = False,
        filter_reposts: bool = True,
    ) -> FetchOutcome:
        self._check_limit(limit)
        effective_query = self._search_term(
            query,
            media_only=skip_plain_text,
        )
        if kind not in ("tag", "phrase"):
            raise ValueError("kind must be tag or phrase")
        if self.nitter is None:
            return fetch_error("search", backend="nitter", source=query)
        kwargs = dict(kind=kind, filter_reposts=filter_reposts, sort="latest")
        if anchor_ids is not None:
            kwargs["anchor_ids"] = anchor_ids
        try:
            async with self._host_skip():
                instance, fetched = await asyncio.to_thread(
                    self.nitter.search, effective_query, limit, **kwargs
                )
        except Exception as exc:
            return fetch_error(
                "search",
                backend="nitter",
                source=query,
                exception=exc,
            )
        kept, filtered = self._filter_media(fetched, media_only=skip_plain_text)
        return outcome_from_tweets(
            "search",
            kept,
            backend="nitter",
            instance=instance,
            source=query,
            scan_complete=getattr(fetched, "scan_complete", True),
            raw_item_count=getattr(fetched, "raw_item_count", len(fetched)),
            retweet_filtered=getattr(fetched, "retweet_filtered", 0),
            plain_text_filtered=filtered,
            anchor_status_ids=getattr(fetched, "anchor_status_ids", None),
            host_attempts=getattr(fetched, "host_attempts", []),
        )

    async def scan_list(
        self,
        list_id: str,
        anchor_ids: list[str] | None,
        *,
        limit: int = 20,
        skip_plain_text: bool = False,
        filter_reposts: bool = True,
    ) -> FetchOutcome:
        self._check_limit(limit)
        if self.nitter is None:
            return fetch_error("list", backend="nitter", source=list_id)
        rss_error = None
        async with self._host_skip():
            try:
                instance, scan = await self.nitter.fetch_list_for_scheduler(
                    list_id,
                    anchor_ids,
                    skip_plain_text=skip_plain_text,
                    filter_reposts=filter_reposts,
                )
                if scan.tweets or scan.complete:
                    return self._from_scheduler_scan("list", list_id, instance, scan)
            except Exception as exc:
                rss_error = exc

            try:
                instance, fetched = await asyncio.to_thread(
                    self.nitter.fetch_list,
                    list_id,
                    limit,
                    filter_reposts=filter_reposts,
                    anchor_ids=anchor_ids,
                )
            except Exception as exc:
                return fetch_error(
                    "list",
                    backend="nitter",
                    source=list_id,
                    exception=rss_error or exc,
                )

        kept, filtered = self._filter_media(
            fetched,
            media_only=skip_plain_text,
        )
        return outcome_from_tweets(
            "list",
            kept,
            backend="nitter",
            instance=instance,
            source=list_id,
            scan_complete=getattr(fetched, "scan_complete", True),
            raw_item_count=getattr(fetched, "raw_item_count", len(fetched)),
            retweet_filtered=getattr(fetched, "retweet_filtered", 0),
            plain_text_filtered=filtered,
            anchor_status_ids=getattr(fetched, "anchor_status_ids", None),
            host_attempts=getattr(fetched, "host_attempts", []),
        )

    async def scan_merged(
        self,
        usernames: list[str],
        watermarks: dict[str, list[str] | None],
        *,
        skip_plain_text: bool = False,
        filter_reposts: bool = True,
    ) -> dict[str, FetchOutcome]:
        """Return only actually scanned users; caller handles missing-user fallback.

        The caller batches long lists via NitterClient.batch_usernames_by_path_length;
        the Nitter client implements oldest-watermark pagination. An absent
        per-user result must never be reported as a successfully empty feed.
        Merged RSS drops cross-author reposts, so this path requires filtering.
        """
        if not filter_reposts:
            raise ValueError("merged scan requires filter_reposts=True")
        if not usernames:
            return {}
        if self.nitter is None:
            return {
                username: fetch_error(
                    "timeline",
                    backend="nitter",
                    source=username,
                )
                for username in usernames
            }
        try:
            async with self._host_skip():
                instance, scans = await self.nitter.fetch_merged_for_scheduler(
                    usernames,
                    watermarks,
                    skip_plain_text=skip_plain_text,
                    filter_reposts=True,
                    media=skip_plain_text,
                )
        except Exception as exc:
            return {
                username: fetch_error(
                    "timeline",
                    backend="nitter",
                    source=username,
                    exception=exc,
                )
                for username in usernames
            }
        return {
            username: self._from_scheduler_scan(
                "timeline",
                username,
                instance,
                scan,
            )
            for username, scan in scans.items()
        }
