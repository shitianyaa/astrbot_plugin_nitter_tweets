"""List-group scheduler initialization and delivery regressions."""

from __future__ import annotations

import sys
import unittest
from itertools import product
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

_TESTS_DIR = Path(__file__).resolve().parent
_ROOT = _TESTS_DIR.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

import test_scheduler_delivery as base  # noqa: E402

from media_support.client import SchedulerFetchResult  # noqa: E402
from media_support.html_backend.pool import HtmlSearchResult  # noqa: E402
from scheduler.runner_seen import SchedulerSeenMixin  # noqa: E402
from shared.utils import TweetItem, TweetMedia  # noqa: E402
from storage import SQLiteStorage, StorageAdapter  # noqa: E402


class _ListBackend:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.filter_reposts_calls = []
        self.anchor_ids_calls = []

    def fetch_list(
        self,
        list_id: str,
        limit: int = 5,
        filter_reposts: bool | None = None,
        anchor_ids: list[str] | None = None,
    ):
        self.calls.append((list_id, limit))
        self.filter_reposts_calls.append(filter_reposts)
        self.anchor_ids_calls.append(None if anchor_ids is None else list(anchor_ids))
        item = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(item, Exception):
            raise item
        instance, tweets = item
        if isinstance(tweets, HtmlSearchResult):
            return (
                instance,
                tweets.limited(limit) if anchor_ids is None else tweets,
            )
        values = list(tweets)
        return instance, values[:limit] if anchor_ids is None else values


class _HostSkipNitter(base._Nitter):
    def __init__(self):
        super().__init__()
        self.host_skip_calls = []

    def begin_run_host_skip(self):
        self.host_skip_calls.append("begin")

    def end_run_host_skip(self):
        self.host_skip_calls.append("end")


class _LegacySeenStorage:
    def __init__(self, *, fail_seen: bool = False):
        self.calls = []
        self.fail_seen = fail_seen

    async def put_group_seen_map(self, group_id, seen_map):
        del group_id, seen_map
        self.calls.append("seen")
        if self.fail_seen:
            raise RuntimeError("seen unavailable")

    async def set_scan_watermark(self, group_id, username, status_ids):
        del group_id, username, status_ids
        self.calls.append("watermark")

    @staticmethod
    def merge_seen_ids(new_ids, old_ids):
        return list(dict.fromkeys([*new_ids, *old_ids]))


