from __future__ import annotations

import asyncio

from astrbot.api import logger

try:
    import httpx
except ImportError:  # pragma: no cover - optional dependency in some AstrBot envs
    httpx = None

try:
    from aiocqhttp.exceptions import ActionFailed, NetworkError as OneBotNetworkError
except ImportError:  # pragma: no cover - non-OneBot envs
    ActionFailed = None
    OneBotNetworkError = None

try:
    from astrbot.api.all import MessageChain
except ImportError:
    from astrbot.api.event import MessageChain

try:
    from astrbot.api.message_components import Plain
except ImportError:
    from astrbot.core.message.components import Plain

try:
    from ..config import (
        configured_merge_tweet_threshold,
        resolve_send_image_attachments,
        resolve_send_video_attachments,
    )
    from .lark_support import is_lark_platform
    from ..shared import (
        TweetItem,
        safe_call,
    )
    from .default import DefaultDeliveryAdapter
    from .onebot import OneBotDeliveryAdapter
    from .outcomes import MergedSendOutcome, SendAttempt, SendOutcome
    from .platforms import PlatformDeliveryRegistry, PlatformResolver, normalize_platform
    from ..rendering import TweetBatch, TweetMessageRenderer
except ImportError:
    from config import (
        configured_merge_tweet_threshold,
        resolve_send_image_attachments,
        resolve_send_video_attachments,
    )
    from delivery.lark_support import is_lark_platform
    from shared import (
        TweetItem,
        safe_call,
    )
    from delivery import (
        DefaultDeliveryAdapter,
        MergedSendOutcome,
        OneBotDeliveryAdapter,
        PlatformDeliveryRegistry,
        PlatformResolver,
        SendAttempt,
        SendOutcome,
        normalize_platform,
    )
    from rendering import TweetBatch, TweetMessageRenderer


