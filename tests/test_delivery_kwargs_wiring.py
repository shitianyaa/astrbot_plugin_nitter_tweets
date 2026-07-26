# -*- coding: utf-8 -*-
"""Delivery-layer contracts for omit / hide / link_style wiring."""
from __future__ import annotations

import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import delivery.lark as lark_module
from delivery.default import DefaultDeliveryAdapter
from delivery.lark import LarkDeliveryAdapter
from delivery.lark_support import LarkSendAttempt
from delivery.outcomes import MergedSendOutcome, SendAttempt, SendOutcome
from delivery.sender import TweetSender
from shared import TweetItem


def _tweet(status_id: str) -> TweetItem:
    return TweetItem(
        text=f"tweet {status_id}",
        link=f"https://x.com/user/status/{status_id}",
        published="",
    )


def _lark_adapter() -> tuple[LarkDeliveryAdapter, SimpleNamespace]:
    renderer = SimpleNamespace(build_direct_components=MagicMock(return_value=[]))
    sender = SimpleNamespace(
        renderer=renderer,
        _platform_inst_from_context=MagicMock(return_value=None),
        _is_uncertain_delivery_error=MagicMock(return_value=False),
        _log_uncertain_delivery=MagicMock(),
        _send_event_chain=AsyncMock(),
        _send_context_message=AsyncMock(),
        _send_default_direct_event=AsyncMock(return_value=True),
        _send_default_direct_to_umo=AsyncMock(
            return_value=SendOutcome(success=True)
        ),
        UNCERTAIN_DELIVERY_WARNING="uncertain",
    )
    adapter = LarkDeliveryAdapter(sender, SimpleNamespace())
    return adapter, sender


def _patch_lark_manual_target(monkeypatch) -> None:
    monkeypatch.setattr(lark_module, "lark_client_from_event", lambda *args: object())
    monkeypatch.setattr(lark_module, "lark_reply_message_id", lambda event: "")
    monkeypatch.setattr(
        lark_module,
        "lark_event_target",
        lambda event: ("chat_id", "chat-1"),
    )
    monkeypatch.setattr(lark_module, "plain_text_from_components", lambda value: "text")
    monkeypatch.setattr(lark_module, "video_components", lambda value: ["video"])
    monkeypatch.setattr(lark_module, "media_components", lambda value: ["media"])


def test_default_and_lark_accept_hide_kwarg():
    for cls in (DefaultDeliveryAdapter, LarkDeliveryAdapter):
        for name in ("send_event", "send_to_umo"):
            sig = inspect.signature(getattr(cls, name))
            assert "hide_original_when_translated" in sig.parameters
            assert "link_style" in sig.parameters
            assert "omit_status_url" in sig.parameters


@pytest.mark.asyncio
async def test_default_adapter_applies_link_style_to_message_chain(monkeypatch):
    attempt = SimpleNamespace(
        success=True,
        uncertain=False,
        retryable=False,
        error="",
        warning="",
    )
    sender = SimpleNamespace(
        send_video_attachments=False,
        send_image_attachments=False,
        renderer=SimpleNamespace(
            build_direct_components=MagicMock(return_value=[]),
        ),
        _send_event_chain=AsyncMock(return_value=attempt),
        _send_context_message=AsyncMock(return_value=attempt),
    )
    adapter = DefaultDeliveryAdapter(sender, SimpleNamespace())
    applied_styles: list[str] = []

    def capture_chain(components, *, link_style="plain"):
        applied_styles.append(link_style)
        return components

    monkeypatch.setattr(adapter, "_message_chain", capture_chain)

    assert await adapter.send_event(
        object(),
        "user",
        "instance",
        [_tweet("1")],
        link_style="telegram_md",
    )
    outcome = await adapter.send_to_umo(
        object(),
        "telegram:GroupMessage:1",
        "user",
        "instance",
        [_tweet("2")],
        link_style="telegram_md",
    )

    assert outcome.success is True
    assert applied_styles == ["telegram_md", "telegram_md"]


@pytest.mark.asyncio
async def test_default_scheduled_media_only_plain_fallback_stays_failed():
    sender = SimpleNamespace(
        send_video_attachments=False,
        send_image_attachments=False,
        renderer=SimpleNamespace(
            build_direct_components=MagicMock(return_value=[]),
            format_plain=MagicMock(return_value="@user"),
        ),
        _send_context_message=AsyncMock(
            side_effect=[
                SendAttempt(success=False, retryable=True, error="media failed"),
                SendAttempt(success=True),
            ]
        ),
        _has_attached_videos=MagicMock(return_value=False),
    )
    adapter = DefaultDeliveryAdapter(sender, SimpleNamespace())

    outcome = await adapter.send_to_umo(
        object(),
        "telegram:GroupMessage:1",
        "user",
        "instance",
        [_tweet("1")],
        media_only=True,
    )

    assert outcome.success is False
    assert outcome.delivery_status == "failed"
    assert outcome.delivery_error == "media failed"
    assert sender._send_context_message.await_count == 1


