from __future__ import annotations

from astrbot.api import logger

from .base import DeliveryAdapter
from .outcomes import SendOutcome

try:
    from ..lark_delivery import (
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
    from lark_delivery import (
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


class LarkDeliveryAdapter(DeliveryAdapter):
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
    ) -> bool:
        sender = self.sender
        components = sender.renderer.build_direct_components(
            username,
            instance,
            tweets,
            start_index=tweet_start_index,
            notices=notices,
            header_text=header_text,
        )
        client = lark_client_from_event(event, sender._platform_inst_from_context)
        if client is None:
            logger.warning("[NitterTweets] Lark client not found; using generic send")
            return await sender._send_direct_event(
                event,
                username,
                instance,
                tweets,
                notices=notices,
                header_text=header_text,
                tweet_start_index=tweet_start_index,
            )

        text = plain_text_from_components(components)
        reply_message_id = lark_reply_message_id(event)
        receive_id_type, receive_id = lark_event_target(event)
        post_attempt = await send_lark_post(
            client,
            lark_tweet_post_title(username, len(tweets), header_text),
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
                "[NitterTweets] Lark reply post failed; retrying current session "
                f"send: {post_attempt.error}"
            )
            post_attempt = await send_lark_post(
                client,
                lark_tweet_post_title(username, len(tweets), header_text),
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
                    "[NitterTweets] Lark post sent but video media failed: "
                    f"{video_attempt.error}"
                )
            return True

        logger.warning(
            "[NitterTweets] Lark post failed; falling back to text/media: "
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
                "[NitterTweets] Lark reply text failed; retrying current session "
                f"send: {text_attempt.error}"
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
                "[NitterTweets] Lark tweet text sent but media failed: "
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
        )
        text = plain_text_from_components(components)
        client, receive_id_type, receive_id = lark_client_and_target(
            context, umo, sender._platform_inst_from_context
        )
        if client is None or not receive_id_type or not receive_id:
            logger.warning(
                f"[NitterTweets] Lark client or target not found for {umo}; "
                "using generic send"
            )
            return await sender._send_direct_to_umo(
                context,
                umo,
                username,
                instance,
                tweets,
                group_label,
                header_text,
                batch_summary,
                tweet_start_index,
            )

        post_attempt = await send_lark_post(
            client,
            lark_tweet_post_title(username, len(tweets), header_text),
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
                    f"[NitterTweets] Lark post sent to {umo} but video media failed: "
                    f"{video_attempt.error}"
                )
            return SendOutcome(success=True, warning=warning)

        logger.warning(
            f"[NitterTweets] Lark post failed for {umo}; falling back to "
            f"text/media: {post_attempt.error}"
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
                f"[NitterTweets] Lark tweet text sent to {umo} but media failed: "
                f"{media_attempt.error}"
            )
        return SendOutcome(success=True, warning=warning)
