"""HTML backend log filtering to avoid AstrBot info spam."""

from __future__ import annotations

import re
from collections.abc import Callable

_SESSION_LOAD_RE = re.compile(r"^session load\s+(\S+)", re.IGNORECASE)
_COOLING_RE = re.compile(r"^(?:skip|defer)\s+cooling\s+(\S+)", re.IGNORECASE)

# Drop routine per-attempt chatter; keep failures / summaries.
_DROP_PREFIXES = (
    "search try ",
    "user try ",
    "list try ",
    "search empty host=",
    "user empty host=",
    "list empty host=",
)


class QuietHtmlLog:
    """Callable log sink: ``log(msg)`` with per-attempt chatter filtered out.

    Always suppressed:
    - ``session load`` (cookie reload noise, can fire on every request)
    - per-attempt try/empty chatter
    - cooling skip/defer lines

    Always kept: punish / fail / ok-after-rotate / empty-after-rotate errors.

    此前这里的过滤受 ``brief_log_enabled`` 开关控制，关闭开关才输出过程行；
    该开关已移除，过滤恒定生效，过程日志统一由 DEBUG 级别承载。
    """

    def __init__(self, emit: Callable[[str], None] | None = None) -> None:
        self.emit = emit or (lambda _m: None)

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
        if _COOLING_RE.match(text):
            # 冷却跳过是限流簿记，每次请求都可能出现，没有可操作信息
            return True
        # Keep punish, rotation summaries and hard response errors.
        return text.startswith(_DROP_PREFIXES)


__all__ = ["QuietHtmlLog"]
