"""P-01 contract tests: side-effect-free shared query/scan adapters."""

from __future__ import annotations

import asyncio
import threading
from unittest.mock import AsyncMock, MagicMock

import pytest

from media_support.client import SchedulerFetchResult
from media_support.html_backend.pool import HtmlSearchResult
from query import (
    FetchStatus,
    QueryService,
    SearchQuery,
    TimelineQuery,
    TrendQuery,
)
from query.session import ResultSessionStore
from shared.utils import TweetItem, TweetMedia


def _tweet(id_: str, *, media: str = "") -> TweetItem:
    return TweetItem(
        text=f"post {id_}",
        link=f"https://x.com/alice/status/{id_}",
        published="2026-10-17 12:00:00",
        media=(
            [TweetMedia(kind=media, url="https://pbs.twimg.com/a.jpg")] if media else []
        ),
    )


def _nitter():
    nitter = MagicMock()
    nitter.fetch_user = AsyncMock(return_value=("internal-instance", [_tweet("1")]))
    nitter.begin_run_host_skip = MagicMock()
    nitter.end_run_host_skip = MagicMock()
    nitter.search = MagicMock(return_value=("internal-instance", [_tweet("2")]))
    return nitter


def _fx():
    fx = MagicMock()
    fx.fetch_user_timeline = MagicMock(return_value=([_tweet("3")], "next"))
    fx.search_tweets = MagicMock(return_value=([_tweet("4")], "cursor"))
    fx.fetch_trends = MagicMock(return_value=[{"name": "#test", "rank": 1}])
    return fx


@pytest.mark.asyncio
async def test_mix_fx_success_and_empty_do_not_fall_back_to_nitter():
    nitter, fx = _nitter(), _fx()
    service = QueryService(nitter, fx, fetch_backend="mix")
    success = await service.fetch_timeline(TimelineQuery("alice", limit=3))
    assert success.status == FetchStatus.SUCCESS
    assert success.backend == "fx"
    assert success.cursor == "next"
    assert [t.status_id for t in success.tweets] == ["3"]
    fx.fetch_user_timeline.assert_called_once_with(
        "alice",
        count=3,
        skip_plain_text=False,
        filter_reposts=True,
        max_pages=3,
    )
    nitter.fetch_user.assert_not_called()

    fx.fetch_user_timeline.return_value = ([], None)
    empty = await service.fetch_timeline(TimelineQuery("alice"))
    assert empty.status == FetchStatus.EMPTY
    assert empty.error_kind == ""
    nitter.fetch_user.assert_not_called()


@pytest.mark.asyncio
async def test_mix_fx_error_falls_back_to_nitter_and_balances_host_skip():
    nitter, fx = _nitter(), _fx()
    fx.fetch_user_timeline.side_effect = RuntimeError("private host http://localhost")
    outcome = await QueryService(nitter, fx).fetch_timeline(
        TimelineQuery("alice", filter_reposts=False, skip_plain_text=True)
    )
    assert outcome.status == FetchStatus.SUCCESS
    assert outcome.backend == "nitter"
    assert outcome.host_attempts == ["FxTwitter=失败", "Nitter=成功"]
    assert outcome.error_kind == ""
    nitter.fetch_user.assert_awaited_once_with(
        "alice", 5, filter_reposts=False, skip_plain_text=True
    )
    nitter.begin_run_host_skip.assert_called_once()
    nitter.end_run_host_skip.assert_called_once()


@pytest.mark.asyncio
async def test_fx_only_error_is_not_mislabeled_empty():
    nitter, fx = _nitter(), _fx()
    fx.fetch_user_timeline.side_effect = RuntimeError("token=private")
    outcome = await QueryService(nitter, fx, fetch_backend="fx").fetch_timeline(
        TimelineQuery("alice")
    )
    assert outcome.status == FetchStatus.ERROR
    assert outcome.error_kind == "RuntimeError"
    assert not outcome.tweets
    assert "private" not in str(outcome)
    nitter.fetch_user.assert_not_called()


@pytest.mark.asyncio
async def test_nitter_mode_never_calls_fx_even_when_it_is_available():
    nitter, fx = _nitter(), _fx()
    outcome = await QueryService(nitter, fx, fetch_backend="nitter").fetch_timeline(
        TimelineQuery("alice")
    )
    assert outcome.backend == "nitter"
    fx.fetch_user_timeline.assert_not_called()


