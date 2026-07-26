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
    from ..config import (
        configured_merge_tweet_threshold,
        resolve_send_image_attachments,
        resolve_send_video_attachments,
    )
    from ..shared import TweetItem
    from .outcomes import SendAttempt, SendOutcome
    from .platforms import PlatformDeliveryRegistry, PlatformResolver
    from .sender_capabilities import SenderCapabilitiesMixin
    from .sender_direct import SenderDirectMixin
    from .sender_forward import SenderForwardMixin
    from .sender_merged import SenderMergedForwardMixin
    from .sender_helpers import SenderHelpersMixin
    from ..rendering import TweetMessageRenderer
except ImportError:
    from config import (
        configured_merge_tweet_threshold,
        resolve_send_image_attachments,
        resolve_send_video_attachments,
    )
    from shared import TweetItem
    from delivery import (
        PlatformDeliveryRegistry,
        PlatformResolver,
        SendAttempt,
        SendOutcome,
    )
    from delivery.sender_capabilities import SenderCapabilitiesMixin
    from delivery.sender_direct import SenderDirectMixin
    from delivery.sender_forward import SenderForwardMixin
    from delivery.sender_merged import SenderMergedForwardMixin
    from delivery.sender_helpers import SenderHelpersMixin
    from rendering import TweetMessageRenderer


class TweetSender(
    SenderCapabilitiesMixin,
    SenderDirectMixin,
    SenderForwardMixin,
    SenderMergedForwardMixin,
    SenderHelpersMixin,
):
    FORWARD_TWEET_CHUNK_SIZE = 8
    # When NapCat/OneBot rejects a forward (often retcode 1200 / res_id fail),
    # recursively split the tweet list and retry smaller merges.
    FORWARD_SPLIT_MIN_TWEETS = 1
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


    @staticmethod
    def resolve_link_style(platform_name: str = "") -> str:
        name = str(platform_name or "").strip().lower()
        if name in {"telegram", "tg"}:
            return "telegram_md"
        return "plain"

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
        omit_status_url: bool = True,
        hide_original_when_translated: bool = False,
        link_style: str = "plain",
        on_sent_progress=None,
    ) -> bool:
        sent_count = 0
        total = len(tweets)

        def record_delivered(delta: int) -> None:
            nonlocal sent_count
            try:
                delivered = max(0, int(delta))
            except (TypeError, ValueError, OverflowError):
                return
            if delivered <= 0 or sent_count >= total:
                return
            sent_count = min(total, sent_count + delivered)
            self._notify_sent_progress(on_sent_progress, sent_count)

        adapter = self._delivery_adapter_for_event(event)
        if link_style == "plain":
            platform_name = getattr(adapter, "name", "") or ""
            link_style = self.resolve_link_style(platform_name)
        if not adapter.supports_merged_forward or not self._should_use_merge_for_count(
            len(tweets)
        ):
            accepted = await self._send_direct_event(
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
            if accepted:
                record_delivered(total)
            return accepted

        if self._should_chunk_forward_tweets(len(tweets)):
            accepted = await self._send_event_forward_chunks(
                event, username, instance, tweets, notices=notices,
                tweet_start_index=tweet_start_index,
                media_only=media_only,
                omit_status_url=omit_status_url,
                hide_original_when_translated=hide_original_when_translated,
                link_style=link_style,
                on_delivered=record_delivered,
            )
            if accepted and sent_count < total:
                record_delivered(total - sent_count)
            return accepted

        accepted = await self._send_event_forward_chunk(
            event, username, instance, tweets, notices=notices,
            tweet_start_index=tweet_start_index,
            media_only=media_only,
            omit_status_url=omit_status_url,
            hide_original_when_translated=hide_original_when_translated,
            link_style=link_style,
            on_delivered=record_delivered,
        )
        if accepted and sent_count < total:
            record_delivered(total - sent_count)
        return accepted

    def should_merge_for_event(self, event, tweet_count: int) -> bool:
        return (
            self._delivery_adapter_for_event(event).supports_merged_forward
            and self._should_use_merge_for_count(tweet_count)
        )

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
        omit_status_url: bool = True,
        hide_original_when_translated: bool = False,
        link_style: str = "plain",
    ) -> bool:
        return (
            await self.send_to_umo_with_outcome(
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
        omit_status_url: bool = True,
        hide_original_when_translated: bool = False,
        link_style: str = "plain",
    ) -> SendOutcome:
        adapter = self._delivery_adapter_for_umo(context, umo)
        if link_style == "plain":
            link_style = self.resolve_link_style(getattr(adapter, "name", ""))
        if not adapter.supports_merged_forward or not self._should_use_merge_for_count(
            len(tweets)
        ):
            return await self._send_direct_to_umo(
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

        if self._should_chunk_forward_tweets(len(tweets)):
            return await self._send_forward_chunks_to_umo(
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

        return await self._send_forward_chunk_to_umo(
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

    async def send_summary_to_umo(self, context, umo: str, summary: str) -> SendOutcome:
        return await self._delivery_adapter_for_umo(context, umo).send_summary_to_umo(
            context, umo, summary
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
    def _is_forward_payload_rejected_error(cls, exc: Exception | None) -> bool:
        """OneBot/NapCat explicit reject of merged-forward content (e.g. retcode 1200)."""
        if exc is None:
            return False
        if ActionFailed is not None and isinstance(exc, ActionFailed):
            retcode = getattr(exc, "retcode", None)
            try:
                if int(retcode) == 1200:
                    return True
            except (TypeError, ValueError):
                pass
        text = str(exc or "")
        lowered = text.lower()
        if "retcode=1200" in lowered or "retcode': 1200" in lowered:
            return True
        if "res_id" in lowered and ("失败" in text or "fail" in lowered):
            return True
        if "发送转发消息" in text and "失败" in text:
            return True
        return False
