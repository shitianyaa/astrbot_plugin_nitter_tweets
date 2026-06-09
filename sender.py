from __future__ import annotations

import asyncio
from dataclasses import dataclass

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
    from .lark_delivery import (
        is_lark_platform,
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
    from .utils import (
        TweetItem,
        configured_merge_tweet_threshold,
        safe_call,
    )
    from .tweet_rendering import TweetBatch, TweetMessageRenderer
except ImportError:
    from lark_delivery import (
        is_lark_platform,
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
    from utils import (
        TweetItem,
        configured_merge_tweet_threshold,
        safe_call,
    )
    from tweet_rendering import TweetBatch, TweetMessageRenderer


@dataclass(slots=True)
class SendAttempt:
    success: bool
    retryable: bool = False
    uncertain: bool = False
    error: str = ""
    warning: str = ""


@dataclass(slots=True)
class SendOutcome:
    success: bool
    error: str = ""
    warning: str = ""


@dataclass(slots=True)
class MergedSendOutcome:
    success: bool
    mode: str
    omitted_videos: int = 0
    error: str = ""
    warning: str = ""


class TweetSender:
    # AstrBot 的 Node/Nodes 合并转发主要由 OneBot v11 实现。
    FORWARD_MESSAGE_PLATFORMS = {"aiocqhttp"}
    FORWARD_TWEET_CHUNK_SIZE = 8
    UNCERTAIN_DELIVERY_WARNING = "发送状态不确定，已跳过降级重试。"

    def __init__(self, config=None):
        config = config or {}
        image_config = config.get("send_image_attachments", None)
        if image_config is None:
            image_config = bool(config.get("download_media", True)) and bool(
                config.get("download_images", True)
            )
        self.send_image_attachments = bool(image_config)
        self.send_video_attachments = bool(
            config.get("send_video_attachments", False)
        )
        self.merge_tweet_threshold = configured_merge_tweet_threshold(config)
        self.renderer = TweetMessageRenderer(
            send_image_attachments=self.send_image_attachments,
            send_video_attachments=self.send_video_attachments,
        )

    async def send(
        self,
        event,
        username: str,
        instance: str,
        tweets: list[TweetItem],
        notices: list[str] | None = None,
    ) -> bool:
        if self._should_use_lark_for_event(event):
            return await self._send_lark_event(
                event, username, instance, tweets, notices=notices
            )

        if not self._should_use_forward_for_event(
            event
        ) or not self._should_use_merge_for_count(len(tweets)):
            return await self._send_direct_event(
                event, username, instance, tweets, notices=notices
            )

        if self._should_chunk_forward_tweets(len(tweets)):
            return await self._send_event_forward_chunks(
                event, username, instance, tweets, notices=notices
            )

        return await self._send_event_forward_chunk(
            event, username, instance, tweets, notices=notices
        )

    async def _send_event_forward_chunks(
        self,
        event,
        username: str,
        instance: str,
        tweets: list[TweetItem],
        notices: list[str] | None = None,
    ) -> bool:
        return await self._send_chunked_bool(
            self._tweet_chunks(tweets),
            lambda chunk: self._send_event_forward_chunk(
                event, username, instance, chunk, notices=notices
            ),
        )

    async def _send_event_forward_chunk(
        self,
        event,
        username: str,
        instance: str,
        tweets: list[TweetItem],
        notices: list[str] | None = None,
    ) -> bool:
        nodes = self.renderer.build_nodes(
            event, username, instance, tweets, notices=notices
        )
        raw_nodes = self.renderer.build_onebot_nodes(
            event, username, instance, tweets, notices=notices
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
            logger.warning(f"Failed to send forwarded tweet nodes: {exc}")

        # 去掉视频后重试
        if any(m.is_video for t in tweets for m in t.media if m.path):
            try:
                nodes_nv = self.renderer.build_nodes(
                    event, username, instance, tweets,
                    exclude_videos=True, notices=notices
                )
                await event.send(event.chain_result([nodes_nv]))
                logger.info("Sent forwarded tweets without videos after initial failure")
                return True
            except Exception as exc:
                if self._is_uncertain_delivery_error(exc):
                    self._log_uncertain_delivery(
                        "manual tweets without videos", self._event_target(event), exc
                    )
                    return True
                logger.warning(
                    f"Failed to send forwarded tweet nodes without videos: {exc}"
                )

        try:
            return await self._send_onebot_forward(event, raw_nodes)
        except Exception as exc:
            if self._is_uncertain_delivery_error(exc):
                self._log_uncertain_delivery(
                    "manual OneBot forward fallback", self._event_target(event), exc
                )
                return True
            logger.warning(f"Failed to send OneBot forward message: {exc}")
            return False

    async def send_to_umo(
        self,
        context,
        umo: str,
        username: str,
        instance: str,
        tweets: list[TweetItem],
    ) -> bool:
        return (
            await self.send_to_umo_with_outcome(context, umo, username, instance, tweets)
        ).success

    async def send_to_umo_with_outcome(
        self,
        context,
        umo: str,
        username: str,
        instance: str,
        tweets: list[TweetItem],
    ) -> SendOutcome:
        if self._should_use_lark_for_umo(context, umo):
            return await self._send_lark_to_umo(
                context, umo, username, instance, tweets
            )

        if not self._should_use_forward_for_umo(
            context, umo
        ) or not self._should_use_merge_for_count(len(tweets)):
            return await self._send_direct_to_umo(
                context, umo, username, instance, tweets
            )

        if self._should_chunk_forward_tweets(len(tweets)):
            return await self._send_forward_chunks_to_umo(
                context, umo, username, instance, tweets
            )

        return await self._send_forward_chunk_to_umo(
            context, umo, username, instance, tweets
        )

    async def _send_forward_chunks_to_umo(
        self,
        context,
        umo: str,
        username: str,
        instance: str,
        tweets: list[TweetItem],
    ) -> SendOutcome:
        return await self._send_chunked_outcomes(
            self._tweet_chunks(tweets),
            lambda chunk: self._send_forward_chunk_to_umo(
                context, umo, username, instance, chunk
            ),
            lambda error, warning: SendOutcome(
                success=True, error=error, warning=warning
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
    ) -> SendOutcome:
        nodes = self.renderer.build_nodes_for_uin(10000, username, instance, tweets)
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
                10000, username, instance, tweets, exclude_videos=True
            )
            attempt_nv = await self._send_context_message(
                context,
                umo,
                MessageChain([nodes_nv]),
                "scheduled tweets without videos",
            )
            if attempt_nv.success:
                logger.info(
                    f"Sent scheduled tweets to {umo} without videos after initial failure"
                )
                return SendOutcome(success=True, error=attempt.error)
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
            MessageChain([Plain(self.renderer.format_plain(username, instance, tweets))]),
            "scheduled tweet fallback",
        )
        return SendOutcome(
            success=fallback.success or fallback.uncertain,
            error=fallback.error or attempt.error,
            warning=fallback.warning,
        )

    async def send_merged_to_umo(
        self,
        context,
        umo: str,
        batches: list[TweetBatch],
    ) -> MergedSendOutcome:
        tweet_count = self._count_batch_tweets(batches)
        if not self._should_use_merge_for_count(tweet_count):
            return await self._send_merged_direct_to_umo(context, umo, batches)

        if not self._should_use_forward_for_umo(
            context, umo
        ):
            return await self._send_merged_direct_to_umo(context, umo, batches)

        if self._should_chunk_forward_tweets(tweet_count):
            return await self._send_merged_forward_chunks_to_umo(
                context, umo, batches
            )

        return await self._send_merged_forward_chunk_to_umo(context, umo, batches)

    async def _send_merged_forward_chunks_to_umo(
        self,
        context,
        umo: str,
        batches: list[TweetBatch],
    ) -> MergedSendOutcome:
        omitted_videos = 0

        def track_omitted_videos(outcome: MergedSendOutcome) -> None:
            nonlocal omitted_videos
            omitted_videos += outcome.omitted_videos

        return await self._send_chunked_outcomes(
            self._batch_chunks(batches),
            lambda chunk: self._send_merged_forward_chunk_to_umo(
                context, umo, chunk
            ),
            lambda error, warning: MergedSendOutcome(
                success=True,
                mode="chunked_forward",
                omitted_videos=omitted_videos,
                error=error,
                warning=warning,
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
    ) -> MergedSendOutcome:
        omitted_videos = self._count_attached_videos(batches)
        nodes = self.renderer.build_merged_nodes_for_uin(10000, batches)
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
            nodes_nv = self.renderer.build_merged_nodes_for_uin(
                10000, batches, exclude_videos=True
            )
            retry_attempt = await self._send_context_message(
                context,
                umo,
                MessageChain([nodes_nv]),
                "merged tweets without videos",
            )
            if retry_attempt.success:
                logger.warning(
                    f"Sent merged tweets to {umo} without {omitted_videos} "
                    "video/GIF attachments after initial failure"
                )
                return MergedSendOutcome(
                    success=True,
                    mode="forward_without_videos",
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
            MessageChain([Plain(self.renderer.format_merged_plain(batches))]),
            "merged scheduled tweet fallback",
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

    async def _send_direct_event(
        self,
        event,
        username: str,
        instance: str,
        tweets: list[TweetItem],
        notices: list[str] | None = None,
    ) -> bool:
        try:
            await event.send(
                MessageChain(
                    self.renderer.build_direct_components(
                        username, instance, tweets, notices=notices
                    )
                )
            )
            return True
        except Exception as exc:
            if self._is_uncertain_delivery_error(exc):
                self._log_uncertain_delivery(
                    "manual direct tweets", self._event_target(event), exc
                )
                return True
            logger.warning(f"Failed to send direct tweets: {exc}")

        if self._has_attached_videos(tweets):
            try:
                await event.send(
                    MessageChain(
                        self.renderer.build_direct_components(
                            username, instance, tweets,
                            exclude_videos=True, notices=notices
                        )
                    )
                )
                logger.info(
                    "Sent direct tweets without videos after initial failure"
                )
                return True
            except Exception as exc:
                if self._is_uncertain_delivery_error(exc):
                    self._log_uncertain_delivery(
                        "manual direct tweets without videos",
                        self._event_target(event),
                        exc,
                    )
                    return True
                logger.warning(
                    f"Failed to send direct tweets without videos: {exc}"
                )

        try:
            await event.send(
                MessageChain(
                    [
                        Plain(
                            self.renderer.format_plain(
                                username, instance, tweets, notices=notices
                            )
                        )
                    ]
                )
            )
            return True
        except Exception as exc:
            if self._is_uncertain_delivery_error(exc):
                self._log_uncertain_delivery(
                    "manual direct tweet fallback", self._event_target(event), exc
                )
                return True
            logger.warning(f"Failed to send direct tweet fallback: {exc}")
            return False

    async def _send_direct_to_umo(
        self,
        context,
        umo: str,
        username: str,
        instance: str,
        tweets: list[TweetItem],
    ) -> SendOutcome:
        attempt = await self._send_context_message(
            context,
            umo,
            MessageChain(
                self.renderer.build_direct_components(username, instance, tweets)
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

        if self._has_attached_videos(tweets):
            retry_attempt = await self._send_context_message(
                context,
                umo,
                MessageChain(
                    self.renderer.build_direct_components(
                        username, instance, tweets, exclude_videos=True
                    )
                ),
                "direct scheduled tweets without videos",
            )
            if retry_attempt.success:
                logger.info(
                    f"Sent direct scheduled tweets to {umo} without videos "
                    "after initial failure"
                )
                return SendOutcome(success=True, error=attempt.error)
            if not retry_attempt.retryable:
                return SendOutcome(
                    success=retry_attempt.uncertain,
                    error=retry_attempt.error or attempt.error,
                    warning=retry_attempt.warning,
                )
            attempt = retry_attempt

        fallback = await self._send_context_message(
            context,
            umo,
            MessageChain([Plain(self.renderer.format_plain(username, instance, tweets))]),
            "direct scheduled fallback",
        )
        return SendOutcome(
            success=fallback.success or fallback.uncertain,
            error=fallback.error or attempt.error,
            warning=fallback.warning,
        )

    async def _send_merged_direct_to_umo(
        self,
        context,
        umo: str,
        batches: list[TweetBatch],
    ) -> MergedSendOutcome:
        omitted_videos = self._count_attached_videos(batches)
        attempt = await self._send_context_message(
            context,
            umo,
            MessageChain(self.renderer.build_merged_direct_components(batches)),
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
                        batches, exclude_videos=True
                    )
                ),
                "direct merged tweets without videos",
            )
            if retry_attempt.success:
                logger.warning(
                    f"Sent direct merged tweets to {umo} without {omitted_videos} "
                    "video/GIF attachments after initial failure"
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
            MessageChain([Plain(self.renderer.format_merged_plain(batches))]),
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

    async def _send_lark_event(
        self,
        event,
        username: str,
        instance: str,
        tweets: list[TweetItem],
        notices: list[str] | None = None,
    ) -> bool:
        components = self.renderer.build_direct_components(
            username, instance, tweets, notices=notices
        )
        client = lark_client_from_event(event, self._platform_inst_from_context)
        if client is None:
            logger.warning("[NitterTweets] Lark client not found; using generic send")
            return await self._send_direct_event(
                event, username, instance, tweets, notices=notices
            )

        text = plain_text_from_components(components)
        reply_message_id = lark_reply_message_id(event)
        receive_id_type, receive_id = lark_event_target(event)
        post_attempt = await send_lark_post(
            client,
            lark_tweet_post_title(username, len(tweets)),
            components,
            "manual Lark tweet post",
            is_uncertain_delivery_error=self._is_uncertain_delivery_error,
            log_uncertain_delivery=self._log_uncertain_delivery,
            uncertain_delivery_warning=self.UNCERTAIN_DELIVERY_WARNING,
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
                lark_tweet_post_title(username, len(tweets)),
                components,
                "manual Lark tweet post fallback",
                is_uncertain_delivery_error=self._is_uncertain_delivery_error,
                log_uncertain_delivery=self._log_uncertain_delivery,
                uncertain_delivery_warning=self.UNCERTAIN_DELIVERY_WARNING,
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
                self._send_event_chain,
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
            is_uncertain_delivery_error=self._is_uncertain_delivery_error,
            log_uncertain_delivery=self._log_uncertain_delivery,
            uncertain_delivery_warning=self.UNCERTAIN_DELIVERY_WARNING,
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
                is_uncertain_delivery_error=self._is_uncertain_delivery_error,
                log_uncertain_delivery=self._log_uncertain_delivery,
                uncertain_delivery_warning=self.UNCERTAIN_DELIVERY_WARNING,
                receive_id=receive_id,
                receive_id_type=receive_id_type,
            )
        if not (text_attempt.success or text_attempt.uncertain):
            return False

        media_attempt = await send_lark_event_media_with_retry(
            event,
            media_components(components),
            "manual Lark tweet media",
            self._send_event_chain,
        )
        if not (media_attempt.success or media_attempt.uncertain):
            logger.warning(
                "[NitterTweets] Lark tweet text sent but media failed: "
                f"{media_attempt.error}"
            )
        return True

    async def _send_lark_to_umo(
        self,
        context,
        umo: str,
        username: str,
        instance: str,
        tweets: list[TweetItem],
    ) -> SendOutcome:
        components = self.renderer.build_direct_components(username, instance, tweets)
        text = plain_text_from_components(components)
        client, receive_id_type, receive_id = lark_client_and_target(
            context, umo, self._platform_inst_from_context
        )
        if client is None or not receive_id_type or not receive_id:
            logger.warning(
                f"[NitterTweets] Lark client or target not found for {umo}; "
                "using generic send"
            )
            return await self._send_direct_to_umo(
                context, umo, username, instance, tweets
            )

        post_attempt = await send_lark_post(
            client,
            lark_tweet_post_title(username, len(tweets)),
            components,
            "scheduled Lark tweet post",
            is_uncertain_delivery_error=self._is_uncertain_delivery_error,
            log_uncertain_delivery=self._log_uncertain_delivery,
            uncertain_delivery_warning=self.UNCERTAIN_DELIVERY_WARNING,
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
                self._send_context_message,
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
            is_uncertain_delivery_error=self._is_uncertain_delivery_error,
            log_uncertain_delivery=self._log_uncertain_delivery,
            uncertain_delivery_warning=self.UNCERTAIN_DELIVERY_WARNING,
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
            self._send_context_message,
        )
        warning = text_attempt.warning or media_attempt.warning
        if not (media_attempt.success or media_attempt.uncertain):
            warning = media_attempt.error
            logger.warning(
                f"[NitterTweets] Lark tweet text sent to {umo} but media failed: "
                f"{media_attempt.error}"
            )
        return SendOutcome(success=True, warning=warning)

    async def _send_context_message(
        self,
        context,
        umo: str,
        chain: MessageChain,
        label: str,
    ) -> SendAttempt:
        try:
            sent = await context.send_message(umo, chain)
        except Exception as exc:
            error = str(exc)
            if self._is_uncertain_delivery_error(exc):
                warning = self.UNCERTAIN_DELIVERY_WARNING
                self._log_uncertain_delivery(label, umo, exc)
                return SendAttempt(
                    success=False,
                    retryable=False,
                    uncertain=True,
                    error=error,
                    warning=warning,
                )
            logger.warning(f"Failed to send {label} to {umo}: {error}")
            return SendAttempt(success=False, retryable=True, error=error)

        if sent is False:
            error = "target platform not found or proactive send is unsupported"
            logger.warning(f"Failed to send {label} to {umo}: {error}")
            return SendAttempt(success=False, retryable=True, error=error)

        return SendAttempt(success=True)

    async def _send_event_chain(
        self,
        event,
        chain: MessageChain,
        label: str,
    ) -> SendAttempt:
        try:
            await event.send(chain)
        except Exception as exc:
            error = str(exc)
            if self._is_uncertain_delivery_error(exc):
                warning = self.UNCERTAIN_DELIVERY_WARNING
                self._log_uncertain_delivery(label, self._event_target(event), exc)
                return SendAttempt(
                    success=False,
                    retryable=False,
                    uncertain=True,
                    error=error,
                    warning=warning,
                )
            logger.warning(f"Failed to send {label}: {error}")
            return SendAttempt(success=False, retryable=True, error=error)
        return SendAttempt(success=True)

    @staticmethod
    def _log_uncertain_delivery(
        label: str = "",
        target: str = "",
        exc: Exception | None = None,
    ) -> None:
        logger.warning("[NitterTweets] 发送状态不确定，跳过降级重试")
        if label or target or exc is not None:
            logger.debug(
                "[NitterTweets] uncertain delivery detail: "
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
        return self._should_use_forward_for_umo(context, umo)

    @classmethod
    def _should_use_lark_for_umo(cls, context, umo: str) -> bool:
        platform = cls._platform_from_umo(umo)
        if cls._is_lark_platform(platform):
            return True
        return cls._is_lark_platform(cls._platform_type_from_context(context, platform))

    @classmethod
    def _should_use_lark_for_event(cls, event) -> bool:
        return cls._is_lark_platform(cls._event_platform(event))

    @classmethod
    def _is_lark_platform(cls, platform: str) -> bool:
        return is_lark_platform(platform)

    @classmethod
    def _should_use_forward_for_umo(cls, context, umo: str) -> bool:
        platform = cls._platform_from_umo(umo)
        if cls._is_forward_platform(platform):
            return True
        return cls._is_forward_platform(cls._platform_type_from_context(context, platform))

    @classmethod
    def _should_use_forward_for_event(cls, event) -> bool:
        return cls._is_forward_platform(cls._event_platform(event))

    @classmethod
    def _is_forward_platform(cls, platform: str) -> bool:
        return str(platform or "").strip().lower() in cls.FORWARD_MESSAGE_PLATFORMS

    @staticmethod
    def _platform_from_umo(umo: str) -> str:
        return str(umo or "").split(":", 1)[0].strip()

    @classmethod
    def _platform_inst_from_context(cls, context, platform_id: str):
        if not platform_id:
            return None

        get_platform_inst = getattr(context, "get_platform_inst", None)
        if callable(get_platform_inst):
            try:
                platform = get_platform_inst(platform_id)
                if platform is not None:
                    return platform
            except Exception as exc:
                logger.debug(
                    f"[NitterTweets] platform lookup failed for {platform_id}: {exc}"
                )

        manager = getattr(context, "platform_manager", None)
        for candidate in getattr(manager, "platform_insts", []) or []:
            meta = cls._safe_platform_meta(candidate)
            if str(getattr(meta, "id", "") or "") == platform_id:
                return candidate

        return None

    @classmethod
    def _platform_type_from_context(cls, context, platform_id: str) -> str:
        platform = cls._platform_inst_from_context(context, platform_id)
        if platform is None:
            return ""

        meta = cls._safe_platform_meta(platform)
        for attr in ("name", "id"):
            value = getattr(meta, attr, None)
            if value:
                return str(value)

        config = getattr(platform, "config", None)
        if isinstance(config, dict):
            return str(config.get("type") or "")
        return ""

    @staticmethod
    def _safe_platform_meta(platform):
        meta = getattr(platform, "meta", None)
        if not callable(meta):
            return None
        try:
            return meta()
        except Exception:
            return None

    @classmethod
    def _event_platform(cls, event) -> str:
        for method_name in ("get_platform_name", "get_platform_id"):
            value = safe_call(event, method_name)
            if value:
                return str(value)

        meta = getattr(event, "platform_meta", None)
        for attr in ("name", "id"):
            value = getattr(meta, attr, None)
            if value:
                return str(value)

        try:
            umo = getattr(event, "unified_msg_origin", "")
        except Exception:
            umo = ""
        return cls._platform_from_umo(str(umo))

    async def _send_onebot_forward(self, event, raw_nodes: list[dict]) -> bool:
        client = getattr(event, "bot", None)
        if client is None:
            return False

        call_action = None
        if hasattr(client, "api") and hasattr(client.api, "call_action"):
            call_action = client.api.call_action
        elif hasattr(client, "call_action"):
            call_action = client.call_action
        if call_action is None:
            return False

        group_id = safe_call(event, "get_group_id")
        if group_id:
            await self._call_forward_action(
                call_action,
                "send_group_forward_msg",
                {"group_id": int(group_id)},
                raw_nodes,
            )
            return True

        user_id = safe_call(event, "get_sender_id")
        if user_id:
            await self._call_forward_action(
                call_action,
                "send_private_forward_msg",
                {"user_id": int(user_id)},
                raw_nodes,
            )
            return True

        return False

    @staticmethod
    async def _call_forward_action(
        call_action,
        action: str,
        base_payload: dict,
        raw_nodes: list[dict],
    ) -> None:
        try:
            await call_action(action, **base_payload, messages=raw_nodes)
        except TypeError:
            await call_action(action, **base_payload, message=raw_nodes)
