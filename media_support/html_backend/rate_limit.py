# -*- coding: utf-8 -*-
"""Global + per-host rate limiting and cooldown (shared by all modes)."""

from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass, field
from urllib.parse import urlparse


@dataclass
class RateLimitConfig:
    global_min_interval: float = 3.0
    jitter: float = 0.8
    # extra floor per host keyword
    host_extra: dict[str, float] = field(
        default_factory=lambda: {
            "kareem.one": 8.0,
            "poast.org": 0.5,
            "tiekoetter.com": 0.0,
        }
    )
    cooldown_base: float = 30.0  # 30s start (2026-07-23)
    cooldown_cap: float = 300.0  # 5min cap (2026-07-23)


class RateLimiter:
    def __init__(self, config: RateLimitConfig | None = None):
        self.config = config or RateLimitConfig()
        self._lock = threading.Lock()
        self._last_global = 0.0
        self._last_host: dict[str, float] = {}
        self._cooldown_until: dict[str, float] = {}
        self._cooldown_strikes: dict[str, int] = {}

    @staticmethod
    def host_of(url_or_host: str) -> str:
        text = (url_or_host or "").strip()
        if "://" in text:
            return (urlparse(text).hostname or text).lower()
        return text.lower().split("/")[0]

    def is_cooling(self, host: str) -> bool:
        host = self.host_of(host)
        with self._lock:
            return time.time() < self._cooldown_until.get(host, 0)

    def cooldown_remaining(self, host: str) -> float:
        host = self.host_of(host)
        with self._lock:
            return max(0.0, self._cooldown_until.get(host, 0) - time.time())

    def wait(self, host: str) -> None:
        host = self.host_of(host)
        while True:
            with self._lock:
                now = time.time()
                until = self._cooldown_until.get(host, 0)
                if now < until:
                    sleep_for = until - now
                else:
                    sleep_for = 0.0
                    extra = 0.0
                    for key, val in self.config.host_extra.items():
                        if key in host:
                            extra = max(extra, val)
                            break
                    need_global = self.config.global_min_interval + random.uniform(
                        0, self.config.jitter
                    )
                    need_host = need_global + extra
                    gap_g = need_global - (now - self._last_global)
                    gap_h = need_host - (now - self._last_host.get(host, 0))
                    sleep_for = max(0.0, gap_g, gap_h)
                    if sleep_for <= 0:
                        self._last_global = now
                        self._last_host[host] = now
                        return
            time.sleep(sleep_for)

    def punish(self, host: str, *, reason: str = "429") -> float:
        """Put host in cooldown; return seconds applied."""
        host = self.host_of(host)
        with self._lock:
            strikes = self._cooldown_strikes.get(host, 0) + 1
            self._cooldown_strikes[host] = strikes
            seconds = min(
                self.config.cooldown_cap,
                self.config.cooldown_base * (2 ** (strikes - 1)),
            )
            self._cooldown_until[host] = time.time() + seconds
            return seconds

    def reward(self, host: str) -> None:
        host = self.host_of(host)
        with self._lock:
            self._cooldown_strikes[host] = 0