@pytest.mark.asyncio
async def test_search_preserves_nitter_html_scan_metadata_and_sort():
    nitter, fx = _nitter(), _fx()
    found = HtmlSearchResult(
        [_tweet("2")],
        raw_item_count=8,
        retweet_filtered=7,
        scan_complete=False,
        anchor_status_ids=["18", "17"],
        host_attempts=["host attempt"],
    )
    nitter.search.return_value = ("private-host", found)
    outcome = await QueryService(nitter, fx, fetch_backend="nitter").search(
        SearchQuery("#hello", limit=4, sort="top")
    )
    assert outcome.status == FetchStatus.INCOMPLETE
    assert outcome.backend == "nitter"
    assert outcome.raw_item_count == 8
    assert outcome.retweet_filtered == 7
    assert outcome.anchor_status_ids == ["18", "17"]
    assert outcome.scan_complete is False
    nitter.search.assert_called_once_with("#hello", 4, max_pages=3, sort="top")


@pytest.mark.asyncio
async def test_search_fx_empty_does_not_trigger_nitter_recovery():
    nitter, fx = _nitter(), _fx()
    fx.search_tweets.return_value = ([], None)
    result = await QueryService(nitter, fx).search(SearchQuery("#test"))
    assert result.status == FetchStatus.EMPTY
    nitter.search.assert_not_called()


@pytest.mark.asyncio
async def test_search_media_filters_from_metadata_without_downloading():
    nitter = _nitter()
    nitter.search.return_value = ("internal", [_tweet("1"), _tweet("2", media="image")])
    result = await QueryService(nitter, None, fetch_backend="nitter").search(
        SearchQuery("cats", is_media=True)
    )
    assert [tweet.status_id for tweet in result.tweets] == ["2"]
    assert result.raw_item_count == 2
    assert result.plain_text_filtered == 1
    assert result.status == FetchStatus.SUCCESS
    assert nitter.search.call_args.args[0] == "cats filter:media"


@pytest.mark.asyncio
async def test_search_filter_empty_is_distinct_from_empty_feed():
    nitter = _nitter()
    nitter.search.return_value = (
        "internal",
        HtmlSearchResult([], raw_item_count=6, retweet_filtered=6),
    )
    result = await QueryService(nitter, fetch_backend="nitter").search(
        SearchQuery("#topic")
    )
    assert result.status == FetchStatus.FILTERED_EMPTY


@pytest.mark.asyncio
async def test_trends_always_uses_fx_provider_without_changing_delivery_state():
    nitter, fx = _nitter(), _fx()
    result = await QueryService(nitter, fx, fetch_backend="nitter").trends(TrendQuery())
    assert result.status == FetchStatus.SUCCESS
    assert result.trends == [{"name": "#test", "rank": 1}]
    fx.fetch_trends.assert_called_once()
    nitter.search.assert_not_called()


@pytest.mark.asyncio
async def test_sync_search_runs_in_thread_and_does_not_block_loop():
    nitter = _nitter()
    started, release = threading.Event(), threading.Event()

    def slow_search(*args, **kwargs):
        started.set()
        assert release.wait(3)
        return "internal", [_tweet("4")]

    nitter.search.side_effect = slow_search
    task = asyncio.create_task(
        QueryService(nitter, fetch_backend="nitter").search(SearchQuery("topic"))
    )
    try:
        await asyncio.wait_for(asyncio.to_thread(started.wait, 3), 4)
        assert not task.done()
    finally:
        release.set()
    assert (await task).status == FetchStatus.SUCCESS


