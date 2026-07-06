from __future__ import annotations

import asyncio
import sqlite3
import sys
import time
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


from sqlite_storage import SQLiteStorage
from utils import TweetItem, TweetMedia


class PendingStorageTest(unittest.IsolatedAsyncioTestCase):
    async def test_push_history_records_and_filters_sent_tweets(self):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "nitter_tweets.db"
            storage = SQLiteStorage(db_path)
            await storage.connect()
            try:
                nasa = TweetItem(
                    text="moon",
                    link="https://x.com/NASA/status/100",
                    published="2026-07-05",
                    translation="月球",
                    ai_comment="值得看",
                    media=[
                        TweetMedia(
                            "image",
                            "https://media.example.test/moon.jpg",
                            Path("C:/tmp/moon.jpg"),
                        )
                    ],
                )
                openai = TweetItem(
                    text="model",
                    link="https://x.com/OpenAI/status/200",
                    published="2026-07-05",
                )

                first_id = await asyncio.to_thread(
                    storage.record_push_history,
                    "default",
                    "NASA",
                    nasa,
                    "telegram:FriendMessage:1",
                    "scheduled",
                    "https://nitter.test",
                    1000,
                )
                await asyncio.to_thread(
                    storage.record_push_history,
                    "tech",
                    "OpenAI",
                    openai,
                    "telegram:FriendMessage:2",
                    "replay",
                    "https://nitter.test",
                    1001,
                )

                all_records = await asyncio.to_thread(storage.get_push_history, limit=10)
                nasa_records = await asyncio.to_thread(
                    storage.get_push_history,
                    group_id="default",
                    username="NASA",
                    limit=10,
                )
                first_record = await asyncio.to_thread(
                    storage.get_push_history_record, first_id
                )
            finally:
                storage.close()

            self.assertEqual([record.username for record in all_records], ["OpenAI", "NASA"])
            self.assertEqual([record.status_id for record in nasa_records], ["100"])
            self.assertIsNotNone(first_record)
            self.assertEqual(first_record.tweet.translation, "月球")
            self.assertEqual(first_record.tweet.ai_comment, "值得看")
            self.assertEqual(len(first_record.tweet.media), 1)
            self.assertEqual(
                first_record.tweet.media[0].url,
                "https://media.example.test/moon.jpg",
            )
            self.assertIsNone(first_record.tweet.media[0].path)
            self.assertNotIn("C:/tmp/moon.jpg", repr(first_record.tweet))
            self.assertEqual(first_record.target_umo, "telegram:FriendMessage:1")
            self.assertEqual(first_record.source, "scheduled")

    async def test_push_history_persists_after_reopening_database(self):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "nitter_tweets.db"
            storage = SQLiteStorage(db_path)
            await storage.connect()
            try:
                await asyncio.to_thread(
                    storage.record_push_history,
                    "default",
                    "NASA",
                    TweetItem(
                        text="moon",
                        link="https://x.com/NASA/status/101",
                        published="",
                    ),
                    "telegram:FriendMessage:1",
                    "scheduled",
                    "https://nitter.test",
                )
            finally:
                storage.close()

            reopened = SQLiteStorage(db_path)
            await reopened.connect()
            try:
                records = await asyncio.to_thread(reopened.get_push_history, limit=10)
            finally:
                reopened.close()

            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].status_id, "101")

    async def test_push_history_supports_partial_username_and_offset(self):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "nitter_tweets.db"
            storage = SQLiteStorage(db_path)
            await storage.connect()
            try:
                for index, username in enumerate(
                    ["Gongye_11", "OpenAI", "oioioi525", "mamania1008"], start=1
                ):
                    await asyncio.to_thread(
                        storage.record_push_history,
                        "default",
                        username,
                        TweetItem(
                            text=f"tweet {index}",
                            link=f"https://x.com/{username}/status/{index}",
                            published="",
                        ),
                        "telegram:FriendMessage:1",
                        "scheduled",
                        "https://nitter.test",
                        1000 + index,
                    )

                gong_records = await asyncio.to_thread(
                    storage.get_push_history,
                    username="gong",
                    limit=10,
                )
                oi_records = await asyncio.to_thread(
                    storage.get_push_history,
                    username="@oi",
                    limit=10,
                )
                page_records = await asyncio.to_thread(
                    storage.get_push_history,
                    limit=2,
                    offset=2,
                )
            finally:
                storage.close()

            self.assertEqual([record.username for record in gong_records], ["Gongye_11"])
            self.assertEqual([record.username for record in oi_records], ["oioioi525"])
            self.assertEqual(
                [record.username for record in page_records],
                ["OpenAI", "Gongye_11"],
            )

    async def test_push_history_allows_one_extra_row_for_pagination_sentinel(self):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "nitter_tweets.db"
            storage = SQLiteStorage(db_path)
            await storage.connect()
            try:
                for index in range(51):
                    await asyncio.to_thread(
                        storage.record_push_history,
                        "default",
                        "NASA",
                        TweetItem(
                            text=f"tweet {index}",
                            link=f"https://x.com/NASA/status/{index}",
                            published="",
                        ),
                        "telegram:FriendMessage:1",
                        "scheduled",
                        "https://nitter.test",
                        1000 + index,
                    )

                records = await asyncio.to_thread(storage.get_push_history, limit=51)
            finally:
                storage.close()

            self.assertEqual(len(records), 51)

    async def test_push_history_treats_username_wildcards_as_literals(self):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "nitter_tweets.db"
            storage = SQLiteStorage(db_path)
            await storage.connect()
            try:
                for index, username in enumerate(["Gongye_11", "GongyeA11"], start=1):
                    await asyncio.to_thread(
                        storage.record_push_history,
                        "default",
                        username,
                        TweetItem(
                            text=f"tweet {index}",
                            link=f"https://x.com/{username}/status/{index}",
                            published="",
                        ),
                        "telegram:FriendMessage:1",
                        "scheduled",
                        "https://nitter.test",
                        1000 + index,
                    )

                underscore_records = await asyncio.to_thread(
                    storage.get_push_history,
                    username="Gongye_1",
                    limit=10,
                )
                percent_records = await asyncio.to_thread(
                    storage.get_push_history,
                    username="%",
                    limit=10,
                )
            finally:
                storage.close()

            self.assertEqual(
                [record.username for record in underscore_records],
                ["Gongye_11"],
            )
            self.assertEqual(percent_records, [])

    async def test_count_push_history_counts_grouped_display_records(self):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "nitter_tweets.db"
            storage = SQLiteStorage(db_path)
            await storage.connect()
            try:
                for index, target in enumerate(
                    ["telegram:FriendMessage:1", "lark:GroupMessage:2"], start=1
                ):
                    await asyncio.to_thread(
                        storage.record_push_history,
                        "coser",
                        "xixikawaii",
                        TweetItem(
                            text="same tweet",
                            link="https://x.com/xixikawaii/status/207",
                            published="",
                        ),
                        target,
                        "scheduled",
                        "https://nitter.test",
                        2000 + index,
                    )
                await asyncio.to_thread(
                    storage.record_push_history,
                    "coser",
                    "Gongye_11",
                    TweetItem(
                        text="underscore",
                        link="https://x.com/Gongye_11/status/208",
                        published="",
                    ),
                    "telegram:FriendMessage:1",
                    "scheduled",
                    "https://nitter.test",
                    2003,
                )
                await asyncio.to_thread(
                    storage.record_push_history,
                    "tech",
                    "GongyeA11",
                    TweetItem(
                        text="other group",
                        link="https://x.com/GongyeA11/status/209",
                        published="",
                    ),
                    "telegram:FriendMessage:1",
                    "scheduled",
                    "https://nitter.test",
                    2004,
                )

                all_count = await asyncio.to_thread(storage.count_push_history)
                coser_count = await asyncio.to_thread(
                    storage.count_push_history,
                    group_id="coser",
                )
                partial_count = await asyncio.to_thread(
                    storage.count_push_history,
                    username="xixi",
                )
                literal_underscore_count = await asyncio.to_thread(
                    storage.count_push_history,
                    username="Gongye_1",
                )
                literal_percent_count = await asyncio.to_thread(
                    storage.count_push_history,
                    username="%",
                )
            finally:
                storage.close()

            self.assertEqual(all_count, 3)
            self.assertEqual(coser_count, 2)
            self.assertEqual(partial_count, 1)
            self.assertEqual(literal_underscore_count, 1)
            self.assertEqual(literal_percent_count, 0)

    async def test_delete_group_runtime_data_removes_only_target_group_rows(self):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "nitter_tweets.db"
            storage = SQLiteStorage(db_path)
            await storage.connect()
            try:
                now = int(time.time())
                await asyncio.to_thread(
                    storage.upsert_group,
                    "default",
                    "默认分组",
                    True,
                    False,
                    True,
                    30,
                    False,
                    [],
                    5,
                    1.5,
                    2.0,
                    False,
                    ["default"],
                )
                await asyncio.to_thread(
                    storage.upsert_group,
                    "tech",
                    "科技",
                    True,
                    False,
                    True,
                    30,
                    False,
                    [],
                    5,
                    1.5,
                    2.0,
                    False,
                    ["tech"],
                )
                await asyncio.to_thread(
                    storage.set_group_users, "default", ["NASA"]
                )
                await asyncio.to_thread(
                    storage.set_group_users, "tech", ["OpenAI"]
                )
                await asyncio.to_thread(
                    storage.set_group_targets,
                    "default",
                    ["telegram:FriendMessage:1"],
                )
                await asyncio.to_thread(
                    storage.set_group_targets,
                    "tech",
                    ["telegram:FriendMessage:2"],
                )
                await asyncio.to_thread(
                    storage.add_seen_ids, "default", "NASA", ["100"]
                )
                await asyncio.to_thread(
                    storage.add_seen_ids, "tech", "OpenAI", ["200"]
                )

                tech_tweet = TweetItem(
                    text="queued",
                    link="https://x.com/OpenAI/status/200",
                    published="2026-07-05",
                )
                default_tweet = TweetItem(
                    text="queued",
                    link="https://x.com/NASA/status/100",
                    published="2026-07-05",
                )
                await asyncio.to_thread(
                    storage.enqueue_pending_tweets,
                    "tech",
                    "OpenAI",
                    "https://nitter.test",
                    [tech_tweet],
                    now,
                )
                await asyncio.to_thread(
                    storage.enqueue_pending_tweets,
                    "default",
                    "NASA",
                    "https://nitter.test",
                    [default_tweet],
                    now,
                )

                summary = await asyncio.to_thread(
                    storage.delete_group_runtime_data, "tech"
                )

                self.assertEqual(summary["groups_deleted"], 1)
                self.assertEqual(summary["users_deleted"], 1)
                self.assertEqual(summary["targets_deleted"], 1)
                self.assertEqual(summary["seen_deleted"], 1)
                self.assertEqual(summary["pending_deleted"], 1)
                self.assertEqual(summary["pending_media_deleted"], 0)
                self.assertEqual(
                    await asyncio.to_thread(storage.get_group_users, "default"),
                    ["NASA"],
                )
                self.assertEqual(
                    await asyncio.to_thread(storage.get_group_users, "tech"),
                    [],
                )
                self.assertEqual(
                    await asyncio.to_thread(storage.get_group_targets, "default"),
                    ["telegram:FriendMessage:1"],
                )
                self.assertEqual(
                    await asyncio.to_thread(storage.get_group_targets, "tech"),
                    [],
                )
                self.assertEqual(
                    await asyncio.to_thread(storage.get_seen_ids, "default", "NASA"),
                    ["100"],
                )
                self.assertEqual(
                    await asyncio.to_thread(storage.get_seen_ids, "tech", "OpenAI"),
                    [],
                )
                remaining_default = storage.conn.execute(
                    "SELECT COUNT(*) FROM pending_tweets WHERE group_id = 'default'"
                ).fetchone()[0]
                remaining_tech = storage.conn.execute(
                    "SELECT COUNT(*) FROM pending_tweets WHERE group_id = 'tech'"
                ).fetchone()[0]
                self.assertEqual(remaining_default, 1)
                self.assertEqual(remaining_tech, 0)
            finally:
                storage.close()

    async def test_pending_queue_round_trips_tweet_and_media(self):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "nitter_tweets.db"
            media_path = Path(temp_dir) / "image.jpg"
            media_path.write_bytes(b"image")
            storage = SQLiteStorage(db_path)
            await storage.connect()
            try:
                tweet = TweetItem(
                    text="hello",
                    link="https://x.com/NASA/status/100",
                    published="2026-06-08",
                    media=[TweetMedia("image", "https://example.test/image.jpg", media_path)],
                    media_warnings=["warn"],
                    ai_warnings=["AI warn"],
                    translation="你好",
                    image_caption="一张图",
                    ai_comment="评论",
                )

                inserted = await asyncio.to_thread(
                    storage.enqueue_pending_tweets,
                    "global",
                    "NASA",
                    "https://nitter.test",
                    [tweet],
                )
                duplicate = await asyncio.to_thread(
                    storage.enqueue_pending_tweets,
                    "global",
                    "NASA",
                    "https://nitter.test",
                    [tweet],
                )
                records = await asyncio.to_thread(
                    storage.get_pending_tweets, "global", 10
                )
                summary = await asyncio.to_thread(
                    storage.get_pending_queue_summary, "global"
                )
            finally:
                storage.close()

            self.assertEqual(inserted, 1)
            self.assertEqual(duplicate, 0)
            self.assertEqual(summary.pending_count, 1)
            self.assertEqual(summary.media_count, 1)
            self.assertEqual(len(records), 1)
            record = records[0]
            self.assertEqual(record.username, "NASA")
            self.assertEqual(record.status_id, "100")
            self.assertEqual(record.instance, "https://nitter.test")
            self.assertEqual(record.tweet.text, "hello")
            self.assertEqual(record.tweet.translation, "你好")
            self.assertEqual(record.tweet.media_warnings, ["warn"])
            self.assertEqual(record.tweet.ai_warnings, ["AI warn"])
            self.assertEqual(record.tweet.media[0].path, media_path)

    async def test_pending_queue_marks_failure_and_publish(self):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "nitter_tweets.db"
            storage = SQLiteStorage(db_path)
            await storage.connect()
            try:
                tweet = TweetItem(
                    text="hello",
                    link="https://x.com/NASA/status/101",
                    published="",
                )
                await asyncio.to_thread(
                    storage.enqueue_pending_tweets,
                    "global",
                    "NASA",
                    "",
                    [tweet],
                )
                records = await asyncio.to_thread(
                    storage.get_pending_tweets, "global", 10
                )
                pending_id = records[0].id
                await asyncio.to_thread(
                    storage.mark_pending_tweets_failed, [pending_id], "send failed"
                )
                failed_summary = await asyncio.to_thread(
                    storage.get_pending_queue_summary, "global"
                )
                await asyncio.to_thread(
                    storage.mark_pending_tweets_published, [pending_id]
                )
                sent_summary = await asyncio.to_thread(
                    storage.get_pending_queue_summary, "global"
                )
            finally:
                storage.close()

            self.assertEqual(failed_summary.pending_count, 1)
            self.assertEqual(failed_summary.failed_count, 1)
            self.assertEqual(sent_summary.pending_count, 0)

    async def test_pending_queue_records_delivered_targets_until_publish(self):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "nitter_tweets.db"
            storage = SQLiteStorage(db_path)
            await storage.connect()
            try:
                tweet = TweetItem(
                    text="hello",
                    link="https://x.com/NASA/status/111",
                    published="",
                )
                await asyncio.to_thread(
                    storage.enqueue_pending_tweets,
                    "global",
                    "NASA",
                    "",
                    [tweet],
                )
                records = await asyncio.to_thread(
                    storage.get_pending_tweets, "global", 10
                )
                pending_id = records[0].id
                await asyncio.to_thread(
                    storage.mark_pending_tweets_delivered,
                    [pending_id],
                    "telegram:FriendMessage:1",
                )
                delivered_records = await asyncio.to_thread(
                    storage.get_pending_tweets, "global", 10
                )
                await asyncio.to_thread(
                    storage.mark_pending_tweets_published, [pending_id]
                )
                sent_summary = await asyncio.to_thread(
                    storage.get_pending_queue_summary, "global"
                )
            finally:
                storage.close()

            self.assertEqual(
                delivered_records[0].delivered_targets,
                ("telegram:FriendMessage:1",),
            )
            self.assertEqual(sent_summary.pending_count, 0)

    async def test_pending_queue_summary_groups_unsent_tweets_by_username(self):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "nitter_tweets.db"
            storage = SQLiteStorage(db_path)
            await storage.connect()
            try:
                tweets = [
                    TweetItem(
                        text="hello",
                        link="https://x.com/NASA/status/201",
                        published="",
                    ),
                    TweetItem(
                        text="hello",
                        link="https://x.com/NASA/status/202",
                        published="",
                    ),
                ]
                openai_tweet = TweetItem(
                    text="hello",
                    link="https://x.com/OpenAI/status/301",
                    published="",
                )
                await asyncio.to_thread(
                    storage.enqueue_pending_tweets,
                    "global",
                    "NASA",
                    "https://nitter.test",
                    tweets,
                )
                await asyncio.to_thread(
                    storage.enqueue_pending_tweets,
                    "global",
                    "OpenAI",
                    "https://nitter.test",
                    [openai_tweet],
                )
                records = await asyncio.to_thread(
                    storage.get_pending_tweets, "global", 10
                )
                await asyncio.to_thread(
                    storage.mark_pending_tweets_failed,
                    [records[0].id],
                    "send failed",
                )
                summary = await asyncio.to_thread(
                    storage.get_pending_queue_summary, "global"
                )
            finally:
                storage.close()

            self.assertEqual(summary.pending_count, 3)
            self.assertEqual(summary.failed_count, 1)
            self.assertEqual(summary.user_counts, [("NASA", 2), ("OpenAI", 1)])

    async def test_cleanup_sent_pending_tweets_removes_current_sent_rows(self):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "nitter_tweets.db"
            media_path = Path(temp_dir) / "image.jpg"
            media_path.write_bytes(b"image")
            storage = SQLiteStorage(db_path)
            await storage.connect()
            try:
                tweet = TweetItem(
                    text="hello",
                    link="https://x.com/NASA/status/102",
                    published="",
                    media=[TweetMedia("image", "https://example.test/image.jpg", media_path)],
                )
                await asyncio.to_thread(
                    storage.enqueue_pending_tweets,
                    "global",
                    "NASA",
                    "",
                    [tweet],
                )
                records = await asyncio.to_thread(
                    storage.get_pending_tweets, "global", 10
                )
                pending_id = records[0].id
                await asyncio.to_thread(
                    storage.mark_pending_tweets_published, [pending_id]
                )
                cleaned = await asyncio.to_thread(
                    storage.cleanup_sent_pending_tweets, int(time.time())
                )
                inserted_again = await asyncio.to_thread(
                    storage.enqueue_pending_tweets,
                    "global",
                    "NASA",
                    "",
                    [tweet],
                )
                summary = await asyncio.to_thread(
                    storage.get_pending_queue_summary, "global"
                )
            finally:
                storage.close()

            self.assertEqual(cleaned, 1)
            self.assertEqual(inserted_again, 1)
            self.assertEqual(summary.pending_count, 1)
            self.assertEqual(summary.media_count, 1)

    async def test_schema_v1_pending_table_migrates_to_current_version(self):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "nitter_tweets.db"
            conn = sqlite3.connect(db_path)
            try:
                conn.execute(
                    """
                    CREATE TABLE meta (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL,
                        updated_at INTEGER NOT NULL
                    )
                    """
                )
                conn.execute(
                    "INSERT INTO meta (key, value, updated_at) VALUES ('schema_version', '1', 0)"
                )
                conn.execute(
                    """
                    CREATE TABLE pending_tweets (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        group_id TEXT NOT NULL,
                        username TEXT NOT NULL,
                        status_id TEXT NOT NULL,
                        tweet_data TEXT NOT NULL,
                        created_at INTEGER NOT NULL,
                        scheduled_at INTEGER,
                        sent_at INTEGER
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO pending_tweets (
                        group_id, username, status_id, tweet_data, created_at
                    ) VALUES ('global', 'NASA', '100', '{}', 1)
                    """
                )
                conn.execute(
                    """
                    INSERT INTO pending_tweets (
                        group_id, username, status_id, tweet_data, created_at
                    ) VALUES ('global', 'NASA', '100', '{}', 2)
                    """
                )
                conn.commit()
            finally:
                conn.close()

            storage = SQLiteStorage(db_path)
            await storage.connect()
            try:
                records = await asyncio.to_thread(
                    storage.get_pending_tweets, "global", 10
                )
                version = await asyncio.to_thread(storage.get_meta, "schema_version")
            finally:
                storage.close()

            self.assertEqual(version, "5")
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].instance, "")
            self.assertEqual(records[0].delivered_targets, ())

    async def test_schema_v4_database_migrates_push_history_table(self):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "nitter_tweets.db"
            conn = sqlite3.connect(db_path)
            try:
                conn.execute(
                    """
                    CREATE TABLE meta (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL,
                        updated_at INTEGER NOT NULL
                    )
                    """
                )
                conn.execute(
                    "INSERT INTO meta (key, value, updated_at) VALUES ('schema_version', '4', 0)"
                )
                conn.commit()
            finally:
                conn.close()

            storage = SQLiteStorage(db_path)
            await storage.connect()
            try:
                exists = storage.conn.execute(
                    """
                    SELECT 1 FROM sqlite_master
                    WHERE type = 'table' AND name = 'push_history'
                    """
                ).fetchone()
                version = await asyncio.to_thread(storage.get_meta, "schema_version")
            finally:
                storage.close()

            self.assertIsNotNone(exists)
            self.assertEqual(version, "5")

    async def test_schema_v2_global_group_rows_merge_to_default(self):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "nitter_tweets.db"
            storage = SQLiteStorage(db_path)
            await storage.connect()
            storage.close()

            conn = sqlite3.connect(db_path)
            try:
                now = int(time.time())
                conn.execute(
                    "UPDATE meta SET value = '2', updated_at = ? WHERE key = 'schema_version'",
                    (now,),
                )
                group_row = (
                    1,
                    0,
                    1,
                    30,
                    0,
                    "[]",
                    5,
                    1.5,
                    2.0,
                    0,
                    "[]",
                    now,
                    now,
                )
                conn.execute(
                    """
                    INSERT INTO groups (
                        group_id, name, enabled, check_on_startup,
                        interval_check_enabled, check_interval_minutes,
                        daily_check_enabled, daily_check_times,
                        scheduled_fetch_limit, send_target_interval,
                        send_user_interval, notify_no_updates, aliases,
                        created_at, updated_at
                    ) VALUES ('default', '默认分组', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    group_row,
                )
                conn.execute(
                    """
                    INSERT INTO groups (
                        group_id, name, enabled, check_on_startup,
                        interval_check_enabled, check_interval_minutes,
                        daily_check_enabled, daily_check_times,
                        scheduled_fetch_limit, send_target_interval,
                        send_user_interval, notify_no_updates, aliases,
                        created_at, updated_at
                    ) VALUES ('global', '全局分组', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    group_row,
                )
                conn.execute(
                    "INSERT INTO group_users (group_id, username, added_at) VALUES ('default', 'NASA', ?)",
                    (now,),
                )
                conn.execute(
                    "INSERT INTO group_users (group_id, username, added_at) VALUES ('global', 'NASA', ?)",
                    (now,),
                )
                conn.execute(
                    "INSERT INTO group_users (group_id, username, added_at) VALUES ('global', 'ESA', ?)",
                    (now,),
                )
                conn.execute(
                    "INSERT INTO group_targets (group_id, target_umo, added_at) VALUES ('default', 'telegram:FriendMessage:1', ?)",
                    (now,),
                )
                conn.execute(
                    "INSERT INTO group_targets (group_id, target_umo, added_at) VALUES ('global', 'telegram:FriendMessage:1', ?)",
                    (now,),
                )
                conn.execute(
                    "INSERT INTO group_targets (group_id, target_umo, added_at) VALUES ('global', 'telegram:FriendMessage:2', ?)",
                    (now,),
                )
                conn.execute(
                    "INSERT INTO seen_tweets (group_id, username, status_id, seen_at) VALUES ('default', 'NASA', '100', ?)",
                    (now,),
                )
                conn.execute(
                    "INSERT INTO seen_tweets (group_id, username, status_id, seen_at) VALUES ('global', 'NASA', '100', ?)",
                    (now,),
                )
                conn.execute(
                    "INSERT INTO seen_tweets (group_id, username, status_id, seen_at) VALUES ('global', 'NASA', '101', ?)",
                    (now,),
                )
                conn.execute(
                    """
                    INSERT INTO pending_tweets (
                        group_id, username, status_id, instance, tweet_data, created_at
                    ) VALUES ('default', 'NASA', '200', '', '{}', ?)
                    """,
                    (now,),
                )
                duplicate_pending_id = conn.execute(
                    """
                    INSERT INTO pending_tweets (
                        group_id, username, status_id, instance, tweet_data, created_at
                    ) VALUES ('global', 'NASA', '200', '', '{}', ?)
                    """,
                    (now,),
                ).lastrowid
                unique_pending_id = conn.execute(
                    """
                    INSERT INTO pending_tweets (
                        group_id, username, status_id, instance, tweet_data, created_at
                    ) VALUES ('global', 'ESA', '300', '', '{}', ?)
                    """,
                    (now,),
                ).lastrowid
                conn.execute(
                    """
                    INSERT INTO pending_media (
                        pending_tweet_id, media_index, kind, url, path, created_at
                    ) VALUES (?, 0, 'image', 'https://example.test/dup.jpg', '', ?)
                    """,
                    (duplicate_pending_id, now),
                )
                conn.execute(
                    """
                    INSERT INTO pending_media (
                        pending_tweet_id, media_index, kind, url, path, created_at
                    ) VALUES (?, 0, 'image', 'https://example.test/unique.jpg', '', ?)
                    """,
                    (unique_pending_id, now),
                )
                conn.commit()
            finally:
                conn.close()

            storage = SQLiteStorage(db_path)
            await storage.connect()
            try:
                version = await asyncio.to_thread(storage.get_meta, "schema_version")
                users = await asyncio.to_thread(storage.get_group_users, "default")
                targets = await asyncio.to_thread(storage.get_group_targets, "default")
                seen_ids = await asyncio.to_thread(storage.get_seen_ids, "default", "NASA")
                global_rows = storage.conn.execute(
                    """
                    SELECT COUNT(*) FROM (
                        SELECT group_id FROM groups WHERE group_id = 'global'
                        UNION ALL
                        SELECT group_id FROM group_users WHERE group_id = 'global'
                        UNION ALL
                        SELECT group_id FROM group_targets WHERE group_id = 'global'
                        UNION ALL
                        SELECT group_id FROM seen_tweets WHERE group_id = 'global'
                        UNION ALL
                        SELECT group_id FROM pending_tweets WHERE group_id = 'global'
                    )
                    """
                ).fetchone()[0]
                pending_count = storage.conn.execute(
                    "SELECT COUNT(*) FROM pending_tweets WHERE group_id = 'default'"
                ).fetchone()[0]
                media_count = storage.conn.execute(
                    "SELECT COUNT(*) FROM pending_media"
                ).fetchone()[0]
            finally:
                storage.close()

            self.assertEqual(version, "5")
            self.assertEqual(users, ["ESA", "NASA"])
            self.assertEqual(
                targets,
                ["telegram:FriendMessage:1", "telegram:FriendMessage:2"],
            )
            self.assertEqual(set(seen_ids), {"100", "101"})
            self.assertEqual(global_rows, 0)
            self.assertEqual(pending_count, 2)
            self.assertEqual(media_count, 1)


if __name__ == "__main__":
    unittest.main()
