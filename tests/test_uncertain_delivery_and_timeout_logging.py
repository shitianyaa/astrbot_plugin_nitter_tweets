from __future__ import annotations

from unittest.mock import patch

import pytest

from delivery.sender import TweetSender
from media_support.service import MediaService, TweetMedia
from shared import TweetItem


def test_uncertain_delivery_warning_constant():
    assert "media_quality" in TweetSender.UNCERTAIN_DELIVERY_WARNING
    assert "media_max_size_mb" in TweetSender.UNCERTAIN_DELIVERY_WARNING


def test_log_uncertain_delivery_with_timeout_logs_tuning_advice():
    with patch("delivery.sender.logger.warning") as mock_warn:
        TweetSender._log_uncertain_delivery(
            label="test",
            target="target:1",
            exc=TimeoutError("websocket api call timeout"),
        )
        assert mock_warn.called
        msg = mock_warn.call_args[0][0]
        assert "大文件/视频发送超时" in msg
        assert "media_quality" in msg
        assert "media_max_size_mb" in msg


def test_log_uncertain_delivery_without_timeout_omits_advice():
    with patch("delivery.sender.logger.warning") as mock_warn:
        TweetSender._log_uncertain_delivery(
            label="test",
            target="target:1",
            exc=RuntimeError("something else"),
        )
        assert mock_warn.called
        msg = mock_warn.call_args[0][0]
        assert "大文件/视频发送超时" not in msg


def test_log_uncertain_delivery_none_exc():
    with patch("delivery.sender.logger.warning") as mock_warn:
        TweetSender._log_uncertain_delivery(label="test", target="target:1", exc=None)
        assert mock_warn.called
        msg = mock_warn.call_args[0][0]
        assert "大文件/视频发送超时" not in msg


def test_handle_send_exception_uncertain():
    sender = TweetSender()
    attempt = sender._send_exception_attempt(
        TimeoutError("timed out"), label="test", target="target:1"
    )
    assert attempt.uncertain is True
    assert attempt.retryable is False
    assert attempt.warning == TweetSender.UNCERTAIN_DELIVERY_WARNING


@pytest.mark.asyncio
async def test_media_download_video_timeout_logs_tuning_advice():
    service = MediaService({"send_video_attachments": True})
    tweet = TweetItem(text="hi", link="https://x.com/user/status/123", published="")
    video_media = TweetMedia(kind="video", url="https://video.twimg.com/vid.mp4")
    tweet.media = [video_media]

    with patch.object(
        service,
        "_download_media_path",
        side_effect=TimeoutError("The read operation timed out"),
    ):
        with patch("media_support.service.logger.warning") as mock_warn:
            downloaded, _ = await service._resolve_and_download_with_status(tweet)
            assert downloaded == []
            assert mock_warn.called
            warn_calls = [call[0][0] for call in mock_warn.call_args_list]
            found = any(
                "若因视频过大或下载超时" in msg and "media_quality" in msg
                for msg in warn_calls
            )
            assert found, f"Expected tuning advice in warnings, got: {warn_calls}"


@pytest.mark.asyncio
async def test_media_download_image_timeout_does_not_log_video_advice():
    service = MediaService({"send_image_attachments": True})
    tweet = TweetItem(text="hi", link="https://x.com/user/status/123", published="")
    image_media = TweetMedia(kind="image", url="https://pbs.twimg.com/pic.jpg")
    tweet.media = [image_media]

    with patch.object(
        service,
        "_download_media_path",
        side_effect=TimeoutError("The read operation timed out"),
    ):
        with patch("media_support.service.logger.warning") as mock_warn:
            downloaded, _ = await service._resolve_and_download_with_status(tweet)
            assert downloaded == []
            assert mock_warn.called
            warn_calls = [call[0][0] for call in mock_warn.call_args_list]
            found = any("若因视频过大或下载超时" in msg for msg in warn_calls)
            assert not found, f"Did not expect video advice for image: {warn_calls}"


def test_download_with_retries_video_timeout_warning():
    service = MediaService({})
    video_media = TweetMedia(kind="video", url="https://video.twimg.com/vid.mp4")

    with (
        patch.object(
            service,
            "_download",
            side_effect=TimeoutError("The read operation timed out"),
        ) as download,
        patch("media_support.service.time.sleep") as sleep,
        patch("media_support.service.logger.warning") as mock_warn,
    ):
        with pytest.raises(TimeoutError):
            service._download_with_retries(video_media)
        assert download.call_count == service.download_retry_attempts
        assert [call.args for call in sleep.call_args_list] == [
            (service.download_retry_delay_seconds,)
        ] * (service.download_retry_attempts - 1)
        warn_calls = [call.args[0] for call in mock_warn.call_args_list]
        assert any(
            "若因视频过大或下载超时" in msg and "media_quality" in msg
            for msg in warn_calls
        ), warn_calls
