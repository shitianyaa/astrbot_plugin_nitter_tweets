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

from .base import DeliveryAdapter
from .outcomes import SendOutcome


class DefaultDeliveryAdapter(DeliveryAdapter):
    async def send_event(
        self,
        event,
        username: str,
        instance: str,
        tweets: list,
        notices: list[str] | None = None,
        header_text: str = "",
        tweet_start_index: int = 1,
    ) -> bool:
        sender = self.sender
        if (
            self._should_split_direct_media(sender, tweets)
        ):
            return await self._send_split_direct_videos_event(
                event,
                username,
                instance,
                tweets,
                notices=notices,
                header_text=header_text,
                tweet_start_index=tweet_start_index,
            )

        attempt = await sender._send_event_chain(
            event,
            MessageChain(
                sender.renderer.build_direct_components(
                    username,
                    instance,
                    tweets,
                    start_index=tweet_start_index,
                    notices=notices,
                    header_text=header_text,
                )
            ),
            "manual direct tweets",
        )
        if attempt.success or attempt.uncertain:
            return True
        if not attempt.retryable:
            return False

        if sender._has_attached_videos(tweets):
            retry_attempt = await sender._send_event_chain(
                event,
                MessageChain(
                    sender.renderer.build_direct_components(
                        username,
                        instance,
                        tweets,
                        start_index=tweet_start_index,
                        exclude_videos=True,
                        notices=notices,
                        header_text=header_text,
                    )
                ),
                "manual direct tweets without videos",
            )
            if retry_attempt.success:
                logger.info("[NitterTweets] 初次失败后已发送去除视频的直发推文")
                return True
            if retry_attempt.uncertain:
                return True
            if not retry_attempt.retryable:
                return False

        return await self._send_event_fallback(
            event,
            username,
            instance,
            tweets,
            notices=notices,
            header_text=header_text,
            tweet_start_index=tweet_start_index,
        )

    async def send_summary_to_umo(self, context, umo: str, summary: str) -> SendOutcome:
        text = summary.strip()
        if not text:
            return SendOutcome(success=True)
        attempt = await self.sender._send_context_message(
            context,
            umo,
            MessageChain([Plain(text)]),
            "scheduled summary",
        )
        return SendOutcome(
            success=attempt.success or attempt.uncertain,
            error=attempt.error,
            warning=attempt.warning,
        )

    async def send_to_umo(
        self,
        context,
        umo: str,
        username: str,
        instance: str,
        tweets: list,
        group_label: str = "",
        header_text: str = "",
        batch_summary: str = "",
        tweet_start_index: int = 1,
    ) -> SendOutcome:
        sender = self.sender
        if (
            self._should_split_direct_media(sender, tweets)
        ):
            return await self._send_split_direct_videos_to_umo(
                context,
                umo,
                username,
                instance,
                tweets,
                group_label=group_label,
                header_text=header_text,
                batch_summary=batch_summary,
                tweet_start_index=tweet_start_index,
            )

        attempt = await sender._send_context_message(
            context,
            umo,
            MessageChain(
                sender.renderer.build_direct_components(
                    username,
                    instance,
                    tweets,
                    start_index=tweet_start_index,
                    group_label=group_label,
                    header_text=header_text,
                    batch_summary=batch_summary,
                )
            ),
            "direct scheduled tweets",
        )
        if attempt.success:
            return SendOutcome(success=True)
        if not attempt.retryable:
            return SendOutcome(
                success=attempt.uncertain,
                error=attempt.error,
                warning=attempt.warning,
            )

        if sender._has_attached_videos(tweets):
            retry_attempt = await sender._send_context_message(
                context,
                umo,
                MessageChain(
                    sender.renderer.build_direct_components(
                        username,
                        instance,
                        tweets,
                        start_index=tweet_start_index,
                        exclude_videos=True,
                        group_label=group_label,
                        header_text=header_text,
                        batch_summary=batch_summary,
                    )
                ),
                "direct scheduled tweets without videos",
            )
            if retry_attempt.success:
                logger.info(
                    f"[NitterTweets] 初次失败后已向 {umo} 发送去除视频的定时直发推文"
                )
                return SendOutcome(
                    success=True,
                    error=attempt.error,
                    delivery_status="partial_failed",
                    delivery_error=attempt.error,
                )
            if not retry_attempt.retryable:
                return SendOutcome(
                    success=retry_attempt.uncertain,
                    error=retry_attempt.error or attempt.error,
                    warning=retry_attempt.warning,
                )
            attempt = retry_attempt

        fallback = await sender._send_context_message(
            context,
            umo,
            MessageChain(
                [
                    Plain(
                        sender.renderer.format_plain(
                            username,
                            instance,
                            tweets,
                            start_index=tweet_start_index,
                            group_label=group_label,
                            header_text=header_text,
                            batch_summary=batch_summary,
                        )
                    )
                ]
            ),
            "direct scheduled fallback",
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

    async def _send_split_direct_videos_to_umo(
        self,
        context,
        umo: str,
        username: str,
        instance: str,
        tweets: list,
        group_label: str = "",
        header_text: str = "",
        batch_summary: str = "",
        tweet_start_index: int = 1,
    ) -> SendOutcome:
        sender = self.sender
        text_attempt = await sender._send_context_message(
            context,
            umo,
            MessageChain(
                sender.renderer.build_direct_components(
                    username,
                    instance,
                    tweets,
                    start_index=tweet_start_index,
                    include_videos=False,
                    include_images=False,
                    group_label=group_label,
                    header_text=header_text,
                    batch_summary=batch_summary,
                )
            ),
            "QQ direct scheduled tweet text before videos",
            )
        if not text_attempt.success:
            return SendOutcome(
                success=text_attempt.uncertain,
                error=text_attempt.error,
                warning=text_attempt.warning,
            )

        image_components = sender.renderer.build_direct_image_components(tweets)
        image_error = ""
        image_warning = ""
        for offset, image_component in enumerate(image_components, start=1):
            image_attempt = await self._send_context_component_with_retry(
                sender,
                context,
                umo,
                image_component,
                f"QQ direct scheduled tweet image {offset}/{len(image_components)}",
            )
            if image_attempt.success or image_attempt.uncertain:
                image_warning = image_warning or image_attempt.warning
                continue
            image_error = image_attempt.error
            logger.warning(
                "[NitterTweets] QQ 直发图片附件失败，正文已发送: "
                f"target={umo}, image={offset}/{len(image_components)}, "
                f"error={image_error}"
            )
            break

        video_components = sender.renderer.build_direct_video_components(tweets)
        video_error = ""
        video_warning = ""
        for offset, video_component in enumerate(video_components, start=1):
            video_attempt = await sender._send_context_message(
                context,
                umo,
                MessageChain([video_component]),
                f"QQ direct scheduled tweet video {offset}/{len(video_components)}",
            )
            if video_attempt.success or video_attempt.uncertain:
                video_warning = video_warning or video_attempt.warning
                continue
            video_error = video_attempt.error
            break
        else:
            delivery_error = video_error or image_error
            return SendOutcome(
                success=True,
                error=delivery_error,
                warning=video_warning or image_warning,
                delivery_status="partial_failed" if delivery_error else "success",
                delivery_error=delivery_error,
            )

        notice_components = sender.renderer.build_video_omitted_notice_components(tweets)
        if not notice_components:
            delivery_error = video_error or image_error
            return SendOutcome(
                success=True,
                error=delivery_error,
                warning=video_warning or image_warning,
                delivery_status="partial_failed" if delivery_error else "success",
                delivery_error=delivery_error,
            )

        notice_attempt = await sender._send_context_message(
            context,
            umo,
            MessageChain(notice_components),
            "QQ direct scheduled video omitted notice",
        )
        delivery_error = video_error or image_error
        return SendOutcome(
            success=True,
            error=delivery_error,
            warning=notice_attempt.warning or video_warning or image_warning,
            delivery_status="partial_failed" if delivery_error else "success",
            delivery_error=delivery_error,
        )

    async def _send_split_direct_videos_event(
        self,
        event,
        username: str,
        instance: str,
        tweets: list,
        notices: list[str] | None = None,
        header_text: str = "",
        tweet_start_index: int = 1,
    ) -> bool:
        sender = self.sender
        text_components = sender.renderer.build_direct_components(
            username,
            instance,
            tweets,
            start_index=tweet_start_index,
            include_videos=False,
            include_images=False,
            notices=notices,
            header_text=header_text,
        )
        text_attempt = await sender._send_event_chain(
            event,
            MessageChain(text_components),
            "manual QQ direct text before videos",
        )
        if not text_attempt.success:
            if text_attempt.uncertain:
                return True
            if not text_attempt.retryable:
                return False
            return await self._send_event_fallback(
                event,
                username,
                instance,
                tweets,
                notices=notices,
                header_text=header_text,
                tweet_start_index=tweet_start_index,
            )

        image_components = sender.renderer.build_direct_image_components(tweets)
        for offset, image_component in enumerate(image_components, start=1):
            image_attempt = await self._send_event_component_with_retry(
                sender,
                event,
                image_component,
                f"manual QQ direct image {offset}/{len(image_components)}",
            )
            if image_attempt.success or image_attempt.uncertain:
                continue
            logger.warning(
                "[NitterTweets] QQ 手动直发图片附件失败，正文已发送: "
                f"image={offset}/{len(image_components)}, error={image_attempt.error}"
            )
            break

        video_components = sender.renderer.build_direct_video_components(tweets)
        if not video_components:
            return True

        for offset, video_component in enumerate(video_components, start=1):
            video_attempt = await sender._send_event_chain(
                event,
                MessageChain([video_component]),
                f"manual QQ direct video {offset}/{len(video_components)}",
            )
            if video_attempt.success or video_attempt.uncertain:
                continue
            if not video_attempt.retryable:
                return False
            break
        else:
            return True

        notice_components = sender.renderer.build_video_omitted_notice_components(tweets)
        if not notice_components:
            return True
        notice_attempt = await sender._send_event_chain(
            event,
            MessageChain(notice_components),
            "manual QQ direct video omitted notice",
        )
        return notice_attempt.success or notice_attempt.uncertain

    async def _send_context_component_with_retry(
        self,
        sender,
        context,
        umo: str,
        component,
        label: str,
    ):
        attempt = await sender._send_context_message(
            context,
            umo,
            MessageChain([component]),
            label,
        )
        if attempt.success or attempt.uncertain or not attempt.retryable:
            return attempt
        return await sender._send_context_message(
            context,
            umo,
            MessageChain([component]),
            label,
        )

    async def _send_event_component_with_retry(
        self,
        sender,
        event,
        component,
        label: str,
    ):
        attempt = await sender._send_event_chain(
            event,
            MessageChain([component]),
            label,
        )
        if attempt.success or attempt.uncertain or not attempt.retryable:
            return attempt
        return await sender._send_event_chain(
            event,
            MessageChain([component]),
            label,
        )

    def _should_split_direct_media(self, sender, tweets: list) -> bool:
        return bool(
            (
                sender.send_video_attachments
                and self.should_split_direct_videos
                and sender._has_attached_videos(tweets)
            )
            or (
                sender.send_image_attachments
                and self.should_split_direct_images
                and sender._has_attached_images(tweets)
            )
        )

    async def _send_event_fallback(
        self,
        event,
        username: str,
        instance: str,
        tweets: list,
        notices: list[str] | None = None,
        header_text: str = "",
        tweet_start_index: int = 1,
    ) -> bool:
        sender = self.sender
        attempt = await sender._send_event_chain(
            event,
            MessageChain(
                [
                    Plain(
                        sender.renderer.format_plain(
                            username,
                            instance,
                            tweets,
                            start_index=tweet_start_index,
                            notices=notices,
                            header_text=header_text,
                        )
                    )
                ]
            ),
            "manual direct tweet fallback",
        )
        return attempt.success or attempt.uncertain
