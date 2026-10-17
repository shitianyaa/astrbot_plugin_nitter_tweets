"""Typed query inputs and lossless, side-effect-free fetch results."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal

try:
    from ..shared import TweetItem
except ImportError:
    from shared import TweetItem


QueryKind = Literal["timeline", "search", "trends", "list"]


class FetchStatus(StrEnum):
    SUCCESS = "success"
    EMPTY = "empty"
    FILTERED_EMPTY = "filtered_empty"
    INCOMPLETE = "incomplete"
    PARTIAL = "partial"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class TimelineQuery:
    username: str
    limit: int = 5
    skip_plain_text: bool = False
    filter_reposts: bool = True
    max_pages: int = 3
    media_filter: str = ""
    cursor: str | None = None


@dataclass(frozen=True, slots=True)
class SearchQuery:
    query: str
    limit: int = 5
    sort: str = "latest"
    is_media: bool = False
    max_pages: int = 3
    media_type: str = ""
    cursor: str | None = None


@dataclass(frozen=True, slots=True)
class TrendQuery:
    """Trends has no required input; FxTwitter remains its sole provider."""


@dataclass(slots=True)
class FetchOutcome:
    kind: QueryKind
    status: FetchStatus
    tweets: list[TweetItem] = field(default_factory=list, repr=False)
    trends: list[dict[str, Any]] = field(default_factory=list, repr=False)
    backend: str = ""
    # Only for internal sender/scan plumbing. Never serialize this as an LLM
    # result: self-hosted instance URLs may reveal private network topology.
    instance: str = field(default="", repr=False)
    source: str = field(default="", repr=False)
    cursor: str | None = None
    scan_complete: bool = True
    scanned_status_ids: list[str] = field(default_factory=list)
    anchor_status_ids: list[str] = field(default_factory=list)
    latest_status_id: str = ""
    raw_item_count: int = 0
    retweet_filtered: int = 0
    plain_text_filtered: int = 0
    reached_watermark: bool = False
    # Scheduler-internal diagnostics, not intended for LLM/user serialization.
    host_attempts: list[str] = field(default_factory=list, repr=False)
    error_kind: str = ""
    warnings: list[str] = field(default_factory=list)


def classify_fetch(
    tweets: list[TweetItem],
    *,
    scan_complete: bool,
    raw_item_count: int,
    retweet_filtered: int,
    plain_text_filtered: int,
) -> FetchStatus:
    """Preserve the existing scheduler distinction between empty and filtered.

    An actually empty HTML page remains EMPTY even if pagination was unable
    to prove completeness; unfiltered rows in an incomplete scan do not
    become a false terminal EMPTY.
    """
    if (
        not tweets
        and not raw_item_count
        and not retweet_filtered
        and not plain_text_filtered
    ):
        return FetchStatus.EMPTY
    if not scan_complete:
        return FetchStatus.INCOMPLETE
    if tweets:
        return FetchStatus.SUCCESS
    return FetchStatus.FILTERED_EMPTY


def outcome_from_tweets(
    kind: QueryKind,
    records: list[TweetItem],
    *,
    backend: str,
    instance: str = "",
    source: str = "",
    cursor: str | None = None,
    scan_complete: bool | None = None,
    raw_item_count: int | None = None,
    retweet_filtered: int | None = None,
    plain_text_filtered: int = 0,
    scanned_status_ids: list[str] | None = None,
    anchor_status_ids: list[str] | None = None,
    latest_status_id: str | None = None,
    reached_watermark: bool = False,
    host_attempts: list[str] | None = None,
    warnings: list[str] | None = None,
) -> FetchOutcome:
    """Adapt RSS/HTML/Fx results without discarding available scan metadata."""
    tweets = list(records or [])
    complete = (
        bool(getattr(records, "scan_complete", True))
        if scan_complete is None
        else bool(scan_complete)
    )
    raw_count = (
        getattr(records, "raw_item_count", len(tweets) + plain_text_filtered)
        if raw_item_count is None
        else raw_item_count
    )
    reposts = (
        getattr(records, "retweet_filtered", 0)
        if retweet_filtered is None
        else retweet_filtered
    )
    ids = (
        [tweet.status_id for tweet in tweets if tweet.status_id]
        if scanned_status_ids is None
        else list(scanned_status_ids)
    )
    anchors = (
        list(getattr(records, "anchor_status_ids", ids[:20]))
        if anchor_status_ids is None
        else list(anchor_status_ids)
    )
    latest = (
        (tweets[0].status_id if tweets else "")
        if latest_status_id is None
        else str(latest_status_id)
    )
    attempts = (
        list(getattr(records, "host_attempts", []) or [])
        if host_attempts is None
        else list(host_attempts)
    )
    filtered = max(0, int(plain_text_filtered))
    raw_count = max(0, int(raw_count or 0))
    reposts = max(0, int(reposts or 0))
    return FetchOutcome(
        kind=kind,
        status=classify_fetch(
            tweets,
            scan_complete=complete,
            raw_item_count=raw_count,
            retweet_filtered=reposts,
            plain_text_filtered=filtered,
        ),
        tweets=tweets,
        backend=backend,
        instance=instance,
        source=source,
        cursor=cursor,
        scan_complete=complete,
        scanned_status_ids=ids,
        anchor_status_ids=anchors,
        latest_status_id=latest,
        raw_item_count=raw_count,
        retweet_filtered=reposts,
        plain_text_filtered=filtered,
        reached_watermark=bool(reached_watermark),
        host_attempts=attempts,
        warnings=list(warnings or []),
    )


def fetch_error(
    kind: QueryKind,
    *,
    backend: str,
    source: str,
    exception: Exception | None = None,
    host_attempts: list[str] | None = None,
) -> FetchOutcome:
    # Keep raw exception strings out of dataclass repr, logs and later LLM
    # output. P-03 may map these stable types to localized user messages.
    return FetchOutcome(
        kind=kind,
        status=FetchStatus.ERROR,
        backend=backend,
        source=source,
        error_kind=type(exception).__name__ if exception else "UnavailableProvider",
        host_attempts=list(host_attempts or []),
    )