class TweetSender:
    # AstrBot 的 Node/Nodes 合并转发主要由 OneBot v11 实现。
    FORWARD_MESSAGE_PLATFORMS = {"aiocqhttp"}
    QQ_DIRECT_VIDEO_SPLIT_PLATFORMS = FORWARD_MESSAGE_PLATFORMS | {
        "qq",
        "qq_official",
        "qqofficial",
        "onebot",
        "onebot_v11",
        "napcat",
    }
    FORWARD_TWEET_CHUNK_SIZE = 8
    UNCERTAIN_DELIVERY_WARNING = "发送状态不确定，已跳过降级重试。"

    def __init__(self, config=None):
        config = config or {}
        self.send_image_attachments = resolve_send_image_attachments(config)
        self.send_video_attachments = resolve_send_video_attachments(config)
        self.merge_tweet_threshold = configured_merge_tweet_threshold(config)
        self.renderer = TweetMessageRenderer(
            send_image_attachments=self.send_image_attachments,
            send_video_attachments=self.send_video_attachments,
        )
        self.platform_resolver = PlatformResolver()
        self.delivery_registry = PlatformDeliveryRegistry()

    async def send(
        self,
        event,
        username: str,
        instance: str,
        tweets: list[TweetItem],
        notices: list[str] | None = None,
        header_text: str = "",
        tweet_start_index: int = 1,
        media_only: bool = False,
    ) -> bool:
        adapter = self._delivery_adapter_for_event(event)
        if not adapter.supports_merged_forward or not self._should_use_merge_for_count(
            len(tweets)
        ):
            return await self._send_direct_event(
                event,
                username,
                instance,
                tweets,
                notices=notices,
                header_text=header_text,
                tweet_start_index=tweet_start_index,
                media_only=media_only,
            )

        if self._should_chunk_forward_tweets(len(tweets)):
            return await self._send_event_forward_chunks(
                event, username, instance, tweets, notices=notices,
                tweet_start_index=tweet_start_index,
                media_only=media_only,
            )

        return await self._send_event_forward_chunk(
            event, username, instance, tweets, notices=notices,
            tweet_start_index=tweet_start_index,
            media_only=media_only,
        )

    def should_merge_for_event(self, event, tweet_count: int) -> bool:
        return (
            self._delivery_adapter_for_event(event).supports_merged_forward
            and self._should_use_merge_for_count(tweet_count)
        )

    async def _send_event_forward_chunks(
        self,
        event,
        username: str,
        instance: str,
        tweets: list[TweetItem],
        notices: list[str] | None = None,
        tweet_start_index: int = 1,
        media_only: bool = False,
    ) -> bool:
        chunks = self._tweet_chunks(tweets)
        indexed_chunks = []
        index = tweet_start_index
        for chunk in chunks:
            indexed_chunks.append((index, chunk))
            index += len(chunk)
        return await self._send_chunked_bool(
            indexed_chunks,
            lambda item: self._send_event_forward_chunk(
                event,
                username,
                instance,
                item[1],
                notices=notices,
                tweet_start_index=item[0],
                media_only=media_only,
            ),
        )

    async def _send_event_forward_chunk(
        self,
        event,
        username: str,
        instance: str,
        tweets: list[TweetItem],
        notices: list[str] | None = None,
        tweet_start_index: int = 1,
        media_only: bool = False,
    ) -> bool:
        nodes = self.renderer.build_nodes(
            event, username, instance, tweets, notices=notices,
            start_index=tweet_start_index,
            media_only=media_only,
        )
        raw_nodes = self.renderer.build_onebot_nodes(
            event, username, instance, tweets, notices=notices,
            start_index=tweet_start_index,
            media_only=media_only,
        )
        try:
            await event.send(event.chain_result([nodes]))
            return True
        except Exception as exc:
            if self._is_uncertain_delivery_error(exc):
                self._log_uncertain_delivery(
                    "manual forwarded tweets", self._event_target(event), exc
                )
                return True
            logger.warning(f"[NitterTweets] 发送合并转发节点失败: {exc}")

        # 去掉视频后重试
        if any(m.is_video for t in tweets for m in t.media if m.path):
            try:
                nodes_nv = self.renderer.build_nodes(
                    event, username, instance, tweets,
                    exclude_videos=True, notices=notices,
                    start_index=tweet_start_index,
                    media_only=media_only,
                )
                await event.send(event.chain_result([nodes_nv]))
                logger.info("[NitterTweets] 初次失败后已发送去除视频的合并转发")
                return True
            except Exception as exc:
                if self._is_uncertain_delivery_error(exc):
                    self._log_uncertain_delivery(
                        "manual tweets without videos", self._event_target(event), exc
                    )
                    return True
                logger.warning(
                    f"[NitterTweets] 发送去除视频的合并转发节点失败: {exc}"
                )

        try:
            return await self._send_onebot_forward(event, raw_nodes)
        except Exception as exc:
            if self._is_uncertain_delivery_error(exc):
                self._log_uncertain_delivery(
                    "manual OneBot forward fallback", self._event_target(event), exc
                )
                return True
            logger.warning(f"[NitterTweets] 发送 OneBot 合并转发消息失败: {exc}")
            return False

    async def send_to_umo(
        self,
        context,
        umo: str,
        username: str,
        instance: str,
        tweets: list[TweetItem],
        group_label: str = "",
        header_text: str = "",
        batch_summary: str = "",
        tweet_start_index: int = 1,
        media_only: bool = False,
    ) -> bool:
        return (
            await self.send_to_umo_with_outcome(
                context,
                umo,
                username,
                instance,
                tweets,
                group_label,
                header_text,
                batch_summary,
                tweet_start_index,
                media_only,
            )
        ).success

    async def send_to_umo_with_outcome(
        self,
        context,
        umo: str,
        username: str,
        instance: str,
        tweets: list[TweetItem],
        group_label: str = "",
        header_text: str = "",
        batch_summary: str = "",
        tweet_start_index: int = 1,
        media_only: bool = False,
    ) -> SendOutcome:
        adapter = self._delivery_adapter_for_umo(context, umo)
        if not adapter.supports_merged_forward or not self._should_use_merge_for_count(
            len(tweets)
        ):
            return await self._send_direct_to_umo(
                context,
                umo,
                username,
                instance,
                tweets,
                group_label,
                header_text,
                batch_summary,
                tweet_start_index,
                media_only,
            )

        if self._should_chunk_forward_tweets(len(tweets)):
            return await self._send_forward_chunks_to_umo(
                context,
                umo,
                username,
                instance,
                tweets,
                group_label,
                header_text,
                batch_summary,
                tweet_start_index,
                media_only,
            )

        return await self._send_forward_chunk_to_umo(
            context,
            umo,
            username,
            instance,
            tweets,
            group_label,
            header_text,
            batch_summary,
            tweet_start_index,
            media_only,
        )

    async def send_summary_to_umo(self, context, umo: str, summary: str) -> SendOutcome:
        return await self._delivery_adapter_for_umo(context, umo).send_summary_to_umo(
            context, umo, summary
        )

    async def _send_forward_chunks_to_umo(
        self,
        context,
        umo: str,
        username: str,
        instance: str,
        tweets: list[TweetItem],
        group_label: str = "",
        header_text: str = "",
        batch_summary: str = "",
        tweet_start_index: int = 1,
        media_only: bool = False,
    ) -> SendOutcome:
        chunks = self._tweet_chunks(tweets)
        indexed_chunks = []
        index = tweet_start_index
        for chunk in chunks:
            indexed_chunks.append((len(indexed_chunks), index, chunk))
            index += len(chunk)
        return await self._send_chunked_outcomes(
            indexed_chunks,
            lambda item: self._send_forward_chunk_to_umo(
                context,
                umo,
                username,
                instance,
                item[2],
                group_label,
                header_text,
                batch_summary if item[0] == 0 else "",
                item[1],
                media_only,
            ),
            lambda error, warning: SendOutcome(
                success=True,
                error=error,
                warning=warning,
                delivery_status="partial_failed" if error else "success",
                delivery_error=error,
            ),
            lambda outcome, error, warning: SendOutcome(
                success=False,
                error=error or outcome.error,
                warning=warning,
            ),
        )

    async def _send_forward_chunk_to_umo(
        self,
        context,
        umo: str,
        username: str,
        instance: str,
        tweets: list[TweetItem],
        group_label: str = "",
        header_text: str = "",
        batch_summary: str = "",
        tweet_start_index: int = 1,
        media_only: bool = False,
    ) -> SendOutcome:
        nodes = self.renderer.build_nodes_for_uin(
            10000,
            username,
            instance,
            tweets,
            start_index=tweet_start_index,
            group_label=group_label,
            header_text=header_text,
            batch_summary=batch_summary,
            media_only=media_only,
        )
        attempt = await self._send_context_message(
            context, umo, MessageChain([nodes]), "scheduled forwarded tweets"
        )
        if attempt.success:
            return SendOutcome(success=True)
        if not attempt.retryable:
            return SendOutcome(
                success=attempt.uncertain,
                error=attempt.error,
                warning=attempt.warning,
            )

        # 去掉视频后重试
        if any(m.is_video for t in tweets for m in t.media if m.path):
            nodes_nv = self.renderer.build_nodes_for_uin(
                10000,
                username,
                instance,
                tweets,
                start_index=tweet_start_index,
                exclude_videos=True,
                group_label=group_label,
                header_text=header_text,
                batch_summary=batch_summary,
                media_only=media_only,
            )
            attempt_nv = await self._send_context_message(
                context,
                umo,
                MessageChain([nodes_nv]),
                "scheduled tweets without videos",
            )
            if attempt_nv.success:
                logger.info(
                    f"[NitterTweets] 初次失败后已向 {umo} 发送去除视频的定时推文"
                )
                return SendOutcome(
                    success=True,
                    error=attempt.error,
                    delivery_status="partial_failed",
                    delivery_error=attempt.error,
                )
            if not attempt_nv.retryable:
                return SendOutcome(
                    success=attempt_nv.uncertain,
                    error=attempt_nv.error or attempt.error,
                    warning=attempt_nv.warning,
                )
            attempt = attempt_nv

        fallback = await self._send_context_message(
            context,
            umo,
            MessageChain(
                [
                    Plain(
                        self.renderer.format_plain(
                            username,
                            instance,
                            tweets,
                            start_index=tweet_start_index,
                            group_label=group_label,
                            header_text=header_text,
                            batch_summary=batch_summary,
                            media_only=media_only,
                        )
                    )
                ]
            ),
            "scheduled tweet fallback",
        )
        return SendOutcome(
            success=fallback.success or fallback.uncertain,
            error=fallback.error or attempt.error,
            warning=fallback.warning,
            delivery_status=(
                "partial_failed"
                if (fallback.success or fallback.uncertain) and (attempt.error or fallback.error)
                else "success"
            ),
            delivery_error=(attempt.error or fallback.error)
            if (fallback.success or fallback.uncertain)
            else "",
        )

    async def send_merged_to_umo(
        self,
        context,
        umo: str,
        batches: list[TweetBatch],
        group_label: str = "",
        batch_summary: str = "",
        media_only: bool = False,
    ) -> MergedSendOutcome:
        tweet_count = self._count_batch_tweets(batches)
        if not self._should_use_merge_for_count(tweet_count):
            return await self._send_merged_direct_to_umo(
                context, umo, batches, group_label, batch_summary,
                media_only=media_only,
            )

        if not self._delivery_adapter_for_umo(context, umo).supports_merged_forward:
            return await self._send_merged_direct_to_umo(
                context, umo, batches, group_label, batch_summary,
                media_only=media_only,
            )

        if self._should_chunk_forward_tweets(tweet_count):
            return await self._send_merged_forward_chunks_to_umo(
                context, umo, batches, group_label, batch_summary,
                media_only=media_only,
            )

        return await self._send_merged_forward_chunk_to_umo(
            context, umo, batches, group_label, batch_summary,
            media_only=media_only,
        )

    async def _send_merged_forward_chunks_to_umo(
        self,
        context,
        umo: str,
        batches: list[TweetBatch],
        group_label: str = "",
        batch_summary: str = "",
        media_only: bool = False,
    ) -> MergedSendOutcome:
        omitted_videos = 0

        def track_omitted_videos(outcome: MergedSendOutcome) -> None:
            nonlocal omitted_videos
            omitted_videos += outcome.omitted_videos

        chunked_batches = []
        start_index = 1
        for chunk_index, chunk in enumerate(self._batch_chunks(batches)):
            chunked_batches.append((chunk_index, start_index, chunk))
            start_index += self._count_batch_tweets(chunk)
        return await self._send_chunked_outcomes(
            chunked_batches,
            lambda indexed_chunk: self._send_merged_forward_chunk_to_umo(
                context,
                umo,
                indexed_chunk[2],
                group_label,
                batch_summary if indexed_chunk[0] == 0 else "",
                tweet_start_index=indexed_chunk[1],
                media_only=media_only,
            ),
            lambda error, warning: MergedSendOutcome(
                success=True,
                mode="chunked_forward",
                omitted_videos=omitted_videos,
                error=error,
                warning=warning,
                delivery_status="partial_failed" if error else "success",
                delivery_error=error,
            ),
            lambda outcome, error, warning: MergedSendOutcome(
                success=False,
                mode=outcome.mode,
                omitted_videos=omitted_videos,
                error=error or outcome.error,
                warning=warning,
            ),
            after_outcome=track_omitted_videos,
        )

    async def _send_merged_forward_chunk_to_umo(
        self,
        context,
        umo: str,
        batches: list[TweetBatch],
        group_label: str = "",
        batch_summary: str = "",
        tweet_start_index: int = 1,
        media_only: bool = False,
    ) -> MergedSendOutcome:
        omitted_videos = self._count_attached_videos(batches)
        has_video = self._merged_forward_has_video(batches)
        raw_forward_available = (
            has_video and self._onebot_call_action_for_umo(context, umo) is not None
        )
        attempt = SendAttempt(
            success=False,
            retryable=True,
            error="video merged forward not attempted",
        )
        if raw_forward_available:
            raw_nodes = self.renderer.build_merged_onebot_nodes_for_uin(
                10000,
                batches,
                start_index=tweet_start_index,
                group_label=group_label,
                batch_summary=batch_summary,
                media_only=media_only,
            )
            attempt = await self._send_onebot_umo_forward(
                context, umo, raw_nodes, "merged scheduled tweets"
            )
            if attempt.success:
                return MergedSendOutcome(success=True, mode="raw_forward")
            if not attempt.retryable:
                return MergedSendOutcome(
                    success=attempt.uncertain,
                    mode="uncertain_delivery" if attempt.uncertain else "failed",
                    omitted_videos=omitted_videos,
                    error=attempt.error,
                    warning=attempt.warning,
                )

        if not raw_forward_available:
            nodes = self.renderer.build_merged_nodes_for_uin(
                10000,
                batches,
                start_index=tweet_start_index,
                group_label=group_label,
                batch_summary=batch_summary,
                media_only=media_only,
            )
            attempt = await self._send_context_message(
                context, umo, MessageChain([nodes]), "merged scheduled tweets"
            )
            if attempt.success:
                return MergedSendOutcome(success=True, mode="full_forward")
            if not attempt.retryable:
                return MergedSendOutcome(
                    success=attempt.uncertain,
                    mode="uncertain_delivery" if attempt.uncertain else "failed",
                    omitted_videos=omitted_videos,
                    error=attempt.error,
                    warning=attempt.warning,
                )

        if omitted_videos:
            raw_nodes_nv = self.renderer.build_merged_onebot_nodes_for_uin(
                10000,
                batches,
                start_index=tweet_start_index,
                exclude_videos=True,
                group_label=group_label,
                batch_summary=batch_summary,
                media_only=media_only,
            )
            raw_retry_attempt = await self._send_onebot_umo_forward(
                context,
                umo,
                raw_nodes_nv,
                "merged tweets without videos",
            )
            if raw_retry_attempt.success:
                logger.warning(
                    f"[NitterTweets] 初次失败后已向 {umo} 发送去除 "
                    f"{omitted_videos} 个视频/GIF 附件的合并推文"
                )
                return MergedSendOutcome(
                    success=True,
                    mode="raw_forward_without_videos",
                    omitted_videos=omitted_videos,
                    error=attempt.error,
                    delivery_status="partial_failed",
                    delivery_error=attempt.error,
                )
            if not raw_retry_attempt.retryable:
                return MergedSendOutcome(
                    success=raw_retry_attempt.uncertain,
                    mode=(
                        "uncertain_delivery" if raw_retry_attempt.uncertain else "failed"
                    ),
                    omitted_videos=omitted_videos,
                    error=raw_retry_attempt.error or attempt.error,
                    warning=raw_retry_attempt.warning,
                )
            nodes_nv = self.renderer.build_merged_nodes_for_uin(
                10000,
                batches,
                start_index=tweet_start_index,
                exclude_videos=True,
                group_label=group_label,
                batch_summary=batch_summary,
                media_only=media_only,
            )
            retry_attempt = await self._send_context_message(
                context,
                umo,
                MessageChain([nodes_nv]),
                "merged tweets without videos",
            )
            if retry_attempt.success:
                logger.warning(
                    f"[NitterTweets] 初次失败后已向 {umo} 发送去除 "
                    f"{omitted_videos} 个视频/GIF 附件的合并推文"
                )
                return MergedSendOutcome(
                    success=True,
                    mode="forward_without_videos",
                    omitted_videos=omitted_videos,
                    error=attempt.error,
                    delivery_status="partial_failed",
                    delivery_error=attempt.error,
                )
            if not retry_attempt.retryable:
                return MergedSendOutcome(
                    success=retry_attempt.uncertain,
                    mode=(
                        "uncertain_delivery" if retry_attempt.uncertain else "failed"
                    ),
                    omitted_videos=omitted_videos,
                    error=retry_attempt.error or attempt.error,
                    warning=retry_attempt.warning,
                )
            attempt = retry_attempt

        fallback = await self._send_context_message(
            context,
            umo,
            MessageChain(
                [
                    Plain(
                        self.renderer.format_merged_plain(
                            batches,
                            start_index=tweet_start_index,
                            group_label=group_label,
                            batch_summary=batch_summary,
                            media_only=media_only,
                        )
                    )
                ]
            ),
            "merged scheduled tweet fallback",
        )
        if fallback.success or fallback.uncertain:
            return MergedSendOutcome(
                success=True,
                mode="uncertain_delivery" if fallback.uncertain else "plain_fallback",
                omitted_videos=omitted_videos,
                error=attempt.error,
                warning=fallback.warning,
                delivery_status="partial_failed" if attempt.error else "success",
                delivery_error=attempt.error,
            )
        return MergedSendOutcome(
            success=False,
            mode="failed",
            omitted_videos=omitted_videos,
            error=fallback.error or attempt.error,
        )

    async def _send_direct_event(
        self,
        event,
        username: str,
        instance: str,
        tweets: list[TweetItem],
        notices: list[str] | None = None,
        header_text: str = "",
        tweet_start_index: int = 1,
        media_only: bool = False,
    ) -> bool:
        return await self._delivery_adapter_for_event(event).send_event(
            event,
            username,
            instance,
            tweets,
            notices=notices,
            header_text=header_text,
            tweet_start_index=tweet_start_index,
            media_only=media_only,
        )

    async def _send_default_direct_event(
        self,
        event,
        username: str,
        instance: str,
        tweets: list[TweetItem],
        notices: list[str] | None = None,
        header_text: str = "",
        tweet_start_index: int = 1,
        media_only: bool = False,
    ) -> bool:
        profile = self.platform_resolver.from_event(event)
        return await DefaultDeliveryAdapter(self, profile).send_event(
            event,
            username,
            instance,
            tweets,
            notices=notices,
            header_text=header_text,
            tweet_start_index=tweet_start_index,
            media_only=media_only,
        )

    async def _send_direct_to_umo(
        self,
        context,
        umo: str,
        username: str,
        instance: str,
        tweets: list[TweetItem],
        group_label: str = "",
        header_text: str = "",
        batch_summary: str = "",
        tweet_start_index: int = 1,
        media_only: bool = False,
    ) -> SendOutcome:
        return await self._delivery_adapter_for_umo(context, umo).send_to_umo(
            context,
            umo,
            username,
            instance,
            tweets,
            group_label,
            header_text,
            batch_summary,
            tweet_start_index,
            media_only,
        )

    async def _send_default_direct_to_umo(
        self,
        context,
        umo: str,
        username: str,
        instance: str,
        tweets: list[TweetItem],
        group_label: str = "",
        header_text: str = "",
        batch_summary: str = "",
        tweet_start_index: int = 1,
        media_only: bool = False,
    ) -> SendOutcome:
        profile = self.platform_resolver.from_umo(context, umo)
        return await DefaultDeliveryAdapter(self, profile).send_to_umo(
            context,
            umo,
            username,
            instance,
            tweets,
            group_label,
            header_text,
            batch_summary,
            tweet_start_index,
            media_only,
        )

    async def _send_merged_direct_to_umo(
        self,
        context,
        umo: str,
        batches: list[TweetBatch],
        group_label: str = "",
        batch_summary: str = "",
        tweet_start_index: int = 1,
        media_only: bool = False,
    ) -> MergedSendOutcome:
        omitted_videos = self._count_attached_videos(batches)
        attempt = await self._send_context_message(
            context,
            umo,
            MessageChain(
                self.renderer.build_merged_direct_components(
                    batches,
                    start_index=tweet_start_index,
                    group_label=group_label,
                    batch_summary=batch_summary,
                    media_only=media_only,
                )
            ),
            "direct merged tweets",
        )
        if attempt.success:
            return MergedSendOutcome(success=True, mode="direct_message")
        if not attempt.retryable:
            return MergedSendOutcome(
                success=attempt.uncertain,
                mode="uncertain_delivery" if attempt.uncertain else "failed",
                omitted_videos=omitted_videos,
                error=attempt.error,
                warning=attempt.warning,
            )

        if omitted_videos:
            retry_attempt = await self._send_context_message(
                context,
                umo,
                MessageChain(
                    self.renderer.build_merged_direct_components(
                        batches,
                        start_index=tweet_start_index,
                        exclude_videos=True,
                        group_label=group_label,
                        batch_summary=batch_summary,
                        media_only=media_only,
                    )
                ),
                "direct merged tweets without videos",
            )
            if retry_attempt.success:
                logger.warning(
                    f"[NitterTweets] 初次失败后已向 {umo} 发送去除 "
                    f"{omitted_videos} 个视频/GIF 附件的直发合并推文"
                )
                return MergedSendOutcome(
                    success=True,
                    mode="direct_without_videos",
                    omitted_videos=omitted_videos,
                    error=attempt.error,
                )
            if not retry_attempt.retryable:
                return MergedSendOutcome(
                    success=retry_attempt.uncertain,
                    mode=(
                        "uncertain_delivery" if retry_attempt.uncertain else "failed"
                    ),
                    omitted_videos=omitted_videos,
                    error=retry_attempt.error or attempt.error,
                    warning=retry_attempt.warning,
                )
            attempt = retry_attempt

        fallback = await self._send_context_message(
            context,
            umo,
            MessageChain(
                [
                    Plain(
                        self.renderer.format_merged_plain(
                            batches,
                            start_index=tweet_start_index,
                            group_label=group_label,
                            batch_summary=batch_summary,
                            media_only=media_only,
                        )
                    )
                ]
            ),
            "direct merged fallback",
        )
        if fallback.success or fallback.uncertain:
            return MergedSendOutcome(
                success=True,
                mode="uncertain_delivery" if fallback.uncertain else "plain_fallback",
                omitted_videos=omitted_videos,
                error=attempt.error,
                warning=fallback.warning,
            )
        return MergedSendOutcome(
            success=False,
            mode="failed",
            omitted_videos=omitted_videos,
            error=fallback.error or attempt.error,
        )

    async def _send_context_message(
        self,
        context,
        umo: str,
        chain: MessageChain,
        label: str,
    ) -> SendAttempt:
        target = umo
        try:
            sent = await context.send_message(umo, chain)
        except Exception as exc:
            flood_attempt = await self._adapter_flood_control_attempt(
                self._delivery_adapter_for_umo(context, umo),
                lambda: context.send_message(umo, chain),
                label,
                target,
                exc,
            )
            if flood_attempt is not None:
                return flood_attempt
            return self._send_exception_attempt(exc, label, target)

        if sent is False:
            error = "未找到目标平台或平台不支持主动发送"
            logger.warning(
                f"[NitterTweets] 发送失败: label={label}, target={umo}, error={error}"
            )
            return SendAttempt(success=False, retryable=True, error=error)

        return SendAttempt(success=True)

    async def _send_event_chain(
        self,
        event,
        chain: MessageChain,
        label: str,
    ) -> SendAttempt:
        target = self._event_target(event)
        try:
            await event.send(chain)
        except Exception as exc:
            flood_attempt = await self._adapter_flood_control_attempt(
                self._delivery_adapter_for_event(event),
                lambda: event.send(chain),
                label,
                target,
                exc,
            )
            if flood_attempt is not None:
                return flood_attempt
            return self._send_exception_attempt(exc, label, target)
        return SendAttempt(success=True)

    async def _adapter_flood_control_attempt(
        self,
        adapter,
        send_call,
        label: str,
        target: str,
        exc: Exception,
    ) -> SendAttempt | None:
        retry_after_flood_control = getattr(
            adapter, "retry_after_flood_control", None
        )
        if not callable(retry_after_flood_control):
            return None
        return await retry_after_flood_control(send_call, label, target, exc)

    def _send_exception_attempt(
        self, exc: Exception, label: str, target: str = "",
    ) -> SendAttempt:
        error = str(exc)
        if self._is_uncertain_delivery_error(exc):
            warning = self.UNCERTAIN_DELIVERY_WARNING
            self._log_uncertain_delivery(label, target, exc)
            return SendAttempt(
                success=False,
                retryable=False,
                uncertain=True,
                error=error,
                warning=warning,
            )
        if target:
            logger.warning(
                f"[NitterTweets] 发送失败: label={label}, target={target}, error={error}"
            )
        else:
            logger.warning(f"[NitterTweets] 发送失败: label={label}, error={error}")
        return SendAttempt(success=False, retryable=True, error=error)

    @staticmethod
    def _log_uncertain_delivery(
        label: str = "",
        target: str = "",
        exc: Exception | None = None,
    ) -> None:
        logger.warning("[NitterTweets] 发送状态不确定，跳过降级重试")
        if label or target or exc is not None:
            logger.debug(
                "[NitterTweets] 发送状态不确定详情: "
                f"label={label}, target={target}, error={exc}"
            )

    @classmethod
    def _is_uncertain_delivery_error(cls, exc: Exception) -> bool:
        if ActionFailed is not None and isinstance(exc, ActionFailed):
            return False

        if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
            return True

        if httpx is not None and isinstance(exc, httpx.TimeoutException):
            return True

        if OneBotNetworkError is not None and isinstance(exc, OneBotNetworkError):
            return cls._error_chain_contains_timeout(exc)

        return cls._error_chain_contains_timeout(exc)

    @staticmethod
    def _error_chain_contains_timeout(exc: BaseException) -> bool:
        timeout_markers = (
            "timeout",
            "timed out",
            "readtimeout",
            "websocket api call timeout",
        )
        current: BaseException | None = exc
        seen: set[int] = set()
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            text = (
                f"{type(current).__module__}.{type(current).__name__}: {current}"
            ).lower()
            if any(marker in text for marker in timeout_markers):
                return True
            current = current.__cause__ or current.__context__
        return False

    @classmethod
    def event_target(cls, event) -> str:
        return cls._event_target(event)

    @classmethod
    def _event_target(cls, event) -> str:
        try:
            umo = getattr(event, "unified_msg_origin", "")
        except Exception:
            umo = ""
        if umo:
            return str(umo)

        group_id = safe_call(event, "get_group_id")
        if group_id:
            return f"group:{group_id}"

        sender_id = safe_call(event, "get_sender_id")
        if sender_id:
            return f"private:{sender_id}"

        platform = cls._event_platform(event)
        return platform or "unknown"

    @staticmethod
    def _count_attached_videos(batches: list[TweetBatch]) -> int:
        return sum(
            1
            for _, _, tweets in batches
            for tweet in tweets
            for media in tweet.media
            if media.path and media.is_video
        )

    @staticmethod
    def _count_batch_tweets(batches: list[TweetBatch]) -> int:
        return sum(len(tweets) for _, _, tweets in batches)

    @staticmethod
    def _has_attached_videos(tweets: list[TweetItem]) -> bool:
        return any(
            media.is_video for tweet in tweets for media in tweet.media if media.path
        )

    @staticmethod
    def _has_attached_images(tweets: list[TweetItem]) -> bool:
        return any(
            media.is_image for tweet in tweets for media in tweet.media if media.path
        )

    def _should_split_qq_direct_videos(self, event, tweets: list[TweetItem]) -> bool:
        return bool(
            self.send_video_attachments
            and self._has_attached_videos(tweets)
            and self._should_split_direct_videos_for_event(event)
        )

    def _should_split_qq_direct_videos_for_umo(
        self,
        context,
        umo: str,
        tweets: list[TweetItem],
    ) -> bool:
        return bool(
            self.send_video_attachments
            and self._has_attached_videos(tweets)
            and self._should_split_direct_videos_for_umo(context, umo)
        )

    def _merged_forward_has_video(self, batches: list[TweetBatch]) -> bool:
        return bool(
            self.send_video_attachments
            and any(
                media.path and media.is_video
                for _, _, tweets in batches
                for tweet in tweets
                for media in tweet.media
            )
        )

    def _should_use_merge_for_count(self, tweet_count: int) -> bool:
        return (
            self.merge_tweet_threshold > 0
            and tweet_count >= self.merge_tweet_threshold
        )

    def _should_chunk_forward_tweets(self, tweet_count: int) -> bool:
        return tweet_count > self.FORWARD_TWEET_CHUNK_SIZE

    @staticmethod
    async def _send_chunked_bool(chunks, send_chunk) -> bool:
        for chunk in chunks:
            if not await send_chunk(chunk):
                return False
        return True

    @staticmethod
    async def _send_chunked_outcomes(
        chunks,
        send_chunk,
        success_factory,
        failure_factory,
        after_outcome=None,
    ):
        errors: list[str] = []
        warnings: list[str] = []
        for chunk in chunks:
            outcome = await send_chunk(chunk)
            if after_outcome is not None:
                after_outcome(outcome)
            if outcome.error:
                errors.append(outcome.error)
            if outcome.warning:
                warnings.append(outcome.warning)
            if not outcome.success:
                return failure_factory(
                    outcome,
                    "; ".join(errors),
                    "; ".join(warnings),
                )
        return success_factory("; ".join(errors), "; ".join(warnings))

    def _tweet_chunks(self, tweets: list[TweetItem]) -> list[list[TweetItem]]:
        size = self.FORWARD_TWEET_CHUNK_SIZE
        return [tweets[index : index + size] for index in range(0, len(tweets), size)]

    def _batch_chunks(self, batches: list[TweetBatch]) -> list[list[TweetBatch]]:
        chunks: list[list[TweetBatch]] = []
        current: list[TweetBatch] = []
        current_count = 0
        size = self.FORWARD_TWEET_CHUNK_SIZE

        for username, instance, tweets in batches:
            for tweet_chunk in self._tweet_chunks(tweets):
                if current and current_count + len(tweet_chunk) > size:
                    chunks.append(current)
                    current = []
                    current_count = 0
                current.append((username, instance, tweet_chunk))
                current_count += len(tweet_chunk)

        if current:
            chunks.append(current)
        return chunks

    def supports_merged_forward_for_umo(self, context, umo: str) -> bool:
        return self._delivery_adapter_for_umo(context, umo).supports_merged_forward

    def _delivery_adapter_for_umo(self, context, umo: str):
        profile = self.platform_resolver.from_umo(context, umo)
        return self.delivery_registry.adapter_for(self, profile)

    def _delivery_adapter_for_event(self, event):
        profile = self.platform_resolver.from_event(event)
        return self.delivery_registry.adapter_for(self, profile)

    @classmethod
    def _should_split_direct_videos_for_umo(cls, context, umo: str) -> bool:
        profile = PlatformResolver().from_umo(context, umo)
        return profile.should_split_qq_direct_videos

    @classmethod
    def _should_split_direct_videos_for_event(cls, event) -> bool:
        profile = PlatformResolver().from_event(event)
        return profile.should_split_qq_direct_videos

    @classmethod
    def _should_use_lark_for_umo(cls, context, umo: str) -> bool:
        return PlatformResolver().from_umo(context, umo).is_lark

    @classmethod
    def _should_use_lark_for_event(cls, event) -> bool:
        return PlatformResolver().from_event(event).is_lark

    @classmethod
    def _is_lark_platform(cls, platform: str) -> bool:
        return is_lark_platform(platform)

    @classmethod
    def _should_use_forward_for_umo(cls, context, umo: str) -> bool:
        return PlatformResolver().from_umo(context, umo).is_onebot

    @classmethod
    def _should_use_forward_for_event(cls, event) -> bool:
        return PlatformResolver().from_event(event).is_onebot

    @classmethod
    def _is_forward_platform(cls, platform: str) -> bool:
        return normalize_platform(platform) in cls.FORWARD_MESSAGE_PLATFORMS

    @classmethod
    def _is_qq_direct_video_split_platform(cls, platform: str) -> bool:
        return normalize_platform(platform) in cls.QQ_DIRECT_VIDEO_SPLIT_PLATFORMS

    @staticmethod
    def _normalize_platform(platform: str) -> str:
        return normalize_platform(platform)

    @staticmethod
    def _platform_from_umo(umo: str) -> str:
        return str(umo or "").split(":", 1)[0].strip()

    @classmethod
    def _platform_inst_from_context(cls, context, platform_id: str):
        return PlatformResolver().platform_inst_from_context(context, platform_id)

    @classmethod
    def _platform_type_from_context(cls, context, platform_id: str) -> str:
        profile = PlatformResolver().from_umo(context, f"{platform_id}:GroupMessage:")
        return profile.platform_types[0] if profile.platform_types else ""

    @staticmethod
    def _safe_platform_meta(platform):
        return PlatformResolver.safe_platform_meta(platform)

    @classmethod
    def _event_platform(cls, event) -> str:
        profile = PlatformResolver().from_event(event)
        return profile.platform_id or (profile.platform_types[0] if profile.platform_types else "")

    async def _send_onebot_forward(self, event, raw_nodes: list[dict]) -> bool:
        send_forward = getattr(
            self._delivery_adapter_for_event(event), "send_event_forward", None
        )
        if not callable(send_forward):
            return False
        return await send_forward(event, raw_nodes)

    async def _send_onebot_umo_forward(
        self,
        context,
        umo: str,
        raw_nodes: list[dict],
        label: str,
    ) -> SendAttempt:
        send_forward = getattr(
            self._delivery_adapter_for_umo(context, umo), "send_umo_forward", None
        )
        if not callable(send_forward):
            return SendAttempt(
                success=False,
                retryable=True,
                error="OneBot call_action unavailable for proactive merged forward",
            )
        return await send_forward(context, umo, raw_nodes, label)

    @classmethod
    def _onebot_call_action_for_umo(cls, context, umo: str):
        return PlatformResolver().from_umo(context, umo).call_action

    @staticmethod
    def _onebot_target_from_umo(umo: str) -> tuple[str, int | str]:
        return OneBotDeliveryAdapter.onebot_target_from_umo(umo)

    @staticmethod
    async def _call_forward_action(
        call_action,
        action: str,
        base_payload: dict,
        raw_nodes: list[dict],
    ) -> None:
        await OneBotDeliveryAdapter.call_forward_action(
            call_action, action, base_payload, raw_nodes
        )
