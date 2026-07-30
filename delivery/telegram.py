from __future__ import annotations

import asyncio
import re
from typing import Any

from astrbot.api import logger

from .default import DefaultDeliveryAdapter
from .outcomes import SendAttempt

try:
    from telegram import LinkPreviewOptions
except ImportError:  # pragma: no cover - Telegram is optional at import time
    LinkPreviewOptions = None


class _TelegramClientWithoutLinkPreview:
    """Proxy the Telegram client while disabling previews for text links."""

    def __init__(self, client: Any):
        self._client = client

    async def send_message(self, *args, **kwargs):
        payload = dict(kwargs)
        if LinkPreviewOptions is not None:
            payload["link_preview_options"] = LinkPreviewOptions(is_disabled=True)
        else:  # pragma: no cover - only old python-telegram-bot versions
            payload["disable_web_page_preview"] = True
        try:
            return await self._client.send_message(*args, **payload)
        except TypeError as exc:
            # Keep compatibility with clients exposing the legacy keyword only.
            if (
                "link_preview_options" not in str(exc)
                or "link_preview_options" not in payload
            ):
                raise
            payload.pop("link_preview_options", None)
            payload["disable_web_page_preview"] = True
            return await self._client.send_message(*args, **payload)

    def __getattr__(self, name: str):
        return getattr(self._client, name)


class TelegramDeliveryAdapter(DefaultDeliveryAdapter):
    name = "telegram"
    is_telegram = True

    FLOOD_CONTROL_MAX_WAIT_SECONDS = 120.0
    FLOOD_CONTROL_RETRY_PADDING_SECONDS = 1.0

    @staticmethod
    def _telegram_event_sender(event):
        client = getattr(event, "client", None)
        sender = getattr(type(event), "send_with_client", None)
        if (
            client is None
            or not callable(getattr(client, "send_message", None))
            or not callable(sender)
        ):
            return None
        return sender, client

    def _telegram_context_sender(self):
        platform = getattr(self.profile, "platform", None)
        for owner in (
            platform,
            getattr(platform, "adapter", None),
            getattr(platform, "platform", None),
        ):
            for attr in ("client", "bot"):
                client = getattr(owner, attr, None)
                if client is not None and callable(
                    getattr(client, "send_message", None)
                ):
                    try:
                        from astrbot.core.platform.sources.telegram.tg_event import (
                            TelegramPlatformEvent,
                        )
                    except ImportError:  # pragma: no cover - non-AstrBot tests
                        return None
                    return TelegramPlatformEvent.send_with_client, client
        return None

    @staticmethod
    def _event_chat_target(event) -> str:
        message_obj = getattr(event, "message_obj", None)
        group_id = getattr(message_obj, "group_id", None)
        if group_id:
            return str(group_id)
        getter = getattr(event, "get_sender_id", None)
        if callable(getter):
            try:
                sender_id = getter()
            except Exception:
                sender_id = ""
            if sender_id:
                return str(sender_id)
        return ""

    def _context_chat_target(self, umo: str) -> str:
        session_id = str(getattr(self.profile, "session_id", "") or "").strip()
        if session_id:
            return session_id
        return str(umo or "").rsplit(":", 1)[-1].strip()

    async def _send_without_preview(self, sender, client, chain, target) -> None:
        await sender(_TelegramClientWithoutLinkPreview(client), chain, target)

    async def send_event_chain(self, event, chain, label: str) -> SendAttempt | None:
        resolved = self._telegram_event_sender(event)
        if resolved is None:
            return None
        sender, client = resolved
        target = self.sender._event_target(event)
        chat_target = self._event_chat_target(event)
        if not chat_target:
            return None
        try:
            await self._send_without_preview(sender, client, chain, chat_target)
        except Exception as exc:
            flood_attempt = await self.sender._adapter_flood_control_attempt(
                self,
                lambda: self._send_without_preview(sender, client, chain, chat_target),
                label,
                target,
                exc,
            )
            if flood_attempt is not None:
                return flood_attempt
            return self.sender._send_exception_attempt(exc, label, target)
        return SendAttempt(success=True)

    async def send_context_chain(
        self, context, umo: str, chain, label: str
    ) -> SendAttempt | None:
        resolved = self._telegram_context_sender()
        if resolved is None:
            return None
        sender, client = resolved
        target = str(umo or "")
        chat_target = self._context_chat_target(umo)
        if not chat_target:
            return None
        try:
            await self._send_without_preview(sender, client, chain, chat_target)
        except Exception as exc:
            flood_attempt = await self.sender._adapter_flood_control_attempt(
                self,
                lambda: self._send_without_preview(sender, client, chain, chat_target),
                label,
                target,
                exc,
            )
            if flood_attempt is not None:
                return flood_attempt
            return self.sender._send_exception_attempt(exc, label, target)
        return SendAttempt(success=True)

    async def retry_after_flood_control(
        self,
        send_call,
        label: str,
        target: str,
        exc: Exception,
    ) -> SendAttempt | None:
        delay = self.flood_control_retry_delay(exc)
        if delay is None:
            return None

        if delay > self.FLOOD_CONTROL_MAX_WAIT_SECONDS:
            warning = f"Telegram 限流，需等待 {delay:g} 秒，已跳过降级重试。"
            logger.warning(
                "[NitterTweets] Telegram 限流等待过长，跳过降级重试: "
                f"label={label}, target={target}, retry_after={delay:g}s, "
                f"error={exc}"
            )
            return SendAttempt(
                success=False,
                retryable=False,
                error=str(exc),
                warning=warning,
            )

        wait_seconds = delay + self.FLOOD_CONTROL_RETRY_PADDING_SECONDS
        logger.info(
            "[NitterTweets] Telegram 限流，等待后重试同一条消息: "
            f"label={label}, target={target}, retry_after={delay:g}s, "
            f"wait={wait_seconds:g}s"
        )
        await asyncio.sleep(wait_seconds)

        try:
            sent = await send_call()
        except Exception as retry_exc:
            retry_delay = self.flood_control_retry_delay(retry_exc)
            if retry_delay is not None:
                warning = (
                    f"Telegram 限流仍未解除，需等待 {retry_delay:g} 秒，"
                    "已跳过降级重试。"
                )
                logger.warning(
                    "[NitterTweets] Telegram 限流仍未解除，跳过降级重试: "
                    f"label={label}, target={target}, retry_after={retry_delay:g}s, "
                    f"error={retry_exc}"
                )
                return SendAttempt(
                    success=False,
                    retryable=False,
                    error=str(retry_exc),
                    warning=warning,
                )
            return self.sender._send_exception_attempt(retry_exc, label, target)

        if sent is False:
            error = "未找到目标平台或平台不支持主动发送"
            logger.warning(
                f"[NitterTweets] Telegram 发送失败: "
                f"label={label}, target={target}, error={error}"
            )
            return SendAttempt(success=False, retryable=True, error=error)
        return SendAttempt(success=True)

    @staticmethod
    def flood_control_retry_delay(exc: Exception) -> float | None:
        text = str(exc or "").lower()
        if "flood" not in text and "retry after" not in text and "retry in" not in text:
            return None
        match = re.search(
            r"(?:retry\s+(?:in|after))\s+(\d+(?:\.\d+)?)\s*(?:s|sec|second|seconds)?",
            text,
        )
        if not match:
            return None
        try:
            return max(0.0, float(match.group(1)))
        except ValueError:
            return None
