"""发送被拒 vs 下载失败：分类、不重试、事后提示。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from delivery.default import DefaultDeliveryAdapter
from delivery.outcomes import SendAttempt
from delivery.sender import TweetSender
from rendering.tweets import TweetMessageRenderer
from shared.utils import TweetItem, TweetMedia

NTEVENT_TIMEOUT = (
    "Timeout: NTEvent serviceAndMethod:NodeIKernelMsgService/sendMsg "
    "ListenerName:NodeIKernelMsgListener/onMsgInfoListUpdate EventRet:\n"
    '{\n    "result": 0,\n    "errMsg": ""\n}\n'
)


class _FakeActionFailed(Exception):
    def __init__(self, retcode=1200, message=""):
        self.retcode = retcode
        self.message = message
        super().__init__(message)


def test_ntevent_timeout_is_content_rejected():
    assert TweetSender._is_content_rejected_error(
        _FakeActionFailed(1200, NTEVENT_TIMEOUT)
    )


def test_res_id_failure_is_content_rejected():
    assert TweetSender._is_content_rejected_error(
        _FakeActionFailed(1200, "发送转发消息（res_id：abc 失败")
    )


def test_enoent_is_not_content_rejected():
    # 本地文件读不到是传输问题，必须放行无损编码梯度重试。
    assert not TweetSender._is_content_rejected_error(
        _FakeActionFailed(
            1200,
            "Error: ENOENT: no such file or directory, copyfile '/a.jpg' -> '/b.jpg'",
        )
    )


def test_ordinary_failure_is_not_content_rejected():
    assert not TweetSender._is_content_rejected_error(Exception("connection reset"))
    assert not TweetSender._is_content_rejected_error(None)


def test_rejected_attempt_is_not_retryable():
    sender = TweetSender.__new__(TweetSender)
    attempt = sender._send_exception_attempt(
        _FakeActionFailed(1200, NTEVENT_TIMEOUT), "img", "group:1"
    )
    assert attempt.success is False
    assert attempt.rejected is True
    # retryable=False 同时让 sender_transport 的编码梯度停手。
    assert attempt.retryable is False


def test_plain_failure_stays_retryable():
    sender = TweetSender.__new__(TweetSender)
    attempt = sender._send_exception_attempt(Exception("boom"), "img", "group:1")
    assert attempt.rejected is False
    assert attempt.retryable is True


def _tweet_with_image() -> TweetItem:
    tweet = TweetItem(
        text="hi",
        link="https://x.com/nasa/status/5",
        published="",
    )
    media = TweetMedia(kind="image", url="https://pbs.twimg.com/media/a.jpg")
    media.path = "/tmp/a.jpg"
    tweet.media = [media]
    return tweet


def test_notice_mentions_risk_control_and_keeps_link():
    renderer = TweetMessageRenderer()
    comps = renderer.build_image_send_failed_notice_components(
        [_tweet_with_image()], rejected=True, omit_status_url=False
    )
    text = getattr(comps[0], "text", "")
    assert "风控" in text
    assert "https://x.com/nasa/status/5" in text


def test_notice_respects_omit_status_url():
    # 与 video_not_sent_notice 一致：该配置的用途就是不放推文 URL 明文。
    renderer = TweetMessageRenderer()
    comps = renderer.build_image_send_failed_notice_components(
        [_tweet_with_image()], rejected=True, omit_status_url=True
    )
    text = getattr(comps[0], "text", "")
    assert "风控" in text
    assert "http" not in text


def test_notice_without_reject_signature_avoids_risk_control_wording():
    renderer = TweetMessageRenderer()
    comps = renderer.build_image_send_failed_notice_components(
        [_tweet_with_image()], rejected=False
    )
    text = getattr(comps[0], "text", "")
    assert "图片发送失败" in text
    assert "风控" not in text


def test_notice_empty_without_downloaded_image():
    renderer = TweetMessageRenderer()
    tweet = TweetItem(text="hi", link="https://x.com/nasa/status/5", published="")
    assert renderer.build_image_send_failed_notice_components([tweet]) == []


def _adapter(attempts):
    sender = SimpleNamespace(
        renderer=SimpleNamespace(
            build_direct_components=MagicMock(return_value=[]),
            build_direct_image_items=MagicMock(
                return_value=[(SimpleNamespace(path=None, url=""), "image")]
            ),
            build_direct_video_items=MagicMock(return_value=[]),
            build_video_omitted_notice_components=MagicMock(return_value=[]),
            build_image_send_failed_notice_components=MagicMock(
                return_value=["NOTICE"]
            ),
        ),
        _send_context_message=AsyncMock(side_effect=attempts),
    )
    adapter = DefaultDeliveryAdapter(sender, SimpleNamespace())
    adapter._message_chain = MagicMock(side_effect=lambda components, **kw: components)
    return adapter, sender


@pytest.mark.asyncio
async def test_scheduled_image_rejection_sends_notice_with_flag():
    adapter, sender = _adapter(
        [
            SendAttempt(success=True),
            SendAttempt(success=False, retryable=False, rejected=True, error="blocked"),
            SendAttempt(success=True),
        ]
    )

    await adapter._send_split_direct_videos_to_umo(
        object(),
        "aiocqhttp:GroupMessage:1",
        "user",
        "instance",
        [_tweet_with_image()],
        media_only=False,
    )

    builder = sender.renderer.build_image_send_failed_notice_components
    builder.assert_called_once()
    assert builder.call_args.kwargs.get("rejected") is True
    # 正文 + 图片 + 提示
    assert sender._send_context_message.await_count == 3


@pytest.mark.asyncio
async def test_media_only_skips_notice_because_batch_is_retried():
    adapter, sender = _adapter(
        [
            SendAttempt(success=True),
            SendAttempt(success=False, retryable=False, rejected=True, error="blocked"),
        ]
    )

    await adapter._send_split_direct_videos_to_umo(
        object(),
        "aiocqhttp:GroupMessage:1",
        "user",
        "instance",
        [_tweet_with_image()],
        media_only=True,
    )

    sender.renderer.build_image_send_failed_notice_components.assert_not_called()
    assert sender._send_context_message.await_count == 2


@pytest.mark.asyncio
async def test_successful_image_sends_no_notice():
    adapter, sender = _adapter([SendAttempt(success=True), SendAttempt(success=True)])

    await adapter._send_split_direct_videos_to_umo(
        object(),
        "aiocqhttp:GroupMessage:1",
        "user",
        "instance",
        [_tweet_with_image()],
        media_only=False,
    )

    sender.renderer.build_image_send_failed_notice_components.assert_not_called()
