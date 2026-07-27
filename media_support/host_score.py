# -*- coding: utf-8 -*-
"""In-memory per-host success scores for mirror selection.

Simple availability-first ordering: higher score first, failure penalizes hard.
Scores live in process memory only (reset on restart). Pools must not share
books across RSS / blogger-HTML / search instance lists.
"""

from __future__ import annotations

import threading
from urllib.parse import urlparse

DEFAULT_SCORE = 1.0
MIN_SCORE = 0.1
MAX_SCORE = 10.0
SUCCESS_DELTA = 0.5
# Soft success (empty-but-alive page/feed): smaller bump so empty noise does not
# dominate real content successes.
SOFT_SUCCESS_DELTA = 0.15
FAILURE_FACTOR = 0.5


def host_key(url_or_host: str) -> str:
    text = str(url_or_host or "").strip()
    if not text:
        return ""
    if "://" in text:
        return (urlparse(text).hostname or text).lower()
    return text.lower().split("/")[0]


class HostScoreBook:
    """Thread-safe score table keyed by hostname."""

    def __init__(
        self,
        *,
        default: float = DEFAULT_SCORE,
        min_score: float = MIN_SCORE,
        max_score: float = MAX_SCORE,
        success_delta: float = SUCCESS_DELTA,
        soft_success_delta: float = SOFT_SUCCESS_DELTA,
        failure_factor: float = FAILURE_FACTOR,
    ) -> None:
        self.default = float(default)
        self.min_score = float(min_score)
        self.max_score = float(max_score)
        self.success_delta = float(success_delta)
        self.soft_success_delta = float(soft_success_delta)
        self.failure_factor = float(failure_factor)
        self._scores: dict[str, float] = {}
        self._lock = threading.Lock()

    def score(self, url_or_host: str) -> float:
        key = host_key(url_or_host)
        if not key:
            return self.default
        with self._lock:
            return self._scores.get(key, self.default)

    def record_success(self, url_or_host: str, *, soft: bool = False) -> float:
        key = host_key(url_or_host)
        if not key:
            return self.default
        delta = self.soft_success_delta if soft else self.success_delta
        with self._lock:
            current = self._scores.get(key, self.default)
            updated = min(self.max_score, current + delta)
            self._scores[key] = updated
            return updated

    def record_failure(self, url_or_host: str) -> float:
        key = host_key(url_or_host)
        if not key:
            return self.default
        with self._lock:
            current = self._scores.get(key, self.default)
            updated = max(self.min_score, current * self.failure_factor)
            self._scores[key] = updated
            return updated

    def order(self, urls: list[str]) -> list[str]:
        """Sort by score descending; ties keep original relative order."""
        if len(urls) <= 1:
            return list(urls)
        with self._lock:
            scored: list[tuple[int, float, str]] = []
            for index, url in enumerate(urls):
                key = host_key(url)
                value = self._scores.get(key, self.default) if key else self.default
                scored.append((index, value, url))
        scored.sort(key=lambda item: (-item[1], item[0]))
        return [url for _index, _score, url in scored]


__all__ = [
    "DEFAULT_SCORE",
    "FAILURE_FACTOR",
    "HostScoreBook",
    "MAX_SCORE",
    "MIN_SCORE",
    "SOFT_SUCCESS_DELTA",
    "SUCCESS_DELTA",
    "host_key",
]