@pytest.mark.asyncio
async def test_default_media_only_skips_no_video_retry():
    sender = SimpleNamespace(
        send_video_attachments=True,
        send_image_attachments=False,
        renderer=SimpleNamespace(
            build_direct_components=MagicMock(return_value=[]),
        ),
        _send_context_message=AsyncMock(
            return_value=SendAttempt(
                success=False,
                retryable=True,
                error="media failed",
            )
        ),
        _has_attached_videos=MagicMock(return_value=True),
    )
    adapter = DefaultDeliveryAdapter(sender, SimpleNamespace())

    outcome = await adapter.send_to_umo(
        object(),
        "telegram:GroupMessage:1",
        "user",
        "instance",
        [_tweet("1")],
        media_only=True,
    )

    assert outcome.success is False
    assert outcome.delivery_status == "failed"
    assert outcome.delivery_error == "media failed"
    assert sender._send_context_message.await_count == 1


@pytest.mark.asyncio
async def test_default_split_media_only_uncertain_header_still_sends_video():
    sender = SimpleNamespace(
        renderer=SimpleNamespace(
            build_direct_components=MagicMock(return_value=[]),
            build_direct_image_components=MagicMock(return_value=[]),
            build_direct_video_components=MagicMock(return_value=["video"]),
            build_video_omitted_notice_components=MagicMock(return_value=[]),
        ),
        _send_context_message=AsyncMock(
            side_effect=[
                SendAttempt(
                    success=False,
                    retryable=False,
                    uncertain=True,
                    warning="header uncertain",
                ),
                SendAttempt(success=False, retryable=False, error="video failed"),
            ]
        ),
    )
    adapter = DefaultDeliveryAdapter(sender, SimpleNamespace())
    adapter._message_chain = MagicMock(side_effect=lambda components, **kwargs: components)

    outcome = await adapter._send_split_direct_videos_to_umo(
        object(),
        "aiocqhttp:GroupMessage:1",
        "user",
        "instance",
        [_tweet("1")],
        media_only=True,
    )

    assert outcome.success is False
    assert outcome.delivery_error == "video failed"
    assert sender._send_context_message.await_count == 2


@pytest.mark.asyncio
async def test_default_manual_media_only_uncertain_header_still_sends_video():
    sender = SimpleNamespace(
        renderer=SimpleNamespace(
            build_direct_components=MagicMock(return_value=[]),
            build_direct_image_components=MagicMock(return_value=[]),
            build_direct_video_components=MagicMock(return_value=["video"]),
            build_video_omitted_notice_components=MagicMock(return_value=[]),
        ),
        _send_event_chain=AsyncMock(
            side_effect=[
                SendAttempt(
                    success=False,
                    retryable=False,
                    uncertain=True,
                ),
                SendAttempt(success=False, retryable=False, error="video failed"),
            ]
        ),
    )
    adapter = DefaultDeliveryAdapter(sender, SimpleNamespace())
    adapter._message_chain = MagicMock(side_effect=lambda components, **kwargs: components)

    accepted = await adapter._send_split_direct_videos_event(
        object(),
        "user",
        "instance",
        [_tweet("1")],
        media_only=True,
    )

    assert accepted is False
    assert sender._send_event_chain.await_count == 2


def test_send_to_umo_with_outcome_uses_keyword_flags_not_positional_shift():
    """Regression: link_style must not bind into hide_original slot."""
    sender = TweetSender.__new__(TweetSender)
    sender.resolve_link_style = MagicMock(return_value="telegram_md")

    adapter = MagicMock()
    adapter.name = "telegram"
    adapter.supports_merged_forward = False
    captured = {}

    async def fake_direct(*args, **kwargs):
        # production still passes leading positionals (context/umo/...)
        captured["args_len"]=len(args)
        captured.update(kwargs)
        from delivery.outcomes import SendOutcome

        return SendOutcome(success=True)

    sender._delivery_adapter_for_umo = MagicMock(return_value=adapter)
    sender._should_use_merge_for_count = MagicMock(return_value=False)
    sender._send_direct_to_umo = AsyncMock(side_effect=fake_direct)

    import asyncio

    async def run():
        return await sender.send_to_umo_with_outcome(
            context=object(),
            umo="telegram:FriendMessage:1",
            username="nasa",
            instance="https://nitter.example",
            tweets=[],
            media_only=False,
            omit_status_url=False,
            hide_original_when_translated=True,
            link_style="telegram_md",
        )

    asyncio.run(run())

    # AsyncMock records kwargs of last call
    kwargs = sender._send_direct_to_umo.await_args.kwargs
    assert kwargs.get("link_style") == "telegram_md"
    assert kwargs.get("hide_original_when_translated") is True
    assert kwargs.get("omit_status_url") is False
    # must not be positional-only mess: hide must be bool not str
    assert isinstance(kwargs.get("hide_original_when_translated"), bool)


