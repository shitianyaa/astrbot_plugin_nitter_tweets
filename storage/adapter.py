"""Storage adapter for SQLite storage and legacy KV migration."""
from __future__ import annotations

import asyncio
from pathlib import Path

from astrbot.api import logger

try:
    from ..config import config_get
    from ..shared.group_ids import (
        DEFAULT_GROUP_ID,
        LEGACY_GLOBAL_GROUP_ID,
        normalize_stable_group_id,
    )
    from .seen import KV_KEY_SEEN_BY_TARGET, SeenStore
    from .sqlite import (
        PendingQueueSummary,
        PendingTweetRecord,
        PushHistoryRecord,
        SQLiteStorage,
    )
except ImportError:
    from config import config_get
    from shared.group_ids import (
        DEFAULT_GROUP_ID,
        LEGACY_GLOBAL_GROUP_ID,
        normalize_stable_group_id,
    )
    from storage.seen import KV_KEY_SEEN_BY_TARGET, SeenStore
    from storage.sqlite import (
        PendingQueueSummary,
        PendingTweetRecord,
        PushHistoryRecord,
        SQLiteStorage,
    )


PLUGIN_NAME = "astrbot_plugin_nitter_tweets"


def _plugin_data_dir() -> Path:
    try:
        from astrbot.api.star import StarTools

        return Path(StarTools.get_data_dir(PLUGIN_NAME))
    except Exception:
        try:
            from astrbot.core.utils.astrbot_path import get_astrbot_data_path

            return Path(get_astrbot_data_path()) / "plugin_data" / PLUGIN_NAME
        except Exception:
            return Path("data") / "plugin_data" / PLUGIN_NAME


