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

    async def test_seen_lookup_connects_sqlite_lazily(self):
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
                seen_ids = await adapter.get_seen_ids("default", "NASA")
            finally:
                adapter.close()

            self.assertEqual(seen_ids, [])
            self.assertTrue(db_path.exists())

    async def test_seen_limit_keeps_latest_insert_when_timestamps_tie(self):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "nitter_tweets.db"
            storage = SQLiteStorage(db_path)
            try:
                await storage.connect()
                with patch("storage.sqlite.time.time", return_value=1000):
                    await asyncio.to_thread(
                        storage.add_seen_ids,
                        "default",
                        "NASA",
                        [str(status_id) for status_id in range(300)],
                    )
                    await asyncio.to_thread(
                        storage.add_seen_ids,
                        "default",
                        "NASA",
                        ["newest"],
                    )
                seen_ids = await asyncio.to_thread(
                    storage.get_seen_ids, "default", "NASA"
                )
            finally:
                storage.close()

            self.assertEqual(len(seen_ids), 300)
            self.assertEqual(seen_ids[0], "newest")
            self.assertNotIn("299", seen_ids)

    async def test_scan_watermark_crud_and_seen_clear_share_group_scope(self):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "nitter_tweets.db"

            with patch.object(
                StorageAdapter,
                "_init_sqlite",
                return_value=SQLiteStorage(db_path),
            ):
                adapter = StorageAdapter(_Owner(), {"storage_backend": "sqlite"}, None)

            try:
                await adapter.set_scan_watermark(
                    "default", "NASA", [str(status_id) for status_id in range(200, 179, -1)]
                )
                await adapter.set_scan_watermark("default", "OpenAI", None)
                await adapter.set_scan_watermark("tech", "NASA", ["300"])
                await adapter.add_seen_ids("default", "NASA", ["200"])

                watermarks = await adapter.get_group_scan_watermarks("default")
                deleted = await adapter.clear_seen_records("default")
                cleared_watermarks = await adapter.get_group_scan_watermarks("default")
                tech_watermarks = await adapter.get_group_scan_watermarks("tech")
            finally:
                adapter.close()

            self.assertEqual(
                watermarks,
                {
                    "NASA": [
                        str(status_id) for status_id in range(200, 180, -1)
                    ],
                    "OpenAI": [],
                },
            )
            self.assertEqual(deleted, 1)
            self.assertEqual(cleared_watermarks, {})
            self.assertEqual(tech_watermarks, {"NASA": ["300"]})

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
                watermarks = await adapter.get_group_scan_watermarks("default")
            finally:
                adapter.close()

            self.assertEqual(seen_ids, ["100", "99"])
            self.assertEqual(watermarks, {"NASA": ["100", "99"]})
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
                await asyncio.to_thread(
                    sqlite.set_scan_watermark, "global", "NASA", "100"
                )
                await asyncio.to_thread(
                    sqlite.set_scan_watermark, "default", "NASA", "200"
                )

                summary = await adapter.delete_orphan_group_runtime_data("global")
                global_seen = await asyncio.to_thread(sqlite.get_seen_ids, "global", "NASA")
                default_seen = await asyncio.to_thread(sqlite.get_seen_ids, "default", "NASA")
                global_watermarks = await asyncio.to_thread(
                    sqlite.get_group_scan_watermarks, "global"
                )
                default_watermarks = await asyncio.to_thread(
                    sqlite.get_group_scan_watermarks, "default"
                )
            finally:
                adapter.close()

            self.assertEqual(summary["seen_deleted"], 1)
            self.assertEqual(summary["scan_watermarks_deleted"], 1)
            self.assertEqual(global_seen, [])
            self.assertEqual(default_seen, ["200"])
            self.assertEqual(global_watermarks, {})
            self.assertEqual(default_watermarks, {"NASA": ["200"]})

    async def test_global_scan_watermarks_merge_into_default(self):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "nitter_tweets.db"

            with patch.object(
                StorageAdapter,
                "_init_sqlite",
                return_value=SQLiteStorage(db_path),
            ):
                adapter = StorageAdapter(_Owner(), {"storage_backend": "sqlite"}, None)

            group = types.SimpleNamespace(
                group_id="default",
                name="默认分组",
                enabled=True,
                check_on_startup=False,
                interval_check_enabled=True,
                check_interval_minutes=30,
                daily_check_enabled=False,
                daily_check_times=[],
                scheduled_fetch_limit=20,
                send_target_interval=1.5,
                send_user_interval=2.0,
                notify_no_updates=False,
                aliases=["global"],
                users=["NASA", "ESA"],
                targets=[],
            )
            try:
                sqlite = await adapter._ensure_sqlite_connected()
                await asyncio.to_thread(
                    sqlite.set_scan_watermark, "global", "NASA", "300"
                )
                await asyncio.to_thread(
                    sqlite.set_scan_watermark, "default", "NASA", "200"
                )
                await asyncio.to_thread(
                    sqlite.set_scan_watermark, "global", "ESA", "150"
                )

                await adapter.migrate_and_sync([group])
                default_watermarks = await adapter.get_group_scan_watermarks("default")
                raw_global_watermarks = await asyncio.to_thread(
                    sqlite.get_group_scan_watermarks, "global"
                )
            finally:
                adapter.close()

            self.assertEqual(
                default_watermarks,
                {"ESA": ["150"], "NASA": ["300", "200"]},
            )
            self.assertEqual(raw_global_watermarks, {})

    async def test_group_snapshot_refreshes_when_runtime_settings_change(self):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "nitter_tweets.db"

            with patch.object(
                StorageAdapter,
                "_init_sqlite",
                return_value=SQLiteStorage(db_path),
            ):
                adapter = StorageAdapter(_Owner(), {"storage_backend": "sqlite"}, None)

            group = types.SimpleNamespace(
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
                aliases=["global"],
                users=["NASA"],
                targets=["telegram:FriendMessage:1"],
            )
            try:
                await adapter.migrate_and_sync([group])
                group.scheduled_fetch_limit = 12
                group.check_interval_minutes = 15
                group.notify_no_updates = True
                await adapter.migrate_and_sync([group])

                sqlite = await adapter._ensure_sqlite_connected()
                snapshots = await asyncio.to_thread(sqlite.get_all_groups)
            finally:
                adapter.close()

            self.assertEqual(len(snapshots), 1)
            self.assertEqual(snapshots[0]["scheduled_fetch_limit"], 12)
            self.assertEqual(snapshots[0]["check_interval_minutes"], 15)
            self.assertTrue(snapshots[0]["notify_no_updates"])

    async def test_orphan_cleanup_removes_stale_scan_watermark_only(self):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "nitter_tweets.db"
            storage = SQLiteStorage(db_path)
            try:
                await storage.connect()
                await asyncio.to_thread(storage.set_group_users, "default", ["NASA"])
                await asyncio.to_thread(
                    storage.set_scan_watermark, "default", "NASA", "200"
                )
                await asyncio.to_thread(
                    storage.set_scan_watermark, "default", "Removed", "100"
                )
                storage.conn.execute(
                    "UPDATE scan_watermarks SET updated_at = 1"
                )
                storage.conn.commit()

                await asyncio.to_thread(storage.cleanup_orphan_seen_tweets)
                watermarks = await asyncio.to_thread(
                    storage.get_group_scan_watermarks, "default"
                )
            finally:
                storage.close()

            self.assertEqual(watermarks, {"NASA": ["200"]})


if __name__ == "__main__":
    unittest.main()
