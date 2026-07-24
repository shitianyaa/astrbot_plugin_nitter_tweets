# -*- coding: utf-8 -*-
"""Instance pool: ordered hosts, skip cooldowns, shared fetch+parse."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from urllib.parse import quote, urlencode

try:
    from ...shared.utils import TweetItem
except ImportError:  # pragma: no cover
    from shared.utils import TweetItem

try:
    from .http_session import HTML_ACCEPT, HttpSession
    from .modes import GateKeeper, detect_gate
    from .parser import parse_timeline_html
    from .query import normalize_query, query_kind
    from .rate_limit import RateLimitConfig, RateLimiter
except ImportError:  # pragma: no cover
    from media_support.html_backend.http_session import HTML_ACCEPT, HttpSession
    from media_support.html_backend.modes import GateKeeper, detect_gate
    from media_support.html_backend.parser import parse_timeline_html
    from media_support.html_backend.query import normalize_query, query_kind
    from media_support.html_backend.rate_limit import RateLimitConfig, RateLimiter


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


class HtmlNitterPool:
    """One pool = one ordered list of HTML instances (blogger fallback OR search)."""

    def __init__(
        self,
        config: PoolConfig,
        *,
        log: Callable[[str], None] | None = None,
        shared_limiter: RateLimiter | None = None,
        shared_session: HttpSession | None = None,
    ):
        self.config = config
        self.log = log or (lambda _m: None)
        self.limiter = shared_limiter or RateLimiter(config.rate)
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
        self.instances = [self._norm(u) for u in config.instances if str(u).strip()]
        # Round-robin start so retries do not always hammer the first mirror.
        self._rr_index = 0

    @staticmethod
    def _norm(url: str) -> str:
        u = str(url).strip().rstrip("/")
        if not u.startswith("http"):
            u = "https://" + u
        return u

    def _hosts_ready(self) -> list[str]:
        ready = []
        for base in self.instances:
            host = self.session.host_of(base)
            if self.limiter.is_cooling(host):
                self.log(
                    f"skip cooling {host} "
                    f"remain={self.limiter.cooldown_remaining(host):.0f}s"
                )
                continue
            ready.append(base)
        return ready or list(self.instances)

    def _hosts_for_rotation(self, instance: str | None = None) -> list[str]:
        """Ordered hosts for multi-mirror retry (ready first, then cooling).

        Explicit ``instance`` (mirror probe) stays single-host. Pool searches
        rotate the start index so each call prefers the next mirror, and on
        failure always continues through the remaining list.
        """
        if instance and str(instance).strip():
            base = self._norm(str(instance).strip())
            return [base] if base else self._hosts_for_rotation(None)

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

        # Prefer ready mirrors; still try cooling ones after ready failures.
        ordered = ready + cooling if ready else list(all_hosts)
        if len(ordered) <= 1:
            return ordered

        start = self._rr_index % len(ordered)
        self._rr_index = (self._rr_index + 1) % max(1, len(ordered))
        return ordered[start:] + ordered[:start]

    def _get_html(self, base: str, path: str) -> bytes:
        host = self.session.host_of(base)
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
            self.log(f"punish {host} http={resp.code} cooldown={sec:.0f}s")
            raise RuntimeError(f"{host} HTTP {resp.code}")
        if gate in {"anubis", "poast_sha1"}:
            if not self.gates.ensure(
                base, seed_path=path if path.startswith("/") else "/NASA"
            ):
                raise RuntimeError(f"{host} gate failed")
            self.limiter.wait(host)
            resp = self.session.request(url, accept=HTML_ACCEPT)
            gate = detect_gate(resp.body)
        if resp.code != 200:
            raise RuntimeError(f"{host} HTTP {resp.code} {resp.error or ''}".strip())
        if gate == "cf":
            raise RuntimeError(f"{host} cloudflare unsupported")
        if gate in {"anubis", "poast_sha1"}:
            raise RuntimeError(f"{host} still gated")
        self.limiter.reward(host)
        self.session.save_cookies(host)
        return resp.body

    def fetch_user(
        self,
        username: str,
        limit: int,
        *,
        instance: str | None = None,
    ) -> tuple[str, list[TweetItem]]:
        user = username.strip().lstrip("@")
        errors: list[str] = []
        hosts = self._hosts_for_rotation(instance)
        total = len(hosts)
        for index, base in enumerate(hosts, 1):
            host = self.session.host_of(base)
            try:
                self.log(f"user try {index}/{total} host={host} user={user}")
                tweets = self._paginate_user(base, user, limit)
                if tweets:
                    if index > 1:
                        self.log(
                            f"user ok after rotate host={host} "
                            f"tried={index}/{total}"
                        )
                    return base, tweets[:limit]
                errors.append(f"{base}: empty")
                self.log(
                    f"user empty host={host}, rotate next "
                    f"({index}/{total})"
                )
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{base}: {exc}")
                self.log(
                    f"user fail host={host}, rotate next "
                    f"({index}/{total}): {exc}"
                )
        raise RuntimeError("HTML user failed: " + "; ".join(errors[-4:]))

    def search(
        self,
        query: str,
        limit: int,
        *,
        kind: str | None = None,
        instance: str | None = None,
        max_pages: int | None = None,
    ) -> tuple[str, list[TweetItem]]:
        q = normalize_query(query)
        if not q:
            raise ValueError("empty query")
        resolved = (kind or query_kind(q)).strip().lower()
        if resolved not in {"tag", "phrase"}:
            resolved = query_kind(q)
        errors: list[str] = []
        hosts = self._hosts_for_rotation(instance)
        total = len(hosts)
        for index, base in enumerate(hosts, 1):
            host = self.session.host_of(base)
            try:
                self.log(
                    f"search try {index}/{total} host={host} "
                    f"query={q!r} kind={resolved}"
                )
                tweets = self._paginate_search(
                    base, q, limit, kind=resolved, max_pages=max_pages
                )
                if tweets:
                    if index > 1:
                        self.log(
                            f"search ok after rotate host={host} "
                            f"tried={index}/{total}"
                        )
                    return base, tweets[:limit]
                errors.append(f"{base}: empty")
                self.log(
                    f"search empty host={host}, rotate next "
                    f"({index}/{total})"
                )
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{base}: {exc}")
                self.log(
                    f"search fail host={host}, rotate next "
                    f"({index}/{total}): {exc}"
                )
        raise RuntimeError("HTML search failed: " + "; ".join(errors[-4:]))

    def _hosts_for_probe(self, instance: str | None) -> list[str]:
        """Backward-compatible alias for mirror probe / single-host selection."""
        return self._hosts_for_rotation(instance)

    def _paginate_user(self, base: str, user: str, limit: int) -> list[TweetItem]:
        tweets: list[TweetItem] = []
        seen: set[str] = set()
        cursor = ""
        for _ in range(max(1, self.config.max_pages)):
            path = f"/{quote(user)}"
            if cursor:
                path += "?" + urlencode({"cursor": cursor})
            body = self._get_html(base, path)
            page = parse_timeline_html(body.decode("utf-8", "replace"), base)
            batch = page.tweets
            if self.config.filter_reposts:
                batch = [
                    t for t in batch if (t.username or "").lower() == user.lower()
                ]
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
    ) -> list[TweetItem]:
        tweets: list[TweetItem] = []
        seen: set[str] = set()
        cursor = ""
        allow_hashtag = kind == "tag"
        pages = self.config.max_pages if max_pages is None else max_pages
        for page_i in range(max(1, int(pages or 1))):
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
            if (
                not page.tweets
                and page_i == 0
                and allow_hashtag
                and query.startswith("#")
            ):
                path = f"/hashtag/{quote(query.lstrip('#'), safe='')}"
                body = self._get_html(base, path)
                page = parse_timeline_html(body.decode("utf-8", "replace"), base)
            for t in page.tweets:
                # /推文搜索 + tag schedule: always drop pure retweets (no user toggle).
                if getattr(t, "is_retweet", False):
                    continue
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
