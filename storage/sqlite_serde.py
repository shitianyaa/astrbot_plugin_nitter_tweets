"""推文与投递字段的序列化 / 反序列化。

`SQLiteStorage` 的 mixin：只通过 `self` 协作，不 import 宿主类。
"""

from __future__ import annotations

import json
import sqlite3

try:
    from ..shared import TweetItem, TweetMedia
    from .records import PushHistoryRecord
    from .sqlite_schema import PUSH_HISTORY_V6_COLUMN_ADD_STATEMENTS
except ImportError:
    from shared import TweetItem, TweetMedia
    from storage.records import PushHistoryRecord
    from storage.sqlite_schema import PUSH_HISTORY_V6_COLUMN_ADD_STATEMENTS


class SQLiteSerdeMixin:
    """行 <-> 对象转换。"""

    @staticmethod
    def _serialize_tweet(tweet: TweetItem) -> str:
        return json.dumps(
            {
                "text": tweet.text,
                "link": tweet.link,
                "published": tweet.published,
                "media": [
                    {
                        "kind": media.kind,
                        "url": media.url,
                        "duration_seconds": media.duration_seconds,
                    }
                    for media in tweet.media
                    if media.url
                ],
                "media_warnings": tweet.media_warnings,
                "ai_warnings": tweet.ai_warnings,
                "translation": tweet.translation,
            },
            ensure_ascii=False,
        )

    @staticmethod
    def _deserialize_tweet(raw_data: str) -> TweetItem:
        try:
            data = json.loads(raw_data)
        except (TypeError, ValueError):
            data = {}
        tweet = TweetItem(
            text=str(data.get("text") or ""),
            link=str(data.get("link") or ""),
            published=str(data.get("published") or ""),
            media=[
                TweetMedia(
                    kind=str(item.get("kind") or ""),
                    url=str(item.get("url") or ""),
                    path=None,
                    duration_seconds=item.get("duration_seconds"),
                )
                for item in data.get("media", [])
                if isinstance(item, dict) and str(item.get("url") or "")
            ],
            media_warnings=[
                str(item) for item in data.get("media_warnings", []) if str(item)
            ],
            ai_warnings=[
                str(item) for item in data.get("ai_warnings", []) if str(item)
            ],
            translation=str(data.get("translation") or ""),
        )
        return tweet

    def _push_history_record_from_row(self, row: sqlite3.Row) -> PushHistoryRecord:
        return PushHistoryRecord(
            id=int(row["id"]),
            group_id=str(row["group_id"]),
            username=str(row["username"]),
            status_id=str(row["status_id"]),
            original_link=str(row["original_link"] or ""),
            target_umo=str(row["target_umo"] or ""),
            source=str(row["source"] or ""),
            instance=str(row["instance"] or ""),
            pushed_at=int(row["pushed_at"]),
            tweet=self._deserialize_tweet(row["tweet_data"]),
            delivery_status=self._normalize_delivery_status(row["delivery_status"]),
            delivery_error=str(row["delivery_error"] or ""),
        )

    def _ensure_push_history_delivery_columns(self, cursor: sqlite3.Cursor) -> None:
        if not self._table_exists(cursor, "push_history"):
            return
        columns = self._table_columns(cursor, "push_history")
        for name, statement in PUSH_HISTORY_V6_COLUMN_ADD_STATEMENTS.items():
            if name not in columns:
                cursor.execute(statement)

    @staticmethod
    def _normalize_delivery_status(value: object) -> str:
        status = str(value or "").strip()
        if status in {"success", "partial_failed", "failed"}:
            return status
        return "success"
