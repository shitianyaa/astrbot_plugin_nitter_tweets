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
from storage.seen import SeenStore
from shared.utils import TweetItem


class SQLiteMigrationTest(unittest.IsolatedAsyncioTestCase):
    async def test_legacy_tag_seen_key_survives_kv_normalization(self):
        class Owner:
            async def get_kv_data(self, key, default):
                if key == "nitter_seen_status_ids":
                    return {"groups": {"tags": {"q:#Foo": ["101"]}}}
                return default

        grouped = await SeenStore(Owner()).get_grouped_seen_map()

        self.assertEqual(grouped.groups, {"tags": {"q:#foo": ["101"]}})

    async def test_global_group_migration_keeps_push_history_visible(self):
        with TemporaryDirectory() as temp_dir:
            storage = SQLiteStorage(Path(temp_dir) / "nitter_tweets.db")
            await storage.connect()
            try:
                tweet = TweetItem(
                    text="hello",
                    link="https://x.com/nasa/status/101",
                    published="",
                )
                await asyncio.to_thread(
                    storage.record_push_history,
                    "global",
                    "nasa",
                    tweet,
                    "telegram:FriendMessage:1",
                    "scheduled",
                    "https://nitter.example",
                )
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
                    send_target_interval=0.0,
                    send_user_interval=0.0,
                    notify_no_updates=False,
                    aliases=[],
                    account_keys=["nasa"],
                    users=["nasa"],
                    targets=["telegram:FriendMessage:1"],
                )

                await asyncio.to_thread(storage.sync_config_groups, [group])
                default_history = await asyncio.to_thread(
                    storage.get_push_history, "default", "", 10, 0
                )
                legacy_count = await asyncio.to_thread(
                    storage.count_push_history, "global"
                )
            finally:
                storage.close()

            self.assertEqual([item.status_id for item in default_history], ["101"])
            self.assertEqual(legacy_count, 0)

    async def test_v7_migration_preserves_legacy_pending_tables(self):
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

            self.assertIsNotNone(pending_table)
            self.assertIsNotNone(media_table)
            self.assertEqual(
                watermark_rows,
                {"NASA": ["200", "99"], "OpenAI": []},
            )
            self.assertIsNotNone(watermark_table)
            self.assertEqual(version, "9")

    async def test_tag_seen_key_is_active_subscription_for_orphan_cleanup(self):
        with TemporaryDirectory() as temp_dir:
            storage = SQLiteStorage(Path(temp_dir) / "nitter_tweets.db")
            await storage.connect()
            try:
                storage.conn.execute(
                    """
                    INSERT INTO seen_tweets(group_id, username, status_id, seen_at)
                    VALUES ('tags', 'q:#foo', '101', 1)
                    """
                )
                storage.conn.commit()
                group = types.SimpleNamespace(
                    group_id="tags",
                    name="标签",
                    enabled=True,
                    check_on_startup=False,
                    interval_check_enabled=True,
                    check_interval_minutes=30,
                    daily_check_enabled=False,
                    daily_check_times=[],
                    scheduled_fetch_limit=20,
                    send_target_interval=0.0,
                    send_user_interval=0.0,
                    notify_no_updates=False,
                    aliases=[],
                    account_keys=["q:#foo"],
                    users=[],
                    targets=[],
                )
                await asyncio.to_thread(storage.sync_config_groups, [group])
                active = await asyncio.to_thread(storage.get_group_users, "tags")
                seen = await asyncio.to_thread(storage.get_seen_ids, "tags", "q:#foo")
            finally:
                storage.close()

            self.assertEqual(active, ["q:#foo"])
            self.assertEqual(seen, ["101"])

    async def test_failed_schema_initialization_can_retry_with_fresh_connection(self):
        with TemporaryDirectory() as temp_dir:
            storage = SQLiteStorage(Path(temp_dir) / "nitter_tweets.db")
            original_init = storage._init_schema
            attempts = 0

            def fail_once():
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    raise RuntimeError("simulated schema failure")
                return original_init()

            storage._init_schema = fail_once
            with self.assertRaisesRegex(RuntimeError, "simulated schema failure"):
                await storage.connect()
            self.assertIsNone(storage.conn)

            await storage.connect()
            try:
                self.assertIsNotNone(storage.conn)
                self.assertEqual(storage.get_meta("schema_version"), "9")
            finally:
                storage.close()

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
