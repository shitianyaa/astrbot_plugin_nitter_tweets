"""OneBot 普通发送的图文归属、显隐策略和降级边界。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from delivery.onebot import OneBotDeliveryAdapter
from delivery.outcomes import SendAttempt
from delivery.platforms import PlatformProfile
from delivery.sender import TweetSender
from scheduler.runner_send import SchedulerSendMixin
from shared import TweetItem, TweetMedia


def _tweet(tmp_path, number=1, *, video=False):
    image_path = tmp_path / f"{number}.jpg"
    image_path.write_bytes(b"image")
    media = [TweetMedia("image", "https://pbs.twimg.com/media/a.jpg", image_path)]
    if video:
        video_path = tmp_path / f"{number}.mp4"
        video_path.write_bytes(b"video")
        media.append(TweetMedia("video", "https://video.twimg.com/a.mp4", video_path))
    return TweetItem(
        text=f"body {number}",
        link=f"https://x.com/author{number}/status/{number}",
        published="2026-11-08 12:00:00",
        media=media,
        translation=f"translation {number}",
    )


def _adapter(*, raw=True, private=False):
    sender = TweetSender({"send_video_attachments": True, "merge_tweet_threshold": 0})
    sender._send_context_message = AsyncMock(return_value=SendAttempt(success=True))
    sender._send_event_chain = AsyncMock(return_value=SendAttempt(success=True))
    action = AsyncMock() if raw else None
    sender._onebot_call_action_for_umo = MagicMock(return_value=action)
    profile = PlatformProfile(
        platform_id="bot", platform_types=("aiocqhttp",), call_action=action
    )
    adapter = OneBotDeliveryAdapter(sender, profile)
    event = SimpleNamespace(
        bot=None,
        get_group_id=lambda: "" if private else "123",
        get_sender_id=lambda: "456",
    )
    return adapter, sender, action, event


async def _send(adapter, event, entry, tweets, private=False, **kwargs):
    if entry == "event":
        return await adapter.send_event(
            event, "group", "https://nitter.example", tweets, **kwargs
        )
    outcome = await adapter.send_to_umo(
        object(),
        "bot:FriendMessage:456" if private else "bot:GroupMessage:123",
        "group",
        "https://nitter.example",
        tweets,
        **kwargs,
    )
    return outcome.success


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("entry", "private", "mode"),
    [
        ("event", False, "normal"),
        ("umo", True, "author_only"),
        ("event", True, "no_text"),
        ("umo", False, "translation_only"),
    ],
)
async def test_each_tweet_has_its_own_text_and_all_images(
    tmp_path, entry, private, mode
):
    adapter, sender, action, event = _adapter(private=private)
    tweets = [_tweet(tmp_path, 1), _tweet(tmp_path, 2)]
    # More than one image must still belong to the same tweet message.
    tweets[0].media.append(tweets[1].media[0])
    media_only = mode in {"author_only", "no_text"}
    if mode == "no_text":
        sender = sender.without_media_text()
        adapter.sender = sender
    assert await _send(
        adapter,
        event,
        entry,
        tweets,
        private,
        media_only=media_only,
        hide_original_when_translated=mode == "translation_only",
        header_text="header",
    )
    assert action.await_count == 2
    for number, call in enumerate(action.call_args_list, start=1):
        assert call.args[0] == ("send_private_msg" if private else "send_group_msg")
        segments = call.kwargs["message"]
        text = "".join(s["data"]["text"] for s in segments if s["type"] == "text")
        assert len([s for s in segments if s["type"] == "image"]) == (
            2 if number == 1 else 1
        )
        assert (f"author{number}" in text) == (mode != "no_text")
        assert (f"body {number}" in text) == (mode == "normal")
        assert (f"translation {number}" in text) == (not media_only)
        assert ("12:00:00" in text) == (not media_only)
        assert f"body {3 - number}" not in text
        assert ("header" in text) == (number == 1 and mode != "no_text")
    sender._send_context_message.assert_not_awaited()
    sender._send_event_chain.assert_not_awaited()


@pytest.mark.asyncio
async def test_without_raw_action_uses_one_mixed_component_chain(tmp_path):
    adapter, sender, _action, event = _adapter(raw=False)
    assert await _send(adapter, event, "umo", [_tweet(tmp_path)])
    send = sender._send_context_message
    send.assert_awaited_once()
    chain = send.call_args.args[2].chain
    assert any(type(c).__name__ == "Plain" and "body 1" in c.text for c in chain)
    assert any(type(c).__name__ == "Image" for c in chain)


@pytest.mark.asyncio
async def test_video_stays_in_a_separate_message(tmp_path):
    adapter, _sender, action, event = _adapter()
    assert await _send(adapter, event, "event", [_tweet(tmp_path, video=True)])
    messages = [call.kwargs["message"] for call in action.call_args_list]
    assert len(messages) == 2
    assert {s["type"] for s in messages[0]} == {"text", "image"}
    assert [s["type"] for s in messages[1]] == ["video"]


@pytest.mark.asyncio
async def test_transport_retry_preserves_whole_message(tmp_path):
    adapter, _sender, action, event = _adapter()
    action.side_effect = [RuntimeError("cannot read file"), None]
    assert await _send(adapter, event, "umo", [_tweet(tmp_path)])
    first, second = [call.kwargs["message"] for call in action.call_args_list]
    assert first[:-1] == second[:-1]
    assert first[-1]["data"]["file"].startswith("file:///")
    assert second[-1]["data"]["file"].startswith("base64://")


@pytest.mark.asyncio
async def test_uncertain_delivery_never_retries_body(tmp_path):
    adapter, sender, action, event = _adapter()
    action.side_effect = TimeoutError("websocket api call timeout")
    assert await _send(adapter, event, "event", [_tweet(tmp_path)])
    action.assert_awaited_once()
    sender._send_context_message.assert_not_awaited()
    sender._send_event_chain.assert_not_awaited()


@pytest.mark.asyncio
async def test_exhausted_transport_uses_existing_split_fallback(tmp_path):
    adapter, sender, action, event = _adapter()
    action.side_effect = RuntimeError("cannot read file")
    tweet = _tweet(tmp_path)
    assert await _send(adapter, event, "umo", [tweet])
    send = sender._send_context_message
    assert send.await_count >= 2  # Text and the image failure notice.
    messages = [call.kwargs["message"] for call in action.call_args_list]
    first_split = next(
        i for i, m in enumerate(messages) if not any(s["type"] == "text" for s in m)
    )
    assert [m[-1]["data"]["file"].split(":", 1)[0] for m in messages[:first_split]] == [
        "file",
        "base64",
        "https",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("entry", "media_only", "omit_url"),
    [("event", False, False), ("umo", True, True)],
)
async def test_rejected_images_are_not_retried_or_restored_by_fallback(
    tmp_path, entry, media_only, omit_url
):
    adapter, sender, action, event = _adapter()
    action.side_effect = RuntimeError(
        "Timeout: NTEvent serviceAndMethod:NodeIKernelMsgService/sendMsg "
        "ListenerName:NodeIKernelMsgListener/onMsgInfoListUpdate"
    )
    accepted = await _send(
        adapter,
        event,
        entry,
        [_tweet(tmp_path)],
        media_only=media_only,
        omit_status_url=omit_url,
    )
    assert accepted is not media_only
    action.assert_awaited_once()
    send = (
        sender._send_event_chain if entry == "event" else sender._send_context_message
    )
    if media_only:
        send.assert_not_awaited()
    else:
        chains = [
            call.args[1 if entry == "event" else 2].chain
            for call in send.call_args_list
        ]
        assert all(type(c).__name__ == "Plain" for chain in chains for c in chain)
        notice = "".join(c.text for c in chains[-1])
        assert "图片" in notice
        assert ("https://x.com/author1/status/1" in notice) is not omit_url


@pytest.mark.asyncio
async def test_pure_media_transport_failure_cannot_restore_hidden_text(tmp_path):
    adapter, sender, action, event = _adapter()
    sender.renderer.hide_media_text = True
    action.side_effect = RuntimeError("cannot read file")
    assert not await _send(adapter, event, "umo", [_tweet(tmp_path)], media_only=True)
    for call in action.call_args_list:
        assert all(s["type"] == "image" for s in call.kwargs["message"])
    send = sender._send_context_message
    for call in send.call_args_list:
        chain = call.args[2].chain
        assert not any(getattr(c, "text", "") for c in chain)


@pytest.mark.asyncio
async def test_mixed_image_sizes_keep_each_images_encoding_limit(tmp_path):
    adapter, _sender, action, event = _adapter()
    tweet = _tweet(tmp_path)
    large = tmp_path / "large.jpg"
    large.write_bytes(b"x" * (9 * 1024 * 1024))
    tweet.media.append(
        TweetMedia("image", "https://pbs.twimg.com/media/large.jpg", large)
    )
    action.side_effect = [RuntimeError("cannot read file"), None]
    assert await _send(adapter, event, "umo", [tweet])
    retry = action.call_args.kwargs["message"]
    image_files = [s["data"]["file"] for s in retry if s["type"] == "image"]
    assert image_files[0].startswith("base64://")
    assert image_files[1] == "https://pbs.twimg.com/media/large.jpg"


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["event", "umo"])
async def test_terminal_video_failure_keeps_event_and_background_semantics(
    tmp_path, entry
):
    adapter, _sender, action, event = _adapter()
    failed = SimpleNamespace(attempt=SendAttempt(success=False, error="not supported"))
    adapter._send_event_media_item = AsyncMock(return_value=failed)
    adapter._send_umo_media_item = AsyncMock(return_value=failed)
    accepted = await _send(adapter, event, entry, [_tweet(tmp_path, video=True)])
    assert accepted is (entry == "umo")
    action.assert_awaited_once()  # The image body was delivered before video failed.


@pytest.mark.asyncio
async def test_image_attachment_switch_still_hides_images(tmp_path):
    adapter, sender, action, event = _adapter()
    sender.send_image_attachments = sender.renderer.send_image_attachments = False
    assert await _send(adapter, event, "event", [_tweet(tmp_path, video=True)])
    assert all(
        segment["type"] != "image"
        for call in action.call_args_list
        for segment in call.kwargs["message"]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("prior_success", [False, True])
async def test_rejected_image_and_failed_text_preserve_history_errors_and_ids(
    tmp_path, prior_success
):
    adapter, sender, action, _event = _adapter()
    rejection = (
        "Timeout: NTEvent serviceAndMethod:NodeIKernelMsgService/sendMsg "
        "ListenerName:NodeIKernelMsgListener/onMsgInfoListUpdate"
    )
    action.side_effect = ([None] if prior_success else []) + [RuntimeError(rejection)]
    sender._send_context_message.return_value = SendAttempt(
        success=False, error="text fallback failed"
    )
    tweets = [_tweet(tmp_path, n) for n in range(1, 3 if prior_success else 2)]
    outcome = await adapter.send_to_umo(
        object(), "bot:GroupMessage:123", "group", "https://nitter.example", tweets
    )
    assert not outcome.success
    assert outcome.error.startswith("text fallback failed")
    assert rejection in outcome.error
    assert outcome.delivery_error == outcome.error
    assert SchedulerSendMixin._delivery_history_error(outcome) == outcome.error
    expected_status = "partial_failed" if prior_success else "failed"
    assert outcome.delivery_status == expected_status
    assert SchedulerSendMixin._delivery_history_status(outcome) == expected_status
    assert outcome.delivered_status_ids == (("1",) if prior_success else ())
    assert action.await_count == len(tweets)
    if prior_success:
        assert SchedulerSendMixin._delivery_history_status_ids(outcome, tweets) == (
            "1",
        )


@pytest.mark.asyncio
async def test_terminal_body_failure_retains_previously_delivered_ids(tmp_path):
    adapter, _sender, _action, _event = _adapter()
    adapter._send_direct_image_body = AsyncMock(
        side_effect=[
            SendAttempt(success=True),
            SendAttempt(success=False, error="fatal"),
        ]
    )
    outcome = await adapter.send_to_umo(
        object(),
        "bot:GroupMessage:123",
        "group",
        "https://nitter.example",
        [_tweet(tmp_path, 1), _tweet(tmp_path, 2)],
    )
    assert not outcome.success
    assert outcome.delivery_status == "partial_failed"
    assert outcome.delivered_status_ids == ("1",)
    assert outcome.delivery_error == "fatal"
