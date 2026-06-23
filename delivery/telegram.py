from __future__ import annotations

import asyncio
import re

from astrbot.api import logger

from .default import DefaultDeliveryAdapter
from .outcomes import SendAttempt


class TelegramDeliveryAdapter(DefaultDeliveryAdapter):
    name = "telegram"
    is_telegram = True

    FLOOD_CONTROL_MAX_WAIT_SECONDS = 120.0
    FLOOD_CONTROL_RETRY_PADDING_SECONDS = 1.0

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