def test_send_to_umo_wrapper_forwards_hide_and_link():
    sender = TweetSender.__new__(TweetSender)
    captured = {}

    async def fake_outcome(*args, **kwargs):
        captured.update(kwargs)
        from delivery.outcomes import SendOutcome

        return SendOutcome(success=True)

    sender.send_to_umo_with_outcome = AsyncMock(side_effect=fake_outcome)

    import asyncio

    async def run():
        return await sender.send_to_umo(
            context=object(),
            umo="x:y:z",
            username="u",
            instance="i",
            tweets=[],
            omit_status_url=False,
            hide_original_when_translated=True,
            link_style="telegram_md",
        )

    assert asyncio.run(run()) is True
    kwargs = sender.send_to_umo_with_outcome.await_args.kwargs
    assert kwargs["hide_original_when_translated"] is True
    assert kwargs["link_style"] == "telegram_md"
    assert kwargs["omit_status_url"] is False


@pytest.mark.asyncio
async def test_lark_manual_post_media_failure_does_not_trigger_plain_fallback(
    monkeypatch,
):
    adapter, sender = _lark_adapter()
    _patch_lark_manual_target(monkeypatch)
    monkeypatch.setattr(
        lark_module,
        "send_lark_post",
        AsyncMock(return_value=LarkSendAttempt(success=True)),
    )
    monkeypatch.setattr(
        lark_module,
        "send_lark_event_media_with_retry",
        AsyncMock(return_value=LarkSendAttempt(success=False, error="media failed")),
    )

    accepted = await adapter.send_event(object(), "user", "instance", [_tweet("1")])

    assert accepted is True
    sender._send_default_direct_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_lark_manual_media_only_uncertain_post_still_sends_video(monkeypatch):
    adapter, sender = _lark_adapter()
    sender.renderer.build_direct_components.return_value = ["video"]
    _patch_lark_manual_target(monkeypatch)
    monkeypatch.setattr(
        lark_module,
        "send_lark_post",
        AsyncMock(
            return_value=LarkSendAttempt(
                success=False,
                uncertain=True,
                warning="post uncertain",
            )
        ),
    )
    media_send = AsyncMock(
        return_value=LarkSendAttempt(success=False, error="video failed")
    )
    monkeypatch.setattr(lark_module, "send_lark_event_media_with_retry", media_send)

    accepted = await adapter.send_event(
        object(),
        "user",
        "instance",
        [_tweet("1")],
        media_only=True,
    )

    assert accepted is False
    media_send.assert_awaited_once()
    sender._send_default_direct_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_lark_manual_media_only_uncertain_post_accepts_sent_video(monkeypatch):
    adapter, sender = _lark_adapter()
    sender.renderer.build_direct_components.return_value = ["video"]
    _patch_lark_manual_target(monkeypatch)
    monkeypatch.setattr(
        lark_module,
        "send_lark_post",
        AsyncMock(
            return_value=LarkSendAttempt(
                success=False,
                uncertain=True,
                warning="post uncertain",
            )
        ),
    )
    media_send = AsyncMock(return_value=LarkSendAttempt(success=True))
    monkeypatch.setattr(lark_module, "send_lark_event_media_with_retry", media_send)

    accepted = await adapter.send_event(
        object(),
        "user",
        "instance",
        [_tweet("1")],
        media_only=True,
    )

    assert accepted is True
    media_send.assert_awaited_once()


