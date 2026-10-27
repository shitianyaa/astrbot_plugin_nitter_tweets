"""有界的内存日志环缓冲，供 WebUI 实例诊断终端展示。

只记录插件自己经 ``safe_task_log`` / ``safe_log`` 发出的事件——宿主 astrbot 的
日志不在此列。缓冲仅存于进程内存，重启即清空；这是「本次会话诊断视图」，
不是持久日志。

运行时模块禁止 ``import logging``（插件市场上架约束），因此级别用整数映射，
不引用标准库常量。
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any

MAX_ENTRIES = 200

_LEVEL_NAMES = {
    10: "debug",
    20: "info",
    30: "warning",
    40: "error",
    50: "critical",
}

_lock = threading.Lock()
_entries: deque[dict[str, Any]] = deque(maxlen=MAX_ENTRIES)
_next_seq = 1


def level_name(level: int | str) -> str:
    """把 logging 级别整数或级别名字符串归一成前端可用的级别名。"""
    if isinstance(level, str):
        # 运行时模块禁止 import logging，允许直接传 "info"/"warning" 这类名字
        name = level.strip().lower()
        if name in {"debug", "info", "warning", "error", "critical"}:
            return name
        if name == "warn":
            return "warning"
        return "info"
    try:
        value = int(level)
    except (TypeError, ValueError):
        return "info"
    return _LEVEL_NAMES.get(value, "info")


def append(level: int | str, lines: list[str]) -> None:
    """追加一条日志事件；``lines`` 必须是已脱敏的文本行。"""
    global _next_seq
    text_lines = [str(line) for line in lines if str(line).strip()]
    if not text_lines:
        return
    with _lock:
        seq = _next_seq
        _next_seq += 1
        _entries.append(
            {
                "seq": seq,
                "ts": time.time(),
                "level": level_name(level),
                "lines": text_lines,
            }
        )


def snapshot(after_seq: int = 0, limit: int = MAX_ENTRIES) -> list[dict[str, Any]]:
    """返回 seq 大于 ``after_seq`` 的条目（最多 ``limit`` 条，最新的在后）。"""
    try:
        cursor = int(after_seq)
    except (TypeError, ValueError):
        cursor = 0
    try:
        cap = max(1, int(limit))
    except (TypeError, ValueError):
        cap = MAX_ENTRIES
    with _lock:
        # 逐条深拷贝：lines 是列表，浅拷贝会让调用方改到缓冲内的原始数据
        picked = [
            {**item, "lines": list(item["lines"])}
            for item in _entries
            if item["seq"] > cursor
        ]
    return picked[-cap:]


def clear() -> None:
    """清空缓冲（测试与显式重置用）。"""
    global _next_seq
    with _lock:
        _entries.clear()
        _next_seq = 1


__all__ = ["MAX_ENTRIES", "append", "clear", "level_name", "snapshot"]
