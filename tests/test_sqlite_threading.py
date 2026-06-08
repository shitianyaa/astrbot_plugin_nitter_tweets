from __future__ import annotations

import asyncio
import sys
import types
import unittest
from pathlib import Path


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


class SQLiteThreadingTest(unittest.IsolatedAsyncioTestCase):
    async def test_storage_connection_can_be_used_from_to_thread_calls(self):
        db_path = Path(__file__).resolve().parent / "sqlite_threading_test.db"
        db_path.unlink(missing_ok=True)
        storage = SQLiteStorage(db_path)
        try:
            await storage.connect()
            await asyncio.to_thread(
                storage.add_seen_ids,
                "global",
                "NASA",
                ["100", "99", "98"],
            )
            seen_ids = await asyncio.to_thread(
                storage.get_seen_ids,
                "global",
                "NASA",
            )
            storage.close()
        finally:
            storage.close()
            db_path.unlink(missing_ok=True)
            db_path.with_suffix(".db-wal").unlink(missing_ok=True)
            db_path.with_suffix(".db-shm").unlink(missing_ok=True)

        self.assertEqual(seen_ids, ["100", "99", "98"])


if __name__ == "__main__":
    unittest.main()
