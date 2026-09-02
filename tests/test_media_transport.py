"""媒体传输编码梯度。

核心不变量：传输降级是**无损的**（同一份媒体换一种线上编码），内容降级是**有损的**
（丢视频、退纯文本）。所以路径档失败时必须先换编码重试，视频不该被丢、也不该退纯文本。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from delivery.default import DefaultDeliveryAdapter
from delivery.media_transport import (
    MediaEncoding,
    MediaTransportPolicy,
    TransportConfig,
    TransportMemo,
    apply_memo,
    is_backend_fetchable_url,
    onebot_segment,
)
from delivery.onebot import OneBotDeliveryAdapter
from delivery.outcomes import SendAttempt
from delivery.platforms import PlatformProfile
from delivery.sender import TweetSender
from shared import TweetItem, TweetMedia

TWIMG_VIDEO = "https://video.twimg.com/ext_tw_video/1/vid/1280x720/abc.mp4"
TWIMG_IMAGE = "https://pbs.twimg.com/media/abc.jpg"
XDOWN_VIDEO = "https://xdown.app/download?token=abc123"


def _write(tmp_path: Path, name: str, size: int) -> Path:
    path = tmp_path / name
    path.write_bytes(b"x" * size)
    return path


def _image(tmp_path: Path, size: int = 1024, url: str = TWIMG_IMAGE) -> TweetMedia:
    return TweetMedia(kind="image", url=url, path=_write(tmp_path, "a.jpg", size))


def _video(tmp_path: Path, size: int = 1024, url: str = TWIMG_VIDEO) -> TweetMedia:
    return TweetMedia(kind="video", url=url, path=_write(tmp_path, "a.mp4", size))


def _policy(**config) -> MediaTransportPolicy:
    return MediaTransportPolicy(TransportConfig(**config))


def _onebot_profile() -> PlatformProfile:
    return PlatformProfile(
        platform_id="aiocqhttp",
        message_type="GroupMessage",
        session_id="1",
        platform_types=("aiocqhttp",),
        call_action=AsyncMock(),
    )


# ---------------------------------------------------------------------------
# 梯度组成
# ---------------------------------------------------------------------------


def test_small_image_ladder_is_path_then_base64(tmp_path):
    ladder = _policy().ladder_for(_image(tmp_path))
    assert ladder == (MediaEncoding.PATH, MediaEncoding.BASE64)


def test_large_image_drops_base64_rung(tmp_path):
    # 上限 1MB，图片 2MB：base64 档不该出现。
    policy = _policy(base64_max_bytes=1024 * 1024)
    ladder = policy.ladder_for(_image(tmp_path, size=2 * 1024 * 1024))
    assert ladder == (MediaEncoding.PATH,)


def test_small_video_gets_base64_and_skip(tmp_path):
    ladder = _policy().ladder_for(_video(tmp_path))
    assert ladder == (MediaEncoding.PATH, MediaEncoding.BASE64, MediaEncoding.SKIP)


def test_large_video_never_offers_base64(tmp_path):
    """默认 8MB 上限把视频挡在 base64 之外，只剩路径和放弃。"""
    ladder = _policy().ladder_for(_video(tmp_path, size=9 * 1024 * 1024))
    assert ladder == (MediaEncoding.PATH, MediaEncoding.SKIP)


def test_image_never_gets_skip_rung(tmp_path):
    """图片没有对应的省略提示文案，失败交给既有的内容降级链。"""
    assert MediaEncoding.SKIP not in _policy().ladder_for(_image(tmp_path))


def test_base64_first_mode_reorders_image_ladder(tmp_path):
    ladder = _policy(mode="base64_first").ladder_for(_image(tmp_path))
    assert ladder == (MediaEncoding.BASE64, MediaEncoding.PATH)


def test_base64_first_falls_back_to_path_when_over_cap(tmp_path):
    policy = _policy(mode="base64_first", base64_max_bytes=512)
    assert policy.ladder_for(_image(tmp_path, size=4096)) == (MediaEncoding.PATH,)


def test_path_only_mode_keeps_single_rung(tmp_path):
    policy = _policy(mode="path_only", url_fallback=True)
    assert policy.ladder_for(_video(tmp_path)) == (MediaEncoding.PATH,)


def test_allow_base64_false_suppresses_rung(tmp_path):
    ladder = _policy().ladder_for(_image(tmp_path), allow_base64=False)
    assert ladder == (MediaEncoding.PATH,)


def test_missing_path_has_no_base64_rung():
    media = TweetMedia(kind="image", url=TWIMG_IMAGE, path=None)
    assert _policy().ladder_for(media) == (MediaEncoding.PATH,)


# ---------------------------------------------------------------------------
# URL 档
# ---------------------------------------------------------------------------


def test_url_rung_absent_by_default(tmp_path):
    """默认不让协议端直连 Twitter CDN。"""
    assert MediaEncoding.URL not in _policy().ladder_for(_video(tmp_path))


def test_url_rung_present_for_twimg_when_enabled(tmp_path):
    ladder = _policy(url_fallback=True).ladder_for(_video(tmp_path))
    assert ladder == (
        MediaEncoding.PATH,
        MediaEncoding.BASE64,
        MediaEncoding.URL,
        MediaEncoding.SKIP,
    )


def test_url_rung_absent_for_non_allowlisted_host(tmp_path):
    """xdown 直链带 token、时效短且对 Referer 敏感，不交给后端。"""
    media = _video(tmp_path, url=XDOWN_VIDEO)
    assert MediaEncoding.URL not in _policy(url_fallback=True).ladder_for(media)


@pytest.mark.parametrize(
    "url,expected",
    [
        (TWIMG_VIDEO, True),
        (TWIMG_IMAGE, True),
        ("https://cdn.video.twimg.com/x.mp4", True),
        (XDOWN_VIDEO, False),
        ("https://evil-twimg.com/x.mp4", False),
        ("ftp://video.twimg.com/x.mp4", False),
        ("", False),
    ],
)
def test_backend_fetchable_host_allowlist(url, expected):
    assert is_backend_fetchable_url(url) is expected


# ---------------------------------------------------------------------------
# 消息段形状
# ---------------------------------------------------------------------------


def test_path_segment_is_file_uri(tmp_path):
    segment = onebot_segment(_image(tmp_path), MediaEncoding.PATH)
    assert segment["type"] == "image"
    assert segment["data"]["file"].startswith("file:///")


def test_video_path_segment_uses_video_type(tmp_path):
    assert onebot_segment(_video(tmp_path), MediaEncoding.PATH)["type"] == "video"


def test_base64_segment_uses_base64_scheme(tmp_path):
    segment = onebot_segment(_image(tmp_path), MediaEncoding.BASE64, "base64://QUJD")
    assert segment == {"type": "image", "data": {"file": "base64://QUJD"}}


def test_base64_segment_without_payload_is_unrepresentable(tmp_path):
    assert onebot_segment(_image(tmp_path), MediaEncoding.BASE64) is None


def test_url_segment_passes_source_url(tmp_path):
    segment = onebot_segment(_video(tmp_path), MediaEncoding.URL)
    assert segment["data"]["file"] == TWIMG_VIDEO


def test_skip_encoding_has_no_segment(tmp_path):
    assert onebot_segment(_video(tmp_path), MediaEncoding.SKIP) is None


# ---------------------------------------------------------------------------
# 编码记忆
# ---------------------------------------------------------------------------


def test_memo_moves_remembered_rung_to_front_keeping_earlier_rungs():
    ladder = (MediaEncoding.PATH, MediaEncoding.BASE64, MediaEncoding.URL)
    # 记忆是起步提示而非限制：path 仍留在 base64 之后继续兜底。
    assert apply_memo(ladder, MediaEncoding.BASE64) == (
        MediaEncoding.BASE64,
        MediaEncoding.PATH,
        MediaEncoding.URL,
    )


def test_memo_of_unknown_or_first_rung_is_a_noop():
    ladder = (MediaEncoding.PATH, MediaEncoding.BASE64)
    assert apply_memo(ladder, MediaEncoding.PATH) == ladder
    assert apply_memo(ladder, MediaEncoding.URL) == ladder
    assert apply_memo(ladder, "") == ladder


def test_memo_is_per_platform_and_per_kind():
    memo = TransportMemo()
    memo.record_success("aiocqhttp", "image", MediaEncoding.BASE64)
    assert memo.preferred("aiocqhttp", "image") == MediaEncoding.BASE64
    assert memo.preferred("aiocqhttp", "video") == ""
    assert memo.preferred("telegram", "image") == ""


def test_memo_never_records_skip():
    memo = TransportMemo()
    memo.record_success("aiocqhttp", "video", MediaEncoding.SKIP)
    assert memo.preferred("aiocqhttp", "video") == ""


def test_memo_forget_clears_entry():
    memo = TransportMemo()
    memo.record_success("aiocqhttp", "image", MediaEncoding.BASE64)
    memo.forget("aiocqhttp", "image")
    assert memo.preferred("aiocqhttp", "image") == ""


# ---------------------------------------------------------------------------
# 合并转发 payload 预算
# ---------------------------------------------------------------------------


def _tweet_with(media: TweetMedia) -> TweetItem:
    return TweetItem(
        text="t", link="https://x.com/u/status/1", published="", media=[media]
    )


def test_forward_allows_base64_for_small_payload(tmp_path):
    assert _policy().forward_allows_base64([_tweet_with(_image(tmp_path))]) is True


def test_forward_base64_budget_blocks_oversized_payload(tmp_path):
    tweets = [_tweet_with(_video(tmp_path, size=4 * 1024 * 1024))]
    # 预算 1MB：4MB 视频加上 base64 膨胀必然超标。
    assert _policy().forward_allows_base64(tweets, budget=1024 * 1024) is False


def test_forward_base64_disabled_in_path_only_mode(tmp_path):
    policy = _policy(mode="path_only")
    assert policy.forward_allows_base64([_tweet_with(_image(tmp_path))]) is False


# ---------------------------------------------------------------------------
# 适配器接线
# ---------------------------------------------------------------------------


def test_default_adapter_stays_path_only_even_with_policy(tmp_path):
    """Lark / Telegram / QQ Official 都在 AstrBot 进程内从本地路径上传，不参与梯度。"""
    sender = TweetSender({})
    adapter = DefaultDeliveryAdapter(sender, PlatformProfile(platform_id="lark"))
    assert adapter.media_transport_ladder(_image(tmp_path)) == (MediaEncoding.PATH,)


def test_onebot_adapter_uses_sender_policy(tmp_path):
    sender = TweetSender({})
    adapter = OneBotDeliveryAdapter(sender, _onebot_profile())
    assert adapter.media_transport_ladder(_image(tmp_path)) == (
        MediaEncoding.PATH,
        MediaEncoding.BASE64,
    )


def test_onebot_adapter_without_policy_falls_back_to_path_only(tmp_path):
    """绕过 __init__ 构造的 sender 没有策略，行为与改动前一致。"""
    sender = TweetSender.__new__(TweetSender)
    adapter = OneBotDeliveryAdapter(sender, _onebot_profile())
    assert adapter.media_transport_ladder(_image(tmp_path)) == (MediaEncoding.PATH,)


# ---------------------------------------------------------------------------
# 顺序不变量：无损的传输降级跑在有损的内容降级之前
# ---------------------------------------------------------------------------


def _umo_sender(config=None):
    sender = TweetSender(config or {})
    sender._send_context_message = AsyncMock(return_value=SendAttempt(success=True))
    return sender


class _RecordingCallAction:
    """记录每次 call_action 收到的 file 值，并按脚本决定成功还是抛错。"""

    def __init__(self, fail_prefixes=("file://",), error=None):
        self.fail_prefixes = fail_prefixes
        self.error = error or RuntimeError("cannot read file")
        self.files: list[str] = []

    async def __call__(self, action, **payload):
        file_value = payload["message"][0]["data"]["file"]
        self.files.append(file_value)
        if file_value.startswith(tuple(self.fail_prefixes)):
            raise self.error


async def _send_media_only(sender, adapter, media):
    return await _send(sender, adapter, media, media_only=True)


async def _send(sender, adapter, media, *, media_only: bool = False):
    return await adapter._send_split_direct_videos_to_umo(
        MagicMock(),
        "aiocqhttp:GroupMessage:1",
        "user",
        "https://nitter.example",
        [_tweet_with(media)],
        media_only=media_only,
    )


@pytest.mark.asyncio
async def test_path_failure_retries_as_base64_without_dropping_video(tmp_path):
    """路径档失败后换 base64 成功：视频送达，没有退到省略提示。

    用 media_only=False，省略提示分支才是真正可达的，断言才有意义。
    """
    sender = _umo_sender({"send_video_attachments": True})
    call_action = _RecordingCallAction()
    sender._onebot_call_action_for_umo = MagicMock(return_value=call_action)
    adapter = OneBotDeliveryAdapter(sender, _onebot_profile())
    sender.renderer.build_video_omitted_notice_components = MagicMock(return_value=[])

    outcome = await _send(sender, adapter, _video(tmp_path))

    assert outcome.success is True
    assert len(call_action.files) == 2
    assert call_action.files[0].startswith("file:///")
    assert call_action.files[1].startswith("base64://")
    # 视频送达了，不该再发省略提示。
    sender.renderer.build_video_omitted_notice_components.assert_not_called()


@pytest.mark.asyncio
async def test_exhausted_video_ladder_emits_the_existing_omitted_notice(tmp_path):
    """梯度耗尽后视频放弃附件，复用既有的「视频未发送」提示，而不是整条失败。"""
    sender = _umo_sender({"send_video_attachments": True})
    call_action = _RecordingCallAction()
    sender._onebot_call_action_for_umo = MagicMock(return_value=call_action)
    adapter = OneBotDeliveryAdapter(sender, _onebot_profile())
    sender.renderer.build_video_omitted_notice_components = MagicMock(
        return_value=["notice"]
    )

    # 9MB 超出 base64 上限，路径档失败后只剩放弃。
    outcome = await _send(sender, adapter, _video(tmp_path, size=9 * 1024 * 1024))

    assert outcome.success is True
    sender.renderer.build_video_omitted_notice_components.assert_called_once()


@pytest.mark.asyncio
async def test_image_path_failure_retries_as_base64(tmp_path):
    sender = _umo_sender()
    call_action = _RecordingCallAction()
    sender._onebot_call_action_for_umo = MagicMock(return_value=call_action)
    adapter = OneBotDeliveryAdapter(sender, _onebot_profile())

    outcome = await _send_media_only(sender, adapter, _image(tmp_path))

    assert outcome.success is True
    assert call_action.files[-1].startswith("base64://")


@pytest.mark.asyncio
async def test_oversized_video_skips_instead_of_sending_base64(tmp_path):
    """超过 base64 上限的视频在路径失败后放弃附件，走既有的省略提示。"""
    sender = _umo_sender({"send_video_attachments": True})
    call_action = _RecordingCallAction()
    sender._onebot_call_action_for_umo = MagicMock(return_value=call_action)
    adapter = OneBotDeliveryAdapter(sender, _onebot_profile())

    media = _video(tmp_path, size=9 * 1024 * 1024)
    outcome = await _send_media_only(sender, adapter, media)

    assert outcome.success is False
    # 只试过路径档，绝不把 9MB 视频塞进 base64。
    assert len(call_action.files) == 1
    assert not any(f.startswith("base64://") for f in call_action.files)


@pytest.mark.asyncio
async def test_uncertain_delivery_does_not_advance_ladder(tmp_path):
    """超时可能已送达，换编码重发会造成重复投递。"""
    sender = _umo_sender()
    call_action = _RecordingCallAction(error=TimeoutError("websocket api call timeout"))
    sender._onebot_call_action_for_umo = MagicMock(return_value=call_action)
    adapter = OneBotDeliveryAdapter(sender, _onebot_profile())

    await _send_media_only(sender, adapter, _image(tmp_path))

    assert len(call_action.files) == 1


@pytest.mark.asyncio
async def test_content_rejection_does_not_advance_ladder(tmp_path):
    """内容被拒时换编码没有意义：base64 与路径是同一份字节。"""
    sender = _umo_sender()
    call_action = _RecordingCallAction(
        error=RuntimeError(
            "Timeout: NTEvent serviceAndMethod:NodeIKernelMsgService/sendMsg "
            "ListenerName:NodeIKernelMsgListener/onMsgInfoListUpdate"
        )
    )
    sender._onebot_call_action_for_umo = MagicMock(return_value=call_action)
    adapter = OneBotDeliveryAdapter(sender, _onebot_profile())

    await _send_media_only(sender, adapter, _image(tmp_path))

    assert len(call_action.files) == 1


@pytest.mark.asyncio
async def test_successful_encoding_is_remembered_for_next_send(tmp_path):
    sender = _umo_sender()
    call_action = _RecordingCallAction()
    sender._onebot_call_action_for_umo = MagicMock(return_value=call_action)
    adapter = OneBotDeliveryAdapter(sender, _onebot_profile())

    await _send_media_only(sender, adapter, _image(tmp_path))
    assert sender.transport_memo.preferred("aiocqhttp", "image") == MediaEncoding.BASE64

    call_action.files.clear()
    await _send_media_only(sender, adapter, _image(tmp_path))

    # 第二次直接从记住的 base64 起步，不再白试一次路径档。
    assert len(call_action.files) == 1
    assert call_action.files[0].startswith("base64://")


@pytest.mark.asyncio
async def test_remembered_encoding_still_falls_back_to_path(tmp_path):
    """记忆是起步提示而非限制：base64 失效后仍要退回路径档。"""
    sender = _umo_sender()
    sender.transport_memo.record_success("aiocqhttp", "image", MediaEncoding.BASE64)
    call_action = _RecordingCallAction(fail_prefixes=("base64://",))
    sender._onebot_call_action_for_umo = MagicMock(return_value=call_action)
    adapter = OneBotDeliveryAdapter(sender, _onebot_profile())

    outcome = await _send_media_only(sender, adapter, _image(tmp_path))

    assert outcome.success is True
    assert call_action.files[0].startswith("base64://")
    assert call_action.files[1].startswith("file:///")


@pytest.mark.asyncio
async def test_path_only_mode_never_leaves_the_component_path(tmp_path):
    sender = _umo_sender({"media_transport_mode": "path_only"})
    call_action = _RecordingCallAction()
    sender._onebot_call_action_for_umo = MagicMock(return_value=call_action)
    adapter = OneBotDeliveryAdapter(sender, _onebot_profile())

    await _send_media_only(sender, adapter, _image(tmp_path))

    # 梯度只有一档时走原始组件链，不碰 call_action。
    assert call_action.files == []
    assert sender._send_context_message.await_count >= 2


@pytest.mark.asyncio
async def test_cached_file_stays_readable_through_the_ladder(tmp_path):
    """cleanup_after_send 在整个发送流程之后才跑，梯度全程文件必须还在。"""
    sender = _umo_sender()
    media = _image(tmp_path)
    seen_sizes: list[int] = []

    class _Watching(_RecordingCallAction):
        async def __call__(self, action, **payload):
            seen_sizes.append(Path(media.path).stat().st_size)
            await super().__call__(action, **payload)

    call_action = _Watching()
    sender._onebot_call_action_for_umo = MagicMock(return_value=call_action)
    adapter = OneBotDeliveryAdapter(sender, _onebot_profile())

    await _send_media_only(sender, adapter, media)

    assert len(seen_sizes) == 2
    assert all(size > 0 for size in seen_sizes)


@pytest.mark.asyncio
async def test_adapter_without_raw_channel_keeps_component_path(tmp_path):
    """取不到 call_action 时退回组件链，不因为传输层而失败。"""
    sender = _umo_sender()
    sender._onebot_call_action_for_umo = MagicMock(return_value=None)
    profile = _onebot_profile()
    profile.call_action = None
    adapter = OneBotDeliveryAdapter(sender, profile)

    outcome = await _send_media_only(sender, adapter, _image(tmp_path))

    assert outcome.success is True
    assert sender._send_context_message.await_count >= 2


# ---------------------------------------------------------------------------
# 渲染层注入
# ---------------------------------------------------------------------------


def test_renderer_uses_injected_segment_builder(tmp_path):
    sender = TweetSender({})
    media = _image(tmp_path)
    segment = sender.renderer.raw_media(
        media, lambda m: onebot_segment(m, MediaEncoding.BASE64, "base64://QUJD")
    )
    assert segment["data"]["file"] == "base64://QUJD"


def test_renderer_falls_back_to_path_when_builder_returns_none(tmp_path):
    sender = TweetSender({})
    segment = sender.renderer.raw_media(_image(tmp_path), lambda _m: None)
    assert segment["data"]["file"].startswith("file:///")


def test_direct_media_items_carry_their_media(tmp_path):
    sender = TweetSender({"send_video_attachments": True})
    image = _image(tmp_path)
    video = _video(tmp_path)
    tweet = TweetItem(
        text="t",
        link="https://x.com/u/status/1",
        published="",
        media=[image, video],
    )

    image_items = sender.renderer.build_direct_image_items([tweet])
    video_items = sender.renderer.build_direct_video_items([tweet])

    assert [media for media, _component in image_items] == [image]
    assert [media for media, _component in video_items] == [video]
    # 旧的 components 接口仍然等价。
    assert len(sender.renderer.build_direct_image_components([tweet])) == 1


def test_transport_config_reads_grouped_media_config():
    config = {
        "media": {
            "media_transport_mode": "base64_first",
            "media_transport_base64_max_mb": 2.0,
            "media_transport_url_fallback": True,
        }
    }
    resolved = TransportConfig.from_config(config)
    assert resolved.mode == "base64_first"
    assert resolved.base64_max_bytes == 2 * 1024 * 1024
    assert resolved.url_fallback is True


def test_transport_config_defaults_are_conservative():
    resolved = TransportConfig.from_config({})
    assert resolved.mode == "auto"
    assert resolved.base64_max_bytes == 8 * 1024 * 1024
    assert resolved.url_fallback is False


def test_media_transport_log_fields_are_allowlisted():
    """safe_log 会静默丢弃未登记的字段，传输日志必须登记。"""
    from shared.observability import ALLOWED_DIAGNOSTIC_FIELDS

    assert {"media_kind", "encoding", "size_bucket"} <= ALLOWED_DIAGNOSTIC_FIELDS


# ---------------------------------------------------------------------------
# 合并转发：整份 payload 按编码重建
# ---------------------------------------------------------------------------


def test_forward_ladder_lists_non_path_rungs(tmp_path):
    sender = TweetSender({"send_video_attachments": True})
    adapter = OneBotDeliveryAdapter(sender, _onebot_profile())
    tweets = [_tweet_with(_image(tmp_path))]

    assert sender._forward_transport_ladder(adapter, tweets) == (MediaEncoding.BASE64,)


def test_forward_ladder_is_empty_without_media():
    sender = TweetSender({})
    adapter = OneBotDeliveryAdapter(sender, _onebot_profile())
    bare = TweetItem(text="t", link="https://x.com/u/status/1", published="")

    assert sender._forward_transport_ladder(adapter, [bare]) == ()


def test_forward_ladder_is_empty_for_non_onebot_adapter(tmp_path):
    sender = TweetSender({})
    adapter = DefaultDeliveryAdapter(sender, PlatformProfile(platform_id="lark"))

    assert (
        sender._forward_transport_ladder(adapter, [_tweet_with(_image(tmp_path))]) == ()
    )


@pytest.mark.asyncio
async def test_forward_retry_rebuilds_nodes_with_base64(tmp_path):
    sender = TweetSender({})
    adapter = OneBotDeliveryAdapter(sender, _onebot_profile())
    tweets = [_tweet_with(_image(tmp_path))]
    seen = []

    async def rebuild_and_send(builder, encoding):
        seen.append((builder(tweets[0].media[0]), encoding))
        return True

    result = await sender._retry_forward_with_transport(
        lambda: adapter,
        tweets,
        rebuild_and_send=rebuild_and_send,
        last_error=RuntimeError("cannot read file"),
    )

    assert result is True
    segment, encoding = seen[0]
    assert encoding == MediaEncoding.BASE64
    assert segment["data"]["file"].startswith("base64://")


@pytest.mark.asyncio
async def test_forward_retry_skips_payload_rejection(tmp_path):
    """retcode 1200 是体积问题，换 base64 只会更大，直接让位给拆分。"""
    sender = TweetSender({})
    adapter = OneBotDeliveryAdapter(sender, _onebot_profile())
    rebuild_and_send = AsyncMock(return_value=True)

    result = await sender._retry_forward_with_transport(
        lambda: adapter,
        [_tweet_with(_image(tmp_path))],
        rebuild_and_send=rebuild_and_send,
        last_error=RuntimeError("send failed retcode=1200"),
    )

    assert result is None
    rebuild_and_send.assert_not_awaited()


@pytest.mark.asyncio
async def test_forward_retry_is_inert_without_policy(tmp_path):
    """绕过 __init__ 构造的 sender 不解析适配器，行为与改动前一致。"""
    sender = TweetSender.__new__(TweetSender)
    adapter_factory = MagicMock()
    rebuild_and_send = AsyncMock(return_value=True)

    result = await sender._retry_forward_with_transport(
        adapter_factory,
        [_tweet_with(_image(tmp_path))],
        rebuild_and_send=rebuild_and_send,
        last_error=None,
    )

    assert result is None
    adapter_factory.assert_not_called()
    rebuild_and_send.assert_not_awaited()
