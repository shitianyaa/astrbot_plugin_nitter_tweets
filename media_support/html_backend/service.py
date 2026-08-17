"""HTML Nitter facade for search plus a disabled legacy blogger entrypoint."""

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

# Public defaults (2026-07): search uses verified CF-tested instances.
# Bloggers use RSS (shared.DEFAULT_INSTANCES = nitter.net) only.
# HTML user fallback pool stays empty (user_html_fallback defaults to False).
DEFAULT_TIEKOETTER = "https://nitter.tiekoetter.com"
DEFAULT_POAST = "https://nitter.poast.org"
DEFAULT_KAREEM = "https://nitter.kareem.one"
DEFAULT_SEARCH_INSTANCES = [
    DEFAULT_TIEKOETTER,  # Anubis PoW, stable search
    DEFAULT_POAST,  # Poast SHA1, stable search + user HTML
    DEFAULT_KAREEM,  # Light gate, stable search + user HTML
]
# Back-compat alias (older imports/tests expected a list named DEFAULT_HTML_*).
DEFAULT_HTML_INSTANCES = list(DEFAULT_SEARCH_INSTANCES)


@dataclass
class HtmlBackendConfig:
    # Off by default: public HTML competes with search and is often unusable.
    user_html_fallback: bool = False
    # Deprecated / unused as a user config. Pool stays empty so blogger path
    # does not hit HTML instances. Kept for dataclass/API compatibility.
    blogger_html_instances: list[str] = field(default_factory=list)
    search_enabled: bool = True
    search_instances: list[str] = field(
        default_factory=lambda: list(DEFAULT_SEARCH_INSTANCES)
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
            timeout=self.config.html_timeout,
            session_dir=Path(session_dir) if session_dir else None,
            log=self.log,
        )
        # Blogger HTML pool: when user_html_fallback is enabled, share
        # search_instances for RSS blogger fallback. Default off to avoid
        # starving tag search.
        blogger_instances = (
            list(self.config.search_instances) if self.config.user_html_fallback else []
        )
        self.blogger_html = HtmlNitterPool(
            PoolConfig(
                instances=blogger_instances,
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
                filter_reposts=self.config.filter_reposts,
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
        filter_reposts: bool | None = None,
    ) -> tuple[str, list[TweetItem]]:
        # When user_html_fallback is enabled, blogger_html shares
        # search_instances. When disabled (default), pool is empty and we
        # return early to avoid triggering an empty-pool error.
        if not self.blogger_html.instances and not instance:
            return "", []
        return self.blogger_html.fetch_user(
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
        """Fetch Twitter List timeline (shares search pool)."""
        if not self.config.search_enabled:
            raise RuntimeError("search_enabled is false")
        return self.search_pool.fetch_list(
            list_id,
            limit,
            instance=instance,
            filter_reposts=filter_reposts,
            anchor_ids=anchor_ids,
        )
