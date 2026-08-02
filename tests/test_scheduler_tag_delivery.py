"""Tag-group scheduler delivery: seen init, empty first scan, push, fail no-seen."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

# Reuse AstrBot stubs and delivery fakes from the blogger scheduler suite.
_TESTS_DIR = Path(__file__).resolve().parent
_ROOT = _TESTS_DIR.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

import test_scheduler_delivery as base  # noqa: E402

from media_support.html_backend import (  # noqa: E402
    normalize_watch_query,
    seen_account_key_for_query,
)
from media_support.html_backend.pool import HtmlSearchResult  # noqa: E402
from shared.utils import TweetItem, TweetMedia  # noqa: E402
from storage import SQLiteStorage, StorageAdapter  # noqa: E402


class _HtmlBackend:
    """Queue of (instance, tweets) responses per raw query string."""

    def __init__(self, responses_by_query: dict[str, list]):
        self.responses_by_query = {
            q: list(items) for q, items in responses_by_query.items()
        }
        self.calls: list[tuple[str, int, str | None]] = []
        self.filter_reposts_calls: list[bool | None] = []
        self.anchor_ids_calls: list[list[str] | None] = []

    def search(
        self,
        query: str,
        limit: int = 5,
        kind: str | None = None,
        filter_reposts: bool | None = None,
        anchor_ids: list[str] | None = None,
    ):
        self.calls.append((query, limit, kind))
        self.filter_reposts_calls.append(filter_reposts)
        self.anchor_ids_calls.append(None if anchor_ids is None else list(anchor_ids))
        queue = self.responses_by_query.setdefault(query, [("", [])])
        if len(queue) > 1:
            item = queue.pop(0)
        else:
            item = queue[0]
        instance, tweets = item
        if isinstance(tweets, HtmlSearchResult):
            return (
                instance,
                tweets.limited(limit) if not anchor_ids else tweets,
            )
        return instance, list(tweets)[:limit]


class _StatsHtmlBackend(_HtmlBackend):
    """Preserve HTML pool RT/row counters for scheduler regression tests."""

    def search(
        self,
        query: str,
        limit: int = 5,
        kind: str | None = None,
        filter_reposts: bool | None = None,
        anchor_ids: list[str] | None = None,
    ):
        instance, tweets = super().search(
            query,
            limit=10_000,
            kind=kind,
            filter_reposts=filter_reposts,
            anchor_ids=anchor_ids,
        )
        use_filter_reposts = True if filter_reposts is None else filter_reposts
        retweets = (
            [tweet for tweet in tweets if getattr(tweet, "is_retweet", False)]
            if use_filter_reposts
            else []
        )
        kept = (
            [tweet for tweet in tweets if not getattr(tweet, "is_retweet", False)]
            if use_filter_reposts
            else list(tweets)
        )
        return instance, HtmlSearchResult(
            kept[:limit],
            raw_item_count=len(tweets),
            retweet_filtered=len(retweets),
            scan_complete=bool(getattr(tweets, "scan_complete", True)),
            anchor_status_ids=getattr(tweets, "anchor_status_ids", None),
        )


class TagSchedulerDeliveryTest(unittest.IsolatedAsyncioTestCase):
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

    def _make_tweet(self, status_id: str, author: str = "someone") -> TweetItem:
        return TweetItem(
            text=f"tweet {status_id}",
            link=f"https://x.com/{author}/status/{status_id}",
            published="",
        )

    def _tag_config(self, query: str = "#foo", **extra) -> dict:
        cfg = {
            "schedule_enabled": True,
            "tweet_groups": [
                {
                    "name": "标签示例",
                    "group_id": "tags1",
                    "group_type": "tag",
                    "watch_queries": [query],
                    "push_targets": ["telegram:FriendMessage:1"],
                    "enabled": True,
                }
            ],
            "send_target_interval": 0,
            "send_user_interval": 0,
            "html_max_pages": 1,
        }
        cfg.update(extra)
        return cfg

    def _account_key(self, query: str = "#foo") -> str:
        q, _kind = normalize_watch_query(query, None)
        return seen_account_key_for_query(q)

    def _create_scheduler(self, config, *, html_backend, sender=None, media=None):
        scheduler = base.NitterTweetScheduler(
            base._Owner(),
            context=None,
            config=config,
            nitter=base._Nitter(),
            media=media or base._Media(),
            sender=sender or base._Sender(),
            translator=base._Translator(),
            html_backend=html_backend,
        )
        self.schedulers.append(scheduler)
        return scheduler

    async def test_tag_first_scan_initializes_seen_without_push(self):
        query = "#foo"
        key = self._account_key(query)
        html = _HtmlBackend(
            {
                query: [
                    (
                        "https://search.test",
                        [self._make_tweet("100"), self._make_tweet("99")],
                    )
                ]
            }
        )
        sender = base._Sender()
        scheduler = self._create_scheduler(
            self._tag_config(query),
            html_backend=html,
            sender=sender,
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )

        result = await scheduler.run_check(reason="tag_first_init", group_name="tags1")

        self.assertEqual(result.new_tweet_count, 0)
        self.assertEqual(sender.sent, [])
        self.assertEqual(len(html.calls), 1)
        self.assertEqual(html.calls[0][0], query)
        self.assertEqual(html.calls[0][2], "tag")
        self.assertEqual(html.filter_reposts_calls, [True])
        seen = await scheduler.storage.get_seen_ids("tags1", key)
        self.assertIn("100", seen)
        self.assertIn("99", seen)
        watermarks = await scheduler.storage.get_group_scan_watermarks("tags1")
        self.assertIn("100", watermarks.get(key) or [])

    async def test_tag_second_scan_pushes_new_and_writes_seen(self):
        query = "#foo"
        key = self._account_key(query)
        html = _HtmlBackend(
            {
                query: [
                    (
                        "https://search.test",
                        [self._make_tweet("100")],
                    ),
                    (
                        "https://search.test",
                        [self._make_tweet("101"), self._make_tweet("100")],
                    ),
                ]
            }
        )
        sender = base._Sender()
        scheduler = self._create_scheduler(
            self._tag_config(query),
            html_backend=html,
            sender=sender,
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )

        first = await scheduler.run_check(reason="tag_init", group_name="tags1")
        second = await scheduler.run_check(reason="tag_new", group_name="tags1")

        self.assertEqual(first.new_tweet_count, 0)
        self.assertEqual(second.new_tweet_count, 1)
        self.assertEqual(len(sender.sent), 1)
        self.assertEqual(sender.sent[0][1], key)
        self.assertEqual(sender.sent[0][3], ["101"])
        seen = await scheduler.storage.get_seen_ids("tags1", key)
        self.assertIn("101", seen)
        self.assertIn("100", seen)

        third = await scheduler.run_check(reason="tag_no_new", group_name="tags1")
        self.assertEqual(third.source_statuses.get(key), "no_new")
        self.assertIn("本次没有发现需要推送的新推文。", third.format_message())

    async def test_tag_scan_passes_watermark_and_pushes_across_pages(self):
        query = "#foo"
        key = self._account_key(query)
        html = _HtmlBackend(
            {
                query: [
                    (
                        "https://search.test",
                        HtmlSearchResult(
                            [self._make_tweet("100"), self._make_tweet("99")],
                            anchor_status_ids=["100", "99"],
                        ),
                    ),
                    (
                        "https://search.test",
                        HtmlSearchResult(
                            [
                                self._make_tweet("101"),
                                self._make_tweet("100"),
                                self._make_tweet("99"),
                            ],
                            anchor_status_ids=["101", "100", "99"],
                        ),
                    ),
                ]
            }
        )
        sender = base._Sender()
        scheduler = self._create_scheduler(
            self._tag_config(query),
            html_backend=html,
            sender=sender,
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )

        await scheduler.run_check(reason="tag_seed", group_name="tags1")
        result = await scheduler.run_check(reason="tag_page_two", group_name="tags1")

        self.assertEqual(result.new_tweet_count, 1)
        self.assertEqual(sender.sent[-1][3], ["101"])
        self.assertEqual(html.anchor_ids_calls, [None, ["100", "99"]])
        self.assertIn(key, await scheduler.storage.get_group_scan_watermarks("tags1"))

    async def test_incomplete_tag_scan_with_zero_limit_rebuilds_without_sending(self):
        query = "#foo"
        key = self._account_key(query)
        html = _HtmlBackend(
            {
                query: [
                    (
                        "https://search.test",
                        HtmlSearchResult(
                            [self._make_tweet("100")],
                            anchor_status_ids=["100"],
                        ),
                    ),
                    (
                        "https://search.test",
                        HtmlSearchResult(
                            [self._make_tweet("102"), self._make_tweet("101")],
                            scan_complete=False,
                            anchor_status_ids=["102", "101"],
                        ),
                    ),
                ]
            }
        )
        sender = base._Sender()
        scheduler = self._create_scheduler(
            self._tag_config(query),
            html_backend=html,
            sender=sender,
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )

        await scheduler.run_check(reason="tag_seed", group_name="tags1")
        result = await scheduler.run_check(reason="tag_incomplete", group_name="tags1")

        self.assertEqual(result.baseline_rebuilt_users.get(key), 2)
        self.assertEqual(result.new_tweet_count, 0)
        self.assertEqual(sender.sent, [])
        self.assertEqual(
            await scheduler.storage.get_group_scan_watermarks("tags1"),
            {key: ["102", "101"]},
        )
        self.assertIn("102", await scheduler.storage.get_seen_ids("tags1", key))
        self.assertNotIn("本次没有发现需要推送的新推文。", result.format_message())

    async def test_incomplete_tag_scan_with_limit_pushes_then_rebuilds(self):
        query = "#foo"
        key = self._account_key(query)
        config = self._tag_config(query)
        config["tweet_groups"][0]["max_tweets_per_check"] = 1
        html = _HtmlBackend(
            {
                query: [
                    ("https://search.test", [self._make_tweet("100")]),
                    (
                        "https://search.test",
                        HtmlSearchResult(
                            [
                                self._make_tweet("103"),
                                self._make_tweet("102"),
                                self._make_tweet("101"),
                            ],
                            scan_complete=False,
                            anchor_status_ids=["103", "102", "101"],
                        ),
                    ),
                ]
            }
        )
        sender = base._Sender()
        scheduler = self._create_scheduler(config, html_backend=html, sender=sender)
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )

        await scheduler.run_check(reason="tag_seed", group_name="tags1")
        result = await scheduler.run_check(reason="tag_incomplete", group_name="tags1")

        self.assertEqual(result.new_tweet_count, 1)
        self.assertEqual(sender.sent[-1][3], ["103"])
        self.assertEqual(result.baseline_rebuilt_users.get(key), 3)
        self.assertEqual(
            await scheduler.storage.get_group_scan_watermarks("tags1"),
            {key: ["103", "102", "101"]},
        )

    async def test_incomplete_tag_scan_delivery_failure_keeps_old_watermark(self):
        query = "#foo"
        key = self._account_key(query)
        html = _HtmlBackend(
            {
                query: [
                    ("https://search.test", [self._make_tweet("100")]),
                    (
                        "https://search.test",
                        HtmlSearchResult(
                            [self._make_tweet("101")],
                            scan_complete=False,
                            anchor_status_ids=["101"],
                        ),
                    ),
                ]
            }
        )
        sender = base._Sender(success=False)
        config = self._tag_config(query)
        config["tweet_groups"][0]["max_tweets_per_check"] = 1
        scheduler = self._create_scheduler(config, html_backend=html, sender=sender)
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )

        await scheduler.run_check(reason="tag_seed", group_name="tags1")
        result = await scheduler.run_check(
            reason="tag_delivery_failure", group_name="tags1"
        )

        self.assertIn(key, result.baseline_rebuild_failed_users)
        self.assertEqual(
            await scheduler.storage.get_group_scan_watermarks("tags1"),
            {key: ["100"]},
        )
        self.assertNotIn("101", await scheduler.storage.get_seen_ids("tags1", key))

    async def test_incomplete_tag_scan_without_old_watermark_keeps_state(self):
        query = "#foo"
        key = self._account_key(query)
        html = _HtmlBackend(
            {
                query: [
                    (
                        "https://search.test",
                        HtmlSearchResult(
                            [self._make_tweet("101")],
                            scan_complete=False,
                            anchor_status_ids=["101"],
                        ),
                    )
                ]
            }
        )
        scheduler = self._create_scheduler(
            self._tag_config(query),
            html_backend=html,
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )

        result = await scheduler.run_check(
            reason="tag_incomplete_without_watermark", group_name="tags1"
        )

        self.assertEqual(
            result.baseline_rebuild_failed_users.get(key),
            "扫描未完整且没有可用旧扫描基准，保留旧水位",
        )
        self.assertEqual(result.failed_users, {})
        self.assertEqual(result.source_statuses.get(key), "incomplete")
        self.assertEqual(await scheduler.storage.get_group_scan_watermarks("tags1"), {})

    async def test_tag_empty_first_scan_does_not_initialize_seen(self):
        query = "#foo"
        key = self._account_key(query)
        html = _HtmlBackend(
            {
                query: [
                    ("https://search.test", []),
                    (
                        "https://search.test",
                        [self._make_tweet("101")],
                    ),
                ]
            }
        )
        sender = base._Sender()
        scheduler = self._create_scheduler(
            self._tag_config(query),
            html_backend=html,
            sender=sender,
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )

        first = await scheduler.run_check(reason="tag_empty_first", group_name="tags1")
        seen_after_first = await scheduler.storage.get_seen_ids("tags1", key)
        watermarks_after_first = await scheduler.storage.get_group_scan_watermarks(
            "tags1"
        )

        second = await scheduler.run_check(reason="tag_after_empty", group_name="tags1")

        self.assertEqual(first.new_tweet_count, 0)
        self.assertEqual(list(seen_after_first), [])
        self.assertNotIn(key, watermarks_after_first)
        # Empty first must not seal init; non-empty next still initializes without flood.
        self.assertEqual(second.new_tweet_count, 0)
        self.assertEqual(sender.sent, [])
        seen_after_second = await scheduler.storage.get_seen_ids("tags1", key)
        self.assertIn("101", seen_after_second)

    async def test_tag_rt_only_first_scan_writes_empty_watermark(self):
        query = "#foo"
        key = self._account_key(query)
        retweet = self._make_tweet("100", author="other")
        retweet.is_retweet = True
        eligible = self._make_tweet("101", author="author")
        html = _StatsHtmlBackend(
            {
                query: [
                    ("https://search.test", [retweet]),
                    ("https://search.test", [eligible]),
                ]
            }
        )
        sender = base._Sender()
        scheduler = self._create_scheduler(
            self._tag_config(query),
            html_backend=html,
            sender=sender,
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )

        first = await scheduler.run_check(
            reason="tag_rt_only_first", group_name="tags1"
        )
        watermark_after_first = await scheduler.storage.get_group_scan_watermarks(
            "tags1"
        )
        second = await scheduler.run_check(
            reason="tag_after_rt_only", group_name="tags1"
        )

        self.assertEqual(first.new_tweet_count, 0)
        self.assertEqual(first.initialized_users.get(key), 0)
        self.assertEqual(first.failed_users, {})
        self.assertEqual(watermark_after_first, {key: []})
        self.assertEqual(second.new_tweet_count, 1)
        self.assertEqual(sender.sent[-1][3], ["101"])

    async def test_incomplete_scan_with_explicit_empty_watermark_can_rebuild(self):
        query = "#foo"
        key = self._account_key(query)
        retweet = self._make_tweet("100", author="other")
        retweet.is_retweet = True
        html = _StatsHtmlBackend(
            {
                query: [
                    ("https://search.test", [retweet]),
                    (
                        "https://search.test",
                        HtmlSearchResult(
                            [self._make_tweet("102"), self._make_tweet("101")],
                            scan_complete=False,
                            anchor_status_ids=["102", "101"],
                        ),
                    ),
                ]
            }
        )
        scheduler = self._create_scheduler(
            self._tag_config(query),
            html_backend=html,
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )

        await scheduler.run_check(reason="tag_filtered_init", group_name="tags1")
        result = await scheduler.run_check(
            reason="tag_incomplete_after_empty", group_name="tags1"
        )

        self.assertEqual(result.baseline_rebuilt_users.get(key), 2)
        self.assertEqual(result.source_statuses.get(key), "baseline_rebuilt")
        self.assertEqual(
            await scheduler.storage.get_group_scan_watermarks("tags1"),
            {key: ["102", "101"]},
        )

    async def test_tag_group_can_disable_repost_filter(self):
        query = "#foo"
        key = self._account_key(query)
        retweet = self._make_tweet("100", author="other")
        retweet.is_retweet = True
        html = _StatsHtmlBackend({query: [("https://search.test", [retweet])]})
        config = self._tag_config(query)
        config["tweet_groups"][0]["filter_reposts_enabled"] = False
        scheduler = self._create_scheduler(config, html_backend=html)
        group = scheduler._schedule_groups(log_invalid_targets=False)[0]

        result = await scheduler._fetch_group_user(
            group,
            0,
            key,
            20,
            False,
            None,
            concurrent=False,
        )

        self.assertEqual(html.filter_reposts_calls, [False])
        self.assertEqual([tweet.status_id for tweet in result.tweets], ["100"])
        self.assertEqual(result.retweet_filtered, 0)

    async def test_tag_filtered_first_scan_uses_empty_watermark_then_pushes(self):
        query = "#foo"
        key = self._account_key(query)
        filtered = self._make_tweet("100")
        eligible = self._make_tweet("101")
        eligible.media = [TweetMedia(kind="image", url="https://img.test/101.jpg")]
        html = _HtmlBackend(
            {
                query: [
                    ("https://search.test", [filtered]),
                    ("https://search.test", [eligible]),
                ]
            }
        )
        sender = base._Sender()
        filtered_config = self._tag_config(query)
        filtered_config["tweet_groups"][0]["filter_plain_text_enabled"] = True
        scheduler = self._create_scheduler(
            filtered_config,
            html_backend=html,
            sender=sender,
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )

        first = await scheduler.run_check(
            reason="tag_filtered_first", group_name="tags1"
        )
        self.assertEqual(first.new_tweet_count, 0)
        self.assertEqual(first.initialized_users.get(key), 0)
        self.assertEqual(await scheduler.storage.get_seen_ids("tags1", key), [])
        self.assertEqual(
            await scheduler.storage.get_group_scan_watermarks("tags1"),
            {key: []},
        )

        second = await scheduler.run_check(
            reason="tag_filtered_next", group_name="tags1"
        )
        self.assertEqual(second.new_tweet_count, 1)
        self.assertEqual(sender.sent[-1][3], ["101"])
        self.assertIn("101", await scheduler.storage.get_seen_ids("tags1", key))

    async def test_tag_failed_push_does_not_mark_seen(self):
        query = "#foo"
        key = self._account_key(query)
        html = _HtmlBackend(
            {
                query: [
                    ("https://search.test", [self._make_tweet("100")]),
                ]
            }
        )
        sender = base._Sender(success=True)
        scheduler = self._create_scheduler(
            self._tag_config(query),
            html_backend=html,
            sender=sender,
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )

        await scheduler.run_check(reason="tag_init_ok", group_name="tags1")
        seen_init = await scheduler.storage.get_seen_ids("tags1", key)
        self.assertIn("100", seen_init)

        sender.success = False
        html.responses_by_query[query] = [
            ("https://search.test", [self._make_tweet("201"), self._make_tweet("100")]),
        ]
        await scheduler.run_check(reason="tag_fail_send", group_name="tags1")

        seen = await scheduler.storage.get_seen_ids("tags1", key)
        self.assertIn("100", seen)
        self.assertNotIn("201", seen)


if __name__ == "__main__":
    unittest.main()
