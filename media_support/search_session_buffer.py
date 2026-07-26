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
from uuid import uuid4

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
    # Items temporarily removed while a command is preparing/sending them.
    # Keeping reservations separate lets a failed send put only the unsent
    # suffix back without losing the rest of the fetched page.
    reservations: dict[str, list[tuple[str, Any]]] = field(default_factory=dict)
    # Monotonic fetch order lets out-of-order concurrent reservations restore
    # unsent items in their original order.
    _item_order: dict[str, int] = field(default_factory=dict, repr=False)
    _next_order: int = field(default=0, repr=False)

    def __post_init__(self) -> None:
        """Assign stable order metadata for callers that pre-populate items."""
        if not isinstance(self.items, OrderedDict):
            self.items = OrderedDict(self.items or {})

        next_order = max(
            [self._next_order, *self._item_order.values()]
            if self._item_order
            else [self._next_order]
        )
        for key in self.items:
            if key not in self._item_order:
                next_order += 1
                self._item_order[key] = next_order
        for reserved in self.reservations.values():
            for key, _tweet in reserved:
                if key not in self._item_order:
                    next_order += 1
                    self._item_order[key] = next_order
        self._next_order = next_order
        self.known_ids.update(self.items)
        for reserved in self.reservations.values():
            self.known_ids.update(key for key, _tweet in reserved)

    def touch(self) -> None:
        self.updated_at = time()

    def expired(self, now: float | None = None, ttl: float = BUFFER_TTL_SECONDS) -> bool:
        now = time() if now is None else now
        if self.reservations:
            return False
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
            self._next_order += 1
            self._item_order[key] = self._next_order
            added += 1
            while len(self.items) > MAX_BUFFER_ITEMS:
                dropped_key, _ = self.items.popitem(last=False)
                self._item_order.pop(dropped_key, None)
            if len(self.known_ids) > MAX_KNOWN_IDS:
                # Keep ids that are still buffered or temporarily reserved.
                active_keys = set(self.items)
                for reserved in self.reservations.values():
                    active_keys.update(key for key, _tweet in reserved)
                excess = len(self.known_ids) - MAX_KNOWN_IDS
                for i, kid in enumerate(list(self.known_ids)):
                    if i >= excess:
                        break
                    if kid not in active_keys:
                        self.known_ids.discard(kid)
        self.touch()
        return added

    def take(self, n: int) -> list[Any]:
        """Pop up to n tweets from the front (oldest fetched / next to show)."""
        token, out = self.reserve(n)
        self.finalize(token, len(out))
        return out

    def reserve(self, n: int) -> tuple[str, list[Any]]:
        """Reserve up to ``n`` front items until :meth:`finalize` is called."""
        try:
            n = max(0, int(n))
        except (TypeError, ValueError, OverflowError):
            n = 0
        token = uuid4().hex
        reserved: list[tuple[str, Any]] = []
        while self.items and len(reserved) < n:
            reserved.append(self.items.popitem(last=False))
        if reserved:
            self.reservations[token] = reserved
        self.touch()
        return token, [tweet for _key, tweet in reserved]

    def finalize(self, token: str, sent_count: int) -> None:
        """Commit a sent prefix and restore any unsent suffix at the front."""
        count = self._coerce_sent_count(sent_count)
        reserved = self.reservations.pop(str(token), None)
        if reserved is None:
            return
        count = min(count, len(reserved))
        for key, _tweet in reserved[:count]:
            self._item_order.pop(key, None)
        unsent = reserved[count:]
        self._restore_items(unsent)
        self.touch()

    def rollback(self, token: str) -> None:
        """Restore every item in a reservation after an aborted send."""
        reserved = self.reservations.pop(str(token), None)
        if reserved is None:
            return
        self._restore_items(reserved)
        self.touch()

    @staticmethod
    def _coerce_sent_count(value: Any) -> int:
        """Treat an invalid/legacy send result as zero confirmed deliveries."""
        try:
            return max(0, int(value))
        except (TypeError, ValueError, OverflowError):
            return 0

    def _restore_items(self, restored: list[tuple[str, Any]]) -> None:
        if not restored:
            return
        for key, tweet in restored:
            self.items[key] = tweet
        ordered = sorted(
            self.items.items(),
            key=lambda item: self._item_order.get(item[0], self._next_order + 1),
        )
        self.items.clear()
        self.items.update(ordered)
        # A concurrent fill can have used the full cap while this reservation
        # was in flight. Keep the restored prefix and drop newest additions.
        while len(self.items) > MAX_BUFFER_ITEMS:
            dropped_key, _ = self.items.popitem(last=True)
            self._item_order.pop(dropped_key, None)

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
            removable = next(
                (
                    key
                    for key, buffer in self._buffers.items()
                    if not buffer.reservations
                ),
                None,
            )
            if removable is None:
                # Do not evict an in-flight send; it may still need to return
                # unsent items to the session buffer.
                break
            self._buffers.pop(removable, None)

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
