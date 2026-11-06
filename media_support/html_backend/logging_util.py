"""HTML 日志分级：重要诊断与 DEBUG 过程分流，始终抑制会话加载。"""

from __future__ import annotations

from collections.abc import Callable

_PROCESS_PREFIXES = (
    "search try ",
    "user try ",
    "list try ",
    "search empty host=",
    "user empty host=",
    "list empty host=",
    "search empty, rotate",
    "user empty, rotate",
    "list empty, rotate",
    "search global retry ",
    "user global retry ",
    "list global retry ",
    "skip cooling ",
    "defer cooling ",
)


class QuietHtmlLog:
    """保留单字符串回调；未提供 debug sink 时回落原 sink，不静默丢事件。"""

    def __init__(
        self,
        emit: Callable[[str], None] | None = None,
        *,
        debug_emit: Callable[[str], None] | None = None,
    ) -> None:
        self.emit = emit or (lambda _m: None)
        self.debug_emit = debug_emit or self.emit

    def __call__(self, msg: str) -> None:
        text = str(msg or "").strip()
        if not text or text.lower().startswith("session load "):
            return
        if text.startswith(_PROCESS_PREFIXES):
            self.debug_emit(text)
        else:
            self.emit(text)


__all__ = ["QuietHtmlLog"]
