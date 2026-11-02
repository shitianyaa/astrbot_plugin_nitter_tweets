"""诊断日志读取接口。

`NitterWebAPI` 的 mixin：把 ``shared.log_buffer`` 的内存环缓冲暴露给 WebUI
实例诊断终端。只读、只含插件自身经安全辅助函数发出的事件。
"""

from __future__ import annotations

from typing import Any

try:
    from ..shared import log_buffer
except ImportError:
    from shared import log_buffer


class WebAPILogsMixin:
    """logs 数据组装。"""

    async def build_logs(
        self, after_seq: int = 0, level: str = "main"
    ) -> dict[str, Any]:
        level = log_buffer.normalize_ring(level)
        entries = log_buffer.snapshot(after_seq, ring=level)
        return self._ok(
            entries=entries,
            level=level,
            max_entries=log_buffer.ring_max_entries(level),
            # 会话标识：进程重启后变，前端据此判定游标失效
            session_id=log_buffer.session_id(),
            # 二级兜底：游标比下一个序号还大时同样重拉
            next_seq=log_buffer.next_seq(),
        )
