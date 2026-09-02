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
    @staticmethod
    def _message_chain(components, *, link_style: str = "plain") -> MessageChain:
        chain = MessageChain(components)
        # Only enable markdown when caller asked for telegram_md; never override plain.
        if link_style == "telegram_md" and hasattr(chain, "use_markdown"):
            chain.use_markdown(True)
        return chain

    async def send_event(
        self,
        event,
        username: str,
        instance: str,
        tweets: list,
        notices: list[str] | None = None,
        header_text: str = "",
        tweet_start_index: int = 1,
        media_only: bool = False,
        omit_status_url: bool = True,
        hide_original_when_translated: bool = False,
        link_style: str = "plain",
    ) -> bool:
        sender = self.sender
        if self._should_split_direct_media(sender, tweets):
            return await self._send_split_direct_videos_event(
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

        attempt = await sender._send_event_chain(
            event,
            self._message_chain(
                sender.renderer.build_direct_components(
                    username,
                    instance,
                    tweets,
                    start_index=tweet_start_index,
                    notices=notices,
                    header_text=header_text,
                    media_only=media_only,
                    omit_status_url=omit_status_url,
                    hide_original_when_translated=hide_original_when_translated,
                    link_style=link_style,
                ),
                link_style=link_style,
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
                self._message_chain(
                    sender.renderer.build_direct_components(
                        username,
                        instance,
                        tweets,
                        start_index=tweet_start_index,
                        exclude_videos=True,
                        notices=notices,
                        header_text=header_text,
                        media_only=media_only,
                        omit_status_url=omit_status_url,
                        hide_original_when_translated=hide_original_when_translated,
                        link_style=link_style,
                    ),
                    link_style=link_style,
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
            media_only=media_only,
            omit_status_url=omit_status_url,
            hide_original_when_translated=hide_original_when_translated,
            link_style=link_style,
        )

    async def send_summary_to_umo(self, context, umo: str, summary: str) -> SendOutcome:
        text = summary.strip()
        if not text:
            return SendOutcome(success=True)
        attempt = await self.sender._send_context_message(
            context,
            umo,
            self._message_chain([Plain(text)]),
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
        media_only: bool = False,
        omit_status_url: bool = True,
        hide_original_when_translated: bool = False,
        link_style: str = "plain",
    ) -> SendOutcome:
        sender = self.sender
        if self._should_split_direct_media(sender, tweets):
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
                media_only=media_only,
                omit_status_url=omit_status_url,
                hide_original_when_translated=hide_original_when_translated,
                link_style=link_style,
            )

        attempt = await sender._send_context_message(
            context,
            umo,
            self._message_chain(
                sender.renderer.build_direct_components(
                    username,
                    instance,
                    tweets,
                    start_index=tweet_start_index,
                    group_label=group_label,
                    header_text=header_text,
                    batch_summary=batch_summary,
                    media_only=media_only,
                    omit_status_url=omit_status_url,
                    hide_original_when_translated=hide_original_when_translated,
                    link_style=link_style,
                ),
                link_style=link_style,
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

        if media_only:
            return SendOutcome(
                success=False,
                error=attempt.error,
                warning=attempt.warning,
                delivery_status="failed",
                delivery_error=attempt.error,
            )

        if sender._has_attached_videos(tweets):
            retry_attempt = await sender._send_context_message(
                context,
                umo,
                self._message_chain(
                    sender.renderer.build_direct_components(
                        username,
                        instance,
                        tweets,
                        start_index=tweet_start_index,
                        exclude_videos=True,
                        group_label=group_label,
                        header_text=header_text,
                        batch_summary=batch_summary,
                        media_only=media_only,
                        omit_status_url=omit_status_url,
                        hide_original_when_translated=hide_original_when_translated,
                        link_style=link_style,
                    ),
                    link_style=link_style,
                ),
                "direct scheduled tweets without videos",
            )
            if retry_attempt.success:
                logger.info(
                    f"[NitterTweets] 初次失败后已向 {umo} 发送去除视频的定时直发推文"
                )
                return SendOutcome(
                    success=not media_only,
                    error=attempt.error,
                    delivery_status="partial_failed",
                    delivery_error=attempt.error,
                )
            if not retry_attempt.retryable:
                retry_accepted = retry_attempt.uncertain
                return SendOutcome(
                    success=retry_accepted and not media_only,
                    error=retry_attempt.error or attempt.error,
                    warning=retry_attempt.warning,
                    delivery_status=("partial_failed" if retry_accepted else "failed"),
                    delivery_error=retry_attempt.error or attempt.error,
                )
            attempt = retry_attempt

        fallback = await sender._send_context_message(
            context,
            umo,
            self._message_chain(
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
                            media_only=media_only,
                            omit_status_url=omit_status_url,
                            hide_original_when_translated=hide_original_when_translated,
                            link_style=link_style,
                        )
                    )
                ],
                link_style=link_style,
            ),
            "direct scheduled fallback",
        )
        fallback_accepted = fallback.success or fallback.uncertain
        return SendOutcome(
            success=fallback_accepted and not media_only,
            error=fallback.error or attempt.error,
            warning=fallback.warning,
            delivery_status=("partial_failed" if fallback_accepted else "failed"),
            delivery_error=fallback.error or attempt.error,
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
        media_only: bool = False,
        omit_status_url: bool = True,
        hide_original_when_translated: bool = False,
        link_style: str = "plain",
    ) -> SendOutcome:
        sender = self.sender
        text_attempt = await sender._send_context_message(
            context,
            umo,
            self._message_chain(
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
                    media_only=media_only,
                    omit_status_url=omit_status_url,
                    hide_original_when_translated=hide_original_when_translated,
                    link_style=link_style,
                ),
                link_style=link_style,
            ),
            "QQ direct scheduled tweet text before videos",
        )
        text_warning = ""
        if not text_attempt.success:
            if media_only and text_attempt.uncertain:
                text_warning = text_attempt.warning
            else:
                return SendOutcome(
                    success=text_attempt.uncertain,
                    error=text_attempt.error,
                    warning=text_attempt.warning,
                )

        image_items = sender.renderer.build_direct_image_items(tweets)
        image_error = ""
        image_warning = ""
        image_rejected = False
        for offset, (media, image_component) in enumerate(image_items, start=1):
            label = f"QQ direct scheduled tweet image {offset}/{len(image_items)}"
            outcome = await self._send_umo_media_item(
                context,
                umo,
                media,
                component_send=self._umo_component_sender(
                    sender, context, umo, image_component, label, retry=True
                ),
                label=label,
            )
            image_attempt = outcome.attempt
            if image_attempt.success or image_attempt.uncertain:
                image_warning = image_warning or image_attempt.warning
                continue
            image_error = image_attempt.error
            image_rejected = bool(getattr(image_attempt, "rejected", False))
            logger.warning(
                "[NitterTweets] QQ 直发图片附件失败，主体文本已发送: "
                f"target={umo}, image={offset}/{len(image_items)}, "
                f"rejected={image_rejected}, error={image_error}"
            )
            break

        # 正文已经先于图片发出，警告写不进正文，只能事后补一条提示。
        # media_only 分组会整条重推，补提示只会在每轮重试里刷屏。
        if image_error and not media_only:
            await self._send_image_failed_notice(
                sender,
                context,
                umo,
                tweets,
                rejected=image_rejected,
                omit_status_url=omit_status_url,
                label="QQ direct scheduled image failed notice",
                link_style=link_style,
            )

        video_items = sender.renderer.build_direct_video_items(tweets)
        video_error = ""
        video_warning = ""
        for offset, (media, video_component) in enumerate(video_items, start=1):
            label = f"QQ direct scheduled tweet video {offset}/{len(video_items)}"
            outcome = await self._send_umo_media_item(
                context,
                umo,
                media,
                component_send=self._umo_component_sender(
                    sender, context, umo, video_component, label, link_style
                ),
                label=label,
            )
            video_attempt = outcome.attempt
            if video_attempt.success or video_attempt.uncertain:
                video_warning = video_warning or video_attempt.warning
                continue
            video_error = video_attempt.error
            break
        else:
            delivery_error = image_error
            # 视频全部送达时，图片失败不应让整批重发。但没有视频组件且图片全部
            # 失败时 media_only 没有任何媒体送达，不能算完成，否则会推进 seen 漏推。
            # 一个媒体组件都没有时同理：不能凭“没有失败”判定完成。
            has_media = bool(video_items) or bool(image_items)
            media_delivered = has_media and (bool(video_items) or not image_error)
            return SendOutcome(
                success=not (media_only and not media_delivered),
                error=delivery_error,
                warning=video_warning or image_warning or text_warning,
                delivery_status="partial_failed" if delivery_error else "success",
                delivery_error=delivery_error,
            )

        if media_only:
            delivery_error = video_error or image_error
            return SendOutcome(
                success=False,
                error=delivery_error,
                warning=video_warning or image_warning or text_warning,
                delivery_status="partial_failed" if delivery_error else "success",
                delivery_error=delivery_error,
            )

        notice_components = sender.renderer.build_video_omitted_notice_components(
            tweets
        )
        if not notice_components:
            delivery_error = video_error or image_error
            return SendOutcome(
                success=True,
                error=delivery_error,
                warning=video_warning or image_warning or text_warning,
                delivery_status="partial_failed" if delivery_error else "success",
                delivery_error=delivery_error,
            )

        notice_attempt = await sender._send_context_message(
            context,
            umo,
            self._message_chain(notice_components, link_style=link_style),
            "QQ direct scheduled video omitted notice",
        )
        delivery_error = video_error or image_error
        return SendOutcome(
            success=True,
            error=delivery_error,
            warning=(
                notice_attempt.warning or video_warning or image_warning or text_warning
            ),
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
        media_only: bool = False,
        omit_status_url: bool = True,
        hide_original_when_translated: bool = False,
        link_style: str = "plain",
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
            media_only=media_only,
            omit_status_url=omit_status_url,
            hide_original_when_translated=hide_original_when_translated,
            link_style=link_style,
        )
        text_attempt = await sender._send_event_chain(
            event,
            self._message_chain(text_components, link_style=link_style),
            "manual QQ direct text before videos",
        )
        if not text_attempt.success:
            if text_attempt.uncertain:
                if not media_only:
                    return True
            elif not text_attempt.retryable:
                return False
            elif not media_only:
                return await self._send_event_fallback(
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

        image_items = sender.renderer.build_direct_image_items(tweets)
        image_failed = False
        image_rejected = False
        for offset, (media, image_component) in enumerate(image_items, start=1):
            label = f"manual QQ direct image {offset}/{len(image_items)}"
            outcome = await self._send_event_media_item(
                event,
                media,
                component_send=self._event_component_sender(
                    sender, event, image_component, label, retry=True
                ),
                label=label,
            )
            image_attempt = outcome.attempt
            if image_attempt.success or image_attempt.uncertain:
                continue
            image_rejected = bool(getattr(image_attempt, "rejected", False))
            logger.warning(
                "[NitterTweets] QQ 手动直发图片附件失败，正文已发送: "
                f"image={offset}/{len(image_items)}, "
                f"rejected={image_rejected}, error={image_attempt.error}"
            )
            image_failed = True
            break

        # 正文已先发出，提示只能事后补；链接是否附带由 omit_status_url 决定。
        if image_failed and not media_only:
            notice_components = (
                sender.renderer.build_image_send_failed_notice_components(
                    tweets,
                    rejected=image_rejected,
                    omit_status_url=omit_status_url,
                )
            )
            if notice_components:
                await sender._send_event_chain(
                    event,
                    self._message_chain(notice_components, link_style=link_style),
                    "manual QQ direct image failed notice",
                )

        video_items = sender.renderer.build_direct_video_items(tweets)
        if not video_items:
            # media_only 必须真的送出媒体：没有图片组件时不能凭“没有失败”判定完成。
            return (bool(image_items) and not image_failed) or not media_only

        for offset, (media, video_component) in enumerate(video_items, start=1):
            label = f"manual QQ direct video {offset}/{len(video_items)}"
            outcome = await self._send_event_media_item(
                event,
                media,
                component_send=self._event_component_sender(
                    sender, event, video_component, label, link_style
                ),
                label=label,
            )
            video_attempt = outcome.attempt
            if video_attempt.success or video_attempt.uncertain:
                continue
            # 梯度耗尽后放弃的视频是可重试失败，走下面的省略提示而不是整条失败。
            if not video_attempt.retryable:
                return False
            break
        else:
            return not (media_only and image_failed)

        if media_only:
            return False

        notice_components = sender.renderer.build_video_omitted_notice_components(
            tweets
        )
        if not notice_components:
            return True
        notice_attempt = await sender._send_event_chain(
            event,
            self._message_chain(notice_components, link_style=link_style),
            "manual QQ direct video omitted notice",
        )
        return notice_attempt.success or notice_attempt.uncertain

    async def _send_image_failed_notice(
        self,
        sender,
        context,
        umo: str,
        tweets,
        *,
        rejected: bool,
        omit_status_url: bool,
        label: str,
        link_style: str = "plain",
    ) -> None:
        """事后补发图片失败提示；提示本身失败不影响推送结论。"""
        notice_components = sender.renderer.build_image_send_failed_notice_components(
            tweets, rejected=rejected, omit_status_url=omit_status_url
        )
        if not notice_components:
            return
        await sender._send_context_message(
            context,
            umo,
            self._message_chain(notice_components, link_style=link_style),
            label,
        )

    def _event_component_sender(
        self,
        sender,
        event,
        component,
        label: str,
        link_style: str = "plain",
        retry: bool = False,
    ):
        """The unchanged component path, as a zero-arg awaitable factory."""

        async def send():
            if retry:
                return await self._send_event_component_with_retry(
                    sender, event, component, label, link_style
                )
            return await sender._send_event_chain(
                event,
                self._message_chain([component], link_style=link_style),
                label,
            )

        return send

    def _umo_component_sender(
        self,
        sender,
        context,
        umo: str,
        component,
        label: str,
        link_style: str = "plain",
        retry: bool = False,
    ):
        async def send():
            if retry:
                return await self._send_context_component_with_retry(
                    sender, context, umo, component, label, link_style
                )
            return await sender._send_context_message(
                context,
                umo,
                self._message_chain([component], link_style=link_style),
                label,
            )

        return send

    async def _send_event_media_item(
        self,
        event,
        media,
        *,
        component_send,
        label: str,
    ):
        async def segment_send(segment):
            return await self.send_event_media_segment(event, segment, label)

        return await self._send_media_with_transport(
            media,
            component_send=component_send,
            segment_send=segment_send,
            label=label,
        )

    async def _send_umo_media_item(
        self,
        context,
        umo: str,
        media,
        *,
        component_send,
        label: str,
    ):
        async def segment_send(segment):
            return await self.send_umo_media_segment(context, umo, segment, label)

        return await self._send_media_with_transport(
            media,
            component_send=component_send,
            segment_send=segment_send,
            label=label,
        )

    async def _send_context_component_with_retry(
        self,
        sender,
        context,
        umo: str,
        component,
        label: str,
        link_style: str = "plain",
    ):
        attempt = await sender._send_context_message(
            context,
            umo,
            self._message_chain([component], link_style=link_style),
            label,
        )
        if (
            attempt.success
            or attempt.uncertain
            or attempt.rejected
            or not attempt.retryable
        ):
            return attempt
        return await sender._send_context_message(
            context,
            umo,
            self._message_chain([component], link_style=link_style),
            label,
        )

    async def _send_event_component_with_retry(
        self,
        sender,
        event,
        component,
        label: str,
        link_style: str = "plain",
    ):
        attempt = await sender._send_event_chain(
            event,
            self._message_chain([component], link_style=link_style),
            label,
        )
        if (
            attempt.success
            or attempt.uncertain
            or attempt.rejected
            or not attempt.retryable
        ):
            return attempt
        return await sender._send_event_chain(
            event,
            self._message_chain([component], link_style=link_style),
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
        media_only: bool = False,
        omit_status_url: bool = True,
        hide_original_when_translated: bool = False,
        link_style: str = "plain",
    ) -> bool:
        sender = self.sender
        attempt = await sender._send_event_chain(
            event,
            self._message_chain(
                [
                    Plain(
                        sender.renderer.format_plain(
                            username,
                            instance,
                            tweets,
                            start_index=tweet_start_index,
                            notices=notices,
                            header_text=header_text,
                            media_only=media_only,
                            omit_status_url=omit_status_url,
                            hide_original_when_translated=hide_original_when_translated,
                            link_style=link_style,
                        )
                    )
                ],
                link_style=link_style,
            ),
            "manual direct tweet fallback",
        )
        return attempt.success or attempt.uncertain
