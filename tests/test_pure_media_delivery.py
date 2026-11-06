"""Pure-media delivery keeps platform routing without emitting plugin text."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from delivery import TweetSender
from shared import TweetItem, TweetMedia


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "platform", ["telegram", "qq_official", "aiocqhttp", "weixin_oc"]
)
async def test_pure_media_direct_never_sends_a_text_or_empty_chain(tmp_path, platform):
    image = tmp_path / "a.jpg"
    image.write_bytes(b"image fixture")
    sender = TweetSender(
        {"send_image_attachments": True, "send_video_attachments": True}
    ).without_media_text()
    context = SimpleNamespace(send_message=AsyncMock(return_value=True))
    tweet = TweetItem(
        text="body",
        link="https://x.com/nasa/status/1",
        published="2026-11-05",
        translation="translation",
        media=[TweetMedia("image", "https://pbs.twimg.com/media/a.jpg", image)],
    )
    outcome = await sender.send_to_umo_with_outcome(
        context,
        f"{platform}:GroupMessage:1",
        "nasa",
        "",
        [tweet],
        media_only=True,
        header_text="header",
        batch_summary="summary",
    )
    assert outcome.success
    assert context.send_message.await_count == 1
    for call in context.send_message.await_args_list:
        components = call.args[1].chain
        assert components
        assert all(
            "image" in type(component).__name__.lower() for component in components
        )


@pytest.mark.asyncio
async def test_pure_media_send_failure_does_not_fall_back_to_text(tmp_path):
    image = tmp_path / "a.jpg"
    image.write_bytes(b"image fixture")
    sender = TweetSender({"send_image_attachments": True}).without_media_text()
    context = SimpleNamespace(send_message=AsyncMock(return_value=False))
    tweet = TweetItem(
        text="body",
        link="https://x.com/nasa/status/1",
        published="",
        media=[TweetMedia("image", "https://pbs.twimg.com/media/a.jpg", image)],
    )
    outcome = await sender.send_to_umo_with_outcome(
        context, "telegram:GroupMessage:1", "nasa", "", [tweet], media_only=True
    )
    assert not outcome.success
    assert context.send_message.await_count
    assert all(
        call.args[1].chain and all(not hasattr(c, "text") for c in call.args[1].chain)
        for call in context.send_message.await_args_list
    )
