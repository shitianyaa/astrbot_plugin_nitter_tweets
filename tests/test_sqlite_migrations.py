from __future__ import annotations

import sqlite3
import sys
import types
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


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


class SQLiteMigrationTest(unittest.IsolatedAsyncioTestCase):
    async def test_v7_migration_removes_legacy_pending_tables(self):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "nitter_tweets.db"
            connection = sqlite3.connect(db_path)
            connection.executescript(
                """
                CREATE TABLE meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at INTEGER NOT NULL
                );
                INSERT INTO meta(key, value, updated_at)
                VALUES ('schema_version', '6', 1);
                CREATE TABLE pending_tweets (
                    id INTEGER PRIMARY KEY,
                    group_id TEXT NOT NULL,
                    status_id TEXT NOT NULL,
                    sent_at INTEGER
                );
                CREATE TABLE pending_media (
                    id INTEGER PRIMARY KEY,
                    pending_tweet_id INTEGER NOT NULL,
                    path TEXT NOT NULL
                );
                INSERT INTO pending_tweets(id, group_id, status_id, sent_at)
                VALUES (7, 'default', 'status-7', NULL);
                INSERT INTO pending_media(id, pending_tweet_id, path)
                VALUES (8, 7, 'cache/staged/default/7/image.jpg');
                """
            )
            connection.commit()
            connection.close()

            storage = SQLiteStorage(db_path)
            try:
                await storage.connect()
                pending_table = storage.conn.execute(
                    "SELECT 1 FROM sqlite_master "
                    "WHERE type = 'table' AND name = 'pending_tweets'"
                ).fetchone()
                media_table = storage.conn.execute(
                    "SELECT 1 FROM sqlite_master "
                    "WHERE type = 'table' AND name = 'pending_media'"
                ).fetchone()
                version = storage.get_meta("schema_version")
            finally:
                storage.close()

            self.assertIsNone(pending_table)
            self.assertIsNone(media_table)
            self.assertEqual(version, "7")


if __name__ == "__main__":
    unittest.main()
