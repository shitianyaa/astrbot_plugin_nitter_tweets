"""有界的内存日志环缓冲，供 WebUI 实例诊断终端展示。

只记录插件自己经 ``safe_task_log`` / ``safe_log`` / ``safe_block_log`` 发出的事件——宿主 astrbot 的
日志不在此列。缓冲仅存于进程内存，重启即清空；这是「本次会话诊断视图」，
不是持久日志。

运行时模块禁止 ``import logging``（插件市场上架约束），因此级别用整数映射，
不引用标准库常量。
"""

from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from typing import Any

MAX_ENTRIES = 200
MAX_DEBUG_ENTRIES = 200
RING_NAMES = ("main", "debug")

# 进程级会话标识：插件重启（热重载）后 seq 从 1 重新计数，客户端靠它判定
# 自己缓存的 after_seq 是否还有效。
_SESSION_ID = uuid.uuid4().hex

_LEVEL_NAMES = {
    10: "debug",
    20: "info",
    30: "warning",
    40: "error",
    50: "critical",
}

_lock = threading.Lock()
_rings: dict[str, deque[dict[str, Any]]] = {
    "main": deque(maxlen=MAX_ENTRIES),
    "debug": deque(maxlen=MAX_DEBUG_ENTRIES),
}
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
        name = level_name(level)
        _rings["debug" if name == "debug" else "main"].append(
            {
                "seq": seq,
                "ts": time.time(),
                "level": name,
                "lines": text_lines,
            }
        )


def normalize_ring(ring: str) -> str:
    return ring if ring in RING_NAMES else "main"


def ring_max_entries(ring: str = "main") -> int:
    return MAX_DEBUG_ENTRIES if normalize_ring(ring) == "debug" else MAX_ENTRIES


def snapshot(
    after_seq: int = 0, limit: int | None = None, ring: str = "main"
) -> list[dict[str, Any]]:
    """读取指定环的新条目；主环与 DEBUG 互不占用容量。"""
    ring = normalize_ring(ring)
    try:
        cursor = int(after_seq)
    except (TypeError, ValueError):
        cursor = 0
    try:
        cap = max(1, int(limit)) if limit is not None else ring_max_entries(ring)
    except (TypeError, ValueError):
        cap = ring_max_entries(ring)
    with _lock:
        # 逐条深拷贝：lines 是列表，浅拷贝会让调用方改到缓冲内的原始数据
        picked = [
            {**item, "lines": list(item["lines"])}
            for item in _rings[ring]
            if item["seq"] > cursor
        ]
    return picked[-cap:]


def session_id() -> str:
    """本进程的环缓冲会话标识；进程重启后会变。"""
    return _SESSION_ID


def next_seq() -> int:
    """下一个待分配的 seq。

    客户端用它判定游标是否还有效：插件进程重启后 seq 从 1 重新计数，
    旧的 ``after_seq`` 会比新序号还大，接口将永远返回空。
    """
    with _lock:
        return _next_seq


def clear() -> None:
    """清空缓冲（测试与显式重置用）。"""
    global _next_seq
    with _lock:
        for entries in _rings.values():
            entries.clear()
        _next_seq = 1


__all__ = [
    "MAX_ENTRIES",
    "MAX_DEBUG_ENTRIES",
    "RING_NAMES",
    "normalize_ring",
    "ring_max_entries",
    "append",
    "clear",
    "level_name",
    "next_seq",
    "session_id",
    "snapshot",
]
