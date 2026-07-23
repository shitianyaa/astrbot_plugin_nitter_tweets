# -*- coding: utf-8 -*-
"""In-memory session buffer for manual /推文搜索 freshness.

Keys by session id (UMO preferred) + normalized query. Each fetch stores the
full page batch; subsequent requests in the same session consume unread items
before hitting the network again. No schema knobs — always on; TTL 10 min, max 40 items per query.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from time import time
from typing import Any

# Defaults (not user-configurable for now)
BUFFER_TTL_SECONDS = 600.0  # 10 min: short-lived group fun
MAX_BUFFER_ITEMS = 40
MAX_PAGES_PER_FILL = 3
MAX_FETCH_CAP = 40
MAX_SESSIONS = 100
MAX_KNOWN_IDS = 80


def tweet_item_key(tweet: Any) -> str:
    sid = str(getattr(tweet, "status_id", "") or "").strip()
    if sid:
        return sid
    return str(getattr(tweet, "link", "") or getattr(tweet, "x_url", "") or "").strip()


@dataclass
class SessionSearchBuffer:
    """Per session+query ordered pool of fetched tweets not yet served."""

    instance: str = ""
    # status_id -> tweet (insertion order = fetch order)
    items: OrderedDict[str, Any] = field(default_factory=OrderedDict)
    # ids already buffered or served this window (avoid re-adding first page)
    known_ids: set[str] = field(default_factory=set)
    updated_at: float = field(default_factory=time)
    cursor: str = ""  # reserved if we later resume pagination explicitly

    def touch(self) -> None:
        self.updated_at = time()

    def expired(self, now: float | None = None, ttl: float = BUFFER_TTL_SECONDS) -> bool:
        now = time() if now is None else now
        return (now - self.updated_at) > ttl

    def add_tweets(self, tweets: list[Any], *, instance: str = "") -> int:
        """Merge tweets preserving order; skip empty keys and known ids. Return added count."""
        if instance:
            self.instance = instance
        added = 0
        for t in tweets or []:
            key = tweet_item_key(t)
            if not key or key in self.known_ids:
                continue
            self.known_ids.add(key)
            self.items[key] = t
            added += 1
            while len(self.items) > MAX_BUFFER_ITEMS:
                self.items.popitem(last=False)
            if len(self.known_ids) > MAX_KNOWN_IDS:
                # drop arbitrary excess; items keys remain consistent enough for TTL window
                excess = len(self.known_ids) - MAX_KNOWN_IDS
                for i, kid in enumerate(list(self.known_ids)):
                    if i >= excess:
                        break
                    if kid not in self.items:
                        self.known_ids.discard(kid)
        self.touch()
        return added

    def take(self, n: int) -> list[Any]:
        """Pop up to n tweets from the front (oldest fetched / next to show)."""
        n = max(0, int(n))
        out: list[Any] = []
        while self.items and len(out) < n:
            _k, t = self.items.popitem(last=False)
            out.append(t)
        self.touch()
        return out

    def __len__(self) -> int:
        return len(self.items)


class SearchSessionStore:
    """Map session_id + query_key -> SessionSearchBuffer."""

    def __init__(
        self,
        *,
        ttl: float = BUFFER_TTL_SECONDS,
        max_sessions: int = MAX_SESSIONS,
    ):
        self.ttl = float(ttl)
        self.max_sessions = int(max_sessions)
        self._buffers: OrderedDict[str, SessionSearchBuffer] = OrderedDict()

    @staticmethod
    def make_key(session_id: str, query_key: str) -> str:
        return f"{session_id}\0{query_key}"

    def _prune(self, now: float | None = None) -> None:
        now = time() if now is None else now
        dead = [k for k, b in self._buffers.items() if b.expired(now, self.ttl)]
        for k in dead:
            self._buffers.pop(k, None)
        while len(self._buffers) > self.max_sessions:
            self._buffers.popitem(last=False)

    def get(self, session_id: str, query_key: str) -> SessionSearchBuffer | None:
        self._prune()
        key = self.make_key(session_id, query_key)
        buf = self._buffers.get(key)
        if buf is None:
            return None
        if buf.expired(ttl=self.ttl):
            self._buffers.pop(key, None)
            return None
        # LRU touch
        self._buffers.move_to_end(key)
        return buf

    def get_or_create(self, session_id: str, query_key: str) -> SessionSearchBuffer:
        self._prune()
        key = self.make_key(session_id, query_key)
        buf = self._buffers.get(key)
        if buf is None or buf.expired(ttl=self.ttl):
            buf = SessionSearchBuffer()
            self._buffers[key] = buf
        self._buffers.move_to_end(key)
        return buf