@pytest.mark.asyncio
async def test_lark_manual_text_media_failure_does_not_duplicate_text(monkeypatch):
    adapter, sender = _lark_adapter()
    _patch_lark_manual_target(monkeypatch)
    monkeypatch.setattr(
        lark_module,
        "send_lark_post",
        AsyncMock(return_value=LarkSendAttempt(success=False, error="post failed")),
    )
    monkeypatch.setattr(
        lark_module,
        "send_lark_text",
        AsyncMock(return_value=LarkSendAttempt(success=True)),
    )
    monkeypatch.setattr(
        lark_module,
        "send_lark_event_media_with_retry",
        AsyncMock(return_value=LarkSendAttempt(success=False, error="media failed")),
    )

    accepted = await adapter.send_event(object(), "user", "instance", [_tweet("1")])

    assert accepted is True
    sender._send_default_direct_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_lark_scheduled_media_failure_keeps_delivered_text_complete(monkeypatch):
    adapter, _sender = _lark_adapter()
    monkeypatch.setattr(
        lark_module,
        "lark_client_and_target",
        lambda *args: (object(), "chat_id", "chat-1"),
    )
    monkeypatch.setattr(lark_module, "plain_text_from_components", lambda value: "text")
    monkeypatch.setattr(lark_module, "video_components", lambda value: ["video"])
    monkeypatch.setattr(
        lark_module,
        "send_lark_post",
        AsyncMock(return_value=LarkSendAttempt(success=True)),
    )
    monkeypatch.setattr(
        lark_module,
        "send_lark_umo_media_with_retry",
        AsyncMock(return_value=LarkSendAttempt(success=False, error="media failed")),
    )

    outcome = await adapter.send_to_umo(
        object(),
        "lark:GroupMessage:chat-1",
        "user",
        "instance",
        [_tweet("1")],
    )

    assert outcome.success is True
    assert outcome.delivery_status == "partial_failed"
    assert outcome.error == "media failed"


@pytest.mark.asyncio
async def test_lark_scheduled_media_only_failure_stays_retryable(monkeypatch):
    adapter, _sender = _lark_adapter()
    monkeypatch.setattr(
        lark_module,
        "lark_client_and_target",
        lambda *args: (object(), "chat_id", "chat-1"),
    )
    monkeypatch.setattr(lark_module, "plain_text_from_components", lambda value: "@user")
    monkeypatch.setattr(lark_module, "video_components", lambda value: ["video"])
    monkeypatch.setattr(
        lark_module,
        "send_lark_post",
        AsyncMock(return_value=LarkSendAttempt(success=True)),
    )
    monkeypatch.setattr(
        lark_module,
        "send_lark_umo_media_with_retry",
        AsyncMock(return_value=LarkSendAttempt(success=False, error="media failed")),
    )

    outcome = await adapter.send_to_umo(
        object(),
        "lark:GroupMessage:chat-1",
        "user",
        "instance",
        [_tweet("1")],
        media_only=True,
    )

    assert outcome.success is False
    assert outcome.delivery_status == "partial_failed"
    assert outcome.error == "media failed"


@pytest.mark.asyncio
async def test_lark_media_only_uncertain_post_still_sends_video(monkeypatch):
    adapter, sender = _lark_adapter()
    sender.renderer.build_direct_components.return_value = ["video"]
    monkeypatch.setattr(
        lark_module,
        "lark_client_and_target",
        lambda *args: (object(), "chat_id", "chat-1"),
    )
    monkeypatch.setattr(lark_module, "plain_text_from_components", lambda value: "@user")
    monkeypatch.setattr(lark_module, "video_components", lambda value: ["video"])
    monkeypatch.setattr(
        lark_module,
        "send_lark_post",
        AsyncMock(
            return_value=LarkSendAttempt(
                success=False,
                uncertain=True,
                warning="post uncertain",
            )
        ),
    )
    media_send = AsyncMock(
        return_value=LarkSendAttempt(success=False, error="video failed")
    )
    monkeypatch.setattr(lark_module, "send_lark_umo_media_with_retry", media_send)

    outcome = await adapter.send_to_umo(
        object(),
        "lark:GroupMessage:chat-1",
        "user",
        "instance",
        [_tweet("1")],
        media_only=True,
    )

    assert outcome.success is False
    assert outcome.delivery_error == "video failed"
    media_send.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_merged_to_umo_resolves_telegram_link_style():
    sender = TweetSender.__new__(TweetSender)
    adapter = SimpleNamespace(name="telegram", supports_merged_forward=False)
    sender._delivery_adapter_for_umo = MagicMock(return_value=adapter)
    sender._should_use_merge_for_count = MagicMock(return_value=False)
    sender._send_merged_direct_to_umo = AsyncMock(
        return_value=MergedSendOutcome(success=True, mode="direct_message")
    )

    await sender.send_merged_to_umo(
        object(),
        "telegram:GroupMessage:1",
        [("user", "instance", [_tweet("1")])],
    )

    assert sender._send_merged_direct_to_umo.await_args.kwargs["link_style"] == (
        "telegram_md"
    )
