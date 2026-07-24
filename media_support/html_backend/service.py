# -*- coding: utf-8 -*-
"""HTML Nitter facade for plugin: blogger HTML + search pools."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

try:
    from ...shared.utils import TweetItem
except ImportError:  # pragma: no cover
    from shared.utils import TweetItem

try:
    from ..host_score import HostScoreBook
    from .http_session import DEFAULT_UA, HttpSession
    from .logging_util import QuietHtmlLog
    from .pool import HtmlNitterPool, PoolConfig
    from .query import normalize_query, query_kind
    from .rate_limit import RateLimitConfig, RateLimiter
except ImportError:  # pragma: no cover
    from media_support.host_score import HostScoreBook
    from media_support.html_backend.http_session import DEFAULT_UA, HttpSession
    from media_support.html_backend.logging_util import QuietHtmlLog
    from media_support.html_backend.pool import HtmlNitterPool, PoolConfig
    from media_support.html_backend.query import normalize_query, query_kind
    from media_support.html_backend.rate_limit import RateLimitConfig, RateLimiter

DEFAULT_HTML_INSTANCES = [
    "https://nitter.tiekoetter.com",
    "https://nitter.poast.org",
    "https://nitter.kareem.one",
]


@dataclass
class HtmlBackendConfig:
    user_html_fallback: bool = True
    blogger_html_instances: list[str] = field(
        default_factory=lambda: list(DEFAULT_HTML_INSTANCES)
    )
    search_enabled: bool = True
    search_instances: list[str] = field(
        default_factory=lambda: list(DEFAULT_HTML_INSTANCES)
    )
    proxy: str | None = None
    session_dir: str | Path | None = None
    html_timeout: float = 35.0
    html_min_interval: float = 3.0
    html_max_pages: int = 1
    filter_reposts: bool = True


class HtmlNitterService:
    """HTML-only service. Plugin RSS remains on NitterClient."""

    def __init__(
        self,
        config: HtmlBackendConfig | None = None,
        *,
        log: Callable[[str], None] | None = None,
        brief_log: bool = True,
    ):
        self.config = config or HtmlBackendConfig()
        raw_log = log or (lambda _m: None)
        # Always wrap so session-load / gate-ok spam is capped even if caller
        # passes a raw logger.info sink.
        self.log = (
            log
            if isinstance(log, QuietHtmlLog)
            else QuietHtmlLog(raw_log, brief=bool(brief_log))
        )
        session_dir = self.config.session_dir
        rate = RateLimitConfig(global_min_interval=self.config.html_min_interval)
        self.limiter = RateLimiter(rate)
        self.session = HttpSession(
            proxy=self.config.proxy,
            user_agent=DEFAULT_UA,
            timeout=self.config.html_timeout,
            session_dir=Path(session_dir) if session_dir else None,
            log=self.log,
        )
        # Separate score books: blogger HTML fallback vs search/tag pool.
        self.blogger_html = HtmlNitterPool(
            PoolConfig(
                instances=list(self.config.blogger_html_instances),
                proxy=self.config.proxy,
                timeout=self.config.html_timeout,
                session_dir=session_dir,
                rate=rate,
                max_pages=self.config.html_max_pages,
                filter_reposts=self.config.filter_reposts,
            ),
            log=self.log,
            shared_limiter=self.limiter,
            shared_session=self.session,
            score_book=HostScoreBook(),
        )
        self.search_pool = HtmlNitterPool(
            PoolConfig(
                instances=list(self.config.search_instances),
                proxy=self.config.proxy,
                timeout=self.config.html_timeout,
                session_dir=session_dir,
                rate=rate,
                max_pages=self.config.html_max_pages,
                filter_reposts=False,
            ),
            log=self.log,
            shared_limiter=self.limiter,
            shared_session=self.session,
            score_book=HostScoreBook(),
        )

    def fetch_user(
        self,
        username: str,
        limit: int = 5,
        *,
        instance: str | None = None,
    ) -> tuple[str, list[TweetItem]]:
        return self.blogger_html.fetch_user(username, limit, instance=instance)

    def search(
        self,
        query: str,
        limit: int = 5,
        *,
        kind: str | None = None,
        instance: str | None = None,
        max_pages: int | None = None,
    ) -> tuple[str, list[TweetItem]]:
        if not self.config.search_enabled:
            raise RuntimeError("search_enabled is false")
        q = normalize_query(query)
        resolved = kind or query_kind(q)
        return self.search_pool.search(
            q,
            limit,
            kind=resolved,
            instance=instance,
            max_pages=max_pages,
        )