class StorageAdapter:
    """SQLite runtime storage with legacy KV used only as a migration source."""

    def __init__(self, owner, config, context):
        self.owner = owner
        self.config = config
        self.context = context

        configured_backend = str(
            config_get(config, "storage_backend", "sqlite")
        ).strip().lower()
        if configured_backend and configured_backend != "sqlite":
            logger.info(
                "[NitterTweets] "
                f"storage_backend={configured_backend} 已不再支持；"
                "将使用 SQLite，并仅导入旧 KV seen ID"
            )

        logger.info("[NitterTweets] 使用 SQLite 存储后端")
        self.sqlite: SQLiteStorage | None = self._init_sqlite()
        self.seen_store = SeenStore(owner)
        self._legacy_global_aliases_default = False

    def _init_sqlite(self) -> SQLiteStorage:
        """Initialize SQLite storage."""
        db_path = _plugin_data_dir() / "nitter_tweets.db"
        return SQLiteStorage(db_path)

    async def _ensure_sqlite_connected(self) -> SQLiteStorage:
        """Return SQLite storage with an initialized connection."""
        assert self.sqlite is not None
        await self.sqlite.connect()
        return self.sqlite

    async def migrate_and_sync(self, schedule_groups: list) -> None:
        """Migrate legacy KV seen IDs once and sync configured groups."""
        sqlite = await self._ensure_sqlite_connected()
        configured_group_ids = {
            normalize_stable_group_id(group.group_id)
            for group in schedule_groups
        }
        self._legacy_global_aliases_default = (
            DEFAULT_GROUP_ID in configured_group_ids
            and LEGACY_GLOBAL_GROUP_ID not in configured_group_ids
        )

        grouped_seen_map = await self.seen_store.get_grouped_seen_map()
        has_legacy_seen = self._has_seen_data(grouped_seen_map.groups)
        await asyncio.to_thread(
            sqlite.migrate_kv_seen_data, grouped_seen_map.groups
        )
        if has_legacy_seen:
            await self.delete_legacy_seen_kv()

        await asyncio.to_thread(sqlite.sync_config_groups, schedule_groups)

    async def get_group_seen_map(self, group_id: str) -> dict[str, list[str]]:
        """Get seen IDs for every user in a group."""
        sqlite = await self._ensure_sqlite_connected()
        return await asyncio.to_thread(
            sqlite.get_group_seen_map, self._storage_group_id(group_id)
        )

    async def put_group_seen_map(
        self, group_id: str, seen_map: dict[str, list[str]]
    ) -> None:
        """Save a group's seen map into SQLite."""
        sqlite = await self._ensure_sqlite_connected()
        storage_group_id = self._storage_group_id(group_id)
        for username, status_ids in seen_map.items():
            if status_ids:
                await asyncio.to_thread(
                    sqlite.add_seen_ids, storage_group_id, username, status_ids
                )

    async def get_seen_ids(self, group_id: str, username: str) -> list[str]:
        """Get seen IDs for a group/user pair."""
        sqlite = await self._ensure_sqlite_connected()
        return await asyncio.to_thread(
            sqlite.get_seen_ids, self._storage_group_id(group_id), username
        )

    async def add_seen_ids(
        self, group_id: str, username: str, status_ids: list[str]
    ) -> None:
        """Add seen IDs for a group/user pair."""
        sqlite = await self._ensure_sqlite_connected()
        await asyncio.to_thread(
            sqlite.add_seen_ids, self._storage_group_id(group_id), username, status_ids
        )

    async def clear_seen_records(self, group_id: str | None = None) -> int:
        """Clear SQLite seen records for a group, or all groups when omitted."""
        sqlite = await self._ensure_sqlite_connected()
        storage_group_id = self._storage_group_id(group_id) if group_id else None
        return await asyncio.to_thread(sqlite.clear_seen_tweets, storage_group_id)

    async def delete_legacy_seen_kv(self) -> bool:
        """Delete legacy KV seen data so it cannot resurrect after reinstall."""
        delete_kv_data = getattr(self.owner, "delete_kv_data", None)
        if not callable(delete_kv_data):
            logger.warning(
                "[NitterTweets] 检测到旧 KV seen 数据，但 owner 不支持 delete_kv_data()"
            )
            return False

        try:
            for key in (self.seen_store.key, KV_KEY_SEEN_BY_TARGET):
                await delete_kv_data(key)
        except Exception as exc:
            logger.warning(f"[NitterTweets] 删除旧 KV seen 数据失败: {exc}")
            return False
        return True

    async def enqueue_pending_tweets(
        self,
        group_id: str,
        username: str,
        instance: str,
        tweets: list,
        scheduled_at: int | None = None,
    ) -> int:
        """Add prepared tweets to the pending publish queue."""
        sqlite = await self._ensure_sqlite_connected()
        return await asyncio.to_thread(
            sqlite.enqueue_pending_tweets,
            self._storage_group_id(group_id),
            username,
            instance,
            tweets,
            scheduled_at,
        )

    async def get_pending_tweets(
        self, group_id: str, limit: int
    ) -> list[PendingTweetRecord]:
        """Get unsent pending tweets for a group."""
        sqlite = await self._ensure_sqlite_connected()
        return await asyncio.to_thread(
            sqlite.get_pending_tweets, self._storage_group_id(group_id), limit
        )

    async def get_pending_queue_summary(
        self, group_id: str
    ) -> PendingQueueSummary:
        """Get pending queue counts for a group."""
        sqlite = await self._ensure_sqlite_connected()
        return await asyncio.to_thread(
            sqlite.get_pending_queue_summary, self._storage_group_id(group_id)
        )

    async def get_pending_media_paths(self) -> set[str]:
        """Get staged media paths still referenced by unsent queue rows."""
        sqlite = await self._ensure_sqlite_connected()
        return await asyncio.to_thread(sqlite.get_pending_media_paths)

    async def mark_pending_tweets_published(self, pending_ids: list[int]) -> None:
        """Mark pending tweets as sent."""
        sqlite = await self._ensure_sqlite_connected()
        await asyncio.to_thread(
            sqlite.mark_pending_tweets_published, pending_ids
        )

    async def mark_pending_tweets_delivered(
        self, pending_ids: list[int], target: str
    ) -> None:
        """Record that pending tweets reached one configured target."""
        sqlite = await self._ensure_sqlite_connected()
        await asyncio.to_thread(
            sqlite.mark_pending_tweets_delivered, pending_ids, target
        )

    async def mark_pending_tweets_failed(
        self, pending_ids: list[int], error: str
    ) -> None:
        """Record a publish failure for pending tweets."""
        sqlite = await self._ensure_sqlite_connected()
        await asyncio.to_thread(
            sqlite.mark_pending_tweets_failed, pending_ids, error
        )

    async def delete_pending_tweets(self, pending_ids: list[int]) -> None:
        """Delete pending tweets and media rows."""
        sqlite = await self._ensure_sqlite_connected()
        await asyncio.to_thread(sqlite.delete_pending_tweets, pending_ids)

    async def delete_group_runtime_data(self, group_id: str) -> dict[str, int]:
        """Delete one group's runtime rows from SQLite."""
        sqlite = await self._ensure_sqlite_connected()
        return await asyncio.to_thread(
            sqlite.delete_group_runtime_data, self._storage_group_id(group_id)
        )

    async def cleanup_sent_pending_tweets(self, older_than: int) -> int:
        """Delete sent pending tweet rows older than a timestamp."""
        sqlite = await self._ensure_sqlite_connected()
        return await asyncio.to_thread(
            sqlite.cleanup_sent_pending_tweets, older_than
        )

    async def record_push_history(
        self,
        group_id: str,
        username: str,
        tweet,
        target_umo: str,
        source: str,
        instance: str = "",
    ) -> int:
        """Record one successful push delivery."""
        sqlite = await self._ensure_sqlite_connected()
        return await asyncio.to_thread(
            sqlite.record_push_history,
            self._storage_group_id(group_id),
            username,
            tweet,
            target_umo,
            source,
            instance,
        )

    async def get_push_history(
        self,
        group_id: str = "",
        username: str = "",
        limit: int = 50,
        offset: int = 0,
    ) -> list[PushHistoryRecord]:
        """Return recent successful push history."""
        sqlite = await self._ensure_sqlite_connected()
        storage_group_id = self._storage_group_id(group_id) if group_id else ""
        return await asyncio.to_thread(
            sqlite.get_push_history,
            storage_group_id,
            username,
            limit,
            offset,
        )

    async def count_push_history(self, group_id: str = "", username: str = "") -> int:
        """Return count of grouped successful push history records."""
        sqlite = await self._ensure_sqlite_connected()
        storage_group_id = self._storage_group_id(group_id) if group_id else ""
        return await asyncio.to_thread(
            sqlite.count_push_history,
            storage_group_id,
            username,
        )

    async def get_push_history_record(self, record_id: int) -> PushHistoryRecord | None:
        """Return one push history record."""
        sqlite = await self._ensure_sqlite_connected()
        return await asyncio.to_thread(sqlite.get_push_history_record, record_id)

    def initial_seen_ids(self, ids: list[str]) -> list[str]:
        """Build an initial limited seen ID list."""
        return self.seen_store.initial_seen_ids(ids)

    def merge_seen_ids(self, new_ids: list[str], old_ids: list[str]) -> list[str]:
        """Merge seen IDs with the legacy-compatible limit/order helper."""
        return self.seen_store.merge_seen_ids(new_ids, old_ids)

    def close(self) -> None:
        """Close the SQLite connection."""
        if self.sqlite:
            self.sqlite.close()

    def _storage_group_id(self, group_id: str | None) -> str:
        normalized = normalize_stable_group_id(group_id or "")
        if (
            self._legacy_global_aliases_default
            and normalized == LEGACY_GLOBAL_GROUP_ID
        ):
            return DEFAULT_GROUP_ID
        return normalized

    @staticmethod
    def _has_seen_data(grouped_seen_map: dict[str, dict[str, list[str]]]) -> bool:
        return any(
            bool(status_ids)
            for seen_map in grouped_seen_map.values()
            for status_ids in seen_map.values()
        )
