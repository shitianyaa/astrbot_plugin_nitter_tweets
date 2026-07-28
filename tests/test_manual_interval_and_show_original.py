"""manual_send_interval + global show_original_when_translated."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from command_handlers.manual import ManualCommandMixin
from config.compat import (
    resolve_hide_original_when_translated,
    resolve_manual_send_interval,
    resolve_show_original_when_translated,
)
from media_support.search_session_buffer import SearchSessionStore
from rendering.tweets import TweetMessageRenderer


class _Cfg(dict):
    def get(self, key, default=None):
        return super().get(key, default)


def test_resolve_show_original_defaults_true():
    assert resolve_show_original_when_translated(_Cfg()) is True
    assert (
        resolve_show_original_when_translated(
            _Cfg({"show_original_when_translated": False})
        )
        is False
    )
    assert (
        resolve_show_original_when_translated(
            _Cfg({"ai_translation": {"show_original_when_translated": False}})
        )
        is False
    )


def test_resolve_hide_combines_global_and_group():
    # Global show → only group can hide
    assert resolve_hide_original_when_translated(_Cfg(), group_hide=False) is False
    assert resolve_hide_original_when_translated(_Cfg(), group_hide=True) is True
    # Global hide forces hide even if group says show
    cfg = _Cfg({"show_original_when_translated": False})
    assert resolve_hide_original_when_translated(cfg, group_hide=False) is True
    assert resolve_hide_original_when_translated(cfg, group_hide=True) is True


def test_resolve_manual_send_interval_clamp():
    assert resolve_manual_send_interval(_Cfg()) == 0.0
    assert resolve_manual_send_interval(_Cfg({"manual_send_interval": 1.5})) == 1.5
    assert (
        resolve_manual_send_interval(_Cfg({"push": {"manual_send_interval": 99}}))
        == 60.0
    )
    assert resolve_manual_send_interval(_Cfg({"manual_send_interval": -1})) == 0.0


def test_renderer_respects_hide_flag_with_translation():
    t = SimpleNamespace(
        status_id="1",
        username="u",
        text="hello",
        x_url="https://x.com/u/status/1",
        link="https://x.com/u/status/1",
        published="",
        media=[],
        translation="你好",
        ai_warnings=[],
        media_warnings=[],
    )
    out = TweetMessageRenderer.format_tweet(
        0, "u", t, hide_original_when_translated=True
    )
    assert "翻译" in out
    assert "原文" not in out


@pytest.mark.asyncio
async def test_manual_sequential_sleeps_between_tweets(monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(seconds):
        sleeps.append(float(seconds))

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    class Host(ManualCommandMixin):
        def __init__(self):
            self.config = _Cfg(
                {
                    "manual_send_interval": 1.25,
                    "show_original_when_translated": True,
                }
            )
            self.sender = MagicMock()
            self.sender.should_merge_for_event = MagicMock(return_value=False)
            self.sender.send = AsyncMock(return_value=True)
            self.media = MagicMock()
            self.media.cleanup_after_send = MagicMock()
            self.translator = MagicMock()
            self.translator.attach_translations = AsyncMock(return_value=None)

        async def _prepare_manual_tweets(self, *args, **kwargs):
            return []

    host = Host()
    tweets = [
        SimpleNamespace(
            text=f"t{i}",
            link=f"https://x.com/u/status/{i}",
            published="",
            media=[],
            translation="",
            media_warnings=[],
            ai_warnings=[],
        )
        for i in range(1, 4)
    ]
    event = MagicMock()
    event.unified_msg_origin = "aiocqhttp:GroupMessage:1"

    await host._send_tweets_response(event, "u", "https://nitter.example", tweets)

    assert sleeps == [1.25, 1.25]
    assert host.sender.send.await_count == 3
    # hide_original forwarded (global show → False)
    for call in host.sender.send.await_args_list:
        assert call.kwargs.get("hide_original_when_translated") is False


@pytest.mark.asyncio
async def test_manual_global_hide_original_passed(monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())

    class Host(ManualCommandMixin):
        def __init__(self):
            self.config = _Cfg({"show_original_when_translated": False})
            self.sender = MagicMock()
            self.sender.should_merge_for_event = MagicMock(return_value=False)
            self.sender.send = AsyncMock(return_value=True)
            self.media = MagicMock()
            self.media.cleanup_after_send = MagicMock()

        async def _prepare_manual_tweets(self, *args, **kwargs):
            return []

    host = Host()
    tweet = SimpleNamespace(
        text="hi",
        link="https://x.com/u/status/1",
        published="",
        media=[],
        translation="你好",
        media_warnings=[],
        ai_warnings=[],
    )
    event = MagicMock()
    event.unified_msg_origin = "telegram:GroupMessage:1"
    await host._send_tweets_response(event, "u", "https://nitter.example", [tweet])
    assert host.sender.send.await_args.kwargs["hide_original_when_translated"] is True


@pytest.mark.asyncio
async def test_manual_merged_records_progress_before_media_cleanup():
    progress: list[int] = []

    class Host(ManualCommandMixin):
        def __init__(self):
            self.config = _Cfg()
            self.sender = MagicMock()
            self.sender.should_merge_for_event = MagicMock(return_value=True)

            async def send(_event, _username, _instance, tweets, **kwargs):
                kwargs["on_sent_progress"](len(tweets))
                return True

            self.sender.send = AsyncMock(side_effect=send)
            self.media = MagicMock()

            def cleanup(_tweets):
                assert progress == [2]

            self.media.cleanup_after_send = MagicMock(side_effect=cleanup)

        async def _prepare_manual_tweets(self, *args, **kwargs):
            return []

    host = Host()
    tweets = [
        SimpleNamespace(
            text=f"t{i}",
            link=f"https://x.com/u/status/{i}",
            published="",
            media=[],
            translation="",
            media_warnings=[],
            ai_warnings=[],
        )
        for i in range(1, 3)
    ]
    event = MagicMock()
    event.unified_msg_origin = "aiocqhttp:GroupMessage:1"

    sent = await host._send_tweets_response(
        event,
        "u",
        "https://nitter.example",
        tweets,
        on_sent_progress=progress.append,
    )

    assert sent == 2
    assert progress == [2]
    host.media.cleanup_after_send.assert_called_once_with(tweets)


@pytest.mark.asyncio
async def test_manual_plain_fallback_sends_only_unconfirmed_suffix():
    class Host(ManualCommandMixin):
        def __init__(self):
            self.sender = MagicMock()
            self.sender.renderer = MagicMock()
            self.sender.renderer.format_plain = MagicMock(return_value="fallback")

            async def send(_event, _username, _instance, _tweets, **kwargs):
                kwargs["on_sent_progress"](2)
                return False

            self.sender.send = AsyncMock(side_effect=send)

    host = Host()
    tweets = [
        SimpleNamespace(
            status_id=str(i),
            text=f"t{i}",
            link=f"https://x.com/u/status/{i}",
            published="",
            media=[],
            translation="",
            media_warnings=[],
            ai_warnings=[],
        )
        for i in range(1, 5)
    ]
    event = MagicMock()
    event.send = AsyncMock()
    progress: list[int] = []

    accepted = await host._send_manual_tweets_with_fallback(
        event,
        "u",
        "https://nitter.example",
        tweets,
        notices=["notice"],
        header_text="header",
        tweet_start_index=1,
        on_sent_progress=progress.append,
    )

    assert accepted is True
    assert progress == [2, 4]
    call = host.sender.renderer.format_plain.call_args
    assert [tweet.status_id for tweet in call.args[2]] == ["3", "4"]
    assert call.kwargs["start_index"] == 3
    assert call.kwargs["notices"] == []
    assert call.kwargs["header_text"] == ""


@pytest.mark.asyncio
async def test_manual_sequential_returns_confirmed_prefix_on_send_failure(monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())

    class Host(ManualCommandMixin):
        def __init__(self):
            self.config = _Cfg()
            self.sender = MagicMock()
            self.sender.should_merge_for_event = MagicMock(return_value=False)
            self.media = MagicMock()
            self.media.cleanup_after_send = MagicMock()
            self.calls = 0

        async def _prepare_manual_tweets(self, *args, **kwargs):
            return []

        async def _send_manual_tweets_with_fallback(self, *args, **kwargs):
            self.calls += 1
            return self.calls == 1

    host = Host()
    tweets = [
        SimpleNamespace(
            text=f"t{i}",
            link=f"https://x.com/u/status/{i}",
            published="",
            media=[],
            translation="",
            media_warnings=[],
            ai_warnings=[],
        )
        for i in range(1, 3)
    ]
    event = MagicMock()
    event.unified_msg_origin = "telegram:GroupMessage:1"

    assert (
        await host._send_tweets_response(event, "u", "https://nitter.example", tweets)
        == 1
    )
    assert host.media.cleanup_after_send.call_count == 2


@pytest.mark.asyncio
async def test_manual_search_cancel_keeps_only_unsent_suffix(monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())

    class Host(ManualCommandMixin):
        def __init__(self):
            self.config = _Cfg()
            self.default_limit = 2
            self.search_default_limit = 2
            self.search_max_limit = 10
            self.search_cooldown_seconds = 0
            self._cooldowns = {}
            self._search_session_store = SearchSessionStore()
            self.sender = MagicMock()
            self.sender.should_merge_for_event = MagicMock(return_value=False)
            self.media = MagicMock()
            self.media.cleanup_after_send = MagicMock()
            self.calls = 0
            self.html_backend = SimpleNamespace(
                config=SimpleNamespace(search_enabled=True),
                search=lambda query, limit, max_pages=3: (
                    "https://nitter.example",
                    [
                        SimpleNamespace(
                            status_id="1",
                            link="https://x.com/u/status/1",
                            text="one",
                            media=[],
                            translation="",
                            media_warnings=[],
                            ai_warnings=[],
                        ),
                        SimpleNamespace(
                            status_id="2",
                            link="https://x.com/u/status/2",
                            text="two",
                            media=[],
                            translation="",
                            media_warnings=[],
                            ai_warnings=[],
                        ),
                    ],
                ),
            )

        async def _prepare_manual_tweets(self, *args, **kwargs):
            return []

        async def _send_manual_tweets_with_fallback(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 2:
                raise asyncio.CancelledError()
            return True

    host = Host()
    event = MagicMock()
    event.unified_msg_origin = "telegram:GroupMessage:1"
    event.send = AsyncMock()
    event.plain_result.side_effect = lambda value: value

    with pytest.raises(asyncio.CancelledError):
        await host._cmd_tweet_search_impl(event, "#foo 2")

    buffer = host._search_session_store.get(
        event.unified_msg_origin,
        "#foo",
    )
    assert buffer is not None
    assert [item.status_id for item in buffer.items.values()] == ["2"]


@pytest.mark.asyncio
async def test_manual_search_merged_error_keeps_only_unsent_suffix(monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())

    class Host(ManualCommandMixin):
        def __init__(self):
            self.config = _Cfg()
            self.default_limit = 2
            self.search_default_limit = 2
            self.search_max_limit = 10
            self.search_cooldown_seconds = 0
            self._cooldowns = {}
            self._search_session_store = SearchSessionStore()
            self.sender = MagicMock()
            self.sender.should_merge_for_event = MagicMock(return_value=True)
            self.media = MagicMock()
            self.media.cleanup_after_send = MagicMock()
            self.html_backend = SimpleNamespace(
                config=SimpleNamespace(search_enabled=True),
                search=lambda query, limit, max_pages=3: (
                    "https://nitter.example",
                    [
                        SimpleNamespace(
                            status_id="1",
                            link="https://x.com/u/status/1",
                            text="one",
                            media=[],
                            translation="",
                            media_warnings=[],
                            ai_warnings=[],
                        ),
                        SimpleNamespace(
                            status_id="2",
                            link="https://x.com/u/status/2",
                            text="two",
                            media=[],
                            translation="",
                            media_warnings=[],
                            ai_warnings=[],
                        ),
                    ],
                ),
            )

        async def _prepare_manual_tweets(self, *args, **kwargs):
            return []

        async def _send_manual_tweets_with_fallback(self, *args, **kwargs):
            kwargs["on_sent_progress"](1)
            raise RuntimeError("second chunk failed")

    host = Host()
    event = MagicMock()
    event.unified_msg_origin = "aiocqhttp:GroupMessage:1"
    event.send = AsyncMock()
    event.plain_result.side_effect = lambda value: value

    with pytest.raises(RuntimeError, match="second chunk failed"):
        await host._cmd_tweet_search_impl(event, "#foo 2")

    buffer = host._search_session_store.get(
        event.unified_msg_origin,
        "#foo",
    )
    assert buffer is not None
    assert [item.status_id for item in buffer.items.values()] == ["2"]


@pytest.mark.asyncio
async def test_manual_none_send_result_remains_legacy_success(monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())

    class Host(ManualCommandMixin):
        def __init__(self):
            self.config = _Cfg()
            self.sender = MagicMock()
            self.sender.should_merge_for_event = MagicMock(return_value=False)
            self.media = MagicMock()
            self.media.cleanup_after_send = MagicMock()

        async def _prepare_manual_tweets(self, *args, **kwargs):
            return []

        async def _send_manual_tweets_with_fallback(self, *args, **kwargs):
            # Pre-reservation overrides returned None on success.
            return None

    host = Host()
    tweet = SimpleNamespace(
        text="hi",
        link="https://x.com/u/status/1",
        published="",
        media=[],
        translation="",
        media_warnings=[],
        ai_warnings=[],
    )
    event = MagicMock()
    event.unified_msg_origin = "telegram:GroupMessage:1"
    assert (
        await host._send_tweets_response(event, "u", "https://nitter.example", [tweet])
        == 1
    )
