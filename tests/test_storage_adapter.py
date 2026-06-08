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


from sqlite_storage import SQLiteStorage
from storage_adapter import StorageAdapter


class _Owner:
    def __init__(self):
        self.data = {}
        self.put_calls = 0

    async def get_kv_data(self, key, default):
        return self.data.get(key, default)

    async def put_kv_data(self, key, value):
        self.put_calls += 1
        self.data[key] = value


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


if __name__ == "__main__":
    unittest.main()
