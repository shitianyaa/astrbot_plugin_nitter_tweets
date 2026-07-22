from __future__ import annotations

import asyncio
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
                CREATE TABLE seen_tweets (
                    group_id TEXT NOT NULL,
                    username TEXT NOT NULL,
                    status_id TEXT NOT NULL,
                    seen_at INTEGER NOT NULL,
                    PRIMARY KEY (group_id, username, status_id)
                );
                INSERT INTO seen_tweets(group_id, username, status_id, seen_at)
                VALUES
                    ('default', 'NASA', '99', 10),
                    ('default', 'NASA', '200', 11),
                    ('default', 'NASA', 'not-a-status', 12),
                    ('default', 'OpenAI', 'legacy-id', 13);
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
                watermark_rows = await asyncio.to_thread(
                    storage.get_group_scan_watermarks, "default"
                )
                watermark_table = storage.conn.execute(
                    "SELECT 1 FROM sqlite_master "
                    "WHERE type = 'table' AND name = 'scan_watermarks'"
                ).fetchone()
                version = storage.get_meta("schema_version")
            finally:
                storage.close()

            self.assertIsNone(pending_table)
            self.assertIsNone(media_table)
            self.assertEqual(
                watermark_rows,
                {"NASA": ["200", "99"], "OpenAI": []},
            )
            self.assertIsNotNone(watermark_table)
            self.assertEqual(version, "9")

    async def test_v9_migration_converts_single_status_id_to_anchor_group(self):
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
                VALUES ('schema_version', '8', 1);
                CREATE TABLE scan_watermarks (
                    group_id TEXT NOT NULL,
                    username TEXT NOT NULL,
                    initialized INTEGER NOT NULL DEFAULT 0,
                    status_id TEXT,
                    updated_at INTEGER NOT NULL,
                    PRIMARY KEY (group_id, username)
                );
                INSERT INTO scan_watermarks(
                    group_id, username, initialized, status_id, updated_at
                ) VALUES
                    ('default', 'NASA', 1, '100', 10),
                    ('default', 'OpenAI', 1, '', 11);
                """
            )
            connection.commit()
            connection.close()

            storage = SQLiteStorage(db_path)
            try:
                await storage.connect()
                columns = {
                    str(row[1])
                    for row in storage.conn.execute(
                        "PRAGMA table_info(scan_watermarks)"
                    ).fetchall()
                }
                watermarks = await asyncio.to_thread(
                    storage.get_group_scan_watermarks, "default"
                )
                version = storage.get_meta("schema_version")
            finally:
                storage.close()

            self.assertIn("status_ids", columns)
            self.assertNotIn("status_id", columns)
            self.assertEqual(
                watermarks,
                {"NASA": ["100"], "OpenAI": []},
            )
            self.assertEqual(version, "9")


if __name__ == "__main__":
    unittest.main()
