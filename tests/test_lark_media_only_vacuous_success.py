"""media_only 下 Lark 不得在“一条媒体都没发”时判定完成。

`send_lark_post` 在没有可渲染内容时、`send_media_with_video_retry` 在组件列表为空时，
都会返回 `success=True`。若直接据此判定 media_only 完成，定时路径会推进 seen，
把这条推文永久丢掉。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import delivery.lark as lark_module
from delivery.lark import LarkDeliveryAdapter
from delivery.lark_support import LarkSendAttempt
from delivery.outcomes import SendOutcome
from shared import TweetItem


def _tweet(status_id: str = "1") -> TweetItem:
    return TweetItem(
        text=f"tweet {status_id}",
        link=f"https://x.com/user/status/{status_id}",
        published="",
    )


def _adapter() -> LarkDeliveryAdapter:
    sender = SimpleNamespace(
        renderer=SimpleNamespace(build_direct_components=MagicMock(return_value=[])),
        _platform_inst_from_context=MagicMock(return_value=None),
        _is_uncertain_delivery_error=MagicMock(return_value=False),
        _log_uncertain_delivery=MagicMock(),
        _send_event_chain=AsyncMock(),
        _send_context_message=AsyncMock(),
        _send_default_direct_event=AsyncMock(return_value=True),
        _send_default_direct_to_umo=AsyncMock(return_value=SendOutcome(success=True)),
        UNCERTAIN_DELIVERY_WARNING="uncertain",
    )
    return LarkDeliveryAdapter(sender, SimpleNamespace())


def _patch_umo(monkeypatch, *, media, post_ok=True) -> None:
    monkeypatch.setattr(
        lark_module,
        "lark_client_and_target",
        lambda *args: (object(), "chat_id", "chat-1"),
    )
    monkeypatch.setattr(
        lark_module, "plain_text_from_components", lambda value: "@user"
    )
    monkeypatch.setattr(lark_module, "video_components", lambda value: [])
    monkeypatch.setattr(lark_module, "media_components", lambda value: list(media))
    monkeypatch.setattr(
        lark_module,
        "send_lark_post",
        AsyncMock(
            return_value=LarkSendAttempt(
                success=post_ok, error="" if post_ok else "post failed"
            )
        ),
    )
    monkeypatch.setattr(
        lark_module,
        "send_lark_text",
        AsyncMock(return_value=LarkSendAttempt(success=True)),
    )
    # 空列表时真实实现返回 success=True，这里如实模拟。
    monkeypatch.setattr(
        lark_module,
        "send_lark_umo_media_with_retry",
        AsyncMock(return_value=LarkSendAttempt(success=True)),
    )


async def _send(adapter, *, media_only: bool):
    return await adapter.send_to_umo(
        object(),
        "lark:GroupMessage:chat-1",
        "user",
        "instance",
        [_tweet()],
        media_only=media_only,
    )


@pytest.mark.asyncio
async def test_scheduled_media_only_without_any_media_is_not_success(monkeypatch):
    adapter = _adapter()
    _patch_umo(monkeypatch, media=[])

    outcome = await _send(adapter, media_only=True)

    assert outcome.success is False


@pytest.mark.asyncio
async def test_scheduled_media_only_with_media_stays_success(monkeypatch):
    adapter = _adapter()
    _patch_umo(monkeypatch, media=["image"])

    outcome = await _send(adapter, media_only=True)

    assert outcome.success is True


@pytest.mark.asyncio
async def test_scheduled_plain_mode_without_media_stays_success(monkeypatch):
    adapter = _adapter()
    _patch_umo(monkeypatch, media=[])

    outcome = await _send(adapter, media_only=False)

    assert outcome.success is True


@pytest.mark.asyncio
async def test_scheduled_fallback_media_only_without_media_is_not_success(monkeypatch):
    adapter = _adapter()
    _patch_umo(monkeypatch, media=[], post_ok=False)

    outcome = await _send(adapter, media_only=True)

    assert outcome.success is False


@pytest.mark.asyncio
async def test_scheduled_fallback_media_only_with_media_stays_success(monkeypatch):
    adapter = _adapter()
    _patch_umo(monkeypatch, media=["image"], post_ok=False)

    outcome = await _send(adapter, media_only=True)

    assert outcome.success is True
