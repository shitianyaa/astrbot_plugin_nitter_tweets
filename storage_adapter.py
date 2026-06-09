"""Storage adapter for SQLite storage and legacy KV migration."""
from __future__ import annotations

import asyncio
from pathlib import Path

from astrbot.api import logger

try:
    from .config_compat import config_get
    from .seen_store import SeenStore
    from .sqlite_storage import PendingQueueSummary, PendingTweetRecord, SQLiteStorage
except ImportError:
    from config_compat import config_get
    from seen_store import SeenStore
    from sqlite_storage import PendingQueueSummary, PendingTweetRecord, SQLiteStorage


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
                f"storage_backend={configured_backend} is no longer supported; "
                "using SQLite and importing legacy KV seen IDs only"
            )

        logger.info("[NitterTweets] Using SQLite storage backend")
        self.sqlite: SQLiteStorage | None = self._init_sqlite()
        self.seen_store = SeenStore(owner)

    def _init_sqlite(self) -> SQLiteStorage:
        """Initialize SQLite storage."""
        try:
            from astrbot.api.star import StarTools

            data_dir = StarTools.get_data_dir("astrbot_plugin_nitter_tweets")
        except Exception:
            data_dir = Path("data")

        db_path = Path(data_dir) / "nitter_tweets.db"
        return SQLiteStorage(db_path)

    async def _ensure_sqlite_connected(self) -> SQLiteStorage:
        """Return SQLite storage with an initialized connection."""
        assert self.sqlite is not None
        await self.sqlite.connect()
        return self.sqlite

    async def migrate_and_sync(self, schedule_groups: list) -> None:
        """Migrate legacy KV seen IDs once and sync configured groups."""
        sqlite = await self._ensure_sqlite_connected()

        grouped_seen_map = await self.seen_store.get_grouped_seen_map()
        await asyncio.to_thread(
            sqlite.migrate_kv_seen_data, grouped_seen_map.groups
        )

        await asyncio.to_thread(sqlite.sync_config_groups, schedule_groups)

    async def get_group_seen_map(self, group_id: str) -> dict[str, list[str]]:
        """Get seen IDs for every user in a group."""
        sqlite = await self._ensure_sqlite_connected()
        return await asyncio.to_thread(sqlite.get_group_seen_map, group_id)

    async def put_group_seen_map(
        self, group_id: str, seen_map: dict[str, list[str]]
    ) -> None:
        """Save a group's seen map into SQLite."""
        sqlite = await self._ensure_sqlite_connected()
        for username, status_ids in seen_map.items():
            if status_ids:
                await asyncio.to_thread(
                    sqlite.add_seen_ids, group_id, username, status_ids
                )

    async def get_seen_ids(self, group_id: str, username: str) -> list[str]:
        """Get seen IDs for a group/user pair."""
        sqlite = await self._ensure_sqlite_connected()
        return await asyncio.to_thread(sqlite.get_seen_ids, group_id, username)

    async def add_seen_ids(
        self, group_id: str, username: str, status_ids: list[str]
    ) -> None:
        """Add seen IDs for a group/user pair."""
        sqlite = await self._ensure_sqlite_connected()
        await asyncio.to_thread(
            sqlite.add_seen_ids, group_id, username, status_ids
        )

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
            group_id,
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
            sqlite.get_pending_tweets, group_id, limit
        )

    async def get_pending_queue_summary(
        self, group_id: str
    ) -> PendingQueueSummary:
        """Get pending queue counts for a group."""
        sqlite = await self._ensure_sqlite_connected()
        return await asyncio.to_thread(
            sqlite.get_pending_queue_summary, group_id
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

    async def cleanup_sent_pending_tweets(self, older_than: int) -> int:
        """Delete sent pending tweet rows older than a timestamp."""
        sqlite = await self._ensure_sqlite_connected()
        return await asyncio.to_thread(
            sqlite.cleanup_sent_pending_tweets, older_than
        )

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