class _SeenWriterHarness(SchedulerSeenMixin):
    def __init__(self, storage):
        self.storage = storage


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

    async def test_legacy_baseline_writer_orders_seen_before_watermark(self):
        storage = _LegacySeenStorage()
        writer = _SeenWriterHarness(storage)

        await writer._rebuild_scan_baseline("lists1", "list:12345", {}, ["101"])

        self.assertEqual(storage.calls, ["seen", "watermark"])

        failed_storage = _LegacySeenStorage(fail_seen=True)
        failed_writer = _SeenWriterHarness(failed_storage)
        with self.assertRaisesRegex(RuntimeError, "seen unavailable"):
            await failed_writer._rebuild_scan_baseline(
                "lists1", "list:12345", {}, ["101"]
            )
        self.assertEqual(failed_storage.calls, ["seen"])

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

    def _create_scheduler(self, html_backend, sender=None, nitter=None, config=None):
        nitter = nitter or base._Nitter()
        nitter.fetch_list = html_backend.fetch_list
        scheduler = base.NitterTweetScheduler(
            base._Owner(),
            context=None,
            config=config or self._config(),
            nitter=nitter,
            media=base._Media(),
            sender=sender or base._Sender(),
            translator=base._Translator(),
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
        self.assertIn(key, first.empty_users)
        self.assertEqual(first.source_statuses.get(key), "empty")
        self.assertNotIn(key, first.failed_users)
        self.assertNotIn(key, first_watermarks)
        self.assertEqual(second.new_tweet_count, 0)
        self.assertEqual(sender.sent, [])
        self.assertIn("101", await scheduler.storage.get_seen_ids("lists1", key))
        self.assertEqual(nitter.host_skip_calls, [])
        self.assertEqual(backend.filter_reposts_calls, [True, True])

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

    async def test_list_rss_advances_filtered_originals_but_not_repost_only(self):
        key = "list:12345"
        media_tweet = self._tweet("140")
        media_tweet.media = [
            TweetMedia(kind="image", url="https://pbs.twimg.com/media/example.jpg")
        ]
        scans = [
            SchedulerFetchResult(
                [],
                ["120", "110", "100"],
                ["120", "110", "100"],
                plain_text_filtered=3,
                complete=True,
            ),
            SchedulerFetchResult([], [], reposts_filtered=2, complete=True),
            SchedulerFetchResult(
                [],
                ["130", "120"],
                ["130", "120"],
                plain_text_filtered=2,
                reposts_filtered=1,
                complete=True,
            ),
            SchedulerFetchResult(
                [media_tweet],
                ["140", "130"],
                ["140", "130"],
                complete=True,
            ),
        ]
        config = self._config()
        config["tweet_groups"][0]["filter_plain_text_enabled"] = True
        nitter = base._Nitter()
        nitter.fetch_list_for_scheduler = AsyncMock(
            side_effect=[("https://list.test", scan) for scan in scans]
        )
        sender = base._Sender()
        scheduler = self._create_scheduler(
            _ListBackend([]), sender=sender, nitter=nitter, config=config
        )
        storage = scheduler.storage
        await storage.add_seen_ids("lists1", key, ["100"])
        await storage.set_scan_watermark("lists1", key, ["100"])

        for expected, plain_count, repost_count in (
            (["120", "110", "100"], 3, 0),
            (["120", "110", "100"], 0, 2),
            (["130", "120"], 2, 1),
        ):
            filtered = await scheduler.run_check(group_name="lists1")
            self.assertEqual(filtered.plain_text_filtered, plain_count)
            self.assertEqual(filtered.retweet_filtered, repost_count)
            self.assertEqual(
                filtered.filtered_empty_users, [] if plain_count else [key]
            )
            self.assertEqual(
                await storage.get_group_scan_watermarks("lists1"), {key: expected}
            )
            self.assertEqual(sender.sent, [])

        self.assertEqual(
            await storage.get_seen_ids("lists1", key), ["130", "120", "110", "100"]
        )
        await scheduler.run_check(group_name="lists1")
        self.assertEqual(
            nitter.fetch_list_for_scheduler.await_args.args[1], ["130", "120"]
        )
        self.assertEqual([item[3] for item in sender.sent], [["140"]])

    async def test_list_group_can_disable_repost_filter(self):
        backend = _ListBackend([("https://list.test", [self._tweet("100")])])
        config = self._config()
        config["tweet_groups"][0]["filter_reposts_enabled"] = False
        scheduler = self._create_scheduler(backend, config=config)
        group = scheduler._schedule_groups(log_invalid_targets=False)[0]

        result = await scheduler._fetch_group_user(
            group,
            0,
            "list:12345",
            20,
            False,
            None,
        )

        self.assertEqual(backend.filter_reposts_calls, [False])
        self.assertEqual([tweet.status_id for tweet in result.tweets], ["100"])

    async def test_existing_list_scan_delivers_items_beyond_first_page_limit(self):
        new_ids = [str(status_id) for status_id in range(121, 100, -1)]
        backend = _ListBackend(
            [
                ("https://list.test", [self._tweet("100")]),
                (
                    "https://list.test",
                    HtmlSearchResult(
                        [self._tweet(status_id) for status_id in [*new_ids, "100"]],
                        raw_item_count=22,
                    ),
                ),
            ]
        )
        sender = base._Sender()
        scheduler = self._create_scheduler(backend, sender=sender)
        await scheduler.storage.migrate_and_sync(scheduler._schedule_groups(False))

        await scheduler.run_check(reason="list_seed", group_name="lists1")
        result = await scheduler.run_check(reason="list_new", group_name="lists1")

        self.assertEqual(backend.anchor_ids_calls, [None, ["100"]])
        self.assertEqual(result.new_tweet_count, 21)
        sent_ids = [status_id for item in sender.sent for status_id in item[3]]
        self.assertEqual(len(sent_ids), 21)
        self.assertEqual(set(sent_ids), set(new_ids))

    async def test_incomplete_list_scan_rebuilds_baseline_without_sending(self):
        backend = _ListBackend(
            [
                ("https://list.test", [self._tweet("100")]),
                (
                    "https://list.test",
                    HtmlSearchResult(
                        [self._tweet("101"), self._tweet("100")],
                        raw_item_count=2,
                        scan_complete=False,
                        anchor_status_ids=["101", "100"],
                    ),
                ),
                (
                    "https://list.test",
                    HtmlSearchResult(
                        [self._tweet("102"), self._tweet("101"), self._tweet("100")],
                        raw_item_count=3,
                        anchor_status_ids=["102", "101", "100"],
                    ),
                ),
            ]
        )
        sender = base._Sender()
        scheduler = self._create_scheduler(backend, sender=sender)
        await scheduler.storage.migrate_and_sync(scheduler._schedule_groups(False))
        key = "list:12345"

        await scheduler.run_check(reason="list_seed", group_name="lists1")
        result = await scheduler.run_check(
            reason="list_incomplete", group_name="lists1"
        )
        watermarks = await scheduler.storage.get_group_scan_watermarks("lists1")

        self.assertEqual(result.baseline_rebuilt_users.get(key), 2)
        self.assertNotIn(key, result.failed_users)
        self.assertEqual(watermarks[key], ["101", "100"])
        self.assertIn("101", await scheduler.storage.get_seen_ids("lists1", key))
        self.assertEqual(sender.sent, [])
        self.assertIn("基准重建:", result.format_structured_task_log())
        self.assertIn("旧积压可能被跳过", result.format_message())

        next_result = await scheduler.run_check(
            reason="list_after_rebuild", group_name="lists1"
        )
        self.assertEqual(next_result.new_tweet_count, 1)
        self.assertEqual(sender.sent[-1][3], ["102"])
        self.assertEqual(backend.anchor_ids_calls, [None, ["100"], ["101", "100"]])

    async def test_existing_empty_list_result_keeps_watermark(self):
        backend = _ListBackend(
            [
                ("https://list.test", [self._tweet("100")]),
                (
                    "https://list.test",
                    HtmlSearchResult([], scan_complete=False),
                ),
            ]
        )
        scheduler = self._create_scheduler(backend)
        await scheduler.storage.migrate_and_sync(scheduler._schedule_groups(False))
        key = "list:12345"

        await scheduler.run_check(reason="list_seed", group_name="lists1")
        before = await scheduler.storage.get_group_scan_watermarks("lists1")
        result = await scheduler.run_check(reason="list_empty", group_name="lists1")
        after = await scheduler.storage.get_group_scan_watermarks("lists1")

        self.assertEqual(result.source_statuses.get(key), "empty")
        self.assertIn(key, result.empty_users)
        self.assertEqual(result.baseline_rebuild_failed_users, {})
        self.assertEqual(before, after)
        self.assertNotIn("本次没有发现需要推送的新推文。", result.format_message())

    async def test_incomplete_list_scan_with_limit_pushes_then_rebuilds(self):
        config = self._config()
        config["tweet_groups"][0]["max_tweets_per_check"] = 1
        backend = _ListBackend(
            [
                ("https://list.test", [self._tweet("100")]),
                (
                    "https://list.test",
                    HtmlSearchResult(
                        [
                            self._tweet("103"),
                            self._tweet("102"),
                            self._tweet("101"),
                        ],
                        scan_complete=False,
                        anchor_status_ids=["103", "102", "101"],
                    ),
                ),
            ]
        )
        sender = base._Sender()
        scheduler = self._create_scheduler(backend, sender=sender, config=config)
        await scheduler.storage.migrate_and_sync(scheduler._schedule_groups(False))
        key = "list:12345"

        await scheduler.run_check(reason="list_seed", group_name="lists1")
        result = await scheduler.run_check(
            reason="list_incomplete", group_name="lists1"
        )

        self.assertEqual(result.new_tweet_count, 1)
        self.assertEqual(sender.sent[-1][3], ["103"])
        self.assertEqual(result.baseline_rebuilt_users.get(key), 3)
        self.assertEqual(
            await scheduler.storage.get_group_scan_watermarks("lists1"),
            {key: ["103", "102", "101"]},
        )

    async def test_incomplete_list_scan_without_valid_page_ids_keeps_old_baseline(self):
        backend = _ListBackend(
            [
                ("https://list.test", [self._tweet("100")]),
                (
                    "https://list.test",
                    HtmlSearchResult(
                        [self._tweet("101"), self._tweet("100")],
                        raw_item_count=2,
                        scan_complete=False,
                        anchor_status_ids=["invalid-status-id"],
                    ),
                ),
            ]
        )
        scheduler = self._create_scheduler(backend)
        await scheduler.storage.migrate_and_sync(scheduler._schedule_groups(False))
        key = "list:12345"

        await scheduler.run_check(reason="list_seed", group_name="lists1")
        before = await scheduler.storage.get_group_scan_watermarks("lists1")
        result = await scheduler.run_check(
            reason="list_incomplete", group_name="lists1"
        )
        after = await scheduler.storage.get_group_scan_watermarks("lists1")

        self.assertEqual(
            result.baseline_rebuild_failed_users.get(key),
            "扫描未完整且当前第一页没有有效状态 ID，保留旧水位",
        )
        self.assertEqual(before, after)
        self.assertNotIn("101", await scheduler.storage.get_seen_ids("lists1", key))
        self.assertEqual(result.new_tweet_count, 0)

    async def test_list_fetch_failure_does_not_rebuild_baseline(self):
        backend = _ListBackend(
            [
                ("https://list.test", [self._tweet("100")]),
                RuntimeError("temporary list failure"),
            ]
        )
        scheduler = self._create_scheduler(backend)
        await scheduler.storage.migrate_and_sync(scheduler._schedule_groups(False))
        key = "list:12345"

        await scheduler.run_check(reason="list_seed", group_name="lists1")
        before = await scheduler.storage.get_group_scan_watermarks("lists1")
        result = await scheduler.run_check(reason="list_failed", group_name="lists1")
        after = await scheduler.storage.get_group_scan_watermarks("lists1")

        self.assertIn(key, result.failed_users)
        self.assertEqual(before, after)
        self.assertEqual(result.baseline_rebuilt_users, {})
        self.assertEqual(result.new_tweet_count, 0)

    async def test_baseline_write_failure_is_reported_without_success_status(self):
        backend = _ListBackend(
            [
                ("https://list.test", [self._tweet("100")]),
                (
                    "https://list.test",
                    HtmlSearchResult(
                        [self._tweet("101")],
                        anchor_status_ids=["101"],
                        scan_complete=False,
                    ),
                ),
            ]
        )
        scheduler = self._create_scheduler(backend)
        await scheduler.storage.migrate_and_sync(scheduler._schedule_groups(False))
        key = "list:12345"

        await scheduler.run_check(reason="list_seed", group_name="lists1")
        original_set_watermark = SQLiteStorage._set_scan_watermark_unlocked

        def fail_new_watermark(storage, group_id, username, status_ids):
            if status_ids == ["101"]:
                raise RuntimeError("watermark unavailable")
            original_set_watermark(storage, group_id, username, status_ids)

        with patch.object(
            SQLiteStorage,
            "_set_scan_watermark_unlocked",
            fail_new_watermark,
        ):
            result = await scheduler.run_check(
                reason="list_write_failure", group_name="lists1"
            )

        self.assertIn(key, result.baseline_rebuild_failed_users)
        self.assertNotIn(key, result.baseline_rebuilt_users)
        self.assertNotIn(key, result.failed_users)
        self.assertEqual(
            await scheduler.storage.get_group_scan_watermarks("lists1"),
            {key: ["100"]},
        )
        self.assertEqual(
            await scheduler.storage.get_seen_ids("lists1", key),
            ["100"],
        )

    async def test_baseline_seen_write_failure_rolls_back_watermark(self):
        backend = _ListBackend(
            [
                ("https://list.test", [self._tweet("100")]),
                (
                    "https://list.test",
                    HtmlSearchResult(
                        [self._tweet("101")],
                        anchor_status_ids=["101"],
                        scan_complete=False,
                    ),
                ),
            ]
        )
        scheduler = self._create_scheduler(backend)
        await scheduler.storage.migrate_and_sync(scheduler._schedule_groups(False))
        key = "list:12345"

        await scheduler.run_check(reason="list_seed", group_name="lists1")
        original_add_seen = SQLiteStorage._add_seen_ids_unlocked

        def fail_new_seen(storage, group_id, username, status_ids):
            if "101" in status_ids:
                raise RuntimeError("seen unavailable")
            original_add_seen(storage, group_id, username, status_ids)

        with patch.object(
            SQLiteStorage,
            "_add_seen_ids_unlocked",
            fail_new_seen,
        ):
            result = await scheduler.run_check(
                reason="list_seen_write_failure", group_name="lists1"
            )

        self.assertIn(key, result.baseline_rebuild_failed_users)
        self.assertNotIn(key, result.baseline_rebuilt_users)
        self.assertEqual(
            await scheduler.storage.get_group_scan_watermarks("lists1"),
            {key: ["100"]},
        )
        self.assertEqual(
            await scheduler.storage.get_seen_ids("lists1", key),
            ["100"],
        )

    async def test_rebuild_baseline_only_writes_new_ids_for_the_current_source(self):
        scheduler = self._create_scheduler(_ListBackend([]))
        storage = scheduler.storage
        source, other_source = "list:12345", "list:67890"
        await storage.add_seen_ids("lists1", source, ["99"], handled=True)
        await storage.add_seen_ids("lists1", other_source, ["150"], handled=True)
        await storage.set_scan_watermark("lists1", other_source, ["150"])
        seen_map = await storage.get_group_seen_map("lists1")
        sqlite = storage.sqlite
        with patch.object(
            sqlite, "_add_seen_ids_unlocked", wraps=sqlite._add_seen_ids_unlocked
        ) as write_seen:
            await scheduler._rebuild_scan_baseline("lists1", source, seen_map, ["100"])

        write_seen.assert_called_once_with("lists1", source, ["100"])
        self.assertEqual(seen_map, {source: ["100", "99"], other_source: ["150"]})
        self.assertEqual(await storage.get_group_seen_map("lists1"), seen_map)
        self.assertEqual(
            await storage.get_group_handled_seen_map("lists1"),
            {source: ["99"], other_source: ["150"]},
        )
        self.assertEqual(
            await storage.get_group_scan_watermarks("lists1"),
            {source: ["100"], other_source: ["150"]},
        )

    async def test_reenabled_list_reseeds_after_restart_and_write_failure(self):
        backend = _ListBackend(
            [
                ("https://list.test", [self._tweet("100")]),
                ("https://list.test", [self._tweet("101")]),
                ("https://list.test", [self._tweet("101")]),
                ("https://list.test", [self._tweet("102"), self._tweet("101")]),
            ]
        )
        config = self._config()
        sender = base._Sender()
        scheduler = self._create_scheduler(backend, config=config, sender=sender)
        await scheduler.run_check(group_name="lists1")
        for enabled in (False, True):
            config["tweet_groups"][0]["enabled"] = enabled
            await scheduler.storage.migrate_and_sync(scheduler._schedule_groups(False))
        scheduler.storage.close()
        self.assertEqual(
            await scheduler.storage.get_pending_baselines("lists1"), {"list:12345"}
        )
        with patch.object(
            scheduler.storage,
            "put_scan_baseline",
            side_effect=RuntimeError("write failed"),
        ):
            with self.assertRaisesRegex(RuntimeError, "write failed"):
                await scheduler.run_check(group_name="lists1")
        self.assertEqual(
            await scheduler.storage.get_pending_baselines("lists1"), {"list:12345"}
        )
        await scheduler.run_check(group_name="lists1")
        self.assertEqual(sender.sent, [])
        self.assertEqual(scheduler.media.attached, 0)
        self.assertEqual(await scheduler.storage.get_pending_baselines("lists1"), set())
        self.assertIn(
            "100", await scheduler.storage.get_seen_ids("lists1", "list:12345")
        )
        await scheduler.run_check(group_name="lists1")
        self.assertEqual(sender.sent[-1][3], ["102"])

    async def test_group_limit_selects_newest_across_lists_before_media(self):
        config = self._config()
        config["tweet_groups"][0]["watch_lists"] = ["12345", "67890"]
        config["tweet_groups"][0]["max_tweets_per_check"] = 2
        backend = _ListBackend(
            [
                ("https://list.test", [self._tweet("100")]),
                ("https://list.test", [self._tweet("200")]),
                ("https://list.test", [self._tweet(i) for i in ("105", "104", "100")]),
                ("https://list.test", [self._tweet(i) for i in ("205", "204", "200")]),
            ]
        )
        sender = base._Sender()
        scheduler = self._create_scheduler(backend, config=config, sender=sender)
        await scheduler.run_check(group_name="lists1")
        result = await scheduler.run_check(group_name="lists1")
        self.assertEqual(result.selected_tweet_count, 2)
        self.assertEqual(result.limit_skipped_count, 2)
        self.assertEqual(scheduler.media.attached, 2)
        self.assertEqual(
            [sid for item in sender.sent for sid in item[3]], ["205", "204"]
        )
        self.assertTrue(
            {"105", "104"}.issubset(
                await scheduler.storage.get_seen_ids("lists1", "list:12345")
            )
        )
        handled = await scheduler.storage.get_group_handled_seen_map("lists1")
        self.assertEqual(set(handled), {"list:12345", "list:67890"})
        self.assertEqual(set(handled["list:12345"]), {"105", "104"})
        self.assertEqual(set(handled["list:67890"]), {"205", "204"})

    async def test_over_limit_skip_is_shared_with_source_that_recovers_later(self):
        config = self._config()
        config["tweet_groups"][0].update(
            watch_lists=["12345", "67890"], max_tweets_per_check=1
        )
        first = [self._tweet(i) for i in ("405", "305", "100")]
        backend = _ListBackend(
            [
                ("https://list.test", [self._tweet("100")]),
                ("https://list.test", [self._tweet("200")]),
                ("https://list.test", first),
                RuntimeError("source unavailable"),
                ("https://list.test", first),
                ("https://list.test", [self._tweet(i) for i in ("305", "200")]),
            ]
        )
        sender = base._Sender()
        scheduler = self._create_scheduler(backend, config=config, sender=sender)
        await scheduler.run_check(group_name="lists1")
        limited = await scheduler.run_check(group_name="lists1")
        self.assertEqual(limited.limit_skipped_count, 1)
        scheduler.storage.close()
        recovered = await scheduler.run_check(group_name="lists1")
        self.assertEqual(recovered.selected_tweet_count, 0)
        self.assertEqual([sid for item in sender.sent for sid in item[3]], ["405"])
        self.assertEqual(scheduler.media.attached, 1)
        self.assertIn(
            "305", await scheduler.storage.get_seen_ids("lists1", "list:67890")
        )

    async def test_overlapping_lists_share_unique_slots_and_retry_failed_owner(self):
        for limit, fail_owner in ((0, False), (2, False), (2, True)):
            with self.subTest(limit=limit, fail_owner=fail_owner):
                config = self._config()
                config["tweet_groups"][0].update(
                    watch_lists=["12345", "67890"], max_tweets_per_check=limit
                )
                first = [self._tweet(i) for i in ("305", "304", "100")]
                second = [self._tweet(i) for i in ("305", "303", "200")]
                backend = _ListBackend(
                    [
                        ("https://list.test", [self._tweet("100")]),
                        ("https://list.test", [self._tweet("200")]),
                        ("https://list.test", first),
                        ("https://list.test", second),
                        ("https://list.test", first),
                        ("https://list.test", second),
                    ]
                )
                sender = base._Sender()
                scheduler = self._create_scheduler(
                    backend, config=config, sender=sender
                )
                # Each subcase has an independent group even though the storage
                # fixture shares the same database file.
                await scheduler.storage.clear_seen_records("lists1")
                await scheduler.run_check(group_name="lists1")
                prepare = scheduler._prepare_immediate_batch

                async def prepare_candidate(batch, target):
                    if fail_owner and batch.tweets[0].status_id == "305":
                        raise RuntimeError("preparation failed")
                    return await prepare(batch, target)

                with patch.object(
                    scheduler, "_prepare_immediate_batch", side_effect=prepare_candidate
                ):
                    result = await scheduler.run_check(group_name="lists1")
                sent_ids = [sid for item in sender.sent for sid in item[3]]
                expected = (
                    ["304"]
                    if fail_owner
                    else (["305", "304", "303"] if limit == 0 else ["305", "304"])
                )
                self.assertEqual(sent_ids, expected)
                self.assertEqual(result.selected_tweet_count, 3 if limit == 0 else 2)
                for key in ("list:12345", "list:67890"):
                    seen = await scheduler.storage.get_seen_ids("lists1", key)
                    self.assertEqual("305" in seen, not fail_owner)
                if fail_owner:
                    scheduler.media = base._Media()
                    await scheduler.run_check(group_name="lists1")
                    self.assertEqual(
                        [sid for item in sender.sent for sid in item[3]], ["304", "305"]
                    )
                    self.assertIn(
                        "305",
                        await scheduler.storage.get_seen_ids("lists1", "list:67890"),
                    )

    async def test_reenable_request_survives_failed_config_sync(self):
        from config import config_get
        from plugin_api.api import NitterWebAPI
        from types import SimpleNamespace

        class SavingConfig(dict):
            def save_config(self):
                pass

        for failed_operation in ("disable", "enable"):
            with self.subTest(failed_operation=failed_operation):
                config = SavingConfig(self._config())
                backend = _ListBackend(
                    [
                        ("https://list.test", [self._tweet("100")]),
                        ("https://list.test", [self._tweet("101")]),
                        ("https://list.test", [self._tweet("102"), self._tweet("101")]),
                    ]
                )
                sender = base._Sender()
                scheduler = self._create_scheduler(
                    backend, config=config, sender=sender
                )
                await scheduler.storage.clear_seen_records("lists1")
                await scheduler.run_check(group_name="lists1")
                api = NitterWebAPI(SimpleNamespace(config=config, scheduler=scheduler))
                for enabled in (False, True):
                    operation = "enable" if enabled else "disable"
                    if operation == failed_operation:
                        with patch.object(
                            scheduler.storage,
                            "migrate_and_sync",
                            side_effect=RuntimeError("sync unavailable"),
                        ):
                            result = await api.update_group(
                                {"group_id": "lists1", "enabled": enabled}
                            )
                        self.assertIn("sync_error", result)
                    else:
                        result = await api.update_group(
                            {"group_id": "lists1", "enabled": enabled}
                        )
                        self.assertNotIn("sync_error", result)
                token = config_get(config, "tweet_groups")[0]["_baseline_reset_token"]
                self.assertTrue(token)
                scheduler.storage.close()
                await scheduler.run_check(group_name="lists1")
                self.assertEqual(sender.sent, [])
                self.assertEqual(
                    await scheduler.storage.get_pending_baselines("lists1"), set()
                )
                # A later snapshot sync must not reapply an already consumed request.
                self.assertEqual(await api._sync_groups(), "")
                self.assertEqual(
                    await scheduler.storage.get_pending_baselines("lists1"), set()
                )
                await scheduler.run_check(group_name="lists1")
                self.assertEqual(sender.sent[-1][3], ["102"])

    async def test_new_source_baseline_does_not_handle_existing_source_candidate(self):
        for baseline_first, new_source_first, fail_prepare in product(
            (False, True), repeat=3
        ):
            with self.subTest(
                baseline_first=baseline_first,
                new_source_first=new_source_first,
                fail_prepare=fail_prepare,
            ):
                config = self._config()
                config["tweet_groups"][0]["max_tweets_per_check"] = 1
                current = [self._tweet(i) for i in ("305", "100")]
                seed = [self._tweet("305")]
                initial_existing = [self._tweet("100")]
                added_round = initial_existing if baseline_first else current
                pair = [seed, added_round] if new_source_first else [added_round, seed]
                retry_pair = [seed, current] if new_source_first else [current, seed]
                pages = [initial_existing, *pair]
                if baseline_first:
                    pages.extend(retry_pair)
                pages.extend(retry_pair)
                backend = _ListBackend(
                    [("https://list.test", tweets) for tweets in pages]
                )
                sender = base._Sender()
                scheduler = self._create_scheduler(
                    backend, config=config, sender=sender
                )
                await scheduler.storage.clear_seen_records("lists1")
                await scheduler.run_check(group_name="lists1")
                config["tweet_groups"][0]["watch_lists"] = (
                    ["67890", "12345"] if new_source_first else ["12345", "67890"]
                )
                if baseline_first:
                    await scheduler.run_check(group_name="lists1")
                    scheduler.storage.close()
                if fail_prepare:
                    with patch.object(
                        scheduler,
                        "_prepare_immediate_batch",
                        side_effect=RuntimeError("preparation failed"),
                    ):
                        result = await scheduler.run_check(group_name="lists1")
                    self.assertEqual(result.selected_tweet_count, 1)
                    self.assertEqual(sender.sent, [])
                    self.assertNotIn(
                        "305",
                        await scheduler.storage.get_seen_ids("lists1", "list:12345"),
                    )
                    self.assertEqual(
                        await scheduler.storage.get_group_handled_seen_map("lists1"),
                        {},
                    )
                    scheduler.storage.close()
                result = await scheduler.run_check(group_name="lists1")
                self.assertEqual(result.selected_tweet_count, 1)
                self.assertEqual(
                    [sid for item in sender.sent for sid in item[3]], ["305"]
                )
                self.assertEqual(scheduler.media.attached, 1)

    async def test_duplicate_seen_write_failure_does_not_redeliver_owner(self):
        config = self._config()
        config["tweet_groups"][0].update(
            watch_lists=["12345", "67890"], max_tweets_per_check=1
        )
        first = [self._tweet(i) for i in ("305", "100")]
        second = [self._tweet(i) for i in ("305", "200")]
        backend = _ListBackend(
            [
                ("https://list.test", [self._tweet("100")]),
                ("https://list.test", [self._tweet("200")]),
                ("https://list.test", first),
                ("https://list.test", second),
                ("https://list.test", first),
                ("https://list.test", second),
            ]
        )
        sender = base._Sender()
        scheduler = self._create_scheduler(backend, config=config, sender=sender)
        await scheduler.run_check(group_name="lists1")
        store = scheduler._store_incremental_seen_ids

        async def fail_duplicate(
            group_id, username, status_ids, seen_map, *, handled=False
        ):
            if username == "list:67890" and "305" in status_ids:
                raise RuntimeError("duplicate seen write failed")
            await store(group_id, username, status_ids, seen_map, handled=handled)

        with (
            patch.object(
                scheduler, "_store_incremental_seen_ids", side_effect=fail_duplicate
            ),
            patch.object(
                scheduler.storage,
                "record_push_history",
                side_effect=RuntimeError("history unavailable"),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "duplicate seen write failed"):
                await scheduler.run_check(group_name="lists1")
        self.assertEqual([sid for item in sender.sent for sid in item[3]], ["305"])
        self.assertEqual(
            await scheduler.storage.get_group_handled_seen_map("lists1"),
            {"list:12345": ["305"]},
        )
        self.assertNotIn(
            "305", await scheduler.storage.get_seen_ids("lists1", "list:67890")
        )
        scheduler.storage.close()
        await scheduler.run_check(group_name="lists1")
        self.assertEqual([sid for item in sender.sent for sid in item[3]], ["305"])
        self.assertIn(
            "305", await scheduler.storage.get_seen_ids("lists1", "list:67890")
        )
