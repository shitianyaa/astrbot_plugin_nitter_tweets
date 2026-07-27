"""push history 记录 DTO。

单独成文件，供 `sqlite.py` 与序列化 mixin 共享而不形成循环导入。
`storage.sqlite.PushHistoryRecord` 与 `storage.PushHistoryRecord` 仍可解析。
"""

from __future__ import annotations

from dataclasses import dataclass

try:
    from ..shared import TweetItem
except ImportError:
    from shared import TweetItem


@dataclass(slots=True)
class PushHistoryRecord:
    id: int
    group_id: str
    username: str
    status_id: str
    original_link: str
    target_umo: str
    source: str
    instance: str
    pushed_at: int
    tweet: TweetItem
    delivery_status: str = "success"
    delivery_error: str = ""


@dataclass(slots=True)
class PushHistoryGroupSummary:
    group_id: str
    record_count: int
    user_count: int
    latest_pushed_at: int
