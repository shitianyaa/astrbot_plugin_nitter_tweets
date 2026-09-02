from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path

from astrbot.api import logger

try:
    from ..config import config_get, parse_config_bool
    from ..shared import TweetItem, clamp_float, clamp_int, sanitize_sensitive_text
except ImportError:
    from config import config_get, parse_config_bool
    from shared import TweetItem, clamp_float, clamp_int, sanitize_sensitive_text

from .client import NitterClient
from .html_backend.service import HtmlBackendConfig, HtmlNitterService


class NitterService(NitterClient):
    """One self-hosted instance pool with RSS and HTML capabilities."""

    def __init__(
        self,
        config,
        *,
        session_dir: str | Path | None = None,
        log: Callable[[str], None] | None = None,
    ):
        super().__init__(config)
        self.html = HtmlNitterService(
            HtmlBackendConfig(
                instances=list(self.instances),
                proxy=None,
                session_dir=session_dir,
                timeout=self.timeout,
                min_interval=clamp_float(
                    config_get(config, "html_min_interval", 3.0), 0.0, 120.0
                ),
                max_pages=clamp_int(config_get(config, "html_max_pages", 1), 1, 5),
                filter_reposts=parse_config_bool(
                    config_get(config, "filter_reposts_enabled", True), True
                ),
                max_global_retries=self.retry_attempts,
                retry_delay_base=self.retry_delay_seconds,
                retry_delay_on_cooldown=float(self.retry_delay_seconds) * 2,
                media_quality=str(config_get(config, "media_quality", "high") or "high")
                .strip()
                .lower(),
            ),
            log=log
            or (
                lambda message: logger.info(
                    f"[NitterTweets][html] {sanitize_sensitive_text(message)}"
                )
            ),
            brief_log=self.brief_log_enabled,
            score_book=self.host_scores,
        )

    @property
    def html_pool(self):
        return self.html.pool

    async def fetch_user(
        self,
        username: str,
        limit: int = 5,
        *,
        filter_reposts: bool | None = None,
    ) -> tuple[str, list[TweetItem]]:
        """Fetch a user timeline using RSS first and HTML automatically."""

        rss_error: Exception | None = None
        try:
            instance, tweets = await self.fetch_tweets(
                username,
                limit,
                filter_reposts=filter_reposts,
            )
            if tweets:
                return instance, tweets
        except Exception as exc:
            rss_error = exc

        try:
            instance, tweets = await asyncio.to_thread(
                self.fetch_user_html,
                username,
                limit,
                filter_reposts=filter_reposts,
            )
        except Exception:
            if rss_error is not None:
                raise rss_error
            raise
        if tweets:
            return instance, tweets
        if rss_error is not None:
            raise rss_error
        return instance, []

    async def fetch_user_from_instance(
        self,
        instance: str,
        username: str,
        limit: int = 5,
        *,
        filter_reposts: bool | None = None,
    ) -> tuple[str, list[TweetItem]]:
        """Probe one instance with RSS first and automatic HTML fallback."""
        rss_error: Exception | None = None
        try:
            used, tweets = await self.fetch_tweets_from_instance(
                instance,
                username,
                limit,
                filter_reposts=filter_reposts,
            )
            if tweets:
                return used, tweets
        except Exception as exc:
            rss_error = exc
        try:
            used, tweets = await asyncio.to_thread(
                self.fetch_user_html,
                username,
                limit,
                instance=instance,
                filter_reposts=filter_reposts,
            )
        except Exception:
            if rss_error is not None:
                raise rss_error
            raise
        if tweets:
            return used, tweets
        if rss_error is not None:
            raise rss_error
        return used, []

    def fetch_user_html(
        self,
        username: str,
        limit: int = 5,
        *,
        instance: str | None = None,
        filter_reposts: bool | None = None,
    ):
        return self.html.fetch_user(
            username,
            limit,
            instance=instance,
            filter_reposts=filter_reposts,
        )

    def search(self, *args, **kwargs):
        return self.html.search(*args, **kwargs)

    def fetch_list(self, *args, **kwargs):
        return self.html.fetch_list(*args, **kwargs)
