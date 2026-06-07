from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from urllib.parse import urlparse

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
    from astrbot.api.message_components import Image, Node, Nodes, Plain, Video
except ImportError:
    from astrbot.core.message.components import Image, Node, Nodes, Plain, Video

try:
    from .utils import (
        TweetItem, TweetMedia, configured_merge_tweet_threshold, file_uri, node_uin,
        normalize_external_links, safe_call, strip_external_links,
    )
except ImportError:
    from utils import (
        TweetItem, TweetMedia, configured_merge_tweet_threshold, file_uri, node_uin,
        normalize_external_links, safe_call, strip_external_links,
    )


TweetBatch = tuple[str, str, list[TweetItem]]


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
    LARK_PLATFORM_NAMES = {"lark", "feishu"}
    LARK_TEXT_CHUNK_SIZE = 28000
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

        nodes = self._build_nodes(event, username, instance, tweets, notices=notices)
        raw_nodes = self._build_onebot_nodes(
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
                nodes_nv = self._build_nodes(
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

        nodes = self._build_nodes_for_uin(10000, username, instance, tweets)
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
            nodes_nv = self._build_nodes_for_uin(
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
            MessageChain([Plain(self.format_plain(username, instance, tweets))]),
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
        if self._should_use_lark_for_umo(context, umo):
            return await self._send_lark_merged_to_umo(context, umo, batches)

        if not self._should_use_forward_for_umo(
            context, umo
        ) or not self._should_use_merge_for_count(self._count_batch_tweets(batches)):
            return await self._send_merged_direct_to_umo(context, umo, batches)

        omitted_videos = self._count_attached_videos(batches)
        nodes = self._build_merged_nodes_for_uin(10000, batches)
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
            nodes_nv = self._build_merged_nodes_for_uin(
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
            MessageChain([Plain(self.format_merged_plain(batches))]),
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
                    self._build_direct_components(
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
                        self._build_direct_components(
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
                    [Plain(self.format_plain(username, instance, tweets, notices=notices))]
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
            MessageChain(self._build_direct_components(username, instance, tweets)),
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
                    self._build_direct_components(
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
            MessageChain([Plain(self.format_plain(username, instance, tweets))]),
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
            MessageChain(self._build_merged_direct_components(batches)),
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
                    self._build_merged_direct_components(
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
            MessageChain([Plain(self.format_merged_plain(batches))]),
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
        components = self._build_direct_components(
            username, instance, tweets, notices=notices
        )
        client = self._lark_client_from_event(event)
        if client is None:
            logger.warning("[NitterTweets] Lark client not found; using generic send")
            return await self._send_direct_event(
                event, username, instance, tweets, notices=notices
            )

        text = self._plain_text_from_components(components)
        reply_message_id = self._lark_reply_message_id(event)
        receive_id_type, receive_id = self._lark_event_target(event)
        text_attempt = await self._send_lark_text(
            client,
            text,
            "manual Lark tweet text",
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
            text_attempt = await self._send_lark_text(
                client,
                text,
                "manual Lark tweet text fallback",
                receive_id=receive_id,
                receive_id_type=receive_id_type,
            )
        if not (text_attempt.success or text_attempt.uncertain):
            return False

        media_attempt = await self._send_lark_event_media_with_retry(
            event, self._media_components(components), "manual Lark tweet media"
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
        components = self._build_direct_components(username, instance, tweets)
        text = self._plain_text_from_components(components)
        client, receive_id_type, receive_id = self._lark_client_and_target(
            context, umo
        )
        if client is None or not receive_id_type or not receive_id:
            logger.warning(
                f"[NitterTweets] Lark client or target not found for {umo}; "
                "using generic send"
            )
            return await self._send_direct_to_umo(
                context, umo, username, instance, tweets
            )

        text_attempt = await self._send_lark_text(
            client,
            text,
            "scheduled Lark tweet text",
            receive_id=receive_id,
            receive_id_type=receive_id_type,
        )
        if not (text_attempt.success or text_attempt.uncertain):
            return SendOutcome(success=False, error=text_attempt.error)

        media_attempt = await self._send_lark_umo_media_with_retry(
            context,
            umo,
            self._media_components(components),
            "scheduled Lark tweet media",
        )
        warning = text_attempt.warning or media_attempt.warning
        if not (media_attempt.success or media_attempt.uncertain):
            warning = media_attempt.error
            logger.warning(
                f"[NitterTweets] Lark tweet text sent to {umo} but media failed: "
                f"{media_attempt.error}"
            )
        return SendOutcome(success=True, warning=warning)

    async def _send_lark_merged_to_umo(
        self,
        context,
        umo: str,
        batches: list[TweetBatch],
    ) -> MergedSendOutcome:
        components = self._build_merged_direct_components(batches)
        omitted_videos = self._count_attached_videos(batches)
        text = self._plain_text_from_components(components)
        client, receive_id_type, receive_id = self._lark_client_and_target(
            context, umo
        )
        if client is None or not receive_id_type or not receive_id:
            logger.warning(
                f"[NitterTweets] Lark client or target not found for {umo}; "
                "using generic send"
            )
            return await self._send_merged_direct_to_umo(context, umo, batches)

        text_attempt = await self._send_lark_text(
            client,
            text,
            "merged scheduled Lark tweet text",
            receive_id=receive_id,
            receive_id_type=receive_id_type,
        )
        if not (text_attempt.success or text_attempt.uncertain):
            return MergedSendOutcome(
                success=False,
                mode="failed",
                omitted_videos=omitted_videos,
                error=text_attempt.error,
            )

        media_attempt = await self._send_lark_umo_media_with_retry(
            context,
            umo,
            self._media_components(components),
            "merged scheduled Lark tweet media",
        )
        warning = text_attempt.warning or media_attempt.warning
        if not (media_attempt.success or media_attempt.uncertain):
            warning = media_attempt.error
            logger.warning(
                f"[NitterTweets] merged Lark tweet text sent to {umo} but media "
                f"failed: {media_attempt.error}"
            )
        return MergedSendOutcome(
            success=True,
            mode=("uncertain_delivery" if text_attempt.uncertain else "text_media"),
            omitted_videos=omitted_videos,
            warning=warning,
        )

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

    async def _send_lark_event_media_with_retry(
        self,
        event,
        media_components: list,
        label: str,
    ) -> SendAttempt:
        async def send_chain(chain: MessageChain, send_label: str) -> SendAttempt:
            return await self._send_event_chain(event, chain, send_label)

        return await self._send_media_with_video_retry(
            media_components,
            label,
            send_chain,
            "[NitterTweets] sent media without video/GIF attachments after initial failure",
        )

    async def _send_lark_umo_media_with_retry(
        self,
        context,
        umo: str,
        media_components: list,
        label: str,
    ) -> SendAttempt:
        async def send_chain(chain: MessageChain, send_label: str) -> SendAttempt:
            return await self._send_context_message(context, umo, chain, send_label)

        return await self._send_media_with_video_retry(
            media_components,
            label,
            send_chain,
            f"[NitterTweets] sent media to {umo} without video/GIF attachments "
            "after initial failure",
        )

    async def _send_media_with_video_retry(
        self,
        media_components: list,
        label: str,
        send_chain,
        retry_success_log: str,
    ) -> SendAttempt:
        if not media_components:
            return SendAttempt(success=True)

        attempt = await send_chain(MessageChain(media_components), label)
        if attempt.success or not attempt.retryable:
            return attempt

        without_videos = [
            component for component in media_components if not isinstance(component, Video)
        ]
        if len(without_videos) == len(media_components):
            return attempt
        if not without_videos:
            logger.warning(
                "[NitterTweets] 媒体附件发送失败，全部为视频/GIF，标记为不确定"
            )
            return SendAttempt(
                success=False,
                retryable=False,
                uncertain=True,
                error=attempt.error,
                warning="视频/GIF 附件发送状态不确定，已跳过降级重试。",
            )

        retry_attempt = await send_chain(
            MessageChain(without_videos), f"{label} without videos"
        )
        if retry_attempt.success:
            logger.warning(retry_success_log)
            return SendAttempt(success=True, error=attempt.error)
        return retry_attempt

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

    async def _send_lark_text(
        self,
        client,
        text: str,
        label: str,
        reply_message_id: str | None = None,
        receive_id: str | None = None,
        receive_id_type: str | None = None,
    ) -> SendAttempt:
        text = (text or "").strip()
        if not text:
            return SendAttempt(success=True)
        if client is None or getattr(client, "im", None) is None:
            error = "Lark API client is unavailable"
            logger.warning(f"Failed to send {label}: {error}")
            return SendAttempt(success=False, retryable=False, error=error)

        try:
            from lark_oapi.api.im.v1 import (
                CreateMessageRequest,
                CreateMessageRequestBody,
                ReplyMessageRequest,
                ReplyMessageRequestBody,
            )
        except Exception as exc:
            error = f"lark_oapi is unavailable: {exc}"
            logger.warning(f"Failed to send {label}: {error}")
            return SendAttempt(success=False, retryable=True, error=error)

        try:
            for chunk in self._split_lark_text(text):
                content = json.dumps({"text": chunk}, ensure_ascii=False)
                if reply_message_id:
                    request = (
                        ReplyMessageRequest.builder()
                        .message_id(reply_message_id)
                        .request_body(
                            ReplyMessageRequestBody.builder()
                            .content(content)
                            .msg_type("text")
                            .build()
                        )
                        .build()
                    )
                    response = await client.im.v1.message.areply(request)
                else:
                    if not receive_id or not receive_id_type:
                        error = "Lark receive_id or receive_id_type is missing"
                        logger.warning(f"Failed to send {label}: {error}")
                        return SendAttempt(
                            success=False, retryable=True, error=error
                        )
                    request = (
                        CreateMessageRequest.builder()
                        .receive_id_type(receive_id_type)
                        .request_body(
                            CreateMessageRequestBody.builder()
                            .receive_id(receive_id)
                            .msg_type("text")
                            .content(content)
                            .build()
                        )
                        .build()
                    )
                    response = await client.im.v1.message.acreate(request)

                if not response.success():
                    error = (
                        f"Lark API returned {getattr(response, 'code', '')}: "
                        f"{getattr(response, 'msg', '')}"
                    )
                    logger.warning(f"Failed to send {label}: {error}")
                    return SendAttempt(
                        success=False, retryable=True, error=error
                    )
        except Exception as exc:
            error = str(exc)
            if self._is_uncertain_delivery_error(exc):
                warning = self.UNCERTAIN_DELIVERY_WARNING
                target = receive_id or reply_message_id or receive_id_type or "unknown"
                self._log_uncertain_delivery(label, target, exc)
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

    def _build_nodes(
        self, event, username: str, instance: str, tweets: list[TweetItem],
        exclude_videos: bool = False, notices: list[str] | None = None,
    ):
        return self._build_nodes_for_uin(
            node_uin(event), username, instance, tweets, exclude_videos, notices
        )

    def _build_nodes_for_uin(
        self, uin, username: str, instance: str, tweets: list[TweetItem],
        exclude_videos: bool = False, notices: list[str] | None = None,
    ):
        nodes = Nodes([])
        nodes.nodes.append(
            Node(
                uin=uin,
                name="Nitter",
                content=[
                    Plain(self._format_header(username, instance, len(tweets), notices))
                ],
            )
        )

        for index, tweet in enumerate(tweets, 1):
            nodes.nodes.append(
                Node(
                    uin=uin,
                    name=f"@{username}",
                    content=self._build_components(
                        index, username, tweet, exclude_videos=exclude_videos
                    ),
                )
            )
        return nodes

    def _build_merged_nodes_for_uin(
        self, uin, batches: list[TweetBatch], exclude_videos: bool = False,
    ):
        nodes = Nodes([])
        nodes.nodes.append(
            Node(
                uin=uin,
                name="Nitter",
                content=[Plain(self.format_merged_header(batches))],
            )
        )

        index = 1
        for username, instance, tweets in batches:
            for tweet in tweets:
                nodes.nodes.append(
                    Node(
                        uin=uin,
                        name=f"@{username}",
                        content=self._build_components(
                            index, username, tweet, source=instance,
                            exclude_videos=exclude_videos,
                        ),
                    )
                )
                index += 1
        return nodes

    def _build_direct_components(
        self,
        username: str,
        instance: str,
        tweets: list[TweetItem],
        exclude_videos: bool = False,
        notices: list[str] | None = None,
    ):
        components = [
            Plain(self._format_header(username, instance, len(tweets), notices))
        ]
        for index, tweet in enumerate(tweets, 1):
            components.extend(
                self._build_direct_tweet_components(
                    index,
                    username,
                    tweet,
                    exclude_videos=exclude_videos,
                )
            )
        return components

    def _build_merged_direct_components(
        self, batches: list[TweetBatch], exclude_videos: bool = False,
    ):
        components = [Plain(self.format_merged_header(batches))]
        index = 1
        for username, instance, tweets in batches:
            for tweet in tweets:
                components.extend(
                    self._build_direct_tweet_components(
                        index,
                        username,
                        tweet,
                        source=instance,
                        exclude_videos=exclude_videos,
                    )
                )
                index += 1
        return components

    def _build_direct_tweet_components(
        self,
        index: int,
        username: str,
        tweet: TweetItem,
        source: str = "",
        exclude_videos: bool = False,
    ):
        components = self._build_components(
            index,
            username,
            tweet,
            source=source,
            exclude_videos=exclude_videos,
        )
        if components and isinstance(components[0], Plain):
            components[0].text = "\n\n" + components[0].text
        return components

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
        return str(platform or "").strip().lower() in cls.LARK_PLATFORM_NAMES

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

    @classmethod
    def _lark_client_and_target(cls, context, umo: str):
        platform_id, message_type, session_id = cls._parse_umo(umo)
        platform = cls._platform_inst_from_context(context, platform_id)
        client = cls._lark_client_from_platform(platform)
        receive_id_type = cls._lark_receive_id_type(message_type)
        receive_id = cls._lark_receive_id(message_type, session_id)
        return client, receive_id_type, receive_id

    @classmethod
    def _lark_client_from_event(cls, event):
        client = getattr(event, "bot", None)
        if cls._is_lark_client(client):
            return client

        platform = getattr(event, "platform", None) or getattr(
            event, "platform_inst", None
        )
        client = cls._lark_client_from_platform(platform)
        if client is not None:
            return client

        context = getattr(event, "context", None)
        try:
            umo = getattr(event, "unified_msg_origin", "")
        except Exception:
            umo = ""
        if context and umo:
            client, _, _ = cls._lark_client_and_target(context, str(umo))
            return client
        return None

    @classmethod
    def _lark_client_from_platform(cls, platform):
        if platform is None:
            return None
        for attr in ("lark_api", "client", "_client", "bot"):
            client = getattr(platform, attr, None)
            if cls._is_lark_client(client):
                return client
        if cls._is_lark_client(platform):
            return platform
        return None

    @staticmethod
    def _is_lark_client(client) -> bool:
        return bool(client is not None and getattr(client, "im", None) is not None)

    @staticmethod
    def _parse_umo(umo: str) -> tuple[str, str, str]:
        parts = str(umo or "").split(":", 2)
        if len(parts) != 3:
            return "", "", ""
        return parts[0].strip(), parts[1].strip(), parts[2].strip()

    @classmethod
    def _lark_receive_id_type(cls, message_type: str) -> str:
        message_type = message_type.strip().lower()
        if message_type in {"groupmessage", "group", "group_message"}:
            return "chat_id"
        if message_type in {"friendmessage", "private", "private_message"}:
            return "open_id"
        return ""

    @classmethod
    def _lark_receive_id(cls, message_type: str, session_id: str) -> str:
        if cls._lark_receive_id_type(message_type) == "chat_id" and "%" in session_id:
            return session_id.split("%", 1)[1]
        return session_id

    @staticmethod
    def _lark_reply_message_id(event) -> str:
        message_obj = getattr(event, "message_obj", None)
        for source in (message_obj, event):
            for attr in ("message_id", "id"):
                value = getattr(source, attr, None)
                if value:
                    return str(value)
        return ""

    @classmethod
    def _lark_event_target(cls, event) -> tuple[str, str]:
        try:
            umo = getattr(event, "unified_msg_origin", "")
        except Exception:
            umo = ""
        _, message_type, session_id = cls._parse_umo(str(umo))
        receive_id_type = cls._lark_receive_id_type(message_type)
        receive_id = cls._lark_receive_id(message_type, session_id)
        return receive_id_type, receive_id

    @staticmethod
    def _plain_text_from_components(components) -> str:
        parts = [
            component.text
            for component in components
            if isinstance(component, Plain) and component.text
        ]
        return "\n".join(part.strip() for part in parts if part.strip())

    @staticmethod
    def _media_components(components) -> list:
        return [
            component
            for component in components
            if isinstance(component, (Image, Video))
        ]

    @classmethod
    def _split_lark_text(cls, text: str) -> list[str]:
        text = text or ""
        if len(text) <= cls.LARK_TEXT_CHUNK_SIZE:
            return [text]

        chunks = []
        remaining = text
        while len(remaining) > cls.LARK_TEXT_CHUNK_SIZE:
            split_at = remaining.rfind("\n\n", 0, cls.LARK_TEXT_CHUNK_SIZE)
            if split_at <= 0:
                split_at = remaining.rfind("\n", 0, cls.LARK_TEXT_CHUNK_SIZE)
            if split_at <= 0:
                split_at = cls.LARK_TEXT_CHUNK_SIZE
            chunks.append(remaining[:split_at].strip())
            remaining = remaining[split_at:].strip()
        if remaining:
            chunks.append(remaining)
        return [chunk for chunk in chunks if chunk]

    def _build_components(
        self, index: int, username: str, tweet: TweetItem, source: str = "",
        exclude_videos: bool = False,
    ):
        text = self.format_tweet_with_source(index, username, tweet, source)
        components = [Plain(text)]
        video_notice_added = False
        for media in tweet.media:
            if not media.path:
                continue
            if media.is_video and exclude_videos:
                if not video_notice_added:
                    components.append(
                        Plain(
                            "视频/GIF 附件未作为消息发送，请打开原文查看："
                            f"{tweet.x_url}"
                        )
                    )
                    video_notice_added = True
                continue
            if media.is_video and not self.send_video_attachments:
                if not video_notice_added:
                    components.append(
                        Plain(
                            "视频/GIF 附件发送功能仍在优化，当前按配置不发送，"
                            f"请打开原文查看：{tweet.x_url}"
                        )
                    )
                    video_notice_added = True
                continue
            if media.is_image and self.send_image_attachments:
                components.append(Image.fromFileSystem(str(media.path)))
            elif media.is_video:
                components.append(Video.fromFileSystem(str(media.path)))
        return components

    def _build_onebot_nodes(
        self,
        event,
        username: str,
        instance: str,
        tweets: list[TweetItem],
        notices: list[str] | None = None,
    ) -> list[dict]:
        uin = str(node_uin(event))
        items = [
            {
                "name": "Nitter",
                "uin": uin,
                "content": [
                    self._raw_text(
                        self._format_header(username, instance, len(tweets), notices)
                    )
                ],
            }
        ]
        for index, tweet in enumerate(tweets, 1):
            content = [self._raw_text(self.format_tweet(index, username, tweet))]
            content.extend(
                self._raw_media(media)
                for media in tweet.media
                if media.path
                and (
                    (media.is_image and self.send_image_attachments)
                    or (media.is_video and self.send_video_attachments)
                )
            )
            items.append({"name": f"@{username}", "uin": uin, "content": content})

        return [
            {
                "type": "node",
                "data": {
                    "name": item["name"],
                    "uin": item["uin"],
                    "content": item["content"],
                },
            }
            for item in items
        ]

    @staticmethod
    def _raw_text(text: str) -> dict:
        return {"type": "text", "data": {"text": text}}

    @staticmethod
    def _raw_media(media: TweetMedia) -> dict:
        uri = file_uri(media.path)
        if media.is_image:
            return {"type": "image", "data": {"file": uri}}
        return {"type": "video", "data": {"file": uri}}

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

    def format_plain(
        self,
        username: str,
        instance: str,
        tweets: list[TweetItem],
        notices: list[str] | None = None,
    ) -> str:
        blocks = [self._format_header(username, instance, len(tweets), notices)]
        notice_text = self._format_notices(notices)
        if notice_text and notice_text not in blocks[0]:
            blocks.append(notice_text)
        blocks.extend(
            self.format_tweet(index, username, tweet)
            for index, tweet in enumerate(tweets, 1)
        )
        return "\n\n".join(blocks)

    def format_merged_plain(self, batches: list[TweetBatch]) -> str:
        blocks = [self.format_merged_header(batches)]
        index = 1
        for username, instance, tweets in batches:
            for tweet in tweets:
                blocks.append(
                    self.format_tweet_with_source(index, username, tweet, instance)
                )
                index += 1
        return "\n\n".join(blocks)

    @staticmethod
    def format_merged_header(batches: list[TweetBatch]) -> str:
        total = sum(len(tweets) for _, _, tweets in batches)
        accounts = "，".join(
            f"@{username} {len(tweets)} 条" for username, _, tweets in batches
        )
        lines = [
            f"Nitter 本次检查发现 {total} 条新推文",
            f"更新账号：{accounts}",
        ]
        return "\n".join(lines)

    @staticmethod
    def format_tweet_with_source(
        index: int, username: str, tweet: TweetItem, source: str = ""
    ) -> str:
        return TweetSender.format_tweet(index, username, tweet, source=source)

    @staticmethod
    def format_tweet(
        index: int,
        username: str,
        tweet: TweetItem,
        source: str = "",
    ) -> str:
        blocks = [f"#{index} @{username}"]
        if tweet.published:
            blocks[0] = f"{blocks[0]}\n时间：{tweet.published}"

        original_text = normalize_external_links(tweet.text).strip()
        if original_text:
            blocks.append(f"原文：\n{original_text}")

        translation = strip_external_links(tweet.translation)
        if translation:
            blocks.append(f"翻译：\n{translation}")

        image_caption = normalize_external_links(tweet.image_caption).strip()
        if image_caption:
            blocks.append(f"识图：\n{image_caption}")

        ai_comment = normalize_external_links(tweet.ai_comment).strip()
        if ai_comment:
            blocks.append(f"评论：\n{ai_comment}")

        original_link = tweet.x_url or tweet.link
        if original_link:
            blocks.append(f"原帖：\n{original_link}")

        if tweet.media_warnings:
            blocks.append(
                "媒体提示：\n"
                + "\n".join(f"- {warning}" for warning in tweet.media_warnings)
            )

        media_summary = TweetSender._format_media_summary(tweet)
        if media_summary:
            blocks.append(media_summary)

        if source:
            blocks.append(f"Nitter：{TweetSender._format_instance_label(source)}")

        return "\n\n".join(blocks)

    @classmethod
    def _format_header(
        cls,
        username: str,
        instance: str,
        tweet_count: int,
        notices: list[str] | None = None,
    ) -> str:
        lines = [
            f"@{username} 最近 {tweet_count} 条推文",
        ]
        if instance:
            lines.append(f"Nitter：{cls._format_instance_label(instance)}")
        notice_text = cls._format_notices(notices)
        if notice_text:
            lines.append(notice_text)
        return "\n".join(lines)

    @staticmethod
    def _format_notices(notices: list[str] | None = None) -> str:
        clean_notices = [
            notice.strip() for notice in notices or [] if notice and notice.strip()
        ]
        if not clean_notices:
            return ""
        return "\n".join(
            ["处理提示：", *[f"- {notice}" for notice in clean_notices]]
        )

    @staticmethod
    def _format_media_summary(tweet: TweetItem) -> str:
        image_count = sum(1 for item in tweet.media if item.is_image)
        video_count = sum(1 for item in tweet.media if item.is_video)
        parts = []
        if image_count:
            parts.append(f"图片 {image_count} 张")
        if video_count:
            parts.append(f"视频/GIF {video_count} 个")
        if not parts:
            return ""
        return "媒体：" + "，".join(parts)

    @staticmethod
    def _format_instance_label(instance: str) -> str:
        parsed = urlparse(instance)
        return parsed.netloc or parsed.path or instance
