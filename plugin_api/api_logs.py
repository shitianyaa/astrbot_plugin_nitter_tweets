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

    async def build_logs(self, after_seq: int = 0) -> dict[str, Any]:
        entries = log_buffer.snapshot(after_seq)
        return self._ok(entries=entries, max_entries=log_buffer.MAX_ENTRIES)
