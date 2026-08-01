"""Instance pool: ordered hosts, skip cooldowns, shared fetch+parse."""

from __future__ import annotations

import time
from collections.abc import Callable
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote, urlencode

try:
    from ...shared.utils import TweetItem
except ImportError:  # pragma: no cover
    from shared.utils import TweetItem

try:
    from ..host_score import HostScoreBook
    from ..network import UnsafeUrlError, validate_http_url
    from .http_session import HTML_ACCEPT, HttpSession
    from .modes import GateKeeper, detect_gate
    from .parser import parse_timeline_html
    from .query import normalize_query, query_kind
    from .rate_limit import RateLimitConfig, RateLimiter
except ImportError:  # pragma: no cover
    from media_support.host_score import HostScoreBook
    from media_support.html_backend.http_session import HTML_ACCEPT, HttpSession
    from media_support.html_backend.modes import GateKeeper, detect_gate
    from media_support.html_backend.parser import parse_timeline_html
    from media_support.html_backend.query import normalize_query, query_kind
    from media_support.html_backend.rate_limit import RateLimitConfig, RateLimiter
    from media_support.network import UnsafeUrlError, validate_http_url


@dataclass
class PoolConfig:
    instances: list[str] = field(default_factory=list)
    proxy: str | None = None
    user_agent: str = ""
    timeout: float = 35.0
    session_dir: str | Path | None = None
    rate: RateLimitConfig = field(default_factory=RateLimitConfig)
    max_pages: int = 1
    filter_reposts: bool = False
    # Global retry configuration
    max_global_retries: int = 2  # Retry all instances N times before giving up
    retry_delay_base: float = 5.0  # Base delay between global retries (seconds)
    retry_delay_on_cooldown: float = 10.0  # Delay when all instances cooling


class HtmlSearchResult(list[TweetItem]):
    """List-compatible search result carrying parser/filter statistics."""

    def __init__(
        self,
        tweets=(),
        *,
        raw_item_count: int = 0,
        retweet_filtered: int = 0,
        scan_complete: bool = True,
        anchor_status_ids: list[str] | str | None = None,
    ):
        super().__init__(tweets or ())
        self.raw_item_count = max(0, int(raw_item_count or 0))
        self.retweet_filtered = max(0, int(retweet_filtered or 0))
        self.scan_complete = bool(scan_complete)
        source_ids = (
            [getattr(tweet, "status_id", "") for tweet in self]
            if anchor_status_ids is None
            else [anchor_status_ids]
            if isinstance(anchor_status_ids, str)
            else anchor_status_ids
        )
        normalized_ids = []
        for status_id in source_ids:
            value = str(status_id or "").strip()
            if value and value not in normalized_ids:
                normalized_ids.append(value)
        self.anchor_status_ids = normalized_ids[:20]

    def limited(self, limit: int) -> HtmlSearchResult:
        """Return a bounded result while retaining parser statistics."""
        return HtmlSearchResult(
            self[:limit],
            raw_item_count=self.raw_item_count,
            retweet_filtered=self.retweet_filtered,
            scan_complete=self.scan_complete,
            anchor_status_ids=self.anchor_status_ids,
        )


