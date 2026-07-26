# -*- coding: utf-8 -*-
"""OneBot merged-forward retcode 1200 → split retry."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from delivery.outcomes import SendAttempt, SendOutcome
from delivery.sender import TweetSender
from shared.utils import TweetItem


class _FakeActionFailed(Exception):
    def __init__(self, retcode=1200, message="发送转发消息（res_id：abc 失败"):
        self.retcode = retcode
        self.message = message
        super().__init__(message)


def _tweets(n: int) -> list[TweetItem]:
    items = []
    for i in range(n):
        items.append(
            TweetItem(
                text=f"t{i}",
                link=f"https://x.com/u/status/{1000 + i}",
                published="2026-07-24",
            )
        )
    return items


def _event_sender(monkeypatch) -> TweetSender:
    import delivery.sender as sender_mod

    monkeypatch.setattr(sender_mod, "ActionFailed", _FakeActionFailed)
    sender = TweetSender.__new__(TweetSender)
    sender.FORWARD_SPLIT_MIN_TWEETS = 1
    sender.renderer = MagicMock()
    sender.renderer.build_nodes = MagicMock(return_value="nodes")
    sender.renderer.build_onebot_nodes = MagicMock(return_value=[{"n": 1}])
    sender._is_uncertain_delivery_error = MagicMock(return_value=False)
    sender._event_target = MagicMock(return_value="g:1")
    return sender


def test_is_forward_payload_rejected_error_retcode_1200(monkeypatch):
    import delivery.sender as sender_mod

    monkeypatch.setattr(sender_mod, "ActionFailed", _FakeActionFailed)
    assert TweetSender._is_forward_payload_rejected_error(_FakeActionFailed(1200))
    assert not TweetSender._is_forward_payload_rejected_error(
        _FakeActionFailed(1, "other")
    )
    assert TweetSender._is_forward_payload_rejected_error(
        Exception("发送转发消息（res_id：xyz 失败")
    )
    assert not TweetSender._is_forward_payload_rejected_error(
        Exception("timeout connecting")
    )


def test_split_tweets_for_forward_retry_halves():
    sender = TweetSender.__new__(TweetSender)
    sender.FORWARD_SPLIT_MIN_TWEETS = 1
    parts = sender._split_tweets_for_forward_retry(_tweets(5))
    assert parts is not None
    assert len(parts) == 2
    assert len(parts[0]) + len(parts[1]) == 5
    assert sender._split_tweets_for_forward_retry(_tweets(1)) is None


@pytest.mark.asyncio
async def test_event_forward_remainder_only_direct_after_partial_split(monkeypatch):
    """First half succeeds; second fails → direct fallback gets only remainder."""
    sender = _event_sender(monkeypatch)

    event = MagicMock()
    event.chain_result = MagicMock(side_effect=lambda x: x)
    event.send = AsyncMock(side_effect=_FakeActionFailed(1200))

    # full(4) fail → left(2) ok → right(2) fail → direct remainder only
    results = iter([False, True, False])

    async def onebot(_ev, _raw):
        try:
            return next(results)
        except StopIteration:
            return False

    sender._send_onebot_forward = AsyncMock(side_effect=onebot)

    direct_payloads: list[list[TweetItem]] = []

    async def send_event(_event, _user, _inst, tweets, **_kwargs):
        direct_payloads.append(list(tweets))
        return True

    adapter = MagicMock()
    adapter.send_event = AsyncMock(side_effect=send_event)
    sender._delivery_adapter_for_event = MagicMock(return_value=adapter)

    tweets = _tweets(4)
    ok = await sender._send_event_forward_chunk(
        event, "u", "https://nitter.example", tweets
    )
    assert ok is True
    # Right half may recursively split further (1+1 directs); union must be remainder only.
    sent_links = [t.link for batch in direct_payloads for t in batch]
    assert sent_links == [t.link for t in tweets[2:]]
    assert all(len(batch) < 4 for batch in direct_payloads)


@pytest.mark.asyncio
async def test_event_forward_recursive_split_all_ok(monkeypatch):
    sender = _event_sender(monkeypatch)

    event = MagicMock()
    event.chain_result = MagicMock(side_effect=lambda x: x)
    event.send = AsyncMock(side_effect=_FakeActionFailed(1200))

    calls = {"onebot": 0}

    async def onebot_counted(_ev, _raw):
        calls["onebot"] += 1
        return calls["onebot"] > 1

    sender._send_onebot_forward = AsyncMock(side_effect=onebot_counted)
    adapter = MagicMock()
    adapter.send_event = AsyncMock(return_value=True)
    sender._delivery_adapter_for_event = MagicMock(return_value=adapter)

    ok = await sender._send_event_forward_chunk(
        event, "u", "https://nitter.example", _tweets(4)
    )
    assert ok is True
    assert adapter.send_event.await_count == 0
    assert calls["onebot"] >= 3


@pytest.mark.asyncio
async def test_event_forward_recursive_failure_skips_delivered_child_prefix(
    monkeypatch,
):
    sender = _event_sender(monkeypatch)

    event = MagicMock()
    event.chain_result = MagicMock(side_effect=lambda x: x)
    event.send = AsyncMock(side_effect=_FakeActionFailed(1200))
    sender._send_onebot_forward = AsyncMock(return_value=False)

    tweets = _tweets(4)
    nested_calls: list[int] = []
    direct_payloads: list[list[TweetItem]] = []
    delivered_deltas: list[int] = []

    async def nested(_event, _user, _inst, part, *, on_delivered=None, **_kwargs):
        nested_calls.append(len(part))
        if len(nested_calls) == 1:
            on_delivered(len(part))
            return True
        on_delivered(1)
        return False

    async def send_event(_event, _user, _inst, part, **_kwargs):
        direct_payloads.append(list(part))
        return False

    sender._send_event_forward_chunk = nested  # type: ignore[method-assign]
    adapter = MagicMock()
    adapter.send_event = AsyncMock(side_effect=send_event)
    sender._delivery_adapter_for_event = MagicMock(return_value=adapter)

    ok = await TweetSender._send_event_forward_chunk(
        sender,
        event,
        "u",
        "https://nitter.example",
        tweets,
        on_delivered=delivered_deltas.append,
    )

    assert ok is False
    assert nested_calls == [2, 2]
    assert delivered_deltas == [2, 1]
    assert len(direct_payloads) == 1
    assert [tweet.link for tweet in direct_payloads[0]] == [tweets[3].link]


@pytest.mark.asyncio
async def test_send_reports_chunk_prefix_before_later_chunk_cancelled():
    sender = TweetSender.__new__(TweetSender)
    sender.FORWARD_TWEET_CHUNK_SIZE = 2
    adapter = MagicMock()
    adapter.name = "onebot"
    adapter.supports_merged_forward = True
    sender._delivery_adapter_for_event = MagicMock(return_value=adapter)
    sender._should_use_merge_for_count = MagicMock(return_value=True)

    calls = 0

    async def send_chunk(
        _event,
        _username,
        _instance,
        chunk,
        *,
        on_delivered=None,
        **_kwargs,
    ):
        nonlocal calls
        calls += 1
        if calls == 1:
            on_delivered(len(chunk))
            return True
        raise asyncio.CancelledError()

    sender._send_event_forward_chunk = send_chunk  # type: ignore[method-assign]
    progress: list[int] = []

    with pytest.raises(asyncio.CancelledError):
        await sender.send(
            MagicMock(),
            "u",
            "https://nitter.example",
            _tweets(4),
            on_sent_progress=progress.append,
        )

    assert calls == 2
    assert progress == [2]


@pytest.mark.asyncio
async def test_umo_forward_skips_split_on_non_reject_error():
    sender = TweetSender.__new__(TweetSender)
    sender.FORWARD_SPLIT_MIN_TWEETS = 1
    sender.renderer = MagicMock()
    sender.renderer.format_plain = MagicMock(return_value="plain text")
    sender.renderer.build_nodes_for_uin = MagicMock(return_value="nodes")

    sender._send_context_message = AsyncMock(
        side_effect=[
            SendAttempt(success=False, retryable=True, error="timeout connecting"),
            SendAttempt(success=True),
        ]
    )
    sender._send_direct_to_umo = AsyncMock(
        return_value=SendOutcome(success=False, error="direct fail")
    )
    sender._split_tweets_for_forward_retry = MagicMock(
        side_effect=AssertionError("must not split on timeout")
    )

    outcome = await TweetSender._send_forward_chunk_to_umo(
        sender,
        MagicMock(),
        "aiocqhttp:GroupMessage:1",
        "u",
        "https://nitter.example",
        _tweets(4),
    )
    assert outcome.success is True
    sender._split_tweets_for_forward_retry.assert_not_called()
    assert sender._send_context_message.await_count == 2


@pytest.mark.asyncio
async def test_umo_media_only_plain_fallback_does_not_complete_delivery():
    sender = TweetSender.__new__(TweetSender)
    sender.FORWARD_SPLIT_MIN_TWEETS = 1
    sender.renderer = MagicMock()
    sender.renderer.format_plain = MagicMock(return_value="@u")
    sender.renderer.build_nodes_for_uin = MagicMock(return_value="nodes")
    sender._send_context_message = AsyncMock(
        side_effect=[
            SendAttempt(success=False, retryable=True, error="timeout connecting"),
            SendAttempt(success=True),
        ]
    )
    sender._send_direct_to_umo = AsyncMock(
        return_value=SendOutcome(success=False, error="media failed")
    )

    outcome = await TweetSender._send_forward_chunk_to_umo(
        sender,
        MagicMock(),
        "aiocqhttp:GroupMessage:1",
        "u",
        "https://nitter.example",
        _tweets(2),
        media_only=True,
    )

    assert outcome.success is False
    assert outcome.delivery_status == "failed"
    assert outcome.delivered_status_ids == ()


@pytest.mark.asyncio
async def test_umo_media_only_skips_no_video_retry():
    sender = TweetSender.__new__(TweetSender)
    sender.renderer = MagicMock()
    sender.renderer.build_nodes_for_uin = MagicMock(return_value="nodes")
    tweets = _tweets(1)
    tweets[0].media = [MagicMock(path="video.mp4", is_video=True)]
    sender._send_context_message = AsyncMock(
        return_value=SendAttempt(
            success=False,
            retryable=True,
            error="media failed",
        )
    )
    sender._send_direct_to_umo = AsyncMock(
        return_value=SendOutcome(success=False, error="media fallback failed")
    )

    outcome = await TweetSender._send_forward_chunk_to_umo(
        sender,
        MagicMock(),
        "aiocqhttp:GroupMessage:1",
        "u",
        "https://nitter.example",
        tweets,
        media_only=True,
    )

    assert outcome.success is False
    assert outcome.delivery_status == "failed"
    assert outcome.delivered_status_ids == ()
    assert sender._send_context_message.await_count == 1


@pytest.mark.asyncio
async def test_umo_media_only_retcode_splits_original_video_payload():
    sender = TweetSender.__new__(TweetSender)
    sender.FORWARD_SPLIT_MIN_TWEETS = 1
    sender.renderer = MagicMock()
    sender.renderer.build_nodes_for_uin = MagicMock(return_value="nodes")
    tweets = _tweets(2)
    for tweet in tweets:
        tweet.media = [MagicMock(path="video.mp4", is_video=True)]
    sender._send_context_message = AsyncMock(
        return_value=SendAttempt(
            success=False,
            retryable=True,
            error="retcode=1200 res_id failed",
        )
    )
    nested_payloads = []

    async def send_part(context, umo, username, instance, part, **kwargs):
        del context, umo, username, instance
        nested_payloads.append((part, kwargs))
        return SendOutcome(success=True)

    sender._send_forward_chunk_to_umo = send_part
    sender._send_direct_to_umo = AsyncMock()

    outcome = await TweetSender._send_forward_chunk_to_umo(
        sender,
        MagicMock(),
        "aiocqhttp:GroupMessage:1",
        "u",
        "https://nitter.example",
        tweets,
        media_only=True,
    )

    assert outcome.success is True
    assert [len(part) for part, _kwargs in nested_payloads] == [1, 1]
    assert all(part[0].media[0].path == "video.mp4" for part, _ in nested_payloads)
    assert all(kwargs["media_only"] is True for _part, kwargs in nested_payloads)
    assert sender._send_context_message.await_count == 1
    sender._send_direct_to_umo.assert_not_awaited()


@pytest.mark.asyncio
async def test_merged_media_only_plain_fallback_does_not_complete_delivery():
    sender = TweetSender.__new__(TweetSender)
    sender.renderer = MagicMock()
    sender.renderer.build_merged_nodes_for_uin = MagicMock(return_value="nodes")
    sender.renderer.format_merged_plain = MagicMock(return_value="@u")
    sender._count_attached_videos = MagicMock(return_value=0)
    sender._merged_forward_has_video = MagicMock(return_value=False)
    sender._send_context_message = AsyncMock(
        side_effect=[
            SendAttempt(success=False, retryable=True, error="forward failed"),
            SendAttempt(success=True),
        ]
    )

    outcome = await TweetSender._send_merged_forward_chunk_to_umo(
        sender,
        MagicMock(),
        "aiocqhttp:GroupMessage:1",
        [("u", "https://nitter.example", _tweets(2))],
        media_only=True,
    )

    assert outcome.success is False
    assert outcome.delivery_status == "failed"
    assert outcome.delivery_error == "forward failed"


@pytest.mark.asyncio
async def test_merged_media_only_no_video_uncertain_does_not_complete_delivery():
    sender = TweetSender.__new__(TweetSender)
    sender.renderer = MagicMock()
    sender.renderer.build_merged_onebot_nodes_for_uin = MagicMock(return_value=[])
    sender._count_attached_videos = MagicMock(return_value=1)
    sender._merged_forward_has_video = MagicMock(return_value=True)
    sender._onebot_call_action_for_umo = MagicMock(return_value=AsyncMock())
    sender._send_onebot_umo_forward = AsyncMock(
        return_value=SendAttempt(
            success=False,
            retryable=True,
            error="media failed",
        )
    )

    outcome = await TweetSender._send_merged_forward_chunk_to_umo(
        sender,
        MagicMock(),
        "aiocqhttp:GroupMessage:1",
        [("u", "https://nitter.example", _tweets(1))],
        media_only=True,
    )

    assert outcome.success is False
    assert outcome.delivery_status == "failed"
    assert outcome.delivery_error == "media failed"
    assert sender._send_onebot_umo_forward.await_count == 1


@pytest.mark.asyncio
async def test_merged_direct_media_only_no_video_uncertain_stays_failed():
    sender = TweetSender.__new__(TweetSender)
    sender.renderer = MagicMock()
    sender.renderer.build_merged_direct_components = MagicMock(return_value=[])
    sender._count_attached_videos = MagicMock(return_value=1)
    sender._send_context_message = AsyncMock(
        return_value=SendAttempt(
            success=False,
            retryable=True,
            error="media failed",
        )
    )

    outcome = await TweetSender._send_merged_direct_to_umo(
        sender,
        MagicMock(),
        "telegram:GroupMessage:1",
        [("u", "https://nitter.example", _tweets(1))],
        media_only=True,
    )

    assert outcome.success is False
    assert outcome.delivery_status == "failed"
    assert outcome.delivery_error == "media failed"
    assert sender._send_context_message.await_count == 1


@pytest.mark.asyncio
async def test_send_merged_to_umo_splits_and_falls_back_only_undelivered_suffix():
    sender = TweetSender.__new__(TweetSender)
    sender.FORWARD_SPLIT_MIN_TWEETS = 1
    adapter = MagicMock()
    adapter.name = "onebot"
    adapter.supports_merged_forward = True
    sender._delivery_adapter_for_umo = MagicMock(return_value=adapter)
    sender._should_use_merge_for_count = MagicMock(return_value=True)
    sender._should_chunk_forward_tweets = MagicMock(return_value=False)
    sender._count_attached_videos = MagicMock(return_value=0)
    sender._merged_forward_has_video = MagicMock(return_value=False)
    sender.renderer = MagicMock()
    sender.renderer.build_merged_nodes_for_uin = MagicMock(return_value="nodes")

    fallback_payloads: list[list[str]] = []

    def format_plain(batches, **_kwargs):
        fallback_payloads.append(
            [tweet.status_id for _username, _instance, tweets in batches for tweet in tweets]
        )
        return "plain"

    sender.renderer.format_merged_plain = MagicMock(side_effect=format_plain)
    rejected = SendAttempt(
        success=False,
        retryable=True,
        error="ActionFailed: retcode=1200 res_id failed",
    )
    sender._send_context_message = AsyncMock(
        side_effect=[
            rejected,  # full batch
            SendAttempt(success=True),  # left half
            rejected,  # right half
            SendAttempt(success=False, retryable=False, error="plain failed"),
            SendAttempt(success=True),  # outer suffix fallback
        ]
    )

    tweets = _tweets(2)
    outcome = await sender.send_merged_to_umo(
        MagicMock(),
        "aiocqhttp:GroupMessage:1",
        [
            ("left", "https://nitter.example", [tweets[0]]),
            ("right", "https://nitter.example", [tweets[1]]),
        ],
        group_label="group",
        batch_summary="summary",
    )

    assert outcome.success is True
    assert outcome.delivery_status == "partial_failed"
    assert outcome.delivered_status_ids == ("1000", "1001")
    assert fallback_payloads == [["1001"], ["1001"]]
    node_calls = sender.renderer.build_merged_nodes_for_uin.call_args_list
    assert node_calls[1].kwargs["group_label"] == "group"
    assert node_calls[1].kwargs["batch_summary"] == "summary"
    assert node_calls[2].kwargs["group_label"] == ""
    assert node_calls[2].kwargs["batch_summary"] == ""
    assert node_calls[2].kwargs["start_index"] == 2


@pytest.mark.asyncio
async def test_umo_forward_remainder_only_after_partial_split():
    sender = TweetSender.__new__(TweetSender)
    sender.FORWARD_SPLIT_MIN_TWEETS = 1
    sender.renderer = MagicMock()
    sender.renderer.format_plain = MagicMock(return_value="plain")
    sender.renderer.build_nodes_for_uin = MagicMock(return_value="nodes")
    err_1200 = "ActionFailed: retcode=1200 发送转发消息（res_id：x 失败"
    sender._send_context_message = AsyncMock(
        return_value=SendAttempt(success=False, retryable=True, error=err_1200)
    )

    rec_calls: list[int] = []
    direct_payloads: list[list[TweetItem]] = []
    tweets = _tweets(4)

    async def rec(context, umo, username, instance, part, **kw):
        rec_calls.append(len(part))
        if len(rec_calls) == 1:
            return SendOutcome(success=True)
        return SendOutcome(success=False, error="right fail")

    async def capture_direct(context, umo, username, instance, part, **kwargs):
        direct_payloads.append(list(part))
        return SendOutcome(success=True)

    # Nested self-calls use the instance attribute; outer entry uses unbound real body.
    sender._send_forward_chunk_to_umo = rec  # type: ignore[method-assign]
    sender._send_direct_to_umo = AsyncMock(side_effect=capture_direct)

    outcome = await TweetSender._send_forward_chunk_to_umo(
        sender,
        MagicMock(),
        "aiocqhttp:GroupMessage:1",
        "u",
        "https://nitter.example",
        tweets,
    )
    assert outcome.success is True
    assert rec_calls == [2, 2]
    assert len(direct_payloads) == 1
    assert [t.link for t in direct_payloads[0]] == [t.link for t in tweets[2:]]
    assert outcome.delivery_status == "partial_failed"


@pytest.mark.asyncio
async def test_chunked_forward_keeps_accepted_uncertain_status_complete():
    sender = TweetSender.__new__(TweetSender)
    sender.FORWARD_TWEET_CHUNK_SIZE = 1
    sender._send_forward_chunk_to_umo = AsyncMock(
        side_effect=[
            SendOutcome(success=True, error="timeout", warning="uncertain"),
            SendOutcome(success=True),
        ]
    )

    outcome = await sender._send_forward_chunks_to_umo(
        object(),
        "aiocqhttp:GroupMessage:1",
        "user",
        "instance",
        _tweets(2),
    )

    assert outcome.success is True
    assert outcome.delivery_status == "success"
    assert outcome.delivered_status_ids == ("1000", "1001")


@pytest.mark.asyncio
async def test_chunked_forward_propagates_partial_status_without_generic_error():
    sender = TweetSender.__new__(TweetSender)
    sender.FORWARD_TWEET_CHUNK_SIZE = 1
    sender._send_forward_chunk_to_umo = AsyncMock(
        side_effect=[
            SendOutcome(
                success=True,
                delivery_status="partial_failed",
                delivery_error="media failed",
            ),
            SendOutcome(success=True),
        ]
    )

    outcome = await sender._send_forward_chunks_to_umo(
        object(),
        "aiocqhttp:GroupMessage:1",
        "user",
        "instance",
        _tweets(2),
    )

    assert outcome.success is True
    assert outcome.delivery_status == "partial_failed"
    assert outcome.delivery_error == "media failed"
