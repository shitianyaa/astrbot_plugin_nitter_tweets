# -*- coding: utf-8 -*-
"""HTML backend log filtering to avoid AstrBot info spam."""

from __future__ import annotations

import re
from typing import Callable

_SESSION_LOAD_RE = re.compile(r"^session load\s+(\S+)", re.I)
_GATE_LINE_RE = re.compile(
    r"^gate\s+(?P<host>\S+)\s+mode=\S+\s+http=(?P<code>\d+)\s+detect=(?P<detect>\S+)",
    re.I,
)
_COOLING_RE = re.compile(r"^(?:skip|defer)\s+cooling\s+(\S+)", re.I)

# Brief mode: drop routine per-attempt chatter; keep failures / summaries.
_BRIEF_DROP_PREFIXES = (
    "search try ",
    "user try ",
    "search empty host=",
    "user empty host=",
    "ensure soft-fail ",
    "anubis: solved ",
    "poast: solved ",
)


class QuietHtmlLog:
    """Callable log sink: ``log(msg)`` with optional brief filtering.

    Always (even when verbose):
    - suppress ``session load`` entirely (cookie reload noise)
    - emit each distinct ``gate host ... detect=...`` at most once

    When ``brief=True`` (default, follows ``brief_log_enabled``):
    - drop per-attempt try/empty/soft-fail/solve chatter
    - drop cooling skip/defer lines
    - keep punish / fail / ok-after-rotate / empty-after-rotate / hard gate errors
    """

    def __init__(
        self,
        emit: Callable[[str], None] | None = None,
        *,
        brief: bool = True,
    ) -> None:
        self.emit = emit or (lambda _m: None)
        self.brief = brief
        self._gate_seen: set[str] = set()
        self._cooling_hosts: set[str] = set()

    def __call__(self, msg: str) -> None:
        text = str(msg or "").strip()
        if not text:
            return
        if self._should_drop(text):
            return
        self.emit(text)

    def _should_drop(self, text: str) -> bool:
        if _SESSION_LOAD_RE.match(text):
            # Cookie reload fires on nearly every ensure(); never useful at info.
            return True

        m = _GATE_LINE_RE.match(text)
        if m:
            key = (
                f"{m.group('host').lower()}|"
                f"{m.group('code')}|"
                f"{m.group('detect').lower()}"
            )
            if key in self._gate_seen:
                return True
            self._gate_seen.add(key)
            # Successful plain gate is pure noise in brief mode.
            if self.brief and m.group("code") == "200" and m.group("detect").lower() == "ok":
                return True
            return False

        m = _COOLING_RE.match(text)
        if m:
            if self.brief:
                return True
            host = m.group(1).lower()
            if host in self._cooling_hosts:
                return True
            self._cooling_hosts.add(host)
            return False

        if self.brief and text.startswith(_BRIEF_DROP_PREFIXES):
            return True

        # Keep: punish, fail rotate, ok after rotate, empty after rotate,
        # cloudflare unsupported, anubis/poast missing challenge, etc.
        return False


__all__ = ["QuietHtmlLog"]
