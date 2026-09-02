"""传输编码降级：一次发送尝试**内部**的无损重试。

传输降级是无损的——同一份媒体换一种线上编码；内容降级是有损的——丢视频、退纯文本。
所以这一层必须跑在内容降级之前：路径档失败先用 base64 重试，成功则视频从未被丢弃、
纯文本 fallback 从未触发。

``uncertain``（超时）**不推进梯度**：沿用既有「可能已送达」语义，推进会造成重复投递。

模块导出两个 mixin，各自落在协作者所在的层：

- ``AdapterTransportMixin``：单个附件的梯度，混入 ``DeliveryAdapter``；
- ``SenderTransportMixin``：整份合并转发 payload 的梯度，混入 ``TweetSender``。

两者都只通过 ``self`` 协作，不 import 宿主类。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

try:
    from ..shared.observability import safe_log
    from .media_transport import (
        PATH_ONLY_LADDER,
        MediaEncoding,
        apply_memo,
        media_kind,
        media_size_bytes,
        onebot_segment,
        read_base64_payload,
        size_bucket,
    )
    from .outcomes import SendAttempt
except ImportError:  # pragma: no cover - flat import fallback
    from delivery.media_transport import (
        PATH_ONLY_LADDER,
        MediaEncoding,
        apply_memo,
        media_kind,
        media_size_bytes,
        onebot_segment,
        read_base64_payload,
        size_bucket,
    )
    from delivery.outcomes import SendAttempt
    from shared.observability import safe_log


#: 梯度耗尽后视频放弃附件时的错误串。落到调用方既有的「视频失败 → 发提示」分支。
MEDIA_SKIPPED_ERROR = "media transport exhausted; attachment skipped"


@dataclass(slots=True)
class TransportOutcome:
    attempt: SendAttempt
    encoding: str = MediaEncoding.PATH
    skipped: bool = False


async def _build_media_segment(media, encoding: str) -> dict | None:
    if encoding != MediaEncoding.BASE64:
        return onebot_segment(media, encoding)
    path = getattr(media, "path", None)
    if not path:
        return None
    try:
        payload = await asyncio.to_thread(read_base64_payload, path)
    except (OSError, ValueError):
        return None
    return onebot_segment(media, encoding, payload)


def _log_transport(
    kind: str,
    encoding: str,
    bucket: str,
    status: str,
    label: str,
) -> None:
    # 只记类型、编码档、体积档位和结果；媒体 URL 绝不入日志。
    safe_log(
        logging.DEBUG,
        "media_transport",
        media_kind=kind,
        encoding=encoding,
        size_bucket=bucket,
        status=status,
        action=label,
    )


class AdapterTransportMixin:
    """按编码梯度重试单个媒体附件。混入 ``DeliveryAdapter``。"""

    async def _send_media_with_transport(
        self,
        media,
        *,
        component_send,
        segment_send,
        label: str,
        allow_skip: bool = True,
    ) -> TransportOutcome:
        """按梯度投递一个媒体附件。

        ``component_send``：未启用传输层时走的原始组件路径（``async () -> SendAttempt``）。
        ``segment_send``：原始消息段路径（``async (segment) -> SendAttempt | None``），
        返回 ``None`` 表示该适配器没有原始通道。
        """
        ladder = self.media_transport_ladder(media, allow_skip=allow_skip)
        if tuple(ladder) == PATH_ONLY_LADDER:
            return TransportOutcome(await component_send(), MediaEncoding.PATH)

        kind = media_kind(media)
        platform_id = str(getattr(self.profile, "platform_id", "") or "")
        memo = getattr(self.sender, "transport_memo", None)
        if memo is not None:
            ladder = apply_memo(tuple(ladder), memo.preferred(platform_id, kind))

        bucket = size_bucket(media_size_bytes(media))
        last_attempt: SendAttempt | None = None

        for encoding in ladder:
            if encoding == MediaEncoding.SKIP:
                _log_transport(kind, encoding, bucket, "skipped", label)
                return TransportOutcome(
                    SendAttempt(
                        success=False, retryable=True, error=MEDIA_SKIPPED_ERROR
                    ),
                    encoding,
                    skipped=True,
                )

            attempt = await self._attempt_media_encoding(
                media, encoding, component_send, segment_send
            )
            if attempt is None:
                # 该编码无法表达（缺路径/缺 URL/读取失败），换下一档。
                continue

            if attempt.success:
                if memo is not None:
                    memo.record_success(platform_id, kind, encoding)
                _log_transport(kind, encoding, bucket, "sent", label)
                return TransportOutcome(attempt, encoding)

            if memo is not None:
                memo.forget(platform_id, kind)

            if attempt.uncertain or attempt.rejected or not attempt.retryable:
                # 可能已送达，或对端明确拒绝：换编码重发只会重复投递。
                status = "uncertain" if attempt.uncertain else "rejected"
                _log_transport(kind, encoding, bucket, status, label)
                return TransportOutcome(attempt, encoding)

            _log_transport(kind, encoding, bucket, "retryable", label)
            last_attempt = attempt

        if last_attempt is None:
            last_attempt = SendAttempt(
                success=False,
                retryable=True,
                error="no usable media transport encoding",
            )
        return TransportOutcome(last_attempt, ladder[-1] if ladder else "")

    async def _attempt_media_encoding(
        self,
        media,
        encoding: str,
        component_send,
        segment_send,
    ) -> SendAttempt | None:
        segment = await _build_media_segment(media, encoding)
        if segment is None:
            # 路径档还可以退回组件链；其余编码没有等价组件形态。
            return await component_send() if encoding == MediaEncoding.PATH else None

        attempt = await segment_send(segment)
        if attempt is not None:
            return attempt
        # 适配器没有原始通道：路径档等价于组件链，其余编码只能跳过。
        return await component_send() if encoding == MediaEncoding.PATH else None


class SenderTransportMixin:
    """整份合并转发 payload 的编码梯度。混入 ``TweetSender``。"""

    # ------------------------------------------------------------------
    # 合并转发：整份节点数组按编码重建重试
    # ------------------------------------------------------------------

    def _forward_transport_ladder(self, adapter, tweets) -> tuple[str, ...]:
        """整份 payload 值得重试的编码档（不含已经试过的 path）。"""
        policy = getattr(self, "transport_policy", None)
        if policy is None:
            return ()
        medias = [
            media
            for tweet in tweets or ()
            for media in (getattr(tweet, "media", ()) or ())
            if getattr(media, "path", None)
        ]
        if not medias:
            return ()

        allow_base64 = policy.forward_allows_base64(tweets)
        steps: list[str] = []
        for media in medias:
            ladder = adapter.media_transport_ladder(
                media, allow_base64=allow_base64, allow_skip=False
            )
            for encoding in ladder:
                if encoding != MediaEncoding.PATH and encoding not in steps:
                    steps.append(encoding)
        return tuple(steps)

    async def _forward_segment_builder(self, tweets, encoding: str):
        """构造一个同步 segment builder 交给渲染层；不适用时返回 ``None``。"""
        if encoding == MediaEncoding.URL:
            return lambda media: onebot_segment(media, MediaEncoding.URL)
        if encoding != MediaEncoding.BASE64:
            return None

        payloads = await self._collect_base64_payloads(tweets)
        if not payloads:
            return None

        def builder(media):
            payload = payloads.get(str(getattr(media, "path", "") or ""))
            if not payload:
                return None
            return onebot_segment(media, MediaEncoding.BASE64, payload)

        return builder

    @staticmethod
    async def _collect_base64_payloads(tweets) -> dict[str, str]:
        """一次线程内读完整份 payload 的媒体，避免逐个 media 反复切线程。"""
        paths = []
        for tweet in tweets or ():
            for media in getattr(tweet, "media", ()) or ():
                path = getattr(media, "path", None)
                if path and str(path) not in paths:
                    paths.append(str(path))
        if not paths:
            return {}

        def read_all() -> dict[str, str]:
            payloads: dict[str, str] = {}
            for path in paths:
                try:
                    payloads[path] = read_base64_payload(path)
                except (OSError, ValueError):
                    continue
            return payloads

        return await asyncio.to_thread(read_all)

    async def _retry_forward_with_transport(
        self,
        adapter_factory,
        tweets,
        *,
        rebuild_and_send,
        last_error=None,
    ):
        """在拆分等有损降级之前，用其他编码重建整份节点数组重试。

        payload 被显式拒绝（retcode 1200 / res_id）是体积问题，换 base64 只会更大，
        那种情况直接让位给既有的拆分机制；但 NapCat 因本地文件读不到而回的 1200
        （ENOENT copyfile）不属于此类，由 `_is_forward_payload_rejected_error`
        放行走这里的无损重试。

        ``adapter_factory`` 是惰性的：没有配置传输策略时（例如绕过 ``__init__``
        构造的 sender）根本不去解析适配器，行为与改动前完全一致。
        """
        if getattr(self, "transport_policy", None) is None:
            return None
        if last_error is not None and self._is_forward_payload_rejected_error(
            last_error
        ):
            return None

        for encoding in self._forward_transport_ladder(adapter_factory(), tweets):
            builder = await self._forward_segment_builder(tweets, encoding)
            if builder is None:
                continue
            result = await rebuild_and_send(builder, encoding)
            if result is not None:
                _log_transport("forward", encoding, "payload", "sent", "merged forward")
                return result
            _log_transport(
                "forward", encoding, "payload", "retryable", "merged forward"
            )
        return None
