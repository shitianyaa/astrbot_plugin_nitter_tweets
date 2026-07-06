from __future__ import annotations

import asyncio
import sys
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


from storage import SQLiteStorage
from storage import StorageAdapter


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
                await adapter.add_seen_ids("global", "NASA", ["100"])
                seen_ids = await adapter.get_seen_ids("global", "NASA")
                seen_map = await adapter.get_group_seen_map("global")
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
                summary = await adapter.get_pending_queue_summary("global")
            finally:
                adapter.close()

            self.assertEqual(summary.group_id, "global")
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

    async def test_grouped_legacy_seen_kv_preserves_explicit_global_group_id(self):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "nitter_tweets.db"
            owner = _Owner()
            owner.data["nitter_seen_status_ids"] = {
                "version": 2,
                "groups": {
                    "global": {"NASA": ["100"]},
                    "default": {"OpenAI": ["200"]},
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
                global_seen = await adapter.get_seen_ids("global", "NASA")
                default_seen = await adapter.get_seen_ids("default", "NASA")
                default_openai_seen = await adapter.get_seen_ids("default", "OpenAI")
            finally:
                adapter.close()

            self.assertEqual(global_seen, ["100"])
            self.assertEqual(default_seen, [])
            self.assertEqual(default_openai_seen, ["200"])

    async def test_orphan_runtime_delete_does_not_alias_global_to_default(self):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "nitter_tweets.db"

            with patch.object(
                StorageAdapter,
                "_init_sqlite",
                return_value=SQLiteStorage(db_path),
            ):
                adapter = StorageAdapter(_Owner(), {"storage_backend": "sqlite"}, None)

            try:
                await adapter.migrate_and_sync([
                    types.SimpleNamespace(
                        group_id="default",
                        name="默认分组",
                        enabled=True,
                        check_on_startup=False,
                        interval_check_enabled=True,
                        check_interval_minutes=30,
                        daily_check_enabled=False,
                        daily_check_times=[],
                        scheduled_fetch_limit=5,
                        send_target_interval=1.5,
                        send_user_interval=2.0,
                        notify_no_updates=False,
                        aliases=["default"],
                        users=["NASA"],
                        targets=[],
                    )
                ])
                sqlite = await adapter._ensure_sqlite_connected()
                await asyncio.to_thread(sqlite.add_seen_ids, "global", "NASA", ["100"])
                await asyncio.to_thread(sqlite.add_seen_ids, "default", "NASA", ["200"])

                summary = await adapter.delete_orphan_group_runtime_data("global")
                global_seen = await asyncio.to_thread(sqlite.get_seen_ids, "global", "NASA")
                default_seen = await asyncio.to_thread(sqlite.get_seen_ids, "default", "NASA")
            finally:
                adapter.close()

            self.assertEqual(summary["seen_deleted"], 1)
            self.assertEqual(global_seen, [])
            self.assertEqual(default_seen, ["200"])


if __name__ == "__main__":
    unittest.main()
