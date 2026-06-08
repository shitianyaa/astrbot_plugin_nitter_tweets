"""Storage adapter for SQLite and KV backends."""
from __future__ import annotations

import asyncio
from pathlib import Path

from astrbot.api import logger

try:
    from .seen_store import GLOBAL_GROUP_ID, SEEN_LIMIT_PER_USER, SeenStore
    from .sqlite_storage import SQLiteStorage
except ImportError:
    from seen_store import GLOBAL_GROUP_ID, SEEN_LIMIT_PER_USER, SeenStore
    from sqlite_storage import SQLiteStorage


class StorageAdapter:
    """存储适配器，统一 SQLite 和 KV 两种后端."""

    def __init__(self, owner, config, context):
        self.owner = owner
        self.config = config
        self.context = context
        self.backend = config.get("storage_backend", "sqlite").strip().lower()

        if self.backend == "kv_legacy":
            logger.info("[NitterTweets] Using KV legacy storage backend")
            self.sqlite: SQLiteStorage | None = None
            self.seen_store = SeenStore(owner)
        else:
            # 默认使用 SQLite
            logger.info("[NitterTweets] Using SQLite storage backend")
            self.sqlite = self._init_sqlite()
            self.seen_store = SeenStore(owner)  # Still needed for merge_seen_ids helper

    def _init_sqlite(self) -> SQLiteStorage:
        """初始化 SQLite 存储."""
        try:
            from astrbot.api.star import StarTools
            data_dir = StarTools.get_data_dir("astrbot_plugin_nitter_tweets")
        except Exception:
            # 降级到当前目录
            data_dir = Path("data")

        db_path = Path(data_dir) / "nitter_tweets.db"
        storage = SQLiteStorage(db_path)
        return storage

    async def migrate_and_sync(self, schedule_groups: list) -> None:
        """执行迁移并同步配置分组到数据库."""
        if self.sqlite is None:
            return

        # Connect to database
        await self.sqlite.connect()

        # 从 KV 迁移 seen 数据
        grouped_seen_map = await self.seen_store.get_grouped_seen_map()
        await asyncio.to_thread(
            self.sqlite.migrate_kv_seen_data, grouped_seen_map.groups
        )

        # 同步配置分组到数据库
        await asyncio.to_thread(self.sqlite.sync_config_groups, schedule_groups)

    async def get_group_seen_map(self, group_id: str) -> dict[str, list[str]]:
        """获取分组的 seen map."""
        if self.sqlite:
            return await asyncio.to_thread(self.sqlite.get_group_seen_map, group_id)
        return await self.seen_store.get_group_seen_map(group_id)

    async def put_group_seen_map(self, group_id: str, seen_map: dict[str, list[str]]) -> None:
        """保存分组的 seen map."""
        if self.sqlite:
            # SQLite 模式：逐个用户更新 seen IDs
            for username, status_ids in seen_map.items():
                if status_ids:  # 只保存非空列表
                    await asyncio.to_thread(
                        self.sqlite.add_seen_ids, group_id, username, status_ids
                    )
        else:
            await self.seen_store.put_group_seen_map(group_id, seen_map)

    async def get_seen_ids(self, group_id: str, username: str) -> list[str]:
        """获取指定分组和用户的 seen IDs."""
        if self.sqlite:
            return await asyncio.to_thread(
                self.sqlite.get_seen_ids, group_id, username
            )

        seen_map = await self.seen_store.get_group_seen_map(group_id)
        return seen_map.get(username, [])

    async def add_seen_ids(self, group_id: str, username: str, status_ids: list[str]) -> None:
        """添加 seen IDs."""
        if self.sqlite:
            await asyncio.to_thread(
                self.sqlite.add_seen_ids, group_id, username, status_ids
            )
        else:
            # KV 模式：读取、合并、写入
            seen_map = await self.seen_store.get_group_seen_map(group_id)
            old_ids = seen_map.get(username, [])
            merged_ids = self.seen_store.merge_seen_ids(status_ids, old_ids)
            seen_map[username] = merged_ids
            await self.seen_store.put_group_seen_map(group_id, seen_map)

    def initial_seen_ids(self, ids: list[str]) -> list[str]:
        """初始化 seen IDs（限制数量）."""
        return self.seen_store.initial_seen_ids(ids)

    def merge_seen_ids(self, new_ids: list[str], old_ids: list[str]) -> list[str]:
        """合并 seen IDs."""
        return self.seen_store.merge_seen_ids(new_ids, old_ids)

    def close(self) -> None:
        """关闭存储连接."""
        if self.sqlite:
            self.sqlite.close()
