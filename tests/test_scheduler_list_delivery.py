"""List-group scheduler initialization and delivery regressions."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

_TESTS_DIR = Path(__file__).resolve().parent
_ROOT = _TESTS_DIR.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

import test_scheduler_delivery as base  # noqa: E402

from media_support.html_backend.pool import HtmlSearchResult  # noqa: E402
from shared.utils import TweetItem  # noqa: E402
from storage import SQLiteStorage, StorageAdapter  # noqa: E402


class _ListBackend:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def fetch_list(self, list_id: str, limit: int = 5):
        self.calls.append((list_id, limit))
        item = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        instance, tweets = item
        if isinstance(tweets, HtmlSearchResult):
            return instance, tweets.limited(limit)
        return instance, list(tweets)[:limit]


class _HostSkipNitter(base._Nitter):
    def __init__(self):
        super().__init__()
        self.host_skip_calls = []

    def begin_run_host_skip(self):
        self.host_skip_calls.append("begin")

    def end_run_host_skip(self):
        self.host_skip_calls.append("end")


class ListSchedulerDeliveryTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = TemporaryDirectory()
        self.schedulers = []
        db_path = Path(self.temp_dir.name) / "nitter_tweets.db"
        self.storage_patch = patch.object(
            StorageAdapter,
            "_init_sqlite",
            return_value=SQLiteStorage(db_path),
        )
        self.storage_patch.start()

    async def asyncTearDown(self):
        for scheduler in self.schedulers:
            scheduler.storage.close()
        self.storage_patch.stop()
        self.temp_dir.cleanup()

    @staticmethod
    def _tweet(status_id: str) -> TweetItem:
        return TweetItem(
            text=f"tweet {status_id}",
            link=f"https://x.com/member/status/{status_id}",
            published="",
        )

    @staticmethod
    def _config():
        return {
            "schedule_enabled": True,
            "tweet_groups": [
                {
                    "name": "列表",
                    "group_id": "lists1",
                    "group_type": "list",
                    "watch_lists": ["12345"],
                    "push_targets": ["telegram:FriendMessage:1"],
                    "enabled": True,
                    "send_user_interval": 0,
                }
            ],
            "send_target_interval": 0,
            "send_user_interval": 0,
        }

    def _create_scheduler(self, html_backend, sender=None, nitter=None):
        scheduler = base.NitterTweetScheduler(
            base._Owner(),
            context=None,
            config=self._config(),
            nitter=nitter or base._Nitter(),
            media=base._Media(),
            sender=sender or base._Sender(),
            translator=base._Translator(),
            html_backend=html_backend,
        )
        self.schedulers.append(scheduler)
        return scheduler

    async def test_empty_first_scan_does_not_initialize_or_push_history(self):
        backend = _ListBackend(
            [
                ("https://list.test", []),
                ("https://list.test", [self._tweet("101")]),
            ]
        )
        sender = base._Sender()
        nitter = _HostSkipNitter()
        scheduler = self._create_scheduler(backend, sender=sender, nitter=nitter)
        await scheduler.storage.migrate_and_sync(scheduler._schedule_groups(False))
        key = "list:12345"

        first = await scheduler.run_check(reason="list_empty", group_name="lists1")
        first_watermarks = await scheduler.storage.get_group_scan_watermarks("lists1")
        second = await scheduler.run_check(reason="list_seed", group_name="lists1")

        self.assertEqual(first.new_tweet_count, 0)
        self.assertIn(key, first.failed_users)
        self.assertNotIn(key, first_watermarks)
        self.assertEqual(second.new_tweet_count, 0)
        self.assertEqual(sender.sent, [])
        self.assertIn("101", await scheduler.storage.get_seen_ids("lists1", key))
        self.assertEqual(nitter.host_skip_calls, [])

    async def test_filtered_first_scan_writes_empty_watermark_then_pushes(self):
        backend = _ListBackend(
            [
                (
                    "https://list.test",
                    HtmlSearchResult([], raw_item_count=1, retweet_filtered=1),
                ),
                ("https://list.test", [self._tweet("102")]),
            ]
        )
        sender = base._Sender()
        scheduler = self._create_scheduler(backend, sender=sender)
        await scheduler.storage.migrate_and_sync(scheduler._schedule_groups(False))
        key = "list:12345"

        first = await scheduler.run_check(reason="list_filtered", group_name="lists1")
        second = await scheduler.run_check(reason="list_new", group_name="lists1")

        self.assertEqual(first.initialized_users.get(key), 0)
        self.assertEqual(second.new_tweet_count, 1)
        self.assertEqual(sender.sent[-1][3], ["102"])
        self.assertIn("102", await scheduler.storage.get_seen_ids("lists1", key))
