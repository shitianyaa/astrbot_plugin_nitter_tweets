from __future__ import annotations

from astrbot.api import logger

from .default import DefaultDeliveryAdapter
from .outcomes import SendOutcome

try:
    from .lark_support import (
        lark_client_and_target,
        lark_client_from_event,
        lark_event_target,
        lark_reply_message_id,
        lark_tweet_post_title,
        media_components,
        plain_text_from_components,
        send_lark_event_media_with_retry,
        send_lark_post,
        send_lark_text,
        send_lark_umo_media_with_retry,
        video_components,
    )
except ImportError:
    from delivery.lark_support import (
        lark_client_and_target,
        lark_client_from_event,
        lark_event_target,
        lark_reply_message_id,
        lark_tweet_post_title,
        media_components,
        plain_text_from_components,
        send_lark_event_media_with_retry,
        send_lark_post,
        send_lark_text,
        send_lark_umo_media_with_retry,
        video_components,
    )


class LarkDeliveryAdapter(DefaultDeliveryAdapter):
    name = "lark"
    is_lark = True

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
        components = sender.renderer.build_direct_components(
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
        client = lark_client_from_event(event, sender._platform_inst_from_context)
        if client is None:
            logger.warning("[NitterTweets] 未找到 Lark 客户端，改用通用发送")
            return await sender._send_default_direct_event(
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

        text = plain_text_from_components(components)
        post_title = (
            f"@{username}"
            if media_only
            else lark_tweet_post_title(username, len(tweets), header_text)
        )
        reply_message_id = lark_reply_message_id(event)
        receive_id_type, receive_id = lark_event_target(event)
        post_attempt = await send_lark_post(
            client,
            post_title,
            components,
            "manual Lark tweet post",
            is_uncertain_delivery_error=sender._is_uncertain_delivery_error,
            log_uncertain_delivery=sender._log_uncertain_delivery,
            uncertain_delivery_warning=sender.UNCERTAIN_DELIVERY_WARNING,
            reply_message_id=reply_message_id,
            receive_id=receive_id,
            receive_id_type=receive_id_type,
        )
        if (
            not (post_attempt.success or post_attempt.uncertain)
            and reply_message_id
            and receive_id
            and receive_id_type
        ):
            logger.warning(
                "[NitterTweets] Lark 回复 post 发送失败，改用当前会话重试: "
                f"{post_attempt.error}"
            )
            post_attempt = await send_lark_post(
                client,
                post_title,
                components,
                "manual Lark tweet post fallback",
                is_uncertain_delivery_error=sender._is_uncertain_delivery_error,
                log_uncertain_delivery=sender._log_uncertain_delivery,
                uncertain_delivery_warning=sender.UNCERTAIN_DELIVERY_WARNING,
                receive_id=receive_id,
                receive_id_type=receive_id_type,
            )
        if post_attempt.uncertain:
            return True
        if post_attempt.success:
            video_attempt = await send_lark_event_media_with_retry(
                event,
                video_components(components),
                "manual Lark tweet video media",
                sender._send_event_chain,
            )
            if not (video_attempt.success or video_attempt.uncertain):
                logger.warning(
                    "[NitterTweets] Lark post 已发送，但视频媒体发送失败: "
                    f"{video_attempt.error}"
                )
            return True

        logger.warning(
            "[NitterTweets] Lark post 发送失败，降级为文本/媒体发送: "
            f"{post_attempt.error}"
        )
        text_attempt = await send_lark_text(
            client,
            text,
            "manual Lark tweet text",
            is_uncertain_delivery_error=sender._is_uncertain_delivery_error,
            log_uncertain_delivery=sender._log_uncertain_delivery,
            uncertain_delivery_warning=sender.UNCERTAIN_DELIVERY_WARNING,
            reply_message_id=reply_message_id,
            receive_id=receive_id,
            receive_id_type=receive_id_type,
        )
        if (
            not (text_attempt.success or text_attempt.uncertain)
            and reply_message_id
            and receive_id
            and receive_id_type
        ):
            logger.warning(
                "[NitterTweets] Lark 回复文本发送失败，改用当前会话重试: "
                f"{text_attempt.error}"
            )
            text_attempt = await send_lark_text(
                client,
                text,
                "manual Lark tweet text fallback",
                is_uncertain_delivery_error=sender._is_uncertain_delivery_error,
                log_uncertain_delivery=sender._log_uncertain_delivery,
                uncertain_delivery_warning=sender.UNCERTAIN_DELIVERY_WARNING,
                receive_id=receive_id,
                receive_id_type=receive_id_type,
            )
        if not (text_attempt.success or text_attempt.uncertain):
            return False

        media_attempt = await send_lark_event_media_with_retry(
            event,
            media_components(components),
            "manual Lark tweet media",
            sender._send_event_chain,
        )
        if not (media_attempt.success or media_attempt.uncertain):
            logger.warning(
                "[NitterTweets] Lark 推文文本已发送，但媒体发送失败: "
                f"{media_attempt.error}"
            )
        return True

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
        components = sender.renderer.build_direct_components(
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
        text = plain_text_from_components(components)
        post_title = (
            f"@{username}"
            if media_only
            else lark_tweet_post_title(username, len(tweets), header_text)
        )
        client, receive_id_type, receive_id = lark_client_and_target(
            context, umo, sender._platform_inst_from_context
        )
        if client is None or not receive_id_type or not receive_id:
            logger.warning(
                f"[NitterTweets] 未找到 Lark 客户端或目标: target={umo}，"
                "改用通用发送"
            )
            return await sender._send_default_direct_to_umo(
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
                omit_status_url=omit_status_url,
                hide_original_when_translated=hide_original_when_translated,
                link_style=link_style,
            )

        post_attempt = await send_lark_post(
            client,
            post_title,
            components,
            "scheduled Lark tweet post",
            is_uncertain_delivery_error=sender._is_uncertain_delivery_error,
            log_uncertain_delivery=sender._log_uncertain_delivery,
            uncertain_delivery_warning=sender.UNCERTAIN_DELIVERY_WARNING,
            receive_id=receive_id,
            receive_id_type=receive_id_type,
        )
        if post_attempt.uncertain:
            return SendOutcome(success=True, warning=post_attempt.warning)
        if post_attempt.success:
            video_attempt = await send_lark_umo_media_with_retry(
                context,
                umo,
                video_components(components),
                "scheduled Lark tweet video media",
                sender._send_context_message,
            )
            warning = post_attempt.warning or video_attempt.warning
            if not (video_attempt.success or video_attempt.uncertain):
                warning = video_attempt.error
                logger.warning(
                    f"[NitterTweets] Lark post 已发送到 {umo}，但视频媒体发送失败: "
                    f"{video_attempt.error}"
                )
            return SendOutcome(
                success=True,
                warning=warning,
                delivery_status=(
                    "partial_failed"
                    if not (video_attempt.success or video_attempt.uncertain)
                    else "success"
                ),
                delivery_error=(
                    video_attempt.error
                    if not (video_attempt.success or video_attempt.uncertain)
                    else ""
                ),
            )

        logger.warning(
            f"[NitterTweets] Lark post 发送到 {umo} 失败，降级为文本/媒体发送: "
            f"{post_attempt.error}"
        )
        text_attempt = await send_lark_text(
            client,
            text,
            "scheduled Lark tweet text",
            is_uncertain_delivery_error=sender._is_uncertain_delivery_error,
            log_uncertain_delivery=sender._log_uncertain_delivery,
            uncertain_delivery_warning=sender.UNCERTAIN_DELIVERY_WARNING,
            receive_id=receive_id,
            receive_id_type=receive_id_type,
        )
        if not (text_attempt.success or text_attempt.uncertain):
            return SendOutcome(success=False, error=text_attempt.error)

        media_attempt = await send_lark_umo_media_with_retry(
            context,
            umo,
            media_components(components),
            "scheduled Lark tweet media",
            sender._send_context_message,
        )
        warning = text_attempt.warning or media_attempt.warning
        if not (media_attempt.success or media_attempt.uncertain):
            warning = media_attempt.error
            logger.warning(
                f"[NitterTweets] Lark 推文文本已发送到 {umo}，但媒体发送失败: "
                f"{media_attempt.error}"
            )
        return SendOutcome(
            success=True,
            warning=warning,
            delivery_status=(
                "partial_failed"
                if not (media_attempt.success or media_attempt.uncertain)
                else "success"
            ),
            delivery_error=(
                media_attempt.error
                if not (media_attempt.success or media_attempt.uncertain)
                else ""
            ),
        )