class HtmlNitterPool:
    """One pool = one ordered list of HTML instances (blogger fallback OR search)."""

    def __init__(
        self,
        config: PoolConfig,
        *,
        log: Callable[[str], None] | None = None,
        shared_limiter: RateLimiter | None = None,
        shared_session: HttpSession | None = None,
        score_book: HostScoreBook | None = None,
    ):
        self.config = config
        self.log = log or (lambda _m: None)
        self.limiter = shared_limiter or RateLimiter(config.rate)
        self.scores = score_book or HostScoreBook()
        default_ua = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        )
        self.session = shared_session or HttpSession(
            proxy=config.proxy,
            user_agent=(config.user_agent or default_ua),
            timeout=config.timeout,
            session_dir=Path(config.session_dir) if config.session_dir else None,
            log=self.log,
        )
        self.gates = GateKeeper(self.session, log=self.log)
        self.instances = []
        for raw in config.instances:
            if not str(raw or "").strip():
                continue
            try:
                self.instances.append(self._norm(raw))
            except UnsafeUrlError as exc:
                # A stale/private configured mirror must not make plugin
                # startup fail. Explicit probe URLs are rejected by
                # _hosts_for_rotation instead of silently falling back.
                self.log(f"skip unsafe HTML instance ({type(exc).__name__})")

    @staticmethod
    def _norm(url: str) -> str:
        u = str(url).strip().rstrip("/")
        if not u.lower().startswith(("http://", "https://")):
            u = "https://" + u
        return validate_http_url(u, resolve_dns=False).rstrip("/")

    @staticmethod
    def _page_count(value) -> int:
        try:
            number = int(value or 1)
        except (TypeError, ValueError):
            number = 1
        return max(1, min(5, number))

    @staticmethod
    def _repost_filter_kwargs(filter_reposts: bool | None) -> dict[str, bool]:
        if filter_reposts is None:
            return {}
        return {"filter_reposts": bool(filter_reposts)}

    def _hosts_for_rotation(self, instance: str | None = None) -> list[str]:
        """Ordered hosts for multi-mirror retry (ready first, then cooling).

        Explicit ``instance`` (mirror probe) stays single-host. Ready hosts are
        sorted by in-memory success score (higher first); cooling hosts stay
        last as fallback. On failure the caller continues through the list.
        Returns ``[]`` when every host is cooling so the caller fails fast
        instead of hammering mirrors that are still rate-limited.
        """
        if instance and str(instance).strip():
            base = self._norm(str(instance).strip())
            return [base]

        all_hosts = list(self.instances)
        if not all_hosts:
            return []

        ready: list[str] = []
        cooling: list[str] = []
        for base in all_hosts:
            host = self.session.host_of(base)
            if self.limiter.is_cooling(host):
                cooling.append(base)
                self.log(
                    f"defer cooling {host} "
                    f"remain={self.limiter.cooldown_remaining(host):.0f}s"
                )
            else:
                ready.append(base)

        # Prefer ready mirrors by success score; cooling only as last resort.
        if ready:
            return self.scores.order(ready) + self.scores.order(cooling)
        # 非空 all_hosts 必然全部落进 ready 或 cooling，走到这里即全部冷却中：
        # 返回空列表让调用方快速失败，而不是继续冲击仍在限流的镜像。
        return []

    @contextmanager
    def _session_transaction(self):
        """Serialize gate + fetch sequences for a shared CookieJar/session."""
        lock = getattr(self.session, "serial_lock", None)
        if lock is None:
            with nullcontext():
                yield
            return
        with lock:
            yield

    def _get_html(self, base: str, path: str) -> bytes:
        with self._session_transaction():
            return self._get_html_unlocked(base, path)

    def _get_html_unlocked(self, base: str, path: str) -> bytes:
        """Fetch HTML. Score only failures here; caller scores success once."""
        host = self.session.host_of(base)
        scored_failure = False
        try:
            self.limiter.wait(host)
            if not self.gates.ensure(base, seed_path="/NASA"):
                self.log(f"ensure soft-fail {host}, trying path anyway")
            self.limiter.wait(host)
            url = f"{base}{path}"
            resp = self.session.request(url, accept=HTML_ACCEPT)
            gate = detect_gate(resp.body)
            if resp.code == 429 or (
                resp.code == 503 and gate not in {"anubis", "poast_sha1"}
            ):
                sec = self.limiter.punish(host)
                self.scores.record_failure(host)
                scored_failure = True
                self.log(f"punish {host} http={resp.code} cooldown={sec:.0f}s")
                raise RuntimeError(f"{host} HTTP {resp.code}")
            if gate in {"anubis", "poast_sha1"}:
                if not self.gates.ensure(
                    base, seed_path=path if path.startswith("/") else "/NASA"
                ):
                    self.scores.record_failure(host)
                    scored_failure = True
                    raise RuntimeError(f"{host} gate failed")
                self.limiter.wait(host)
                resp = self.session.request(url, accept=HTML_ACCEPT)
                gate = detect_gate(resp.body)
            if resp.code != 200:
                self.scores.record_failure(host)
                scored_failure = True
                raise RuntimeError(
                    f"{host} HTTP {resp.code} {resp.error or ''}".strip()
                )
            if gate in {"cf", "error", "other"}:
                self.scores.record_failure(host)
                scored_failure = True
                reason = (
                    "cloudflare unsupported"
                    if gate == "cf"
                    else "login/maintenance/error page"
                    if gate == "error"
                    else "unexpected HTML page"
                )
                raise RuntimeError(f"{host} {reason}")
            if gate in {"anubis", "poast_sha1"}:
                self.scores.record_failure(host)
                scored_failure = True
                raise RuntimeError(f"{host} still gated")
            self.limiter.reward(host)
            self.session.save_cookies(host)
            return resp.body
        except Exception:
            # Timeouts/connection errors never hit explicit branches above.
            if not scored_failure:
                self.scores.record_failure(host)
            raise

    def fetch_user(
        self,
        username: str,
        limit: int,
        *,
        instance: str | None = None,
        filter_reposts: bool | None = None,
    ) -> tuple[str, list[TweetItem]]:
        """Fetch user timeline with global retry on total failure."""
        # Skip global retry when targeting a specific instance (probe mode)
        if instance and str(instance).strip():
            return self._fetch_user_once(
                username,
                limit,
                instance=instance,
                **self._repost_filter_kwargs(filter_reposts),
            )

        max_retries = self.config.max_global_retries
        for attempt in range(max_retries):
            try:
                return self._fetch_user_once(
                    username,
                    limit,
                    instance=instance,
                    **self._repost_filter_kwargs(filter_reposts),
                )
            except RuntimeError as exc:
                msg = str(exc)
                is_last_attempt = attempt >= max_retries - 1

                if "all instances in cooldown" in msg:
                    if is_last_attempt:
                        raise
                    delay = self.config.retry_delay_on_cooldown
                    self.log(
                        f"user global retry {attempt + 1}/{max_retries}: "
                        f"all cooling, wait {delay:.0f}s"
                    )
                    time.sleep(delay)
                elif is_last_attempt:
                    raise
                else:
                    delay = self.config.retry_delay_base * (attempt + 1)
                    self.log(
                        f"user global retry {attempt + 1}/{max_retries}: "
                        f"{exc}, wait {delay:.0f}s"
                    )
                    time.sleep(delay)
        # Unreachable (loop always raises on last attempt)
        raise RuntimeError("fetch_user: exhausted retries")

    def _fetch_user_once(
        self,
        username: str,
        limit: int,
        *,
        instance: str | None = None,
        filter_reposts: bool | None = None,
    ) -> tuple[str, list[TweetItem]]:
        user = username.strip().lstrip("@")
        errors: list[str] = []
        # At least one host answered with a parsed empty timeline. Do not treat
        # that as hard failure after rotation; scheduler empty-init depends on it.
        empty_success_base: str | None = None
        hosts = self._hosts_for_rotation(instance)
        if not hosts:
            raise RuntimeError("HTML user fetch unavailable: all instances in cooldown")
        total = len(hosts)
        for index, base in enumerate(hosts, 1):
            host = self.session.host_of(base)
            try:
                self.log(f"user try {index}/{total} host={host} user={user}")
                tweets = self._paginate_user(
                    base,
                    user,
                    limit,
                    **self._repost_filter_kwargs(filter_reposts),
                )
                if tweets:
                    self.scores.record_success(host)
                    if index > 1:
                        self.log(
                            f"user ok after rotate host={host} tried={index}/{total}"
                        )
                    return base, tweets[:limit]
                empty_success_base = base
                # Alive empty timeline: soft success (aligned with RSS empty feed).
                self.scores.record_success(host, soft=True)
                errors.append(f"{base}: empty")
                self.log(f"user empty host={host}, rotate next ({index}/{total})")
            except Exception as exc:
                # Failures scored inside _get_html (including transport errors).
                errors.append(f"{base}: {exc}")
                self.log(f"user fail host={host}, rotate next ({index}/{total}): {exc}")
        if empty_success_base is not None:
            self.log(
                f"user empty after rotate hosts={total}, "
                f"last_empty={self.session.host_of(empty_success_base)}"
            )
            return empty_success_base, []
        raise RuntimeError("HTML user failed: " + "; ".join(errors[-4:]))

    def search(
        self,
        query: str,
        limit: int,
        *,
        kind: str | None = None,
        instance: str | None = None,
        max_pages: int | None = None,
        filter_reposts: bool | None = None,
    ) -> tuple[str, list[TweetItem]]:
        """Search with global retry on total failure."""
        # Skip global retry when targeting a specific instance (probe mode)
        if instance and str(instance).strip():
            return self._search_once(
                query,
                limit,
                kind=kind,
                instance=instance,
                max_pages=max_pages,
                **self._repost_filter_kwargs(filter_reposts),
            )

        max_retries = self.config.max_global_retries
        for attempt in range(max_retries):
            try:
                return self._search_once(
                    query,
                    limit,
                    kind=kind,
                    instance=instance,
                    max_pages=max_pages,
                    **self._repost_filter_kwargs(filter_reposts),
                )
            except RuntimeError as exc:
                msg = str(exc)
                is_last_attempt = attempt >= max_retries - 1

                if "all instances in cooldown" in msg:
                    if is_last_attempt:
                        raise
                    delay = self.config.retry_delay_on_cooldown
                    self.log(
                        f"search global retry {attempt + 1}/{max_retries}: "
                        f"all cooling, wait {delay:.0f}s"
                    )
                    time.sleep(delay)
                elif is_last_attempt:
                    raise
                else:
                    delay = self.config.retry_delay_base * (attempt + 1)
                    self.log(
                        f"search global retry {attempt + 1}/{max_retries}: "
                        f"{exc}, wait {delay:.0f}s"
                    )
                    time.sleep(delay)
            except ValueError:
                # "empty query" and similar validation errors should not retry
                raise
        # Unreachable (loop always raises on last attempt)
        raise RuntimeError("search: exhausted retries")

    def _search_once(
        self,
        query: str,
        limit: int,
        *,
        kind: str | None = None,
        instance: str | None = None,
        max_pages: int | None = None,
        filter_reposts: bool | None = None,
    ) -> tuple[str, list[TweetItem]]:
        q = normalize_query(query)
        if not q:
            raise ValueError("empty query")
        resolved = (kind or query_kind(q)).strip().lower()
        if resolved not in {"tag", "phrase"}:
            resolved = query_kind(q)
        errors: list[str] = []
        # Empty after pure-RT filter is a valid search result. Keep rotating in
        # case another mirror still has non-RT hits, but if every host only
        # yields empty, return [] so tag schedule can skip seen init instead of
        # treating the query as permanently failed.
        empty_success_base: str | None = None
        empty_success_result = HtmlSearchResult()
        hosts = self._hosts_for_rotation(instance)
        if not hosts:
            raise RuntimeError("HTML search unavailable: all instances in cooldown")
        total = len(hosts)
        for index, base in enumerate(hosts, 1):
            host = self.session.host_of(base)
            try:
                self.log(
                    f"search try {index}/{total} host={host} "
                    f"query={q!r} kind={resolved}"
                )
                tweets = self._as_search_result(
                    self._paginate_search(
                        base,
                        q,
                        limit,
                        kind=resolved,
                        max_pages=max_pages,
                        **self._repost_filter_kwargs(filter_reposts),
                    )
                )
                if tweets:
                    self.scores.record_success(host)
                    if index > 1:
                        self.log(
                            f"search ok after rotate host={host} tried={index}/{total}"
                        )
                    return base, tweets.limited(limit)
                empty_success_base = base
                empty_success_result.raw_item_count += tweets.raw_item_count
                empty_success_result.retweet_filtered += tweets.retweet_filtered
                # Empty after RT filter: soft success, not an outage.
                self.scores.record_success(host, soft=True)
                errors.append(f"{base}: empty")
                self.log(f"search empty host={host}, rotate next ({index}/{total})")
            except Exception as exc:
                # Failures scored inside _get_html (including transport errors).
                errors.append(f"{base}: {exc}")
                self.log(
                    f"search fail host={host}, rotate next ({index}/{total}): {exc}"
                )
        if empty_success_base is not None:
            self.log(
                f"search empty after rotate hosts={total}, "
                f"query={q!r} kind={resolved}, "
                f"last_empty={self.session.host_of(empty_success_base)}"
            )
            return empty_success_base, empty_success_result
        raise RuntimeError("HTML search failed: " + "; ".join(errors[-4:]))

    def fetch_list(
        self,
        list_id: str,
        limit: int,
        *,
        instance: str | None = None,
        filter_reposts: bool | None = None,
        anchor_ids: list[str] | None = None,
    ) -> tuple[str, HtmlSearchResult]:
        """Fetch Twitter List timeline with global retry."""
        # Skip global retry when targeting a specific instance (probe mode)
        if instance and str(instance).strip():
            return self._fetch_list_once(
                list_id,
                limit,
                instance=instance,
                **self._repost_filter_kwargs(filter_reposts),
                anchor_ids=anchor_ids,
            )

        max_retries = self.config.max_global_retries
        for attempt in range(max_retries):
            try:
                return self._fetch_list_once(
                    list_id,
                    limit,
                    instance=instance,
                    **self._repost_filter_kwargs(filter_reposts),
                    anchor_ids=anchor_ids,
                )
            except RuntimeError as exc:
                msg = str(exc)
                is_last_attempt = attempt >= max_retries - 1

                if "all instances in cooldown" in msg:
                    if is_last_attempt:
                        raise
                    delay = self.config.retry_delay_on_cooldown
                    self.log(
                        f"list global retry {attempt + 1}/{max_retries}: "
                        f"all cooling, wait {delay:.0f}s"
                    )
                    time.sleep(delay)
                elif is_last_attempt:
                    raise
                else:
                    delay = self.config.retry_delay_base * (attempt + 1)
                    self.log(
                        f"list global retry {attempt + 1}/{max_retries}: "
                        f"{exc}, wait {delay:.0f}s"
                    )
                    time.sleep(delay)
            except ValueError:
                # Validation errors should not retry
                raise
        raise RuntimeError("fetch_list: exhausted retries")

    def _fetch_list_once(
        self,
        list_id: str,
        limit: int,
        *,
        instance: str | None = None,
        filter_reposts: bool | None = None,
        anchor_ids: list[str] | None = None,
    ) -> tuple[str, HtmlSearchResult]:
        """Fetch Twitter List timeline (HTML only, same structure as user timeline)."""
        list_id_str = str(list_id).strip()
        if not list_id_str:
            raise ValueError("empty list_id")

        errors: list[str] = []
        empty_success_base: str | None = None
        empty_success_result = HtmlSearchResult(
            scan_complete=False,
            anchor_status_ids=[],
        )
        hosts = self._hosts_for_rotation(instance)
        if not hosts:
            raise RuntimeError("HTML list fetch unavailable: all instances in cooldown")

        total = len(hosts)
        for index, base in enumerate(hosts, 1):
            host = self.session.host_of(base)
            try:
                self.log(f"list try {index}/{total} host={host} list_id={list_id_str}")
                paginate_kwargs = self._repost_filter_kwargs(filter_reposts)
                if anchor_ids is not None:
                    paginate_kwargs["anchor_ids"] = anchor_ids
                tweets = self._as_search_result(
                    self._paginate_list(
                        base,
                        list_id_str,
                        limit,
                        **paginate_kwargs,
                    )
                )
                if tweets:
                    self.scores.record_success(host)
                    if index > 1:
                        self.log(
                            f"list ok after rotate host={host} tried={index}/{total}"
                        )
                    return (
                        base,
                        tweets.limited(limit) if anchor_ids is None else tweets,
                    )
                empty_success_base = base
                empty_success_result.raw_item_count += tweets.raw_item_count
                empty_success_result.retweet_filtered += tweets.retweet_filtered
                empty_success_result.scan_complete = (
                    empty_success_result.scan_complete or tweets.scan_complete
                )
                for status_id in tweets.anchor_status_ids or []:
                    if status_id not in empty_success_result.anchor_status_ids:
                        empty_success_result.anchor_status_ids.append(status_id)
                empty_success_result.anchor_status_ids = (
                    empty_success_result.anchor_status_ids[:20]
                )
                # Empty list: soft success (valid but no content)
                self.scores.record_success(host, soft=True)
                errors.append(f"{base}: empty")
                self.log(f"list empty host={host}, rotate next ({index}/{total})")
            except Exception as exc:
                errors.append(f"{base}: {exc}")
                self.log(f"list fail host={host}, rotate next ({index}/{total}): {exc}")

        if empty_success_base is not None:
            self.log(
                f"list empty after rotate hosts={total}, "
                f"list_id={list_id_str}, "
                f"last_empty={self.session.host_of(empty_success_base)}"
            )
            return empty_success_base, empty_success_result
        raise RuntimeError("HTML list failed: " + "; ".join(errors[-4:]))

    def _paginate_list(
        self,
        base: str,
        list_id: str,
        limit: int,
        *,
        filter_reposts: bool | None = None,
        anchor_ids: list[str] | None = None,
    ) -> HtmlSearchResult:
        """Paginate Twitter List timeline (same HTML structure as user timeline)."""
        initial_scan = anchor_ids is None
        normalized_anchor_ids = anchor_ids or []
        boundary_ids = {
            str(status_id).strip()
            for status_id in normalized_anchor_ids
            if str(status_id or "").strip()
        }
        tweets: list[TweetItem] = []
        seen: set[str] = set()
        cursor = ""
        raw_count = 0
        retweet_filtered = 0
        scan_complete = initial_scan
        anchor_status_ids: list[str] = []
        use_filter_reposts = (
            bool(self.config.filter_reposts)
            if filter_reposts is None
            else bool(filter_reposts)
        )

        page_count = self._page_count(self.config.max_pages)
        for page_index in range(page_count):
            # Nitter List path: /i/lists/{list_id}
            path = f"/i/lists/{quote(list_id, safe='')}"
            if cursor:
                path += "?" + urlencode({"cursor": cursor})

            body = self._get_html(base, path)
            page = parse_timeline_html(
                body.decode("utf-8", "replace"), base, source=f"list:{base}"
            )

            raw_count += int(getattr(page, "raw_item_count", len(page.tweets)) or 0)

            if page_index == 0:
                anchor_status_ids = [
                    str(tweet.status_id).strip()
                    for tweet in page.tweets
                    if str(tweet.status_id or "").strip()
                ][:20]

            for t in page.tweets:
                k = t.status_id or t.link
                reached_boundary = bool(t.status_id and t.status_id in boundary_ids)
                if k in seen:
                    if reached_boundary:
                        scan_complete = True
                        break
                    continue

                if use_filter_reposts and t.is_retweet:
                    retweet_filtered += 1
                    if reached_boundary:
                        scan_complete = True
                        break
                    continue

                seen.add(k)
                tweets.append(t)
                if reached_boundary:
                    scan_complete = True
                    break

            if scan_complete and not initial_scan:
                break
            if initial_scan and len(tweets) >= limit:
                break

            if not page.next_cursor or page.next_cursor == cursor:
                scan_complete = True
                break
            cursor = page.next_cursor

        return HtmlSearchResult(
            tweets[:limit] if initial_scan else tweets,
            raw_item_count=raw_count,
            retweet_filtered=retweet_filtered,
            scan_complete=scan_complete,
            anchor_status_ids=anchor_status_ids,
        )

    @staticmethod
    def _as_search_result(value) -> HtmlSearchResult:
        """Normalize legacy or mocked list results without changing the API."""
        if isinstance(value, HtmlSearchResult):
            return value
        return HtmlSearchResult(value or ())

    def _hosts_for_probe(self, instance: str | None) -> list[str]:
        """Backward-compatible alias for mirror probe / single-host selection."""
        return self._hosts_for_rotation(instance)

    def _paginate_user(
        self,
        base: str,
        user: str,
        limit: int,
        *,
        filter_reposts: bool | None = None,
    ) -> list[TweetItem]:
        tweets: list[TweetItem] = []
        seen: set[str] = set()
        cursor = ""
        use_filter_reposts = (
            bool(self.config.filter_reposts)
            if filter_reposts is None
            else bool(filter_reposts)
        )
        page_count = self._page_count(self.config.max_pages)
        for _ in range(page_count):
            path = f"/{quote(user)}"
            if cursor:
                path += "?" + urlencode({"cursor": cursor})
            body = self._get_html(base, path)
            page = parse_timeline_html(body.decode("utf-8", "replace"), base)
            batch = page.tweets
            if use_filter_reposts:
                batch = [t for t in batch if (t.username or "").lower() == user.lower()]
            for t in batch:
                k = t.status_id or t.link
                if k in seen:
                    continue
                seen.add(k)
                tweets.append(t)
                if len(tweets) >= limit:
                    return tweets
            if not page.next_cursor or page.next_cursor == cursor:
                break
            cursor = page.next_cursor
        return tweets

    def _paginate_search(
        self,
        base: str,
        query: str,
        limit: int,
        *,
        kind: str,
        max_pages: int | None = None,
        filter_reposts: bool | None = None,
    ) -> HtmlSearchResult:
        tweets = HtmlSearchResult()
        seen: set[str] = set()
        cursor = ""
        raw_item_count = 0
        retweet_filtered = 0
        use_filter_reposts = True if filter_reposts is None else bool(filter_reposts)
        allow_hashtag = kind == "tag"
        pages = self.config.max_pages if max_pages is None else max_pages
        page_count = self._page_count(pages)
        for page_i in range(page_count):
            params = {"f": "tweets", "q": query}
            if cursor:
                params["cursor"] = cursor
            path = "/search?" + urlencode(params)
            try:
                body = self._get_html(base, path)
            except RuntimeError:
                if page_i == 0 and allow_hashtag and query.startswith("#"):
                    path = f"/hashtag/{quote(query.lstrip('#'), safe='')}"
                    body = self._get_html(base, path)
                else:
                    raise
            page = parse_timeline_html(body.decode("utf-8", "replace"), base)
            raw_item_count += int(
                getattr(page, "raw_item_count", len(page.tweets)) or 0
            )
            if (
                not page.tweets
                and page_i == 0
                and allow_hashtag
                and query.startswith("#")
            ):
                path = f"/hashtag/{quote(query.lstrip('#'), safe='')}"
                body = self._get_html(base, path)
                page = parse_timeline_html(body.decode("utf-8", "replace"), base)
                raw_item_count += int(
                    getattr(page, "raw_item_count", len(page.tweets)) or 0
                )
            for t in page.tweets:
                if use_filter_reposts and getattr(t, "is_retweet", False):
                    retweet_filtered += 1
                    continue
                k = t.status_id or t.link
                if k in seen:
                    continue
                seen.add(k)
                tweets.append(t)
                if len(tweets) >= limit:
                    tweets.raw_item_count = raw_item_count
                    tweets.retweet_filtered = retweet_filtered
                    return tweets
            if not page.next_cursor or page.next_cursor == cursor:
                break
            cursor = page.next_cursor
        tweets.raw_item_count = raw_item_count
        tweets.retweet_filtered = retweet_filtered
        return tweets
