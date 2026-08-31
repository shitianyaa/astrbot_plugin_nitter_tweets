"""HTML backend log filtering to avoid AstrBot info spam."""

from __future__ import annotations

import re
from collections.abc import Callable

_SESSION_LOAD_RE = re.compile(r"^session load\s+(\S+)", re.IGNORECASE)
_COOLING_RE = re.compile(r"^(?:skip|defer)\s+cooling\s+(\S+)", re.IGNORECASE)

# Brief mode: drop routine per-attempt chatter; keep failures / summaries.
_BRIEF_DROP_PREFIXES = (
    "search try ",
    "user try ",
    "list try ",
    "search empty host=",
    "user empty host=",
    "list empty host=",
)


class QuietHtmlLog:
    """Callable log sink: ``log(msg)`` with optional brief filtering.

    Always suppress ``session load`` entirely (cookie reload noise).

    When ``brief=True`` (default, follows ``brief_log_enabled``):
    - drop per-attempt try/empty chatter
    - drop cooling skip/defer lines
    - keep punish / fail / ok-after-rotate / empty-after-rotate errors
    """

    def __init__(
        self,
        emit: Callable[[str], None] | None = None,
        *,
        brief: bool = True,
    ) -> None:
        self.emit = emit or (lambda _m: None)
        self.brief = brief
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
            # Cookie reload can fire on every request; never useful at info.
            return True

        m = _COOLING_RE.match(text)
        if m:
            if self.brief:
                return True
            host = m.group(1).lower()
            if host in self._cooling_hosts:
                return True
            self._cooling_hosts.add(host)
            return False

        # Keep punish, rotation summaries and hard response errors.
        return bool(self.brief and text.startswith(_BRIEF_DROP_PREFIXES))


__all__ = ["QuietHtmlLog"]
