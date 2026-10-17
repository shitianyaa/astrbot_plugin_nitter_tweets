"""P-01 behavior anchors for the existing fetch and reservation paths.

These assertions deliberately exercise the pre-refactor APIs; they remain
valid after the common query backend is introduced.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from media_support.html_backend.pool import HtmlSearchResult
from media_support.nitter import NitterService
from media_support.search_session_buffer import SessionSearchBuffer
from scheduler.models import SourceStatus
from scheduler.runner_fetch import _classify_html_fetch
from shared.utils import TweetItem


def _tweet(status_id: str) -> TweetItem:
    return TweetItem(
        text="original text",
        link=f"https://x.com/example/status/{status_id}",
        published="",
    )


def test_existing_nitter_fetch_skips_html_when_rss_has_tweets():
    service = NitterService({"instances": ["https://example.test"]})
    tweets = [_tweet("11")]
    service.fetch_tweets = AsyncMock(return_value=("rss-host", tweets))
    service.fetch_user_html = MagicMock(side_effect=AssertionError("HTML used"))

    assert asyncio.run(service.fetch_user("example", 5)) == ("rss-host", tweets)
    service.fetch_user_html.assert_not_called()


def test_existing_nitter_fetch_preserves_rss_failure_when_html_also_fails():
    service = NitterService({"instances": ["https://example.test"]})
    rss_error = RuntimeError("rss unavailable")
    service.fetch_tweets = AsyncMock(side_effect=rss_error)
    service.fetch_user_html = MagicMock(side_effect=RuntimeError("html unavailable"))

    with pytest.raises(RuntimeError) as raised:
        asyncio.run(service.fetch_user("example", 5))
    assert raised.value is rss_error


def test_existing_html_scan_preserves_raw_and_filtered_information():
    tweets = HtmlSearchResult(
        [],
        raw_item_count=4,
        retweet_filtered=4,
        scan_complete=True,
        anchor_status_ids=["501", "502"],
    )
    assert tweets.anchor_status_ids == ["501", "502"]
    assert (
        _classify_html_fetch(
            tweets,
            scan_complete=tweets.scan_complete,
            raw_item_count=tweets.raw_item_count,
            retweet_filtered=tweets.retweet_filtered,
            plain_text_filtered=0,
        )
        == SourceStatus.FILTERED_EMPTY
    )
    assert (
        _classify_html_fetch(
            [],
            scan_complete=False,
            raw_item_count=0,
            retweet_filtered=0,
            plain_text_filtered=0,
        )
        == SourceStatus.EMPTY
    )
    assert (
        _classify_html_fetch(
            [_tweet("11")],
            scan_complete=False,
            raw_item_count=1,
            retweet_filtered=0,
            plain_text_filtered=0,
        )
        == SourceStatus.INCOMPLETE
    )


def test_existing_buffer_rollback_restores_only_unsent_suffix():
    buffer = SessionSearchBuffer()
    buffer.add_tweets([_tweet("1"), _tweet("2"), _tweet("3")])
    token, batch = buffer.reserve(3)
    assert [item.status_id for item in batch] == ["1", "2", "3"]

    buffer.finalize(token, sent_count=1, failed_count=1)
    assert [item.status_id for item in buffer.take(3)] == ["3"]
    assert buffer.add_tweets([_tweet("2")]) == 0
