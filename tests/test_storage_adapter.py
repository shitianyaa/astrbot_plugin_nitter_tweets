from __future__ import annotations

import asyncio
import sys
import time
import types
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


if "astrbot.api" not in sys.modules:
    astrbot_module = types.ModuleType("astrbot")
    astrbot_api_module = types.ModuleType("astrbot.api")

    class _Logger:
        def debug(self, *args, **kwargs):
            pass

        def info(self, *args, **kwargs):
            pass

        def warning(self, *args, **kwargs):
            pass

        def error(self, *args, **kwargs):
            pass

    astrbot_api_module.logger = _Logger()
    sys.modules["astrbot"] = astrbot_module
    sys.modules["astrbot.api"] = astrbot_api_module


from sqlite_storage import SQLiteStorage
from storage_adapter import StorageAdapter


class _Owner:
    def __init__(self):
        self.data = {}
        self.put_calls = 0
        self.deleted_keys = []

    async def get_kv_data(self, key, default):
        return self.data.get(key, default)

    async def put_kv_data(self, key, value):
        self.put_calls += 1
        self.data[key] = value

    async def delete_kv_data(self, key):
        self.deleted_keys.append(key)
        self.data.pop(key, None)


class StorageAdapterTest(unittest.IsolatedAsyncioTestCase):
    async def test_kv_legacy_config_still_uses_sqlite_runtime_storage(self):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "nitter_tweets.db"
            owner = _Owner()

            with patch.object(
                StorageAdapter,
                "_init_sqlite",
                return_value=SQLiteStorage(db_path),
            ):
                adapter = StorageAdapter(
                    owner,
                    {"storage_backend": "kv_legacy"},
                    context=None,
                )

            try:
                await adapter.migrate_and_sync([])
                await adapter.add_seen_ids("default", "NASA", ["100"])
                seen_ids = await adapter.get_seen_ids("default", "NASA")
                seen_map = await adapter.get_group_seen_map("default")
            finally:
                adapter.close()

            self.assertEqual(seen_ids, ["100"])
            self.assertEqual(seen_map["NASA"], ["100"])
            self.assertEqual(owner.put_calls, 0)
            self.assertTrue(db_path.exists())

            await asyncio.to_thread(db_path.unlink, missing_ok=True)
            await asyncio.to_thread(db_path.with_suffix(".db-wal").unlink, missing_ok=True)
            await asyncio.to_thread(db_path.with_suffix(".db-shm").unlink, missing_ok=True)

    async def test_queue_summary_connects_sqlite_lazily(self):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "nitter_tweets.db"

            with patch.object(
                StorageAdapter,
                "_init_sqlite",
                return_value=SQLiteStorage(db_path),
            ):
                adapter = StorageAdapter(
                    _Owner(),
                    {"storage_backend": "sqlite"},
                    context=None,
                )

            try:
                summary = await adapter.get_pending_queue_summary("default")
            finally:
                adapter.close()

            self.assertEqual(summary.group_id, "default")
            self.assertEqual(summary.pending_count, 0)
            self.assertTrue(db_path.exists())

    async def test_legacy_seen_kv_is_deleted_after_migration(self):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "nitter_tweets.db"
            owner = _Owner()
            owner.data["nitter_seen_status_ids"] = {"NASA": ["100", "99"]}

            with patch.object(
                StorageAdapter,
                "_init_sqlite",
                return_value=SQLiteStorage(db_path),
            ):
                adapter = StorageAdapter(owner, {"storage_backend": "sqlite"}, None)

            try:
                await adapter.migrate_and_sync([])
                seen_ids = await adapter.get_seen_ids("default", "NASA")
            finally:
                adapter.close()

            self.assertEqual(seen_ids, ["100", "99"])
            self.assertEqual(
                owner.deleted_keys,
                [
                    "nitter_seen_status_ids",
                    "nitter_seen_status_ids_by_target_v1",
                ],
            )
            self.assertNotIn("nitter_seen_status_ids", owner.data)

    async def test_target_scoped_legacy_seen_kv_is_migrated_and_deleted(self):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "nitter_tweets.db"
            owner = _Owner()
            owner.data["nitter_seen_status_ids_by_target_v1"] = {
                "telegram:FriendMessage:1": {
                    "NASA": ["100", "99"],
                    "OpenAI": ["80"],
                },
                "telegram:FriendMessage:2": {
                    "NASA": ["98"],
                },
            }

            with patch.object(
                StorageAdapter,
                "_init_sqlite",
                return_value=SQLiteStorage(db_path),
            ):
                adapter = StorageAdapter(owner, {"storage_backend": "sqlite"}, None)

            try:
                await adapter.migrate_and_sync([])
                nasa_seen = await adapter.get_seen_ids("default", "NASA")
                openai_seen = await adapter.get_seen_ids("default", "OpenAI")
            finally:
                adapter.close()

            self.assertEqual(set(nasa_seen), {"100", "99", "98"})
            self.assertEqual(len(nasa_seen), 3)
            self.assertEqual(openai_seen, ["80"])
            self.assertEqual(
                owner.deleted_keys,
                [
                    "nitter_seen_status_ids",
                    "nitter_seen_status_ids_by_target_v1",
                ],
            )
            self.assertNotIn("nitter_seen_status_ids_by_target_v1", owner.data)

    async def test_migrate_legacy_global_group_id(self):
        """SQLite 中 group_id='global' 的行应被迁移为 'default'."""
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "nitter_tweets.db"
            owner = _Owner()

            with patch.object(
                StorageAdapter,
                "_init_sqlite",
                return_value=SQLiteStorage(db_path),
            ):
                adapter = StorageAdapter(owner, {"storage_backend": "sqlite"}, None)

            try:
                sqlite = adapter.sqlite
                await sqlite.connect()

                # 模拟 v0.9.x 数据：手动插入 group_id='global' 的行
                now = int(time.time())
                sqlite.conn.execute(
                    "INSERT INTO seen_tweets (group_id, username, status_id, seen_at) "
                    "VALUES (?, ?, ?, ?)",
                    ("global", "NASA", "100", now),
                )
                sqlite.conn.execute(
                    "INSERT INTO seen_tweets (group_id, username, status_id, seen_at) "
                    "VALUES (?, ?, ?, ?)",
                    ("global", "NASA", "101", now),
                )
                sqlite.conn.execute(
                    "INSERT INTO group_users (group_id, username, added_at) "
                    "VALUES (?, ?, ?)",
                    ("global", "NASA", now),
                )
                sqlite.conn.execute(
                    "INSERT INTO group_targets (group_id, target_umo, added_at) "
                    "VALUES (?, ?, ?)",
                    ("global", "aiocqhttp:GroupMessage:123", now),
                )
                sqlite.conn.execute(
                    "INSERT INTO groups ("
                    "group_id, name, enabled, check_on_startup, "
                    "interval_check_enabled, check_interval_minutes, "
                    "daily_check_enabled, daily_check_times, "
                    "scheduled_fetch_limit, send_target_interval, "
                    "send_user_interval, notify_no_updates, aliases, "
                    "created_at, updated_at"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        "global", "默认分组", 1, 0,
                        1, 30, 0, "[]", 5, 1.5, 2.0, 0, "[]",
                        now, now,
                    ),
                )
                sqlite.conn.commit()

                # 执行迁移
                sqlite.migrate_legacy_global_group_id()

                # 验证：seen_tweets 应迁移到 'default'
                seen_ids = sqlite.get_seen_ids("default", "NASA")
                self.assertEqual(set(seen_ids), {"100", "101"})

                # 验证：group_users 应迁移到 'default'
                users = sqlite.get_group_users("default")
                self.assertEqual(users, ["NASA"])

                # 验证：group_targets 应迁移到 'default'
                targets = sqlite.get_group_targets("default")
                self.assertEqual(targets, ["aiocqhttp:GroupMessage:123"])

                # 验证：groups 应迁移到 'default'
                groups = sqlite.get_all_groups()
                self.assertEqual(len(groups), 1)
                self.assertEqual(groups[0]["group_id"], "default")

                # 验证：'global' 行应已删除
                global_seen = sqlite.conn.execute(
                    "SELECT 1 FROM seen_tweets WHERE group_id = 'global' LIMIT 1"
                ).fetchone()
                self.assertIsNone(global_seen)

                # 验证：迁移标记应已设置
                migrated_at = sqlite.get_meta("legacy_global_group_id_migrated")
                self.assertIsNotNone(migrated_at)

                # 验证：再次调用应跳过（幂等）
                sqlite.migrate_legacy_global_group_id()
                seen_ids_2 = sqlite.get_seen_ids("default", "NASA")
                self.assertEqual(set(seen_ids_2), {"100", "101"})

            finally:
                adapter.close()

    async def test_migrate_legacy_global_id_with_existing_default(self):
        """当 'default' 行已存在时，'global' 行应合并（INSERT OR IGNORE/REPLACE）."""
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "nitter_tweets.db"
            owner = _Owner()

            with patch.object(
                StorageAdapter,
                "_init_sqlite",
                return_value=SQLiteStorage(db_path),
            ):
                adapter = StorageAdapter(owner, {"storage_backend": "sqlite"}, None)

            try:
                sqlite = adapter.sqlite
                await sqlite.connect()

                now = int(time.time())

                # 同时有 'default' 和 'global' 的 seen 数据
                sqlite.conn.execute(
                    "INSERT INTO seen_tweets (group_id, username, status_id, seen_at) "
                    "VALUES (?, ?, ?, ?)",
                    ("default", "NASA", "200", now),
                )
                sqlite.conn.execute(
                    "INSERT INTO seen_tweets (group_id, username, status_id, seen_at) "
                    "VALUES (?, ?, ?, ?)",
                    ("global", "NASA", "100", now),
                )
                sqlite.conn.execute(
                    "INSERT INTO seen_tweets (group_id, username, status_id, seen_at) "
                    "VALUES (?, ?, ?, ?)",
                    ("global", "NASA", "200", now),  # 与 default 重复
                )

                # group_users：default 已有 OpenAI，global 有 NASA
                sqlite.conn.execute(
                    "INSERT INTO group_users (group_id, username, added_at) "
                    "VALUES (?, ?, ?)",
                    ("default", "OpenAI", now),
                )
                sqlite.conn.execute(
                    "INSERT INTO group_users (group_id, username, added_at) "
                    "VALUES (?, ?, ?)",
                    ("global", "NASA", now),
                )
                sqlite.conn.commit()

                sqlite.migrate_legacy_global_group_id()

                # seen：100 和 200 应都在 default 下
                seen_ids = sqlite.get_seen_ids("default", "NASA")
                self.assertEqual(set(seen_ids), {"100", "200"})

                # group_users：OpenAI 和 NASA 都应在 default 下
                users = sqlite.get_group_users("default")
                self.assertIn("NASA", users)
                self.assertIn("OpenAI", users)

                # global 行应全部删除
                global_count = sqlite.conn.execute(
                    "SELECT COUNT(*) FROM seen_tweets WHERE group_id = 'global'"
                ).fetchone()[0]
                self.assertEqual(global_count, 0)

            finally:
                adapter.close()


if __name__ == "__main__":
    unittest.main()
