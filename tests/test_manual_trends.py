"""Tests for /推特热搜 manual command and trends formatting."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from command_handlers.manual import ManualCommandMixin
from rendering.tweets import format_twitter_trends


class TestFormatTwitterTrends:
    def test_empty_or_invalid_trends(self):
        assert format_twitter_trends([]) == "暂无实时 Twitter/X 热搜趋势，请稍后再试。"
        assert (
            format_twitter_trends(None) == "暂无实时 Twitter/X 热搜趋势，请稍后再试。"
        )
        assert (
            format_twitter_trends([{}]) == "暂无实时 Twitter/X 热搜趋势，请稍后再试。"
        )
        assert (
            format_twitter_trends([{"name": ""}])
            == "暂无实时 Twitter/X 热搜趋势，请稍后再试。"
        )

    def test_format_with_null_ranks_and_contexts(self):
        """Must use enumerate(trends, 1) defensively when rank is None or missing."""
        trends = [
            {
                "name": "Harry Shum Jr",
                "rank": None,
                "context": "Entertainment · Trending",
            },
            {
                "name": "George Marciniw",
                "rank": None,
                "context": "Trending in United States",
            },
            {
                "name": "SpaceX",
                "rank": None,
                "context": "",
            },
        ]
        result = format_twitter_trends(trends)

        # Header with fire icon
        assert "🔥 Twitter/X 实时趋势热搜榜" in result

        # 1-based index numbers
        assert "1. Harry Shum Jr (Entertainment · Trending)" in result
        assert "2. George Marciniw (Trending in United States)" in result
        assert "3. SpaceX" in result

        # Data source disclaimer
        assert "数据来源：FxTwitter / X" in result

    def test_format_with_intermittent_empty_items_preserves_consecutive_ranks(self):
        """Must produce consecutive 1-based ranks even if middle items are null or empty."""
        trends = [
            {"name": "Topic 1", "rank": None, "context": "Gaming"},
            {},
            {"name": ""},
            {"name": "Topic 2", "rank": None, "context": ""},
        ]
        result = format_twitter_trends(trends)
        assert "1. Topic 1 (Gaming)" in result
        assert "2. Topic 2" in result
        assert "3." not in result


class _Host(ManualCommandMixin):
    def __init__(self, cooldown_seconds: float = 0.0):
        self.cooldown_seconds = cooldown_seconds
        self._cooldowns: dict[str, float] = {}
        self.fxtwitter = MagicMock()


def _make_event(sender_id: str = "u1", group_id: str = "g1") -> MagicMock:
    event = MagicMock()
    event.stop_event = MagicMock()
    event.get_sender_id = MagicMock(return_value=sender_id)
    event.get_group_id = MagicMock(return_value=group_id)
    event.plain_result = MagicMock(side_effect=lambda text: f"MSG:{text}")
    event.send = AsyncMock()
    return event


class TestManualTrendsCommand:
    @pytest.mark.asyncio
    async def test_cmd_tweet_trends_success(self, monkeypatch):
        host = _Host(cooldown_seconds=0.0)
        sample_trends = [
            {"name": "Topic 1", "rank": None, "context": "Category A"},
            {"name": "Topic 2", "rank": None, "context": "Category B"},
        ]
        host.fxtwitter.fetch_trends = MagicMock(return_value=sample_trends)

        logged_tasks: list[dict] = []

        def mock_log_task(title, **kwargs):
            logged_tasks.append({"title": title, **kwargs})

        monkeypatch.setattr(host, "_log_manual_send_task", mock_log_task)

        event = _make_event()
        await host._cmd_tweet_trends_impl(event)

        event.stop_event.assert_called_once()
        host.fxtwitter.fetch_trends.assert_called_once()
        event.send.assert_awaited_once()

        # Check sent message
        sent_arg = event.send.await_args[0][0]
        assert "🔥 Twitter/X 实时趋势热搜榜" in sent_arg
        assert "1. Topic 1 (Category A)" in sent_arg
        assert "2. Topic 2 (Category B)" in sent_arg

        # Check audit log
        assert len(logged_tasks) == 1
        assert logged_tasks[0]["title"] == "推特热搜查询"
        assert logged_tasks[0]["operation"] == "trends"
        assert logged_tasks[0]["instance"] == "FxTwitter"
        assert logged_tasks[0]["tweet_count"] == 2
        assert logged_tasks[0]["sent_count"] == 2

    @pytest.mark.asyncio
    async def test_cmd_tweet_trends_cooldown(self):
        host = _Host(cooldown_seconds=60.0)
        host.fxtwitter.fetch_trends = MagicMock(
            return_value=[{"name": "Topic", "rank": None, "context": ""}]
        )

        event = _make_event(sender_id="spammer", group_id="g1")

        # First request passes
        await host._cmd_tweet_trends_impl(event)
        assert host.fxtwitter.fetch_trends.call_count == 1
        first_call_msg = event.send.await_args[0][0]
        assert "🔥 Twitter/X 实时趋势热搜榜" in first_call_msg

        # Second request intercepted by cooldown
        event.send.reset_mock()
        await host._cmd_tweet_trends_impl(event)

        # fetch_trends must NOT be called again
        assert host.fxtwitter.fetch_trends.call_count == 1
        event.send.assert_awaited_once()
        cooldown_msg = event.send.await_args[0][0]
        assert "请求太快啦" in cooldown_msg

    @pytest.mark.asyncio
    async def test_cmd_tweet_trends_empty_fallback(self, monkeypatch):
        host = _Host(cooldown_seconds=0.0)
        host.fxtwitter.fetch_trends = MagicMock(return_value=[])

        logged_tasks: list[dict] = []
        monkeypatch.setattr(
            host,
            "_log_manual_no_send_task",
            lambda title, **kwargs: logged_tasks.append({"title": title, **kwargs}),
        )

        event = _make_event()
        await host._cmd_tweet_trends_impl(event)

        event.stop_event.assert_called_once()
        event.send.assert_awaited_once()
        msg = event.send.await_args[0][0]
        assert "暂无数据" in msg

        assert len(logged_tasks) == 1
        assert logged_tasks[0]["status"] == "无数据"
        assert logged_tasks[0]["instance"] == "FxTwitter"
        assert logged_tasks[0]["warning"] is True

    @pytest.mark.asyncio
    async def test_cmd_tweet_trends_exception_fallback(self, monkeypatch):
        host = _Host(cooldown_seconds=0.0)
        host.fxtwitter.fetch_trends = MagicMock(
            side_effect=RuntimeError("Connection timeout")
        )

        logged_tasks: list[dict] = []
        monkeypatch.setattr(
            host,
            "_log_manual_no_send_task",
            lambda title, **kwargs: logged_tasks.append({"title": title, **kwargs}),
        )

        event = _make_event()
        # Must not raise exception to user
        await host._cmd_tweet_trends_impl(event)

        event.stop_event.assert_called_once()
        event.send.assert_awaited_once()
        msg = event.send.await_args[0][0]
        assert "失败" in msg

        assert len(logged_tasks) == 1
        assert logged_tasks[0]["status"] == "抓取失败"
        assert logged_tasks[0]["instance"] == "FxTwitter"
        # Shared query layer reports a stable error kind, not exception text
        # that can include credential-bearing request URLs.
        assert logged_tasks[0]["error_detail"] == "RuntimeError"
        assert logged_tasks[0]["warning"] is True


class TestPluginCommandRegistration:
    def test_cmd_tweet_trends_registered_on_plugin(self):
        from main import NitterTweetsPlugin

        assert hasattr(NitterTweetsPlugin, "cmd_tweet_trends")
        cmd_fn = getattr(NitterTweetsPlugin, "cmd_tweet_trends")
        assert callable(cmd_fn)
        assert "查看 Twitter/X 实时趋势热搜榜" in (cmd_fn.__doc__ or "")
