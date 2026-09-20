"""Tests for fetch_backend three-mode switching (mix | nitter | fx),

incremental Nitter fallback, and physical isolation of Twitter Lists.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from command_handlers.manual import ManualCommandMixin
from media_support.client import SchedulerFetchResult
from media_support.fxtwitter_client import (
    FxTwitterError,
    FxTwitterNotFoundError,
)
from media_support.search_session_buffer import SearchSessionStore
from scheduler.config import SchedulerConfigReader
from scheduler.models import ScheduledCheckResult, SourceStatus
from scheduler.runner_fetch import SchedulerFetchMixin
from scheduler.runner_status import SchedulerStatusMixin
from shared.utils import TweetItem, TweetMedia


def _make_tweet(username: str, status_id: str, is_retweet: bool = False) -> TweetItem:
    return TweetItem(
        text=f"tweet from {username} id {status_id}",
        link=f"https://x.com/{username}/status/{status_id}",
        published="2026-09-16 12:00:00",
        media=[],
        is_retweet=is_retweet,
    )


class DummyRunner(SchedulerFetchMixin):
    def __init__(
        self, config: dict, nitter: MagicMock, fxtwitter: MagicMock | None = None
    ):
        self.config = config
        self.nitter = nitter
        if fxtwitter is not None:
            self.fxtwitter = fxtwitter
            self.nitter.fxtwitter = fxtwitter
        self._log_verbose_info = MagicMock()


class DummyManualHost(ManualCommandMixin):
    def __init__(
        self, config: dict, nitter: MagicMock, fxtwitter: MagicMock | None = None
    ):
        self.config = config
        self.default_limit = 5
        self.search_default_limit = 5
        self.search_max_limit = 20
        self.search_cooldown_seconds = 0.0
        self.cooldown_seconds = 0.0
        self._cooldowns: dict = {}
        self._search_session_store = SearchSessionStore()
        self.nitter = nitter
        if fxtwitter is not None:
            self.fxtwitter = fxtwitter
        self.sender = MagicMock()
        self.sender.should_merge_for_event = MagicMock(return_value=False)
        self.media = MagicMock()
        self.media.attach_media_with_results = AsyncMock(return_value=[])
        self.media.cleanup_after_send = MagicMock()

    def _cooldown_left(self, event, scope="tweet") -> float:
        return 0.0

    def _mark_cooldown(self, event, scope="tweet") -> None:
        pass

    async def _send_tweets_response(
        self, event, username: str, instance: str, tweets, on_sent_progress=None
    ) -> int:
        return len(tweets)


def _blogger_group(users: list[str], filter_reposts: bool = True):
    config = {
        "tweet_groups": [
            {
                "group_id": "test_bloggers",
                "group_type": "blogger",
                "watch_users": users,
                "filter_reposts_enabled": filter_reposts,
                "concurrent_fetch_enabled": False,
                "send_user_interval": 0.0,
            }
        ]
    }
    reader = SchedulerConfigReader(config, context=None)
    return reader.schedule_groups()[0]


def _tag_group(queries: list[str]):
    config = {
        "tweet_groups": [
            {
                "group_id": "test_tags",
                "group_type": "tag",
                "watch_queries": queries,
                "filter_reposts_enabled": True,
                "send_user_interval": 0.0,
            }
        ]
    }
    reader = SchedulerConfigReader(config, context=None)
    return reader.schedule_groups()[0]


def _list_group(list_ids: list[str]):
    config = {
        "tweet_groups": [
            {
                "group_id": "test_lists",
                "group_type": "list",
                "watch_lists": list_ids,
                "filter_reposts_enabled": True,
                "send_user_interval": 0.0,
            }
        ]
    }
    reader = SchedulerConfigReader(config, context=None)
    return reader.schedule_groups()[0]


# ==============================================================================
# 1. Multi-blogger: all success on FX -> Nitter never called
# ==============================================================================
@pytest.mark.asyncio
async def test_multi_blogger_all_success_does_not_call_nitter():
    mock_nitter = MagicMock()
    mock_nitter.fetch_merged_for_scheduler = AsyncMock()
    mock_nitter.fetch_tweets_for_scheduler = AsyncMock()

    mock_fx = MagicMock()
    mock_fx.base_url = "https://api.fxtwitter.com"

    def fx_fetch(username, count=10, **kw):
        return [_make_tweet(username, "1001")], None

    mock_fx.fetch_user_timeline = MagicMock(side_effect=fx_fetch)

    runner = DummyRunner({"fetch_backend": "mix"}, mock_nitter, mock_fx)
    group = _blogger_group(["alice", "bob", "carol"])

    results = await runner._fetch_group_users(
        group, fetch_limit=10, skip_plain_text=False, scan_watermarks={}
    )

    assert len(results) == 3
    assert mock_fx.fetch_user_timeline.call_count == 3
    mock_nitter.fetch_merged_for_scheduler.assert_not_called()
    mock_nitter.fetch_tweets_for_scheduler.assert_not_called()

    for r in results:
        assert r.error is None
        assert r.instance == "FxTwitter"
        assert r.host_attempts == ["FxTwitter=成功"]
        assert len(r.tweets) == 1
        assert r.fetch_status == SourceStatus.SUCCESS


# ==============================================================================
# 2. Multi-blogger: partial success (incremental fallback to Nitter)
# ==============================================================================
@pytest.mark.asyncio
async def test_multi_blogger_partial_success_incremental_nitter_fallback():
    mock_nitter = MagicMock()
    # Nitter merged RSS returns results for failed accounts
    mock_nitter.fetch_merged_for_scheduler = AsyncMock(
        return_value=(
            "http://nitter.test",
            {
                "bob": SchedulerFetchResult(
                    tweets=[_make_tweet("bob", "2001")],
                    scanned_status_ids=["2001"],
                    complete=True,
                ),
                "carol": SchedulerFetchResult(
                    tweets=[_make_tweet("carol", "3001")],
                    scanned_status_ids=["3001"],
                    complete=True,
                ),
            },
        )
    )
    mock_nitter.fetch_tweets_for_scheduler = AsyncMock()

    mock_fx = MagicMock()
    mock_fx.base_url = "https://api.fxtwitter.com"

    def fx_fetch(username, count=10, **kw):
        if username == "alice":
            return [_make_tweet("alice", "1001")], None
        raise FxTwitterError(f"HTTP 429 rate limit for {username}")

    mock_fx.fetch_user_timeline = MagicMock(side_effect=fx_fetch)

    runner = DummyRunner({"fetch_backend": "mix"}, mock_nitter, mock_fx)
    group = _blogger_group(["alice", "bob", "carol"], filter_reposts=True)

    results = await runner._fetch_group_users(
        group, fetch_limit=10, skip_plain_text=False, scan_watermarks={}
    )

    # FX called for all 3
    assert mock_fx.fetch_user_timeline.call_count == 3

    # Nitter merged RSS called ONLY for failed accounts: bob and carol
    mock_nitter.fetch_merged_for_scheduler.assert_called_once()
    called_batch = mock_nitter.fetch_merged_for_scheduler.call_args[0][0]
    assert set(called_batch) == {"bob", "carol"}
    assert "alice" not in called_batch

    # Results merged
    assert len(results) == 3
    results_by_user = {r.username: r for r in results}
    assert results_by_user["alice"].instance == "FxTwitter"
    assert results_by_user["alice"].host_attempts == ["FxTwitter=成功"]
    assert results_by_user["bob"].instance == "http://nitter.test"
    assert results_by_user["bob"].host_attempts == [
        "FxTwitter=失败",
        "Nitter=成功",
    ]
    assert results_by_user["carol"].instance == "http://nitter.test"
    assert results_by_user["carol"].host_attempts == [
        "FxTwitter=失败",
        "Nitter=成功",
    ]


@pytest.mark.asyncio
async def test_multi_blogger_single_failure_falls_back_to_single_nitter_fetch():
    """When only 1 account fails, it falls back to single user fetch instead of merged."""
    mock_nitter = MagicMock()
    mock_nitter.fetch_merged_for_scheduler = AsyncMock()
    mock_nitter.fetch_tweets_for_scheduler = AsyncMock(
        return_value=(
            "http://nitter.test",
            SchedulerFetchResult(
                tweets=[_make_tweet("bob", "2001")],
                scanned_status_ids=["2001"],
                complete=True,
            ),
        )
    )

    mock_fx = MagicMock()
    mock_fx.base_url = "https://api.fxtwitter.com"

    def fx_fetch(username, count=10, **kw):
        if username == "alice":
            return [_make_tweet("alice", "1001")], None
        raise FxTwitterError("500 Server Error")

    mock_fx.fetch_user_timeline = MagicMock(side_effect=fx_fetch)

    runner = DummyRunner({"fetch_backend": "mix"}, mock_nitter, mock_fx)
    group = _blogger_group(["alice", "bob"], filter_reposts=True)

    results = await runner._fetch_group_users(
        group, fetch_limit=10, skip_plain_text=False, scan_watermarks={}
    )

    assert mock_fx.fetch_user_timeline.call_count == 2
    mock_nitter.fetch_merged_for_scheduler.assert_not_called()
    mock_nitter.fetch_tweets_for_scheduler.assert_called_once()
    assert len(results) == 2


@pytest.mark.asyncio
async def test_multi_blogger_first_failure_preserves_order_and_indices_single_nitter_fallback():
    """When the first blogger fails on FX and subsequent succeed, results strictly preserve original order and indices."""
    mock_nitter = MagicMock()
    mock_nitter.fetch_merged_for_scheduler = AsyncMock()
    mock_nitter.fetch_tweets_for_scheduler = AsyncMock(
        return_value=(
            "http://nitter.test",
            SchedulerFetchResult(
                tweets=[_make_tweet("alice", "1001")],
                scanned_status_ids=["1001"],
                complete=True,
            ),
        )
    )

    mock_fx = MagicMock()
    mock_fx.base_url = "https://api.fxtwitter.com"

    def fx_fetch(username, count=10, **kw):
        if username == "alice":
            raise FxTwitterError("500 Server Error")
        return [_make_tweet(username, "2001")], None

    mock_fx.fetch_user_timeline = MagicMock(side_effect=fx_fetch)

    runner = DummyRunner({"fetch_backend": "mix"}, mock_nitter, mock_fx)
    group = _blogger_group(["alice", "bob", "carol"], filter_reposts=True)

    results = await runner._fetch_group_users(
        group, fetch_limit=10, skip_plain_text=False, scan_watermarks={}
    )

    assert len(results) == 3
    # Order must strictly match original accounts list
    assert [r.username for r in results] == ["alice", "bob", "carol"]
    # Indices must strictly match 0, 1, 2
    assert [r.index for r in results] == [0, 1, 2]
    # First blogger fell back to Nitter
    assert results[0].instance == "http://nitter.test"
    assert results[0].host_attempts == ["FxTwitter=失败", "Nitter=成功"]
    # Subsequent bloggers succeeded on FX
    assert results[1].instance == "FxTwitter"
    assert results[1].host_attempts == ["FxTwitter=成功"]
    assert results[2].instance == "FxTwitter"
    assert results[2].host_attempts == ["FxTwitter=成功"]


@pytest.mark.asyncio
async def test_multi_blogger_first_failures_preserves_order_and_indices_merged_nitter_fallback():
    """When first multiple bloggers fail on FX and fall back to merged Nitter, order and indices are preserved."""
    mock_nitter = MagicMock()
    mock_nitter.fetch_merged_for_scheduler = AsyncMock(
        return_value=(
            "http://nitter.test",
            {
                "alice": SchedulerFetchResult(
                    tweets=[_make_tweet("alice", "1001")],
                    scanned_status_ids=["1001"],
                    complete=True,
                ),
                "bob": SchedulerFetchResult(
                    tweets=[_make_tweet("bob", "2001")],
                    scanned_status_ids=["2001"],
                    complete=True,
                ),
            },
        )
    )
    mock_nitter.fetch_tweets_for_scheduler = AsyncMock()

    mock_fx = MagicMock()
    mock_fx.base_url = "https://api.fxtwitter.com"

    def fx_fetch(username, count=10, **kw):
        if username in ("alice", "bob"):
            raise FxTwitterError("500 Server Error")
        return [_make_tweet(username, "3001")], None

    mock_fx.fetch_user_timeline = MagicMock(side_effect=fx_fetch)

    runner = DummyRunner({"fetch_backend": "mix"}, mock_nitter, mock_fx)
    group = _blogger_group(["alice", "bob", "carol"], filter_reposts=True)

    results = await runner._fetch_group_users(
        group, fetch_limit=10, skip_plain_text=False, scan_watermarks={}
    )

    assert len(results) == 3
    assert [r.username for r in results] == ["alice", "bob", "carol"]
    assert [r.index for r in results] == [0, 1, 2]
    assert results[0].instance == "http://nitter.test"
    assert results[0].host_attempts == ["FxTwitter=失败", "Nitter=成功"]
    assert results[1].instance == "http://nitter.test"
    assert results[1].host_attempts == ["FxTwitter=失败", "Nitter=成功"]
    assert results[2].instance == "FxTwitter"
    assert results[2].host_attempts == ["FxTwitter=成功"]


@pytest.mark.asyncio
async def test_multi_blogger_middle_failure_preserves_order_and_indices_single_nitter_fallback():
    """When a middle blogger fails on FX and subsequent succeed, results strictly preserve order and indices."""
    mock_nitter = MagicMock()
    mock_nitter.fetch_merged_for_scheduler = AsyncMock()
    mock_nitter.fetch_tweets_for_scheduler = AsyncMock(
        return_value=(
            "http://nitter.test",
            SchedulerFetchResult(
                tweets=[_make_tweet("bob", "2001")],
                scanned_status_ids=["2001"],
                complete=True,
            ),
        )
    )

    mock_fx = MagicMock()
    mock_fx.base_url = "https://api.fxtwitter.com"

    def fx_fetch(username, count=10, **kw):
        if username == "bob":
            raise FxTwitterError("500 Server Error")
        return [_make_tweet(username, "1001")], None

    mock_fx.fetch_user_timeline = MagicMock(side_effect=fx_fetch)

    runner = DummyRunner({"fetch_backend": "mix"}, mock_nitter, mock_fx)
    group = _blogger_group(["alice", "bob", "carol"], filter_reposts=True)

    results = await runner._fetch_group_users(
        group, fetch_limit=10, skip_plain_text=False, scan_watermarks={}
    )

    assert len(results) == 3
    assert [r.username for r in results] == ["alice", "bob", "carol"]
    assert [r.index for r in results] == [0, 1, 2]
    assert results[0].instance == "FxTwitter"
    assert results[0].host_attempts == ["FxTwitter=成功"]
    assert results[1].instance == "http://nitter.test"
    assert results[1].host_attempts == ["FxTwitter=失败", "Nitter=成功"]
    assert results[2].instance == "FxTwitter"
    assert results[2].host_attempts == ["FxTwitter=成功"]


@pytest.mark.asyncio
async def test_multi_blogger_first_failure_preserves_order_and_indices_fx_mode():
    """In pure fx mode, if the first blogger fails, results list still preserves original order and indices."""
    mock_nitter = MagicMock()
    mock_fx = MagicMock()
    mock_fx.base_url = "https://api.fxtwitter.com"

    def fx_fetch(username, count=10, **kw):
        if username == "alice":
            raise FxTwitterError("404 Not Found")
        return [_make_tweet(username, "2001")], None

    mock_fx.fetch_user_timeline = MagicMock(side_effect=fx_fetch)

    runner = DummyRunner({"fetch_backend": "fx"}, mock_nitter, mock_fx)
    group = _blogger_group(["alice", "bob"])

    results = await runner._fetch_group_users(
        group, fetch_limit=10, skip_plain_text=False, scan_watermarks={}
    )

    assert len(results) == 2
    assert [r.username for r in results] == ["alice", "bob"]
    assert [r.index for r in results] == [0, 1]
    assert results[0].error is not None
    assert results[1].error is None


# ==============================================================================
# 3. Multi-blogger: all fail on FX -> full fallback to Nitter
# ==============================================================================
@pytest.mark.asyncio
async def test_multi_blogger_all_fail_falls_back_to_nitter():
    mock_nitter = MagicMock()
    mock_nitter.fetch_merged_for_scheduler = AsyncMock(
        return_value=(
            "http://nitter.test",
            {
                "alice": SchedulerFetchResult(
                    tweets=[_make_tweet("alice", "1001")],
                    scanned_status_ids=["1001"],
                    complete=True,
                ),
                "bob": SchedulerFetchResult(
                    tweets=[_make_tweet("bob", "2001")],
                    scanned_status_ids=["2001"],
                    complete=True,
                ),
            },
        )
    )

    mock_fx = MagicMock()
    mock_fx.base_url = "https://api.fxtwitter.com"
    mock_fx.fetch_user_timeline = MagicMock(
        side_effect=FxTwitterError("FX unavailable")
    )

    runner = DummyRunner({"fetch_backend": "mix"}, mock_nitter, mock_fx)
    group = _blogger_group(["alice", "bob"], filter_reposts=True)

    results = await runner._fetch_group_users(
        group, fetch_limit=10, skip_plain_text=False, scan_watermarks={}
    )

    assert mock_fx.fetch_user_timeline.call_count == 2
    mock_nitter.fetch_merged_for_scheduler.assert_called_once()
    called_batch = mock_nitter.fetch_merged_for_scheduler.call_args[0][0]
    assert set(called_batch) == {"alice", "bob"}

    assert len(results) == 2
    for r in results:
        assert r.instance == "http://nitter.test"


# ==============================================================================
# 4. Tag search: 404 (SafeSearch) smooth fallback to Nitter HTML
# ==============================================================================
@pytest.mark.asyncio
async def test_tag_search_404_smooth_fallback_to_nitter_html():
    mock_nitter = MagicMock()
    nitter_tweet = _make_tweet("taguser", "9999")
    mock_nitter.search = MagicMock(
        return_value=("http://nitter-html.test", [nitter_tweet])
    )

    mock_fx = MagicMock()
    mock_fx.search_tweets = MagicMock(
        side_effect=FxTwitterNotFoundError(
            "FxTwitter returned code 404: SafeSearch restricted"
        )
    )

    runner = DummyRunner({"fetch_backend": "mix"}, mock_nitter, mock_fx)
    group = _tag_group(["#nsfw"])

    results = await runner._fetch_group_users(
        group, fetch_limit=10, skip_plain_text=False, scan_watermarks={}
    )

    assert len(results) == 1
    mock_fx.search_tweets.assert_called_once()
    mock_nitter.search.assert_called_once()
    assert results[0].error is None
    assert results[0].instance == "http://nitter-html.test"
    assert len(results[0].tweets) == 1


@pytest.mark.asyncio
async def test_tag_search_mix_fx_success_does_not_call_nitter():
    mock_nitter = MagicMock()
    mock_nitter.search = MagicMock()

    mock_fx = MagicMock()
    mock_fx.base_url = "https://api.fxtwitter.com"
    fx_tweet = _make_tweet("news", "5555")
    mock_fx.search_tweets = MagicMock(return_value=([fx_tweet], None))

    runner = DummyRunner({"fetch_backend": "mix"}, mock_nitter, mock_fx)
    group = _tag_group(["#news"])

    results = await runner._fetch_group_users(
        group, fetch_limit=10, skip_plain_text=False, scan_watermarks={}
    )

    assert len(results) == 1
    mock_fx.search_tweets.assert_called_once()
    mock_nitter.search.assert_not_called()
    assert results[0].instance == "FxTwitter"
    assert results[0].host_attempts == ["FxTwitter=成功"]
    assert len(results[0].tweets) == 1


# ==============================================================================
# 5. List subscription: 100% locked to Nitter, physically isolated from FX
# ==============================================================================
@pytest.mark.asyncio
@pytest.mark.parametrize("backend_mode", ["mix", "fx", "nitter"])
async def test_list_subscription_always_uses_nitter_never_fx(backend_mode: str):
    mock_nitter = MagicMock()
    mock_nitter.fetch_list_for_scheduler = AsyncMock(
        return_value=(
            "http://nitter-list.test",
            SchedulerFetchResult(
                tweets=[_make_tweet("listuser", "8888")],
                scanned_status_ids=["8888"],
                complete=True,
            ),
        )
    )

    mock_fx = MagicMock()
    mock_fx.fetch_user_timeline = MagicMock()
    mock_fx.search_tweets = MagicMock()

    runner = DummyRunner({"fetch_backend": backend_mode}, mock_nitter, mock_fx)
    group = _list_group(["1234567890"])

    results = await runner._fetch_group_users(
        group, fetch_limit=10, skip_plain_text=False, scan_watermarks={}
    )

    assert len(results) == 1
    # FX must NEVER be touched under any backend mode
    mock_fx.fetch_user_timeline.assert_not_called()
    mock_fx.search_tweets.assert_not_called()

    # Nitter list RSS was called
    mock_nitter.fetch_list_for_scheduler.assert_called_once()
    assert results[0].instance == "http://nitter-list.test"


# ==============================================================================
# 6. fetch_backend = "nitter": never calls FX
# ==============================================================================
@pytest.mark.asyncio
async def test_fetch_backend_nitter_mode_never_calls_fx():
    mock_nitter = MagicMock()
    mock_nitter.fetch_merged_for_scheduler = AsyncMock(
        return_value=(
            "http://nitter.test",
            {
                "alice": SchedulerFetchResult(
                    tweets=[_make_tweet("alice", "1001")],
                    scanned_status_ids=["1001"],
                    complete=True,
                )
            },
        )
    )
    mock_nitter.search = MagicMock(
        return_value=("http://nitter.test", [_make_tweet("t", "2001")])
    )

    mock_fx = MagicMock()
    mock_fx.fetch_user_timeline = MagicMock()
    mock_fx.search_tweets = MagicMock()

    runner = DummyRunner({"fetch_backend": "nitter"}, mock_nitter, mock_fx)

    # Multi-blogger
    b_group = _blogger_group(["alice", "bob"])
    await runner._fetch_group_users(b_group, 10, False, {})
    mock_fx.fetch_user_timeline.assert_not_called()

    # Tag
    t_group = _tag_group(["#test"])
    await runner._fetch_group_users(t_group, 10, False, {})
    mock_fx.search_tweets.assert_not_called()


# ==============================================================================
# 7. fetch_backend = "fx": never calls Nitter, reports errors directly
# ==============================================================================
@pytest.mark.asyncio
async def test_fetch_backend_fx_mode_never_calls_nitter():
    mock_nitter = MagicMock()
    mock_nitter.fetch_merged_for_scheduler = AsyncMock()
    mock_nitter.fetch_tweets_for_scheduler = AsyncMock()
    mock_nitter.search = MagicMock()

    mock_fx = MagicMock()
    mock_fx.fetch_user_timeline = MagicMock(side_effect=FxTwitterError("Timeline 500"))
    mock_fx.search_tweets = MagicMock(side_effect=FxTwitterNotFoundError("Search 404"))

    runner = DummyRunner({"fetch_backend": "fx"}, mock_nitter, mock_fx)

    # Blogger
    b_group = _blogger_group(["alice", "bob"])
    b_results = await runner._fetch_group_users(b_group, 10, False, {})

    assert len(b_results) == 2
    mock_nitter.fetch_merged_for_scheduler.assert_not_called()
    mock_nitter.fetch_tweets_for_scheduler.assert_not_called()
    for r in b_results:
        assert r.error is not None
        assert "Timeline 500" in r.error.message

    # Tag
    t_group = _tag_group(["#test"])
    t_results = await runner._fetch_group_users(t_group, 10, False, {})

    assert len(t_results) == 1
    mock_nitter.search.assert_not_called()
    assert t_results[0].error is not None
    assert "Search 404" in t_results[0].error.message


# ==============================================================================
# 8. Single blogger fetch routing and fallback
# ==============================================================================
@pytest.mark.asyncio
async def test_single_blogger_fetch_user_mix_fallback():
    mock_nitter = MagicMock()
    mock_nitter.fetch_tweets_for_scheduler = AsyncMock(
        return_value=(
            "http://nitter.test",
            SchedulerFetchResult(
                tweets=[_make_tweet("alice", "1001")],
                scanned_status_ids=["1001"],
                complete=True,
            ),
        )
    )

    mock_fx = MagicMock()
    mock_fx.fetch_user_timeline = MagicMock(side_effect=FxTwitterError("Temporary 429"))

    runner = DummyRunner({"fetch_backend": "mix"}, mock_nitter, mock_fx)
    group = _blogger_group(["alice"])

    result = await runner._fetch_group_user(
        group,
        0,
        "alice",
        10,
        skip_plain_text=False,
        scan_watermark=None,
        concurrent=False,
    )

    mock_fx.fetch_user_timeline.assert_called_once()
    mock_nitter.fetch_tweets_for_scheduler.assert_called_once()
    assert result.instance == "http://nitter.test"
    assert len(result.tweets) == 1


# ==============================================================================
# 9. Manual command /推文 routing and fallback
# ==============================================================================
@pytest.mark.asyncio
async def test_manual_cmd_tweets_mix_fx_success():
    mock_nitter = MagicMock()
    mock_nitter.fetch_user = AsyncMock()

    mock_fx = MagicMock()
    mock_fx.base_url = "https://api.fxtwitter.com"
    mock_fx.fetch_user_timeline = MagicMock(
        return_value=([_make_tweet("nasa", "1001")], None)
    )

    host = DummyManualHost({"fetch_backend": "mix"}, mock_nitter, mock_fx)
    event = MagicMock()
    event.send = AsyncMock()
    event.stop_event = MagicMock()
    event.plain_result.side_effect = lambda v: v

    await host._cmd_tweets_impl(event, "nasa", "5")

    mock_fx.fetch_user_timeline.assert_called_once()
    mock_nitter.fetch_user.assert_not_called()


@pytest.mark.asyncio
async def test_manual_cmd_tweets_mix_fx_error_falls_back_to_nitter():
    mock_nitter = MagicMock()
    mock_nitter.fetch_user = AsyncMock(
        return_value=("http://nitter.test", [_make_tweet("nasa", "1001")])
    )

    mock_fx = MagicMock()
    mock_fx.fetch_user_timeline = MagicMock(
        side_effect=FxTwitterNotFoundError("User not found 404")
    )

    host = DummyManualHost({"fetch_backend": "mix"}, mock_nitter, mock_fx)
    event = MagicMock()
    event.send = AsyncMock()
    event.stop_event = MagicMock()
    event.plain_result.side_effect = lambda v: v

    await host._cmd_tweets_impl(event, "nasa", "5")

    mock_fx.fetch_user_timeline.assert_called_once()
    mock_nitter.fetch_user.assert_called_once()


@pytest.mark.asyncio
async def test_manual_cmd_tweets_fx_mode_does_not_fallback():
    mock_nitter = MagicMock()
    mock_nitter.fetch_user = AsyncMock()

    mock_fx = MagicMock()
    mock_fx.fetch_user_timeline = MagicMock(
        side_effect=FxTwitterError("Rate limited 429")
    )

    host = DummyManualHost({"fetch_backend": "fx"}, mock_nitter, mock_fx)
    event = MagicMock()
    event.send = AsyncMock()
    event.stop_event = MagicMock()
    event.plain_result.side_effect = lambda v: v

    await host._cmd_tweets_impl(event, "nasa", "5")

    mock_fx.fetch_user_timeline.assert_called_once()
    mock_nitter.fetch_user.assert_not_called()
    sent_msgs = [call.args[0] for call in event.send.await_args_list]
    assert any("获取 @nasa 推文失败" in msg for msg in sent_msgs)


@pytest.mark.asyncio
async def test_manual_cmd_tweet_pic_mix_fx_success(monkeypatch):
    """Verify /推图 passes is_media_only parameters to FX timeline and logs operation='user_media'."""
    mock_nitter = MagicMock()
    mock_nitter.fetch_user = AsyncMock()

    mock_fx = MagicMock()
    mock_fx.base_url = "https://api.fxtwitter.com"
    mock_fx.fetch_user_timeline = MagicMock(
        return_value=([_make_tweet("nasa", "1001")], None)
    )

    logged_tasks = []
    monkeypatch.setattr(
        "command_handlers.manual.safe_task_log",
        lambda level, title, **kwargs: logged_tasks.append({"title": title, **kwargs}),
    )

    host = DummyManualHost({"fetch_backend": "mix"}, mock_nitter, mock_fx)
    event = MagicMock()
    event.send = AsyncMock()
    event.stop_event = MagicMock()
    event.plain_result.side_effect = lambda v: v

    await host._cmd_tweets_impl(event, "nasa", "5", is_media_only=True)

    mock_fx.fetch_user_timeline.assert_called_once_with(
        "nasa", count=5, skip_plain_text=True, filter_reposts=True, max_pages=3
    )
    mock_nitter.fetch_user.assert_not_called()
    assert len(logged_tasks) == 1
    assert logged_tasks[0]["operation"] == "user_media"
    assert logged_tasks[0]["source"] == "@nasa"
    assert logged_tasks[0]["instance"] == "FxTwitter"


@pytest.mark.asyncio
async def test_manual_cmd_tweet_pic_mix_fx_error_falls_back_to_nitter(monkeypatch):
    """Verify /推图 falls back to Nitter with skip_plain_text=True and operation='user_media'."""
    mock_nitter = MagicMock()
    mock_nitter.fetch_user = AsyncMock(
        return_value=("http://nitter.test", [_make_tweet("nasa", "1001")])
    )

    mock_fx = MagicMock()
    mock_fx.fetch_user_timeline = MagicMock(
        side_effect=FxTwitterNotFoundError("User not found 404")
    )

    logged_tasks = []
    monkeypatch.setattr(
        "command_handlers.manual.safe_task_log",
        lambda level, title, **kwargs: logged_tasks.append({"title": title, **kwargs}),
    )

    host = DummyManualHost({"fetch_backend": "mix"}, mock_nitter, mock_fx)
    event = MagicMock()
    event.send = AsyncMock()
    event.stop_event = MagicMock()
    event.plain_result.side_effect = lambda v: v

    await host._cmd_tweets_impl(event, "nasa", "5", is_media_only=True)

    mock_fx.fetch_user_timeline.assert_called_once_with(
        "nasa", count=5, skip_plain_text=True, filter_reposts=True, max_pages=3
    )
    mock_nitter.fetch_user.assert_called_once_with(
        "nasa", 5, filter_reposts=True, skip_plain_text=True
    )
    assert len(logged_tasks) == 1
    assert logged_tasks[0]["operation"] == "user_media"
    assert logged_tasks[0]["source"] == "@nasa"


@pytest.mark.asyncio
async def test_manual_cmd_tweet_pic_nitter_typeerror_fallback_filters_media(
    monkeypatch,
):
    """Verify /推图 falls back to local media filter when nitter.fetch_user rejects skip_plain_text."""
    media_tweet = TweetItem(
        text="pic tweet",
        link="https://x.com/nasa/status/1001",
        published="2026-09-16 12:00:00",
        media=[TweetMedia(kind="image", url="https://img.test/pic.jpg")],
    )
    plain_tweet = _make_tweet("nasa", "1002")

    mock_nitter = MagicMock()

    async def fake_fetch_user(username, limit, **kwargs):
        if "skip_plain_text" in kwargs:
            raise TypeError("unexpected keyword argument 'skip_plain_text'")
        return "http://nitter.test", [media_tweet, plain_tweet]

    mock_nitter.fetch_user = AsyncMock(side_effect=fake_fetch_user)

    mock_fx = MagicMock()
    mock_fx.base_url = "https://api.fxtwitter.com"
    mock_fx.fetch_user_timeline = MagicMock(
        side_effect=FxTwitterNotFoundError("User not found 404")
    )

    logged_tasks = []
    monkeypatch.setattr(
        "command_handlers.manual.safe_task_log",
        lambda level, title, **kwargs: logged_tasks.append({"title": title, **kwargs}),
    )

    host = DummyManualHost({"fetch_backend": "mix"}, mock_nitter, mock_fx)
    host._send_tweets_response = AsyncMock(return_value=1)
    event = MagicMock()
    event.send = AsyncMock()
    event.stop_event = MagicMock()
    event.plain_result.side_effect = lambda v: v

    await host._cmd_tweets_impl(event, "nasa", "5", is_media_only=True)

    assert mock_nitter.fetch_user.call_count == 2
    host._send_tweets_response.assert_called_once()
    sent_tweets = host._send_tweets_response.call_args[0][3]
    assert len(sent_tweets) == 1
    assert sent_tweets[0].status_id == "1001"


@pytest.mark.asyncio
async def test_nitter_service_fetch_user_skip_plain_text_html_fallback():
    """Verify NitterService.fetch_user filters non-media tweets when falling back to HTML."""
    from media_support.nitter import NitterService

    service = NitterService({"instances": ["https://nitter.test"]})
    service.fetch_tweets = AsyncMock(return_value=("https://nitter.test", []))
    plain_tweet = _make_tweet("testuser", "1")
    media_tweet = TweetItem(
        text="media tweet",
        link="https://x.com/testuser/status/2",
        published="",
        media=[TweetMedia(kind="image", url="https://img.test/pic.jpg")],
    )
    service.fetch_user_html = MagicMock(
        return_value=("https://nitter.test", [plain_tweet, media_tweet])
    )

    used, tweets = await service.fetch_user("testuser", 5, skip_plain_text=True)
    assert len(tweets) == 1
    assert tweets[0].status_id == "2"
    service.fetch_tweets.assert_called_once_with(
        "testuser", 5, skip_plain_text=True, filter_reposts=None
    )


@pytest.mark.asyncio
async def test_manual_cmd_tweet_pic_empty_message(monkeypatch):
    """Verify /推图 returns correct empty message and logs operation='user_media' when no tweets found."""
    mock_nitter = MagicMock()
    mock_fx = MagicMock()
    mock_fx.fetch_user_timeline = MagicMock(return_value=([], None))

    logged_tasks = []
    monkeypatch.setattr(
        "command_handlers.manual.safe_task_log",
        lambda level, title, **kwargs: logged_tasks.append({"title": title, **kwargs}),
    )

    host = DummyManualHost({"fetch_backend": "mix"}, mock_nitter, mock_fx)
    event = MagicMock()
    event.send = AsyncMock()
    event.stop_event = MagicMock()
    event.plain_result.side_effect = lambda v: v

    await host._cmd_tweets_impl(event, "nasa", "5", is_media_only=True)

    sent_msgs = [call.args[0] for call in event.send.await_args_list]
    assert any("没有找到 @nasa 的相册媒体推文。" in msg for msg in sent_msgs)
    assert len(logged_tasks) == 1
    assert logged_tasks[0]["operation"] == "user_media"
    assert logged_tasks[0]["result_status"] == "无公开推文"


@pytest.mark.asyncio
async def test_manual_cmd_tweet_pic_empty_username():
    """Verify /推图 usage message when username is empty."""
    host = DummyManualHost({"fetch_backend": "mix"}, MagicMock())
    event = MagicMock()
    event.send = AsyncMock()
    event.stop_event = MagicMock()
    event.plain_result.side_effect = lambda v: v

    await host._cmd_tweets_impl(event, "", "", is_media_only=True)

    sent_msgs = [call.args[0] for call in event.send.await_args_list]
    assert any("用法：/推图 用户名 [数量]" in msg for msg in sent_msgs)


def test_cmd_tweet_pic_registered_on_plugin():
    from main import NitterTweetsPlugin

    assert hasattr(NitterTweetsPlugin, "cmd_tweet_pic")
    cmd_fn = getattr(NitterTweetsPlugin, "cmd_tweet_pic")
    assert callable(cmd_fn)
    assert "用法：/推图 用户名 [数量]" in (cmd_fn.__doc__ or "")


@pytest.mark.asyncio
async def test_main_cmd_tweet_pic_delegates_to_impl():
    from main import NitterTweetsPlugin

    plugin = MagicMock(spec=NitterTweetsPlugin)
    plugin._cmd_tweets_impl = AsyncMock()
    event = MagicMock()

    await NitterTweetsPlugin.cmd_tweet_pic(plugin, event, "nasa", "3")
    plugin._cmd_tweets_impl.assert_called_once_with(
        event, "nasa", "3", is_media_only=True
    )


# ==============================================================================
# 10. Manual command /推文搜索 and /推文搜图 routing and fallback
# ==============================================================================
@pytest.mark.asyncio
async def test_manual_cmd_tweet_search_mix_fallback():
    mock_nitter = MagicMock()
    mock_nitter.search = MagicMock(
        return_value=("http://nitter.test", [_make_tweet("t", "9001")])
    )

    mock_fx = MagicMock()
    mock_fx.search_tweets = MagicMock(
        side_effect=FxTwitterNotFoundError("Search 404 SafeSearch")
    )

    host = DummyManualHost({"fetch_backend": "mix"}, mock_nitter, mock_fx)
    event = MagicMock()
    event.unified_msg_origin = "session:test_search_fallback"
    event.send = AsyncMock()
    event.stop_event = MagicMock()
    event.plain_result.side_effect = lambda v: v

    await host._cmd_tweet_search_impl(event, "#test 2")

    mock_fx.search_tweets.assert_called_once()
    mock_nitter.search.assert_called_once()


@pytest.mark.asyncio
async def test_manual_cmd_tweet_pic_search_passes_is_media():
    mock_nitter = MagicMock()
    mock_fx = MagicMock()
    mock_fx.base_url = "https://api.fxtwitter.com"
    tw = _make_tweet("pic", "7777")
    tw.media = [TweetMedia(kind="image", url="http://img.test")]
    mock_fx.search_tweets = MagicMock(return_value=([tw], None))

    host = DummyManualHost({"fetch_backend": "mix"}, mock_nitter, mock_fx)
    event = MagicMock()
    event.unified_msg_origin = "session:test_pic_search"
    event.send = AsyncMock()
    event.stop_event = MagicMock()
    event.plain_result.side_effect = lambda v: v

    await host._cmd_tweet_search_impl(event, "#art 1", is_media_search=True)

    mock_fx.search_tweets.assert_called_once()
    call_kwargs = mock_fx.search_tweets.call_args[1]
    assert call_kwargs.get("is_media") is True
    assert call_kwargs.get("feed") == "latest"


@pytest.mark.asyncio
async def test_manual_cmd_tweet_search_passes_top_feed():
    mock_nitter = MagicMock()
    mock_fx = MagicMock()
    mock_fx.base_url = "https://api.fxtwitter.com"
    tw = _make_tweet("pic", "8888")
    mock_fx.search_tweets = MagicMock(return_value=([tw], None))

    host = DummyManualHost({"fetch_backend": "mix"}, mock_nitter, mock_fx)
    event = MagicMock()
    event.unified_msg_origin = "session:test_top_search"
    event.send = AsyncMock()
    event.stop_event = MagicMock()
    event.plain_result.side_effect = lambda v: v

    await host._cmd_tweet_search_impl(event, "#news 2 -top")

    mock_fx.search_tweets.assert_called_once()
    call_kwargs = mock_fx.search_tweets.call_args[1]
    assert call_kwargs.get("feed") == "top"


@pytest.mark.asyncio
async def test_manual_cmd_tweet_search_inherits_config_search_sort_top():
    """Unspecified sort on CLI automatically inherits search_sort='top' from config."""
    mock_nitter = MagicMock()
    mock_fx = MagicMock()
    mock_fx.base_url = "https://api.fxtwitter.com"
    tw = _make_tweet("topuser", "6666")
    mock_fx.search_tweets = MagicMock(return_value=([tw], None))

    host = DummyManualHost(
        {"fetch_backend": "mix", "search_sort": "top"}, mock_nitter, mock_fx
    )
    event = MagicMock()
    event.unified_msg_origin = "session:test_inherit_top"
    event.send = AsyncMock()
    event.stop_event = MagicMock()
    event.plain_result.side_effect = lambda v: v

    await host._cmd_tweet_search_impl(event, "#news 2")

    mock_fx.search_tweets.assert_called_once()
    call_kwargs = mock_fx.search_tweets.call_args[1]
    assert call_kwargs.get("feed") == "top"


@pytest.mark.asyncio
async def test_manual_cmd_tweet_search_inherits_config_search_sort_top_nitter_fallback():
    """Inherited top sort is preserved when FX fails and falls back to Nitter."""
    mock_nitter = MagicMock()
    mock_nitter.search = MagicMock(
        return_value=("http://nitter.test", [_make_tweet("t", "9002")])
    )

    mock_fx = MagicMock()
    mock_fx.search_tweets = MagicMock(
        side_effect=FxTwitterNotFoundError("Search 404 SafeSearch")
    )

    host = DummyManualHost(
        {"fetch_backend": "mix", "search_sort": "top"}, mock_nitter, mock_fx
    )
    event = MagicMock()
    event.unified_msg_origin = "session:test_inherit_top_fallback"
    event.send = AsyncMock()
    event.stop_event = MagicMock()
    event.plain_result.side_effect = lambda v: v

    await host._cmd_tweet_search_impl(event, "#test 2")

    mock_fx.search_tweets.assert_called_once()
    call_kwargs_fx = mock_fx.search_tweets.call_args[1]
    assert call_kwargs_fx.get("feed") == "top"

    mock_nitter.search.assert_called_once()
    call_kwargs_nitter = mock_nitter.search.call_args[1]
    assert call_kwargs_nitter.get("sort") == "top"


@pytest.mark.asyncio
async def test_manual_cmd_tweet_search_default_inherits_latest():
    """Default search_sort='latest' passes feed='latest' to FX."""
    mock_nitter = MagicMock()
    mock_fx = MagicMock()
    mock_fx.base_url = "https://api.fxtwitter.com"
    tw = _make_tweet("latestuser", "5555")
    mock_fx.search_tweets = MagicMock(return_value=([tw], None))

    host = DummyManualHost({"fetch_backend": "mix"}, mock_nitter, mock_fx)
    event = MagicMock()
    event.unified_msg_origin = "session:test_default_latest"
    event.send = AsyncMock()
    event.stop_event = MagicMock()
    event.plain_result.side_effect = lambda v: v

    await host._cmd_tweet_search_impl(event, "#news 2")

    mock_fx.search_tweets.assert_called_once()
    call_kwargs = mock_fx.search_tweets.call_args[1]
    assert call_kwargs.get("feed") == "latest"


@pytest.mark.asyncio
async def test_manual_cmd_tweet_search_explicit_last_overrides_config_search_sort_top():
    """Explicit -last on CLI overrides config search_sort='top'."""
    mock_nitter = MagicMock()
    mock_fx = MagicMock()
    mock_fx.base_url = "https://api.fxtwitter.com"
    tw = _make_tweet("latestuser", "7777")
    mock_fx.search_tweets = MagicMock(return_value=([tw], None))

    host = DummyManualHost(
        {"fetch_backend": "mix", "search_sort": "top"}, mock_nitter, mock_fx
    )
    event = MagicMock()
    event.unified_msg_origin = "session:test_override_last"
    event.send = AsyncMock()
    event.stop_event = MagicMock()
    event.plain_result.side_effect = lambda v: v

    await host._cmd_tweet_search_impl(event, "#news 2 -last")

    mock_fx.search_tweets.assert_called_once()
    call_kwargs = mock_fx.search_tweets.call_args[1]
    assert call_kwargs.get("feed") == "latest"


@pytest.mark.asyncio
async def test_manual_cmd_tweet_search_explicit_last_overrides_config_search_sort_top_nitter_fallback():
    """Explicit -last on CLI overrides config search_sort='top' on Nitter fallback."""
    mock_nitter = MagicMock()
    mock_nitter.search = MagicMock(
        return_value=("http://nitter.test", [_make_tweet("t", "9003")])
    )

    mock_fx = MagicMock()
    mock_fx.search_tweets = MagicMock(
        side_effect=FxTwitterNotFoundError("Search 404 SafeSearch")
    )

    host = DummyManualHost(
        {"fetch_backend": "mix", "search_sort": "top"}, mock_nitter, mock_fx
    )
    event = MagicMock()
    event.unified_msg_origin = "session:test_override_last_fallback"
    event.send = AsyncMock()
    event.stop_event = MagicMock()
    event.plain_result.side_effect = lambda v: v

    await host._cmd_tweet_search_impl(event, "#test 2 -last")

    mock_fx.search_tweets.assert_called_once()
    call_kwargs_fx = mock_fx.search_tweets.call_args[1]
    assert call_kwargs_fx.get("feed") == "latest"

    mock_nitter.search.assert_called_once()
    call_kwargs_nitter = mock_nitter.search.call_args[1]
    assert call_kwargs_nitter.get("sort") == "latest"


def test_scheduler_log_fxtwitter_instance_and_fallback_trace():
    """Verify FxTwitter instance and fallback trace in structured scheduler logs."""
    # FX success: outputs 生效实例: FxTwitter, no failover trace
    res_fx = ScheduledCheckResult(
        reason="interval:20m",
        group_id="g1",
        group_name="测试组",
        group_type="blogger",
        users=["alice"],
        source_attempts={"alice": ["FxTwitter=成功"]},
    )
    log_fx = res_fx.format_structured_task_log()
    assert "生效实例: FxTwitter" in log_fx
    assert "轮换轨迹" not in log_fx

    # FX fallback to Nitter: outputs 生效实例: http://nitter.test and 轮换轨迹 containing FxTwitter ➔ Nitter
    res_fallback = ScheduledCheckResult(
        reason="interval:20m",
        group_id="g1",
        group_name="测试组",
        group_type="blogger",
        users=["bob"],
        source_attempts={"bob": ["FxTwitter=失败", "Nitter=成功"]},
    )
    log_fallback = res_fallback.format_structured_task_log()
    assert "生效实例: Nitter" in log_fallback
    assert "轮换轨迹" in log_fallback
    assert "FxTwitter[失败] ➔ Nitter[成功]" in log_fallback


@pytest.mark.asyncio
async def test_status_summary_displays_fetch_backend():
    """Verify /推文状态 summary outputs the configured fetch_backend mode."""

    class _DummyStatus(SchedulerStatusMixin):
        def __init__(self, config: dict):
            self.config = config
            self.is_running = True
            self.schedule_enabled = True

        def _schedule_groups(self, **kwargs):
            return SchedulerConfigReader(self.config, context=None).schedule_groups()

        def _merge_tweet_threshold(self) -> int:
            return 2

    config_mix = {
        "schedule_enabled": True,
        "fetch_backend": "mix",
        "tweet_groups": [
            {
                "name": "博主组",
                "group_id": "bloggers",
                "group_type": "blogger",
                "watch_users": ["alice"],
            }
        ],
    }
    status_mix = _DummyStatus(config_mix)
    summary_mix = await status_mix.status_summary()
    assert "抓取策略: mix (FxTwitter 优先 + 自建 Nitter 容灾)" in summary_mix

    config_fx = dict(config_mix, fetch_backend="fx")
    status_fx = _DummyStatus(config_fx)
    summary_fx = await status_fx.status_summary()
    assert "抓取策略: fx (纯 FxTwitter API 抓取)" in summary_fx

    config_nitter = dict(config_mix, fetch_backend="nitter")
    status_nitter = _DummyStatus(config_nitter)
    summary_nitter = await status_nitter.status_summary()
    assert "抓取策略: nitter (纯自建 Nitter 实例抓取)" in summary_nitter


# ==============================================================================
# 11. Property default & case-insensitivity
# ==============================================================================
def test_fetch_backend_property():
    runner = DummyRunner({}, MagicMock())
    assert runner.fetch_backend == "mix"

    runner.config = {"fetch_backend": "NITTER"}
    assert runner.fetch_backend == "nitter"

    runner.config = {"fetch_backend": "  Fx  "}
    assert runner.fetch_backend == "fx"

    runner.config = {"fetch_backend": None}
    assert runner.fetch_backend == "mix"


# ==============================================================================
# 12. _get_fxtwitter_client resolution
# ==============================================================================
def test_get_fxtwitter_client_resolution():
    from media_support.fxtwitter_client import FxTwitterClient

    # 1. Directly on runner
    mock_direct = MagicMock(spec=FxTwitterClient)
    runner = DummyRunner({}, MagicMock())
    runner.fxtwitter = mock_direct
    assert runner._get_fxtwitter_client() is mock_direct

    # 2. On runner.owner
    runner2 = DummyRunner({}, MagicMock())
    runner2.fxtwitter = None
    mock_owner_fx = MagicMock(spec=FxTwitterClient)
    runner2.owner = MagicMock()
    runner2.owner.fxtwitter = mock_owner_fx
    assert runner2._get_fxtwitter_client() is mock_owner_fx

    # 3. Explicit mix mode instantiates FxTwitterClient
    runner3 = DummyRunner({"fetch_backend": "mix"}, MagicMock())
    runner3.fxtwitter = None
    runner3.owner = None
    runner3.nitter = MagicMock()
    runner3.nitter.fxtwitter = None
    runner3.nitter.timeout = 18.0
    client = runner3._get_fxtwitter_client()
    assert isinstance(client, FxTwitterClient)

    # 4. Pure nitter mode returns None
    runner4 = DummyRunner({"fetch_backend": "nitter"}, MagicMock())
    runner4.fxtwitter = None
    runner4.owner = None
    runner4.nitter = MagicMock()
    runner4.nitter.fxtwitter = None
    assert runner4._get_fxtwitter_client() is None


@pytest.mark.asyncio
async def test_manual_search_buffer_notice_failure_preserves_reserved_tweets():
    mock_nitter = MagicMock()
    mock_fx = MagicMock()
    host = DummyManualHost({"fetch_backend": "mix"}, mock_nitter, mock_fx)
    event = MagicMock()
    event.unified_msg_origin = "session:test_buffer_fail"
    event.plain_result.side_effect = lambda v: v
    event.stop_event = MagicMock()

    # Pre-populate session buffer with 2 tweets
    session_id = host._search_session_id(event)
    store = host._get_search_session_store()
    query_key = host._search_query_key("cats", "")
    buf = store.get_or_create(session_id, query_key)
    buf.add_tweets([_make_tweet("user", "1001"), _make_tweet("user", "1002")])
    assert len(buf) == 2

    # Simulate event.send failing on the preliminary cache-notice message
    event.send = AsyncMock(side_effect=RuntimeError("connection dropped"))
    host._send_tweets_response = AsyncMock()

    with pytest.raises(RuntimeError, match="connection dropped"):
        await host._cmd_tweet_search_impl(event, "cats 2")

    # Tweet response should never have been attempted
    host._send_tweets_response.assert_not_called()

    # Buffer must preserve all reserved tweets without dropping any (failed_count=0)
    assert len(buf) == 2
    remaining = buf.take(2)
    assert [t.status_id for t in remaining] == ["1001", "1002"]


@pytest.mark.asyncio
async def test_manual_search_buffer_delivery_failure_drops_failed_tweet():
    mock_nitter = MagicMock()
    mock_fx = MagicMock()
    host = DummyManualHost({"fetch_backend": "mix"}, mock_nitter, mock_fx)
    event = MagicMock()
    event.unified_msg_origin = "session:test_buffer_fail_delivery"
    event.plain_result.side_effect = lambda v: v
    event.send = AsyncMock()
    event.stop_event = MagicMock()

    session_id = host._search_session_id(event)
    store = host._get_search_session_store()
    query_key = host._search_query_key("dogs", "")
    buf = store.get_or_create(session_id, query_key)
    buf.add_tweets([_make_tweet("user", "2001"), _make_tweet("user", "2002")])
    assert len(buf) == 2

    # event.send succeeds, but _send_tweets_response fails
    host._send_tweets_response = AsyncMock(side_effect=RuntimeError("delivery failed"))

    with pytest.raises(RuntimeError, match="delivery failed"):
        await host._cmd_tweet_search_impl(event, "dogs 2")

    # 1 failed tweet should be dropped, remaining 1 preserved
    assert len(buf) == 1
    remaining = buf.take(2)
    assert [t.status_id for t in remaining] == ["2002"]


@pytest.mark.asyncio
async def test_manual_search_buffer_cancelled_before_delivery_preserves_reserved_tweets():
    mock_nitter = MagicMock()
    mock_fx = MagicMock()
    host = DummyManualHost({"fetch_backend": "mix"}, mock_nitter, mock_fx)
    event = MagicMock()
    event.unified_msg_origin = "session:test_buffer_cancelled"
    event.plain_result.side_effect = lambda v: v
    event.send = AsyncMock()
    event.stop_event = MagicMock()

    session_id = host._search_session_id(event)
    store = host._get_search_session_store()
    query_key = host._search_query_key("birds", "")
    buf = store.get_or_create(session_id, query_key)
    buf.add_tweets([_make_tweet("user", "3001"), _make_tweet("user", "3002")])
    assert len(buf) == 2

    # event.send succeeds, but _send_tweets_response is cancelled before any progress
    host._send_tweets_response = AsyncMock(side_effect=asyncio.CancelledError())

    with pytest.raises(asyncio.CancelledError):
        await host._cmd_tweet_search_impl(event, "birds 2")

    # Cancelled before any progress -> all 2 tweets must be preserved in buffer (failed_count=0)
    assert len(buf) == 2
    remaining = buf.take(2)
    assert [t.status_id for t in remaining] == ["3001", "3002"]


@pytest.mark.asyncio
async def test_manual_cmd_tweets_respects_global_filter_reposts_disabled():
    """Verify /推文 with filter_reposts_enabled=False passes filter_reposts=False to FX."""
    mock_nitter = MagicMock()
    mock_nitter.fetch_user = AsyncMock()

    mock_fx = MagicMock()
    mock_fx.base_url = "https://api.fxtwitter.com"
    mock_fx.fetch_user_timeline = MagicMock(
        return_value=([_make_tweet("nasa", "1001")], None)
    )

    host = DummyManualHost(
        {"fetch_backend": "mix", "filter_reposts_enabled": False},
        mock_nitter,
        mock_fx,
    )
    event = MagicMock()
    event.send = AsyncMock()
    event.stop_event = MagicMock()
    event.plain_result.side_effect = lambda v: v

    await host._cmd_tweets_impl(event, "nasa", "5")

    mock_fx.fetch_user_timeline.assert_called_once_with(
        "nasa", count=5, skip_plain_text=False, filter_reposts=False, max_pages=3
    )


@pytest.mark.asyncio
async def test_manual_cmd_tweet_pic_respects_global_filter_reposts_disabled():
    """Verify /推图 with filter_reposts_enabled=False passes filter_reposts=False to FX and Nitter fallback."""
    mock_nitter = MagicMock()
    mock_nitter.fetch_user = AsyncMock(
        return_value=("http://nitter.test", [_make_tweet("nasa", "1001")])
    )

    mock_fx = MagicMock()
    mock_fx.fetch_user_timeline = MagicMock(
        side_effect=FxTwitterNotFoundError("User not found 404")
    )

    host = DummyManualHost(
        {"fetch_backend": "mix", "filter_reposts_enabled": False},
        mock_nitter,
        mock_fx,
    )
    event = MagicMock()
    event.send = AsyncMock()
    event.stop_event = MagicMock()
    event.plain_result.side_effect = lambda v: v

    await host._cmd_tweets_impl(event, "nasa", "5", is_media_only=True)

    mock_fx.fetch_user_timeline.assert_called_once_with(
        "nasa", count=5, skip_plain_text=True, filter_reposts=False, max_pages=3
    )
    mock_nitter.fetch_user.assert_called_once_with(
        "nasa", 5, filter_reposts=False, skip_plain_text=True
    )


@pytest.mark.asyncio
async def test_scheduler_fetch_passes_configured_html_max_pages():
    mock_fx = MagicMock()
    mock_fx.base_url = "https://api.fxtwitter.com"
    mock_fx.fetch_user_timeline = MagicMock(return_value=([], None))
    mock_nitter = MagicMock()

    runner = DummyRunner(
        {"fetch_backend": "fx", "html_max_pages": 5}, mock_nitter, mock_fx
    )
    group = _blogger_group(["alice"])

    await runner._fetch_group_users(
        group, fetch_limit=10, skip_plain_text=False, scan_watermarks={}
    )
    mock_fx.fetch_user_timeline.assert_called_once_with(
        "alice", count=10, skip_plain_text=False, filter_reposts=True, max_pages=5
    )


@pytest.mark.asyncio
async def test_manual_cmd_tweet_pic_video_mode_passes_media_filter_and_force_media(
    monkeypatch,
):
    """Verify /推图 user 5 视频 passes media_filter='video' and force_media=True."""
    mock_nitter = MagicMock()
    mock_fx = MagicMock()
    mock_fx.base_url = "https://api.fxtwitter.com"
    mock_fx.fetch_user_timeline = MagicMock(
        return_value=([_make_tweet("nasa", "1001")], None)
    )

    host = DummyManualHost({"fetch_backend": "mix"}, mock_nitter, mock_fx)
    event = MagicMock()
    event.send = AsyncMock()
    event.stop_event = MagicMock()
    event.plain_result.side_effect = lambda v: v

    captured_kwargs = {}

    async def fake_send_tweets(evt, usr, inst, tws, **kwargs):
        captured_kwargs.update(kwargs)
        return len(tws)

    host._send_tweets_response = fake_send_tweets

    await host._cmd_tweets_impl(
        event, "nasa", "5", media_type_arg="视频", is_media_only=True
    )

    mock_fx.fetch_user_timeline.assert_called_once_with(
        "nasa",
        count=5,
        skip_plain_text=True,
        filter_reposts=True,
        max_pages=3,
        media_filter="video",
    )
    assert captured_kwargs.get("force_media") is True


@pytest.mark.asyncio
async def test_manual_cmd_tweet_pic_nitter_video_and_image_attaches_media_before_filter(
    monkeypatch,
):
    """Verify Nitter manual /推图 in video/image mode attaches media before filtering."""
    video_item = TweetMedia(kind="video", url="https://video.twimg.com/1.mp4")
    image_item = TweetMedia(kind="image", url="https://pbs.twimg.com/1.jpg")
    raw_tweet1 = _make_tweet("nasa", "1001")
    raw_tweet2 = _make_tweet("nasa", "1002")

    async def fake_attach(tweets, *, force_all_media=False):
        for t in tweets:
            if t.status_id == "1001":
                t.media = [video_item]
            elif t.status_id == "1002":
                t.media = [image_item]
        return []

    mock_nitter = MagicMock()
    mock_nitter.fetch_user = AsyncMock(
        return_value=("http://nitter.test", [raw_tweet1, raw_tweet2])
    )

    host = DummyManualHost({"fetch_backend": "nitter"}, mock_nitter, None)
    host.media.attach_media_with_results = AsyncMock(side_effect=fake_attach)

    event = MagicMock()
    event.send = AsyncMock()
    event.stop_event = MagicMock()
    event.plain_result.side_effect = lambda v: v

    captured_tweets = []

    async def fake_send_tweets(evt, usr, inst, tws, **kwargs):
        captured_tweets.extend(tws)
        return len(tws)

    host._send_tweets_response = fake_send_tweets

    # 1. Test video mode
    await host._cmd_tweets_impl(
        event, "nasa", "5", media_type_arg="视频", is_media_only=True
    )
    host.media.attach_media_with_results.assert_awaited_with(
        [raw_tweet1, raw_tweet2], force_all_media=True
    )
    assert len(captured_tweets) == 1
    assert captured_tweets[0].status_id == "1001"

    # 2. Test image mode
    captured_tweets.clear()
    host.media.attach_media_with_results.reset_mock()
    raw_tweet1.media = []
    raw_tweet2.media = []
    await host._cmd_tweets_impl(
        event, "nasa", "5", media_type_arg="图片", is_media_only=True
    )
    host.media.attach_media_with_results.assert_awaited_with(
        [raw_tweet1, raw_tweet2], force_all_media=False
    )
    assert len(captured_tweets) == 1
    assert captured_tweets[0].status_id == "1002"
