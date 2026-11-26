"""media_only 拆分直发的部分成功语义。

视频全部送达时，图片失败不能让整批重发（否则下一轮会重复推送视频）；
但没有视频组件、图片又全部失败时没有任何媒体送达，不能算完成，
否则 scheduler 会推进 seen 导致漏推。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from delivery.default import DefaultDeliveryAdapter
from delivery.outcomes import SendAttempt
from shared import TweetItem


def _media(*, is_video: bool = True):
    """Stand-in TweetMedia. Path-only transport, so identity is all that matters."""
    return SimpleNamespace(path=None, url="", is_image=not is_video, is_video=is_video)


def _tweet(status_id: str) -> TweetItem:
    return TweetItem(
        text=f"tweet {status_id}",
        link=f"https://x.com/user/status/{status_id}",
        published="",
    )


def _adapter(*, images, videos, attempts):
    sender = SimpleNamespace(
        renderer=SimpleNamespace(
            build_direct_components=MagicMock(return_value=[]),
            build_direct_image_items=MagicMock(
                return_value=[(_media(is_video=False), c) for c in images]
            ),
            build_direct_video_items=MagicMock(
                return_value=[(_media(), c) for c in videos]
            ),
            build_video_omitted_notice_components=MagicMock(return_value=[]),
            build_image_send_failed_notice_components=MagicMock(return_value=[]),
        ),
        _send_context_message=AsyncMock(side_effect=attempts),
    )
    adapter = DefaultDeliveryAdapter(sender, SimpleNamespace())
    adapter._message_chain = MagicMock(
        side_effect=lambda components, **kwargs: components
    )
    return adapter, sender


async def _send(adapter, *, media_only: bool):
    return await adapter._send_split_direct_videos_to_umo(
        object(),
        "aiocqhttp:GroupMessage:1",
        "user",
        "instance",
        [_tweet("1")],
        media_only=media_only,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "images,videos,media_only,image_failed,expected",
    [
        pytest.param(
            ["image"],
            [],
            True,
            True,
            {"success": False, "delivery_error": "image failed"},
            id="media-only-image-failed",
        ),
        pytest.param(
            ["image"],
            ["video"],
            True,
            True,
            {
                "success": True,
                "delivery_status": "partial_failed",
                "delivery_error": "image failed",
            },
            id="video-delivered-image-failed",
        ),
        pytest.param(
            ["image"],
            [],
            False,
            True,
            {"success": True, "delivery_status": "partial_failed"},
            id="text-delivered-image-failed",
        ),
        pytest.param([], [], True, False, {"success": False}, id="empty-media-only"),
        pytest.param([], [], False, False, {"success": True}, id="empty-with-text"),
        pytest.param(
            ["image"],
            ["video"],
            True,
            False,
            {"success": True, "delivery_status": "success", "delivery_error": ""},
            id="all-media-delivered",
        ),
    ],
)
async def test_split_media_completion(
    images, videos, media_only, image_failed, expected
):
    attempts = [SendAttempt(success=True)]
    attempts.extend(
        SendAttempt(success=False, retryable=False, error="image failed")
        if image_failed
        else SendAttempt(success=True)
        for _ in images
    )
    attempts.extend(SendAttempt(success=True) for _ in videos)
    adapter, sender = _adapter(images=images, videos=videos, attempts=attempts)

    outcome = await _send(adapter, media_only=media_only)

    for field, value in expected.items():
        assert getattr(outcome, field) == value, field
    assert sender._send_context_message.await_count == len(attempts)


@pytest.mark.asyncio
async def test_event_media_only_without_any_media_component_is_not_success():
    sender = SimpleNamespace(
        renderer=SimpleNamespace(
            build_direct_components=MagicMock(return_value=[]),
            build_direct_image_items=MagicMock(return_value=[]),
            build_direct_video_items=MagicMock(return_value=[]),
            build_video_omitted_notice_components=MagicMock(return_value=[]),
            build_image_send_failed_notice_components=MagicMock(return_value=[]),
        ),
        _send_event_chain=AsyncMock(return_value=SendAttempt(success=True)),
    )
    adapter = DefaultDeliveryAdapter(sender, SimpleNamespace())
    adapter._message_chain = MagicMock(
        side_effect=lambda components, **kwargs: components
    )

    assert (
        await adapter._send_split_direct_videos_event(
            object(), "user", "instance", [_tweet("1")], media_only=True
        )
        is False
    )
    assert (
        await adapter._send_split_direct_videos_event(
            object(), "user", "instance", [_tweet("1")], media_only=False
        )
        is True
    )
