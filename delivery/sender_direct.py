"""直发路径：事件直发、UMO 直发和多账号合并直发降级。

`TweetSender` 的 mixin：只通过 `self` / `cls` 协作，不 import 宿主类。
"""

from __future__ import annotations

from astrbot.api import logger

try:
    from astrbot.api.all import MessageChain
except ImportError:
    from astrbot.api.event import MessageChain

try:
    from astrbot.api.message_components import Plain
except ImportError:
    from astrbot.core.message.components import Plain

try:
    from ..shared import TweetItem
    from .default import DefaultDeliveryAdapter
    from .outcomes import MergedSendOutcome, SendOutcome
    from ..rendering import TweetBatch
except ImportError:
    from shared import TweetItem
    from delivery import DefaultDeliveryAdapter, MergedSendOutcome, SendOutcome
    from rendering import TweetBatch


class SenderDirectMixin:
    """不走合并转发的发送路径。"""

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
        omit_status_url: bool = True,
        hide_original_when_translated: bool = False,
        link_style: str = "plain",
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
            omit_status_url=omit_status_url,
            hide_original_when_translated=hide_original_when_translated,
            link_style=link_style,
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
        omit_status_url: bool = True,
        hide_original_when_translated: bool = False,
        link_style: str = "plain",
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
            omit_status_url=omit_status_url,
            hide_original_when_translated=hide_original_when_translated,
            link_style=link_style,
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
        omit_status_url: bool = True,
        hide_original_when_translated: bool = False,
        link_style: str = "plain",
    ) -> SendOutcome:
        return await self._delivery_adapter_for_umo(context, umo).send_to_umo(
            context,
            umo,
            username,
            instance,
            tweets,
            group_label=group_label,
            header_text=header_text,
            batch_summary=batch_summary,
            tweet_start_index=tweet_start_index,
            media_only=media_only,
            omit_status_url=omit_status_url,
            hide_original_when_translated=hide_original_when_translated,
            link_style=link_style,
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
        omit_status_url: bool = True,
        hide_original_when_translated: bool = False,
        link_style: str = "plain",
    ) -> SendOutcome:
        profile = self.platform_resolver.from_umo(context, umo)
        return await DefaultDeliveryAdapter(self, profile).send_to_umo(
            context,
            umo,
            username,
            instance,
            tweets,
            group_label=group_label,
            header_text=header_text,
            batch_summary=batch_summary,
            tweet_start_index=tweet_start_index,
            media_only=media_only,
            omit_status_url=omit_status_url,
            hide_original_when_translated=hide_original_when_translated,
            link_style=link_style,
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
        omit_status_url: bool = True,
        hide_original_when_translated: bool = False,
        link_style: str = "plain",
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
                    omit_status_url=omit_status_url,
                    hide_original_when_translated=hide_original_when_translated,
                    link_style=link_style,
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

        if media_only:
            return MergedSendOutcome(
                success=False,
                mode="failed",
                omitted_videos=omitted_videos,
                error=attempt.error,
                warning=attempt.warning,
                delivery_status="failed",
                delivery_error=attempt.error,
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
                        omit_status_url=omit_status_url,
                        hide_original_when_translated=hide_original_when_translated,
                        link_style=link_style,
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
                    success=not media_only,
                    mode="direct_without_videos",
                    omitted_videos=omitted_videos,
                    error=attempt.error,
                    delivery_status="partial_failed",
                    delivery_error=attempt.error,
                )
            if not retry_attempt.retryable:
                retry_accepted = retry_attempt.uncertain
                return MergedSendOutcome(
                    success=retry_accepted and not media_only,
                    mode=(
                        "uncertain_delivery" if retry_accepted else "failed"
                    ),
                    omitted_videos=omitted_videos,
                    error=retry_attempt.error or attempt.error,
                    warning=retry_attempt.warning,
                    delivery_status=(
                        "partial_failed" if retry_accepted else "failed"
                    ),
                    delivery_error=retry_attempt.error or attempt.error,
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
                            omit_status_url=omit_status_url,
                            hide_original_when_translated=hide_original_when_translated,
                            link_style=link_style,
                        )
                    )
                ]
            ),
            "direct merged fallback",
        )
        if fallback.success or fallback.uncertain:
            if media_only:
                error = attempt.error or fallback.error or "media-only fallback omitted media"
                return MergedSendOutcome(
                    success=False,
                    mode="plain_fallback",
                    omitted_videos=omitted_videos,
                    error=error,
                    warning=fallback.warning,
                    delivery_status="failed",
                    delivery_error=error,
                )
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
