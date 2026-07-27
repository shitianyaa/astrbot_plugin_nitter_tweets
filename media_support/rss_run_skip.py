# -*- coding: utf-8 -*-
"""Per-run RSS host skip (S2=A): only within one check/command, no disk."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator
from urllib.parse import urlparse


class RssRunHostSkip:
    """Hosts that failed earlier in the same run; cleared when the run ends."""

    def __init__(self) -> None:
        self._skipped: set[str] = set()

    @staticmethod
    def host_of(instance: str) -> str:
        text = (instance or "").strip()
        if not text:
            return ""
        if "://" in text:
            return (urlparse(text).hostname or text).lower()
        return text.lower().split("/")[0]

    def mark(self, instance: str) -> None:
        host = self.host_of(instance)
        if host:
            self._skipped.add(host)

    def is_skipped(self, instance: str) -> bool:
        host = self.host_of(instance)
        return bool(host) and host in self._skipped

    def filter_instances(self, instances: list[str]) -> list[str]:
        return [item for item in instances if not self.is_skipped(item)]

    def clear(self) -> None:
        self._skipped.clear()

    def __len__(self) -> int:
        return len(self._skipped)


@contextmanager
def host_skip_scope(holder) -> Iterator[RssRunHostSkip]:
    """Attach a fresh skip set on ``holder._run_host_skip`` for the duration."""
    token = RssRunHostSkip()
    previous = getattr(holder, "_run_host_skip", None)
    holder._run_host_skip = token
    try:
        yield token
    finally:
        holder._run_host_skip = previous