@pytest.mark.asyncio
async def test_host_skip_is_restored_even_when_nitter_is_cancelled():
    nitter = _nitter()
    started = asyncio.Event()

    async def hang(*args, **kwargs):
        started.set()
        await asyncio.Event().wait()

    nitter.fetch_user.side_effect = hang
    task = asyncio.create_task(
        QueryService(nitter, fetch_backend="nitter").fetch_timeline(
            TimelineQuery("alice")
        )
    )
    await asyncio.wait_for(started.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    nitter.begin_run_host_skip.assert_called_once()
    nitter.end_run_host_skip.assert_called_once()


@pytest.mark.asyncio
async def test_scheduler_scan_preserves_raw_watermark_and_filter_metadata():
    nitter = _nitter()
    scan = SchedulerFetchResult(
        tweets=[_tweet("91")],
        scanned_status_ids=["91", "90"],
        anchor_status_ids=["91", "90"],
        latest_status_id="91",
        plain_text_filtered=6,
        reposts_filtered=4,
        complete=False,
        reached_watermark=False,
    )
    nitter.fetch_tweets_for_scheduler = AsyncMock(return_value=("internal", scan))
    result = await QueryService(nitter, fetch_backend="nitter").scan_timeline(
        "alice", ["89"], skip_plain_text=True, filter_reposts=True
    )
    assert result.status == FetchStatus.INCOMPLETE
    assert result.scan_complete is False
    assert result.scanned_status_ids == ["91", "90"]
    assert result.anchor_status_ids == ["91", "90"]
    assert result.latest_status_id == "91"
    assert result.plain_text_filtered == 6
    assert result.retweet_filtered == 4
    nitter.fetch_tweets_for_scheduler.assert_awaited_once_with(
        "alice",
        ["89"],
        skip_plain_text=True,
        filter_reposts=True,
        path_override="alice/media",
    )


@pytest.mark.asyncio
async def test_scheduler_search_preserves_anchor_and_filtered_empty():
    nitter = _nitter()
    nitter.search.return_value = (
        "internal",
        HtmlSearchResult(
            [], raw_item_count=3, retweet_filtered=3, anchor_status_ids=["302", "301"]
        ),
    )
    result = await QueryService(nitter, fetch_backend="nitter").scan_search(
        "#news", 20, anchor_ids=["290"], kind="tag"
    )
    assert result.status == FetchStatus.FILTERED_EMPTY
    assert result.anchor_status_ids == ["302", "301"]
    nitter.search.assert_called_once_with(
        "#news",
        20,
        kind="tag",
        anchor_ids=["290"],
        filter_reposts=True,
        sort="latest",
    )


@pytest.mark.asyncio
async def test_scheduler_list_uses_rss_scan_and_preserves_complete_empty():
    nitter = _nitter()
    nitter.fetch_list_for_scheduler = AsyncMock(
        return_value=(
            "internal",
            SchedulerFetchResult(
                tweets=[],
                scanned_status_ids=["99"],
                complete=True,
                anchor_status_ids=["99"],
            ),
        )
    )
    result = await QueryService(nitter, fetch_backend="fx").scan_list("123", ["90"])
    assert result.status == FetchStatus.EMPTY
    assert result.scanned_status_ids == ["99"]
    nitter.fetch_list_for_scheduler.assert_awaited_once()
    nitter.fetch_list.assert_not_called()


def test_result_session_store_isolated_namespace_preserves_reservation_protocol():
    store = ResultSessionStore()
    manual = store.window("manual", "same-session", "#news")
    llm = store.window("llm", "same-session", "#news")
    manual.add_tweets([_tweet("10")])
    assert len(llm) == 0

    token, records = manual.reserve(1)
    assert len(records) == 1
    manual.rollback(token)
    assert [x.status_id for x in manual.take(1)] == ["10"]


@pytest.mark.asyncio
async def test_search_mix_fx_error_falls_back_without_treating_it_as_empty():
    nitter, fx = _nitter(), _fx()
    fx.search_tweets.side_effect = TimeoutError("https://private.example/key")
    result = await QueryService(nitter, fx).search(SearchQuery("topic", sort="latest"))
    assert result.status == FetchStatus.SUCCESS
    assert result.backend == "nitter"
    assert result.host_attempts == ["FxTwitter=失败", "Nitter=成功"]
    assert "private" not in repr(result)


@pytest.mark.asyncio
async def test_search_double_failure_is_error_not_empty():
    nitter, fx = _nitter(), _fx()
    fx.search_tweets.side_effect = TimeoutError("private token")
    nitter.search.side_effect = ConnectionError("https://private.example")
    result = await QueryService(nitter, fx).search(SearchQuery("topic"))
    assert result.status == FetchStatus.ERROR
    assert result.error_kind == "ConnectionError"
    assert result.host_attempts == ["FxTwitter=失败", "Nitter=失败"]
    assert "private" not in repr(result)


@pytest.mark.asyncio
async def test_scheduler_list_rss_incomplete_empty_falls_back_to_html():
    nitter = _nitter()
    nitter.fetch_list_for_scheduler = AsyncMock(
        return_value=(
            "rss",
            SchedulerFetchResult(
                tweets=[],
                scanned_status_ids=["100"],
                anchor_status_ids=["100"],
                complete=False,
            ),
        )
    )
    nitter.fetch_list = MagicMock(
        return_value=(
            "html",
            HtmlSearchResult(
                [_tweet("101")],
                raw_item_count=4,
                retweet_filtered=3,
                anchor_status_ids=["104", "103"],
                scan_complete=False,
            ),
        )
    )
    result = await QueryService(nitter).scan_list("123", ["90"], limit=15)
    assert result.instance == "html"
    assert result.status == FetchStatus.INCOMPLETE
    assert result.anchor_status_ids == ["104", "103"]
    assert result.retweet_filtered == 3
    nitter.fetch_list.assert_called_once_with(
        "123", 15, filter_reposts=True, anchor_ids=["90"]
    )


@pytest.mark.asyncio
async def test_scheduler_merged_keeps_each_accounts_scan_without_inventing_missing():
    nitter = _nitter()
    nitter.fetch_merged_for_scheduler = AsyncMock(
        return_value=(
            "rss",
            {
                "alice": SchedulerFetchResult(
                    tweets=[_tweet("101")],
                    scanned_status_ids=["101"],
                    anchor_status_ids=["101"],
                    complete=True,
                    reached_watermark=True,
                ),
                "bob": SchedulerFetchResult(
                    tweets=[],
                    scanned_status_ids=["202"],
                    anchor_status_ids=["202"],
                    complete=False,
                    plain_text_filtered=2,
                ),
            },
        )
    )
    result = await QueryService(nitter).scan_merged(
        ["alice", "bob", "carol"],
        {"alice": ["99"], "bob": None, "carol": ["1"]},
        skip_plain_text=True,
        filter_reposts=True,
    )
    assert set(result) == {"alice", "bob"}
    assert result["alice"].reached_watermark is True
    assert result["bob"].status == FetchStatus.INCOMPLETE
    assert result["bob"].plain_text_filtered == 2
    nitter.fetch_merged_for_scheduler.assert_awaited_once_with(
        ["alice", "bob", "carol"],
        {"alice": ["99"], "bob": None, "carol": ["1"]},
        skip_plain_text=True,
        filter_reposts=True,
        media=True,
    )


@pytest.mark.asyncio
async def test_scheduler_html_media_filter_preserves_original_raw_counts():
    nitter = _nitter()
    nitter.search.return_value = (
        "html",
        HtmlSearchResult(
            [_tweet("1"), _tweet("2", media="image")],
            raw_item_count=6,
            retweet_filtered=3,
            anchor_status_ids=["8", "7"],
        ),
    )
    result = await QueryService(nitter).scan_search("#tag", 20, skip_plain_text=True)
    assert result.status == FetchStatus.SUCCESS
    assert result.raw_item_count == 6
    assert result.plain_text_filtered == 1
    assert result.retweet_filtered == 3
    assert [tweet.status_id for tweet in result.tweets] == ["2"]
    assert nitter.search.call_args.args[0] == "#tag filter:media"


@pytest.mark.asyncio
async def test_invalid_request_is_rejected_before_touching_provider():
    nitter, fx = _nitter(), _fx()
    service = QueryService(nitter, fx)
    with pytest.raises(ValueError, match="positive integer"):
        await service.fetch_timeline(TimelineQuery("alice", limit=True))
    with pytest.raises(ValueError, match="MAX_QUERY_LENGTH"):
        await service.search(SearchQuery("x" * 195, is_media=True))
    with pytest.raises(ValueError, match="sort"):
        await service.search(SearchQuery("valid", sort="unknown"))
    fx.fetch_user_timeline.assert_not_called()
    fx.search_tweets.assert_not_called()
    nitter.search.assert_not_called()


@pytest.mark.asyncio
async def test_trends_failure_retains_type_without_raw_error():
    nitter, fx = _nitter(), _fx()
    fx.fetch_trends.side_effect = TimeoutError("https://internal.host")
    result = await QueryService(nitter, fx).trends(TrendQuery())
    assert result.status == FetchStatus.ERROR
    assert result.error_kind == "TimeoutError"
    assert "internal.host" not in repr(result)


@pytest.mark.asyncio
async def test_merged_scan_rejects_repost_preserving_mode():
    nitter = _nitter()
    nitter.fetch_merged_for_scheduler = AsyncMock()
    with pytest.raises(ValueError, match="filter_reposts"):
        await QueryService(nitter).scan_merged(
            ["alice", "bob"],
            {"alice": None, "bob": None},
            filter_reposts=False,
        )
    nitter.fetch_merged_for_scheduler.assert_not_called()


@pytest.mark.asyncio
async def test_merged_scan_failure_is_reported_per_source_without_private_details():
    nitter = _nitter()
    nitter.fetch_merged_for_scheduler = AsyncMock(
        side_effect=TimeoutError("http://private-nitter:8080/tokens")
    )
    results = await QueryService(nitter).scan_merged(
        ["alice", "bob"],
        {"alice": None, "bob": None},
    )
    assert set(results) == {"alice", "bob"}
    assert all(item.status == FetchStatus.ERROR for item in results.values())
    assert all(item.error_kind == "TimeoutError" for item in results.values())
    assert all("private-nitter" not in repr(item) for item in results.values())


@pytest.mark.asyncio
async def test_fx_only_without_client_does_not_silently_use_nitter():
    nitter = _nitter()
    service = QueryService(nitter, None, fetch_backend="fx")
    timeline = await service.fetch_timeline(TimelineQuery("alice"))
    search = await service.search(SearchQuery("topic"))
    assert timeline.status == FetchStatus.ERROR
    assert search.status == FetchStatus.ERROR
    assert timeline.backend == "fx"
    assert search.backend == "fx"
    nitter.fetch_user.assert_not_called()
    nitter.search.assert_not_called()
