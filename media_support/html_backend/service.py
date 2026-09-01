"""HTML Nitter facade for self-hosted search and list timelines."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

try:
    from ...shared.utils import TweetItem
except ImportError:  # pragma: no cover
    from shared.utils import TweetItem

try:
    from ..host_score import HostScoreBook
    from .http_session import HttpSession
    from .logging_util import QuietHtmlLog
    from .pool import HtmlNitterPool, HtmlSearchResult, PoolConfig
    from .query import normalize_query, query_kind
    from .rate_limit import RateLimitConfig, RateLimiter
except ImportError:  # pragma: no cover
    from media_support.host_score import HostScoreBook
    from media_support.html_backend.http_session import HttpSession
    from media_support.html_backend.logging_util import QuietHtmlLog
    from media_support.html_backend.pool import (
        HtmlNitterPool,
        HtmlSearchResult,
        PoolConfig,
    )
    from media_support.html_backend.query import normalize_query, query_kind
    from media_support.html_backend.rate_limit import RateLimitConfig, RateLimiter


@dataclass
class HtmlBackendConfig:
    instances: list[str] = field(default_factory=list)
    proxy: str | None = None
    session_dir: str | Path | None = None
    timeout: float = 35.0
    min_interval: float = 3.0
    max_pages: int = 1
    filter_reposts: bool = True
    # HTML retry policy.  Populated from the RSS retry config by NitterService
    # so a single retry setting governs both fetch paths.
    max_global_retries: int = 2
    retry_delay_base: float = 5.0
    retry_delay_on_cooldown: float = 10.0
    media_quality: str = "high"


class HtmlNitterService:
    """HTML-only service. Plugin RSS remains on NitterClient."""

    def __init__(
        self,
        config: HtmlBackendConfig | None = None,
        *,
        log: Callable[[str], None] | None = None,
        brief_log: bool = True,
        score_book: HostScoreBook | None = None,
    ):
        self.config = config or HtmlBackendConfig()
        raw_log = log or (lambda _m: None)
        # Always wrap repetitive per-host request logs even for a raw logger sink.
        self.log = (
            log
            if isinstance(log, QuietHtmlLog)
            else QuietHtmlLog(raw_log, brief=bool(brief_log))
        )
        session_dir = self.config.session_dir
        rate = RateLimitConfig(global_min_interval=self.config.min_interval)
        self.limiter = RateLimiter(rate)
        self.session = HttpSession(
            proxy=self.config.proxy,
            timeout=self.config.timeout,
            session_dir=Path(session_dir) if session_dir else None,
            log=self.log,
        )
        self.pool = HtmlNitterPool(
            PoolConfig(
                instances=list(self.config.instances),
                proxy=self.config.proxy,
                timeout=self.config.timeout,
                session_dir=session_dir,
                rate=rate,
                max_pages=self.config.max_pages,
                filter_reposts=self.config.filter_reposts,
                max_global_retries=self.config.max_global_retries,
                retry_delay_base=self.config.retry_delay_base,
                retry_delay_on_cooldown=self.config.retry_delay_on_cooldown,
                media_quality=self.config.media_quality,
            ),
            log=self.log,
            shared_limiter=self.limiter,
            shared_session=self.session,
            score_book=score_book or HostScoreBook(),
        )

    def fetch_user(
        self,
        username: str,
        limit: int = 5,
        *,
        instance: str | None = None,
        filter_reposts: bool | None = None,
    ) -> tuple[str, list[TweetItem]]:
        if not self.pool.instances and not instance:
            return "", []
        return self.pool.fetch_user(
            username,
            limit,
            instance=instance,
            filter_reposts=filter_reposts,
        )

    def search(
        self,
        query: str,
        limit: int = 5,
        *,
        kind: str | None = None,
        instance: str | None = None,
        max_pages: int | None = None,
        filter_reposts: bool | None = None,
        anchor_ids: list[str] | None = None,
    ) -> tuple[str, HtmlSearchResult]:
        q = normalize_query(query)
        resolved = kind or query_kind(q)
        return self.pool.search(
            q,
            limit,
            kind=resolved,
            instance=instance,
            max_pages=max_pages,
            filter_reposts=filter_reposts,
            anchor_ids=anchor_ids,
        )

    def fetch_list(
        self,
        list_id: str,
        limit: int = 5,
        *,
        instance: str | None = None,
        filter_reposts: bool | None = None,
        anchor_ids: list[str] | None = None,
    ) -> tuple[str, HtmlSearchResult]:
        """Fetch a Twitter List timeline through the shared HTML pool."""
        return self.pool.fetch_list(
            list_id,
            limit,
            instance=instance,
            filter_reposts=filter_reposts,
            anchor_ids=anchor_ids,
        )
