from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch


astrbot_module = sys.modules.get("astrbot", types.ModuleType("astrbot"))
astrbot_api_module = sys.modules.get("astrbot.api", types.ModuleType("astrbot.api"))
astrbot_api_all_module = sys.modules.get(
    "astrbot.api.all", types.ModuleType("astrbot.api.all")
)
astrbot_api_event_module = sys.modules.get(
    "astrbot.api.event", types.ModuleType("astrbot.api.event")
)
astrbot_api_message_components_module = sys.modules.get(
    "astrbot.api.message_components",
    types.ModuleType("astrbot.api.message_components"),
)


class _Logger:
    def debug(self, *args, **kwargs):
        pass

    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass


class _MessageChain:
    def __init__(self, components=None):
        self.components = components or []


class _Plain:
    def __init__(self, text=""):
        self.text = text


class _Image:
    @classmethod
    def fromFileSystem(cls, path):
        return cls()


class _Video:
    @classmethod
    def fromFileSystem(cls, path):
        return cls()


class _Node:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.uin = kwargs.get("uin")
        self.name = kwargs.get("name")
        self.content = kwargs.get("content", [])


class _Nodes:
    def __init__(self, *args, **kwargs):
        self.nodes = []


class _At:
    pass


class _Star:
    def __init__(self, context=None):
        self.context = context


class _Filter:
    class PermissionType:
        ADMIN = "admin"

    @staticmethod
    def command(*args, **kwargs):
        def decorator(func):
            return func

        return decorator

    @staticmethod
    def permission_type(*args, **kwargs):
        def decorator(func):
            return func

        return decorator

    @staticmethod
    def on_astrbot_loaded():
        def decorator(func):
            return func

        return decorator


def _register(*args, **kwargs):
    def decorator(cls):
        return cls

    return decorator


astrbot_api_star_module = sys.modules.get(
    "astrbot.api.star", types.ModuleType("astrbot.api.star")
)
astrbot_core_command_module = sys.modules.get(
    "astrbot.core.star.filter.command",
    types.ModuleType("astrbot.core.star.filter.command"),
)
astrbot_core_module = sys.modules.get("astrbot.core", types.ModuleType("astrbot.core"))
astrbot_core_message_module = sys.modules.get(
    "astrbot.core.message", types.ModuleType("astrbot.core.message")
)
astrbot_core_message_components_module = sys.modules.get(
    "astrbot.core.message.components",
    types.ModuleType("astrbot.core.message.components"),
)


astrbot_api_module.logger = _Logger()
astrbot_api_all_module.At = _At
astrbot_api_all_module.AstrBotConfig = dict
astrbot_api_all_module.Context = object
astrbot_api_all_module.MessageChain = _MessageChain
astrbot_api_all_module.Plain = _Plain
astrbot_api_all_module.Star = _Star
astrbot_api_all_module.logger = astrbot_api_module.logger
astrbot_api_event_module.MessageChain = _MessageChain
astrbot_api_event_module.AstrMessageEvent = object
astrbot_api_event_module.filter = _Filter
astrbot_api_message_components_module.Plain = _Plain
astrbot_api_message_components_module.Image = _Image
astrbot_api_message_components_module.Video = _Video
astrbot_api_message_components_module.Node = _Node
astrbot_api_message_components_module.Nodes = _Nodes
astrbot_api_star_module.register = _register
astrbot_core_command_module.GreedyStr = str
astrbot_core_message_components_module.Image = _Image
astrbot_core_message_components_module.Video = _Video
astrbot_core_message_components_module.Node = _Node
astrbot_core_message_components_module.Nodes = _Nodes
astrbot_core_message_components_module.Plain = _Plain
sys.modules["astrbot"] = astrbot_module
sys.modules["astrbot.api"] = astrbot_api_module
sys.modules["astrbot.api.all"] = astrbot_api_all_module
sys.modules["astrbot.api.event"] = astrbot_api_event_module
sys.modules["astrbot.api.message_components"] = astrbot_api_message_components_module
sys.modules["astrbot.api.star"] = astrbot_api_star_module
sys.modules["astrbot.core"] = astrbot_core_module
sys.modules["astrbot.core.message"] = astrbot_core_message_module
sys.modules["astrbot.core.message.components"] = (
    astrbot_core_message_components_module
)
sys.modules["astrbot.core.star.filter.command"] = astrbot_core_command_module

if "rendering.tweets" in sys.modules:
    tweet_rendering_module = sys.modules["rendering.tweets"]
    tweet_rendering_module.Plain = _Plain
    tweet_rendering_module.Image = _Image
    tweet_rendering_module.Video = _Video
    tweet_rendering_module.Node = _Node
    tweet_rendering_module.Nodes = _Nodes


import scheduler as scheduler_module  # noqa: E402
import delivery.telegram as telegram_delivery_module  # noqa: E402
from delivery import PlatformResolver  # noqa: E402
from scheduler import NitterTweetScheduler  # noqa: E402
from delivery import SendAttempt, TweetSender  # noqa: E402
from storage import SQLiteStorage  # noqa: E402
from storage import StorageAdapter  # noqa: E402
from rendering import TweetMessageRenderer  # noqa: E402
from shared import TweetItem, TweetMedia  # noqa: E402


class _Owner:
    async def get_kv_data(self, key, default):
        return default


class _Nitter:
    def __init__(self):
        self.tweets = [
            TweetItem(
                text="old",
                link="https://x.com/NASA/status/100",
                published="",
            ),
            TweetItem(
                text="new",
                link="https://x.com/NASA/status/101",
                published="",
            ),
        ]

    async def fetch_tweets(self, username, limit, skip_plain_text=False):
        return "https://nitter.test", self.tweets[:limit]

    async def fetch_tweets_with_stats(
        self, username, limit, skip_plain_text=False
    ):
        return "https://nitter.test", self.tweets[:limit], 0


class _MultiUserNitter:
    def __init__(self, tweets_by_user, events=None):
        self.tweets_by_user = tweets_by_user
        self.events = events if events is not None else []
        self.concurrent_calls = []

    async def fetch_tweets(self, username, limit, skip_plain_text=False):
        self.events.append(f"fetch:{username}")
        return "https://nitter.test", self.tweets_by_user.get(username, [])[:limit]

    async def fetch_tweets_with_stats(
        self, username, limit, skip_plain_text=False
    ):
        self.events.append(f"fetch:{username}")
        return "https://nitter.test", self.tweets_by_user.get(username, [])[:limit], 0

    async def fetch_tweets_with_stats_from_instances(
        self,
        username,
        limit,
        instances,
        start_index=0,
        skip_plain_text=False,
        retry_attempts=3,
    ):
        self.concurrent_calls.append(
            (username, tuple(instances), start_index, skip_plain_text, retry_attempts)
        )
        self.events.append(f"concurrent_fetch:{username}")
        return "https://concurrent.test", self.tweets_by_user.get(username, [])[:limit], 0


class _PartiallyFailingNitter(_MultiUserNitter):
    def __init__(self, tweets_by_user, failures_by_user, events=None):
        super().__init__(tweets_by_user, events=events)
        self.failures_by_user = failures_by_user

    async def fetch_tweets(self, username, limit, skip_plain_text=False):
        self.events.append(f"fetch:{username}")
        if username in self.failures_by_user:
            raise RuntimeError(self.failures_by_user[username])
        return "https://nitter.test", self.tweets_by_user.get(username, [])[:limit]

    async def fetch_tweets_with_stats(
        self, username, limit, skip_plain_text=False
    ):
        self.events.append(f"fetch:{username}")
        if username in self.failures_by_user:
            raise RuntimeError(self.failures_by_user[username])
        return "https://nitter.test", self.tweets_by_user.get(username, [])[:limit], 0


class _ConcurrentNitter(_MultiUserNitter):
    def __init__(self, tweets_by_user, events=None, failures_by_user=None, filtered=None):
        super().__init__(tweets_by_user, events=events)
        self.failures_by_user = failures_by_user or {}
        self.filtered = filtered or {}
        self.release_first = scheduler_module.asyncio.Event()

    async def fetch_tweets_with_stats_from_instances(
        self,
        username,
        limit,
        instances,
        start_index=0,
        skip_plain_text=False,
        retry_attempts=3,
    ):
        self.concurrent_calls.append(
            (username, tuple(instances), start_index, skip_plain_text, retry_attempts)
        )
        self.events.append(f"concurrent_fetch_start:{username}")
        if username == "NASA":
            await self.release_first.wait()
        else:
            self.release_first.set()
        self.events.append(f"concurrent_fetch_done:{username}")
        if username in self.failures_by_user:
            raise RuntimeError(self.failures_by_user[username])
        return (
            "https://concurrent.test",
            self.tweets_by_user.get(username, [])[:limit],
            self.filtered.get(username, 0),
        )


class _NoConcurrentNitter(_MultiUserNitter):
    async def fetch_tweets_with_stats_from_instances(self, *args, **kwargs):
        raise AssertionError("concurrent fetch should not be used")


class _Media:
    def __init__(self):
        self.attached = 0
        self.moved = 0
        self.cleaned = 0
        self.staged_cleaned = 0

    async def attach_media(self, tweets):
        self.attached += len(tweets)

    async def move_tweets_media_to_staged(self, group_id, username, tweets, interval):
        self.moved += len(tweets)

    def cleanup_after_send(self, tweets):
        self.cleaned += len(tweets)

    def cleanup_expired_staged_media(self, retention_hours, protected_paths=None):
        return None

    def cleanup_staged_media_for_tweets(self, tweets):
        self.staged_cleaned += len(tweets)


class _RecordingMedia(_Media):
    def __init__(self, events):
        super().__init__()
        self.events = events

    async def attach_media(self, tweets):
        self.events.append("media:" + ",".join(tweet.status_id for tweet in tweets))
        for tweet in tweets:
            for media in tweet.media:
                if media.path is None:
                    media.path = Path(f"/tmp/{tweet.status_id}.jpg")
        await super().attach_media(tweets)

    def cleanup_after_send(self, tweets):
        self.events.append("cleanup:" + ",".join(tweet.status_id for tweet in tweets))
        super().cleanup_after_send(tweets)


class _Translator:
    async def attach_translations(self, tweets, target):
        for tweet in tweets:
            tweet.translation = "translated"


class _RecordingTranslator(_Translator):
    def __init__(self, events):
        self.events = events

    async def attach_translations(self, tweets, target):
        self.events.append(
            "translate:" + ",".join(tweet.status_id for tweet in tweets)
        )
        await super().attach_translations(tweets, target)


class _OutOfOrderTranslator(_Translator):
    def __init__(self, events):
        self.events = events
        self.release_first = scheduler_module.asyncio.Event()

    async def attach_translations(self, tweets, target):
        status_id = tweets[0].status_id
        self.events.append(f"translate_start:{status_id}")
        if status_id == "101":
            await self.release_first.wait()
        else:
            self.release_first.set()
        self.events.append(f"translate_done:{status_id}")
        await super().attach_translations(tweets, target)


class _RecordingEnricher:
    def __init__(self, events, fail_status_ids=None):
        self.events = events
        self.fail_status_ids = set(fail_status_ids or [])

    async def attach_enrichments(self, tweets, target):
        status_ids = [tweet.status_id for tweet in tweets]
        self.events.append("enrich:" + ",".join(status_ids))
        failed = self.fail_status_ids.intersection(status_ids)
        if failed:
            raise RuntimeError(f"enrich failed: {','.join(sorted(failed))}")
        for tweet in tweets:
            tweet.ai_comment = "comment"
        return types.SimpleNamespace(visible_notices=lambda: [])


class _Sender:
    def __init__(
        self,
        success=True,
        failed_targets=None,
        merge_targets=None,
        events=None,
    ):
        self.sent = []
        self.merged_sent = []
        self.group_labels = []
        self.merged_group_labels = []
        self.headers = []
        self.summary_sends = []
        self.batch_summaries = []
        self.merged_batch_summaries = []
        self.tweet_start_indexes = []
        self.success = success
        self.failed_targets = set(failed_targets or [])
        self.merge_targets = set(merge_targets or [])
        self.events = events if events is not None else []

    def supports_merged_forward_for_umo(self, context, umo):
        return umo in self.merge_targets

    async def send_summary_to_umo(self, context, umo, summary):
        del context
        self.summary_sends.append((umo, summary))
        success = self.success and umo not in self.failed_targets
        return types.SimpleNamespace(
            success=success,
            warning="",
            error="" if success else "send failed",
        )

    async def send_to_umo_with_outcome(
        self,
        context,
        umo,
        username,
        instance,
        tweets,
        group_label="",
        header_text="",
        batch_summary="",
        tweet_start_index=1,
    ):
        self.events.append(f"send:{umo}:{username}")
        self.sent.append((umo, username, instance, [tweet.status_id for tweet in tweets]))
        self.group_labels.append((umo, username, group_label))
        self.headers.append((umo, username, header_text))
        self.batch_summaries.append((umo, username, batch_summary))
        self.tweet_start_indexes.append((umo, username, tweet_start_index))
        success = self.success and umo not in self.failed_targets
        return types.SimpleNamespace(success=success, warning="")

    async def send_merged_to_umo(
        self, context, umo, batches, group_label="", batch_summary=""
    ):
        self.events.append(f"merged:{umo}")
        self.merged_sent.append(
            (
                umo,
                [
                    (username, instance, [tweet.status_id for tweet in tweets])
                    for username, instance, tweets in batches
                ],
            )
        )
        self.merged_group_labels.append((umo, group_label))
        self.merged_batch_summaries.append((umo, batch_summary))
        success = self.success and umo not in self.failed_targets
        return types.SimpleNamespace(
            success=success,
            warning="",
            error="" if success else "send failed",
            mode="full_forward",
        )


class _CancelingSender(_Sender):
    async def send_to_umo_with_outcome(
        self,
        context,
        umo,
        username,
        instance,
        tweets,
        group_label="",
        header_text="",
        batch_summary="",
        tweet_start_index=1,
    ):
        self.events.append(f"cancel:{umo}:{username}")
        raise scheduler_module.asyncio.CancelledError()


class _RecordingSender(_Sender):
    async def send_to_umo_with_outcome(
        self,
        context,
        umo,
        username,
        instance,
        tweets,
        group_label="",
        header_text="",
        batch_summary="",
        tweet_start_index=1,
    ):
        status_ids = ",".join(tweet.status_id for tweet in tweets)
        self.events.append(f"send:{umo}:{username}:{status_ids}")
        self.sent.append((umo, username, instance, [tweet.status_id for tweet in tweets]))
        self.group_labels.append((umo, username, group_label))
        self.headers.append((umo, username, header_text))
        self.batch_summaries.append((umo, username, batch_summary))
        self.tweet_start_indexes.append((umo, username, tweet_start_index))
        success = self.success and umo not in self.failed_targets
        return types.SimpleNamespace(success=success, warning="")


class DeferredSchedulerTest(unittest.IsolatedAsyncioTestCase):
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

    def _create_scheduler(
        self,
        config,
        *,
        nitter=None,
        media=None,
        sender=None,
        translator=None,
        enricher=None,
    ):
        scheduler = NitterTweetScheduler(
            _Owner(),
            context=None,
            config=config,
            nitter=nitter or _Nitter(),
            media=media or _Media(),
            sender=sender or _Sender(),
            translator=translator or _Translator(),
            enricher=enricher,
        )
        self.schedulers.append(scheduler)
        return scheduler

    async def test_global_schedule_switch_gates_group_interval_and_daily_checks(self):
        config = {
            "schedule_enabled": False,
            "tweet_groups": [
                {
                    "name": "Tech",
                    "group_id": "tech",
                    "enabled": True,
                    "watch_users": ["NASA"],
                    "push_targets": ["telegram:FriendMessage:1"],
                    "interval_check_enabled": True,
                    "daily_check_times": ["08:00"],
                }
            ],
        }
        scheduler = self._create_scheduler(config)
        scheduler._migration_done = True

        async def cancel_after_first_loop_sleep(_seconds):
            nonlocal sleep_calls
            sleep_calls += 1
            if sleep_calls >= 2:
                raise scheduler_module.asyncio.CancelledError()

        scheduler._tick = AsyncMock()
        sleep_calls = 0
        with patch.object(
            scheduler_module.asyncio,
            "sleep",
            side_effect=cancel_after_first_loop_sleep,
        ):
            with self.assertRaises(scheduler_module.asyncio.CancelledError):
                await scheduler._loop()
        scheduler._tick.assert_not_awaited()

        config["schedule_enabled"] = True
        scheduler._tick = AsyncMock()
        sleep_calls = 0
        with patch.object(
            scheduler_module.asyncio,
            "sleep",
            side_effect=cancel_after_first_loop_sleep,
        ):
            with self.assertRaises(scheduler_module.asyncio.CancelledError):
                await scheduler._loop()
        scheduler._tick.assert_awaited_once()

    async def test_check_result_seen_count_refreshes_after_initialization(self):
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "watch_users": ["NASA"],
                "push_targets": ["telegram:FriendMessage:1"],
                "scheduled_fetch_limit": 2,
            }
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )

        result = await scheduler.run_check(reason="test_initial_seen_count")

        self.assertEqual(result.initialized_users, {"NASA": 2})
        self.assertEqual(result.seen_users, 1)
        self.assertIn("已记录账号索引: 1 个", result.format_message())

    async def test_plain_text_filtered_count_surfaces_in_brief_summary(self):
        nitter = _Nitter()
        nitter.tweets = [
            TweetItem(
                text="new",
                link="https://x.com/NASA/status/101",
                published="",
            )
        ]

        async def fetch_tweets_with_stats(username, limit, skip_plain_text=False):
            return "https://nitter.test", nitter.tweets[:limit], 3

        nitter.fetch_tweets_with_stats = fetch_tweets_with_stats

        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "watch_users": ["NASA"],
                "push_targets": ["telegram:FriendMessage:1"],
                "scheduled_fetch_limit": 1,
                "tweet_groups": [
                    {
                        "name": "Default",
                        "group_id": "global",
                        "filter_plain_text_enabled": True,
                        "watch_users": ["NASA"],
                        "push_targets": ["telegram:FriendMessage:1"],
                    }
                ],
            },
            nitter=nitter,
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )

        result = await scheduler.run_check(reason="test_plain_text_filter")

        self.assertEqual(result.plain_text_filtered, 3)
        self.assertIn("filtered=3", result.format_log_summary())
        self.assertIn("filtered=3", result.format_brief_log_lines()[0])

    async def test_scheduler_ignores_unseen_tweets_older_than_seen_watermark(self):
        sender = _Sender()
        nitter = _MultiUserNitter(
            {
                "NASA": [
                    self._make_tweet("NASA", "200"),
                    self._make_tweet("NASA", "150"),
                ],
            }
        )
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "watch_users": ["NASA"],
                "push_targets": ["telegram:FriendMessage:1"],
                "scheduled_fetch_limit": 2,
            },
            nitter=nitter,
            sender=sender,
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )
        await scheduler.storage.add_seen_ids("global", "NASA", ["200"])

        result = await scheduler.run_check(reason="test_seen_watermark_older")
        seen_ids = await scheduler.storage.get_seen_ids("global", "NASA")

        self.assertEqual(result.new_tweet_count, 0)
        self.assertEqual(sender.sent, [])
        self.assertIn("NASA", result.no_new_users)
        self.assertIn("150", seen_ids)
        self.assertIn("200", seen_ids)

    async def test_scheduler_sends_only_unseen_tweets_newer_than_seen_watermark(self):
        sender = _Sender()
        nitter = _MultiUserNitter(
            {
                "NASA": [
                    self._make_tweet("NASA", "201"),
                    self._make_tweet("NASA", "150"),
                    self._make_tweet("NASA", "200"),
                ],
            }
        )
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "watch_users": ["NASA"],
                "push_targets": ["telegram:FriendMessage:1"],
                "scheduled_fetch_limit": 3,
            },
            nitter=nitter,
            sender=sender,
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )
        await scheduler.storage.add_seen_ids("global", "NASA", ["200"])

        result = await scheduler.run_check(reason="test_seen_watermark_mixed")
        seen_ids = await scheduler.storage.get_seen_ids("global", "NASA")

        self.assertEqual(result.new_tweet_count, 1)
        self.assertEqual(
            sender.sent,
            [
                (
                    "telegram:FriendMessage:1",
                    "NASA",
                    "https://nitter.test",
                    ["201"],
                )
            ],
        )
        self.assertIn("150", seen_ids)
        self.assertIn("201", seen_ids)

    async def test_successful_scheduled_push_records_history(self):
        sender = _Sender()
        nitter = _MultiUserNitter(
            {
                "NASA": [
                    self._make_tweet("NASA", "201"),
                ],
            }
        )
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "watch_users": ["NASA"],
                "push_targets": ["telegram:FriendMessage:1"],
                "scheduled_fetch_limit": 1,
            },
            nitter=nitter,
            sender=sender,
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )
        await scheduler.storage.add_seen_ids("global", "NASA", ["100"])

        result = await scheduler.run_check(reason="test_history")
        records = await scheduler.storage.get_push_history()

        self.assertEqual(result.pushed_target_successes, 1)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].group_id, "default")
        self.assertEqual(records[0].username, "NASA")
        self.assertEqual(records[0].status_id, "201")
        self.assertEqual(records[0].target_umo, "telegram:FriendMessage:1")
        self.assertEqual(records[0].source, "scheduled")

    async def test_failed_scheduled_push_does_not_record_history(self):
        sender = _Sender(success=False)
        nitter = _MultiUserNitter(
            {
                "NASA": [
                    self._make_tweet("NASA", "201"),
                ],
            }
        )
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "watch_users": ["NASA"],
                "push_targets": ["telegram:FriendMessage:1"],
                "scheduled_fetch_limit": 1,
            },
            nitter=nitter,
            sender=sender,
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )
        await scheduler.storage.add_seen_ids("global", "NASA", ["100"])

        await scheduler.run_check(reason="test_history_fail")
        records = await scheduler.storage.get_push_history()

        self.assertEqual(records, [])

    async def test_concurrent_fetch_requires_enabled_pool_and_parallelism(self):
        events = []
        nitter = _NoConcurrentNitter(
            {
                "NASA": [
                    self._make_tweet("NASA", "100"),
                    self._make_tweet("NASA", "101"),
                ]
            },
            events=events,
        )
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "watch_users": ["NASA"],
                "push_targets": ["telegram:FriendMessage:1"],
                "scheduled_fetch_limit": 2,
                "concurrent_fetch_enabled": True,
                "fetch_concurrency": 3,
                "concurrent_fetch_instances": [],
            },
            nitter=nitter,
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )
        await scheduler.storage.add_seen_ids("global", "NASA", ["100"])

        result = await scheduler.run_check(reason="test_concurrent_fetch_disabled")

        self.assertEqual(events[0], "fetch:NASA")
        self.assertEqual(result.new_tweet_count, 1)

    async def test_concurrent_fetch_preserves_watch_user_order_after_out_of_order_fetch(self):
        events = []
        media = _Media()
        sender = _RecordingSender(events=events)
        nitter = _ConcurrentNitter(
            {
                "NASA": [
                    self._make_tweet("NASA", "100"),
                    self._make_tweet("NASA", "101"),
                ],
                "ESA": [
                    self._make_tweet("ESA", "200"),
                    self._make_tweet("ESA", "201"),
                ],
                "OpenAI": [
                    self._make_tweet("OpenAI", "300"),
                    self._make_tweet("OpenAI", "301"),
                ],
            },
            events=events,
            filtered={"NASA": 1, "ESA": 2},
        )
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "watch_users": ["NASA", "ESA", "OpenAI"],
                "push_targets": ["telegram:FriendMessage:1"],
                "scheduled_fetch_limit": 2,
                "tweet_groups": [
                    {
                        "name": "Default",
                        "group_id": "global",
                        "filter_plain_text_enabled": True,
                        "watch_users": ["NASA", "ESA", "OpenAI"],
                        "push_targets": ["telegram:FriendMessage:1"],
                    }
                ],
                "concurrent_fetch_enabled": True,
                "fetch_concurrency": 3,
                "concurrent_fetch_instances": [
                    "https://mirror-a.example",
                    "https://mirror-b.example",
                ],
            },
            nitter=nitter,
            media=media,
            sender=sender,
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )
        await scheduler.storage.add_seen_ids("global", "NASA", ["100"])
        await scheduler.storage.add_seen_ids("global", "ESA", ["200"])
        await scheduler.storage.add_seen_ids("global", "OpenAI", ["300"])

        result = await scheduler.run_check(reason="test_concurrent_fetch_order")

        self.assertEqual(result.plain_text_filtered, 3)
        self.assertEqual(
            [item[1] for item in sender.sent],
            ["NASA", "ESA", "OpenAI"],
        )
        self.assertEqual(
            [call[:4] for call in nitter.concurrent_calls],
            [
                (
                    "NASA",
                    ("https://mirror-a.example", "https://mirror-b.example"),
                    0,
                    True,
                ),
                (
                    "ESA",
                    ("https://mirror-a.example", "https://mirror-b.example"),
                    1,
                    True,
                ),
                (
                    "OpenAI",
                    ("https://mirror-a.example", "https://mirror-b.example"),
                    2,
                    True,
                ),
            ],
        )
        self.assertTrue(
            events.index("concurrent_fetch_done:ESA")
            < events.index("concurrent_fetch_done:NASA")
        )

    async def test_concurrent_fetch_records_failures_in_watch_user_order(self):
        events = []
        nitter = _ConcurrentNitter(
            {
                "NASA": [
                    self._make_tweet("NASA", "100"),
                    self._make_tweet("NASA", "101"),
                ],
                "ESA": [self._make_tweet("ESA", "200")],
                "OpenAI": [
                    self._make_tweet("OpenAI", "300"),
                    self._make_tweet("OpenAI", "301"),
                ],
            },
            events=events,
            failures_by_user={"ESA": "RSS down"},
        )
        sender = _Sender(events=events)
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "watch_users": ["NASA", "ESA", "OpenAI"],
                "push_targets": ["telegram:FriendMessage:1"],
                "scheduled_fetch_limit": 2,
                "concurrent_fetch_enabled": True,
                "fetch_concurrency": 3,
                "concurrent_fetch_instances": [
                    "https://mirror-a.example",
                    "https://mirror-b.example",
                ],
            },
            nitter=nitter,
            sender=sender,
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )
        await scheduler.storage.add_seen_ids("global", "NASA", ["100"])
        await scheduler.storage.add_seen_ids("global", "ESA", ["200"])
        await scheduler.storage.add_seen_ids("global", "OpenAI", ["300"])

        result = await scheduler.run_check(reason="test_concurrent_fetch_failure")

        self.assertEqual(list(result.failed_users), ["ESA"])
        self.assertEqual(
            [item[1] for item in sender.sent],
            ["NASA", "OpenAI"],
        )

    async def _create_scheduler_with_deferred_publish_enabled(
        self,
        push_targets=None,
        *,
        media=None,
        sender=None,
        watch_users=None,
        extra_config=None,
    ):
        config = {
            "schedule_enabled": True,
            "watch_users": watch_users or ["NASA"],
            "push_targets": (
                ["aiocqhttp:GroupMessage:1"]
                if push_targets is None
                else push_targets
            ),
            "deferred_publish_enabled": True,
            "deferred_publish_times": ["08:00"],
        }
        if extra_config:
            config.update(extra_config)
        scheduler = self._create_scheduler(config, media=media, sender=sender)
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )
        return scheduler

    @staticmethod
    def _make_tweet(username, status_id):
        return TweetItem(
            text=f"queued {status_id}",
            link=f"https://x.com/{username}/status/{status_id}",
            published="",
        )

    def test_merged_header_aggregates_repeated_account_batches(self):
        header = TweetMessageRenderer.format_merged_header(
            [
                ("NASA", "https://nitter.test", [self._make_tweet("NASA", "101")]),
                ("NASA", "https://nitter.test", [self._make_tweet("NASA", "102")]),
                (
                    "OpenAI",
                    "https://nitter.test",
                    [self._make_tweet("OpenAI", "201")],
                ),
            ]
        )

        self.assertIn("Nitter 本次检查发现 3 条新推文", header)
        self.assertIn("更新账号：@NASA 2 条，@OpenAI 1 条", header)

    def test_tweet_headers_include_group_label(self):
        header = TweetMessageRenderer.format_header(
            "NASA", "https://nitter.test", 1, group_label="Tech"
        )
        merged_header = TweetMessageRenderer.format_merged_header(
            [
                ("NASA", "https://nitter.test", [self._make_tweet("NASA", "101")]),
            ],
            group_label="Tech",
        )

        self.assertIn("分组：Tech", header)
        self.assertIn("分组：Tech", merged_header)

    def test_plain_tweet_body_uses_start_index_and_source(self):
        header = TweetMessageRenderer.format_header(
            "NASA", "https://nitter.test", 1, group_label="Tech"
        )
        text = TweetMessageRenderer().format_plain(
            "NASA",
            "https://nitter.test",
            [self._make_tweet("NASA", "101")],
            start_index=5,
        )

        self.assertNotIn("nitter.test", header)
        self.assertIn("#5 @NASA", text)
        self.assertIn("nitter.test", text)

    def test_tweet_rendering_omits_image_caption_block(self):
        tweet = self._make_tweet("NASA", "101")
        tweet.image_caption = "一张火箭照片"
        tweet.ai_comment = "发射任务值得关注。"

        text = TweetMessageRenderer().format_tweet(1, "NASA", tweet)

        self.assertNotIn("识图：", text)
        self.assertNotIn("一张火箭照片", text)
        self.assertIn("评论：\n发射任务值得关注。", text)

    async def test_immediate_single_tweet_push_uses_new_tweet_progress_header(self):
        media = _Media()
        sender = _Sender()
        nitter = _MultiUserNitter(
            {
                "NASA": [
                    self._make_tweet("NASA", "100"),
                    self._make_tweet("NASA", "101"),
                    self._make_tweet("NASA", "102"),
                ],
            },
        )
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "watch_users": ["NASA"],
                "push_targets": ["telegram:FriendMessage:1"],
                "scheduled_fetch_limit": 3,
            },
            nitter=nitter,
            media=media,
            sender=sender,
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )
        await scheduler.storage.add_seen_ids("global", "NASA", ["100"])

        result = await scheduler.run_check(reason="test_new_tweet_headers")

        self.assertEqual(result.new_tweet_count, 2)
        self.assertEqual(
            sender.headers,
            [
                (
                    "telegram:FriendMessage:1",
                    "NASA",
                    "@NASA 新推文\n所有账号：1/1\n该账号推文：1/2",
                ),
                (
                    "telegram:FriendMessage:1",
                    "NASA",
                    "@NASA 新推文\n所有账号：1/1\n该账号推文：2/2",
                ),
            ],
        )
        self.assertNotIn("最近 1 条推文", "\n".join(item[2] for item in sender.headers))

        self.assertEqual(
            sender.tweet_start_indexes,
            [
                ("telegram:FriendMessage:1", "NASA", 1),
                ("telegram:FriendMessage:1", "NASA", 2),
            ],
        )

    async def _enqueue_deferred_tweets(self, scheduler, tweets_by_user):
        for username, tweets in tweets_by_user.items():
            await scheduler.storage.enqueue_pending_tweets(
                "global", username, "https://nitter.test", tweets
            )

    async def test_ordinary_targets_send_after_update_discovery(self):
        events = []
        media = _Media()
        sender = _Sender(events=events)
        nitter = _MultiUserNitter(
            {
                "NASA": [
                    self._make_tweet("NASA", "100"),
                    self._make_tweet("NASA", "101"),
                ],
                "ESA": [
                    self._make_tweet("ESA", "300"),
                ],
                "NASAHubble": [
                    self._make_tweet("NASAHubble", "200"),
                    self._make_tweet("NASAHubble", "201"),
                ],
            },
            events=events,
        )
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "watch_users": ["NASA", "ESA", "NASAHubble"],
                "push_targets": ["telegram:FriendMessage:1"],
                "scheduled_fetch_limit": 2,
                "send_user_interval": 0.25,
            },
            nitter=nitter,
            media=media,
            sender=sender,
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )
        await scheduler.storage.add_seen_ids("global", "NASA", ["100"])
        await scheduler.storage.add_seen_ids("global", "ESA", ["300"])
        await scheduler.storage.add_seen_ids("global", "NASAHubble", ["200"])

        sleep_calls = []

        async def fake_sleep(seconds):
            sleep_calls.append(seconds)

        with patch.object(scheduler_module.asyncio, "sleep", fake_sleep):
            result = await scheduler.run_check(reason="test_immediate_ordinary")

        self.assertEqual(
            events,
            [
                "fetch:NASA",
                "fetch:ESA",
                "fetch:NASAHubble",
                "send:telegram:FriendMessage:1:NASA",
                "send:telegram:FriendMessage:1:NASAHubble",
            ],
        )
        self.assertEqual(result.push_mode, "per_user")
        self.assertEqual(result.new_tweet_count, 2)
        self.assertEqual(result.pushed_target_successes, 2)
        self.assertEqual(result.pushed_target_attempts, 2)
        self.assertEqual(media.cleaned, 2)
        self.assertEqual(sleep_calls, [0.25])
        self.assertEqual(
            sender.headers,
            [
                (
                    "telegram:FriendMessage:1",
                    "NASA",
                    "@NASA 新推文\n所有账号：1/2\n该账号推文：1/1",
                ),
                (
                    "telegram:FriendMessage:1",
                    "NASAHubble",
                    "@NASAHubble 新推文\n所有账号：2/2\n该账号推文：1/1",
                ),
            ],
        )

    async def test_target_override_limits_scheduled_check_targets(self):
        events = []
        media = _Media()
        sender = _Sender(events=events)
        nitter = _MultiUserNitter(
            {
                "NASA": [
                    self._make_tweet("NASA", "100"),
                    self._make_tweet("NASA", "101"),
                ],
            },
            events=events,
        )
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "watch_users": ["NASA"],
                "push_targets": [
                    "telegram:FriendMessage:1",
                    "telegram:FriendMessage:2",
                ],
                "scheduled_fetch_limit": 2,
            },
            nitter=nitter,
            media=media,
            sender=sender,
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )
        await scheduler.storage.add_seen_ids("global", "NASA", ["100"])

        result = await scheduler.run_check(
            reason="test_target_override",
            target_override=["telegram:FriendMessage:2"],
        )

        self.assertEqual(result.targets, ["telegram:FriendMessage:2"])
        self.assertEqual(
            events,
            [
                "fetch:NASA",
                "send:telegram:FriendMessage:2:NASA",
            ],
        )
        self.assertEqual(
            sender.sent,
            [
                (
                    "telegram:FriendMessage:2",
                    "NASA",
                    "https://nitter.test",
                    ["101"],
                )
            ],
        )
        self.assertEqual(result.new_tweet_count, 1)
        self.assertEqual(result.pushed_target_successes, 1)
        self.assertEqual(result.pushed_target_attempts, 1)
        self.assertEqual(media.cleaned, 1)

    async def test_force_immediate_bypasses_deferred_queue_for_override_target(self):
        events = []
        media = _Media()
        sender = _Sender(events=events)
        nitter = _MultiUserNitter(
            {
                "NASA": [
                    self._make_tweet("NASA", "100"),
                    self._make_tweet("NASA", "101"),
                ],
            },
            events=events,
        )
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "watch_users": ["NASA"],
                "push_targets": [
                    "telegram:FriendMessage:1",
                    "telegram:FriendMessage:2",
                ],
                "scheduled_fetch_limit": 2,
                "deferred_publish_enabled": True,
                "deferred_publish_times": ["08:00"],
            },
            nitter=nitter,
            media=media,
            sender=sender,
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )
        await scheduler.storage.add_seen_ids("global", "NASA", ["100"])

        result = await scheduler.run_check(
            reason="test_force_immediate",
            target_override=["telegram:FriendMessage:2"],
            force_immediate=True,
        )
        summary = await scheduler.storage.get_pending_queue_summary("global")

        self.assertEqual(result.targets, ["telegram:FriendMessage:2"])
        self.assertEqual(result.push_mode, "per_user")
        self.assertEqual(result.new_tweet_count, 1)
        self.assertEqual(summary.pending_count, 0)
        self.assertEqual(
            events,
            [
                "fetch:NASA",
                "send:telegram:FriendMessage:2:NASA",
            ],
        )
        self.assertEqual(
            sender.sent,
            [
                (
                    "telegram:FriendMessage:2",
                    "NASA",
                    "https://nitter.test",
                    ["101"],
                )
            ],
        )
        self.assertEqual(media.attached, 1)
        self.assertEqual(media.moved, 0)
        self.assertEqual(media.cleaned, 1)

    async def test_custom_group_label_is_passed_to_ordinary_push(self):
        sender = _Sender()
        nitter = _MultiUserNitter(
            {
                "OpenAI": [
                    self._make_tweet("OpenAI", "100"),
                    self._make_tweet("OpenAI", "101"),
                ],
            }
        )
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "watch_users": [],
                "push_targets": [],
                "tweet_groups": [
                    {
                        "name": "Tech",
                        "group_id": "tech",
                        "watch_users": ["OpenAI"],
                        "push_targets": ["telegram:FriendMessage:1"],
                        "scheduled_fetch_limit": 2,
                    }
                ],
            },
            nitter=nitter,
            sender=sender,
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )
        await scheduler.storage.add_seen_ids("tech", "OpenAI", ["100"])

        result = await scheduler.run_check(reason="test_group_label", group_name="tech")

        self.assertEqual(result.new_tweet_count, 1)
        self.assertEqual(
            sender.group_labels,
            [("telegram:FriendMessage:1", "OpenAI", "Tech")],
        )

    async def test_custom_group_label_is_passed_to_merged_push(self):
        sender = _Sender(merge_targets={"aiocqhttp:GroupMessage:1"})
        nitter = _MultiUserNitter(
            {
                "OpenAI": [
                    self._make_tweet("OpenAI", "100"),
                    self._make_tweet("OpenAI", "101"),
                ],
            }
        )
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "watch_users": [],
                "push_targets": [],
                "merge_tweet_threshold": 1,
                "tweet_groups": [
                    {
                        "name": "Tech",
                        "group_id": "tech",
                        "watch_users": ["OpenAI"],
                        "push_targets": ["aiocqhttp:GroupMessage:1"],
                        "scheduled_fetch_limit": 2,
                    }
                ],
            },
            nitter=nitter,
            sender=sender,
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )
        await scheduler.storage.add_seen_ids("tech", "OpenAI", ["100"])

        result = await scheduler.run_check(
            reason="test_merged_group_label", group_name="tech"
        )

        self.assertEqual(result.push_mode, "merged")
        self.assertEqual(sender.group_labels, [])
        self.assertEqual(
            sender.merged_group_labels,
            [("aiocqhttp:GroupMessage:1", "Tech")],
        )

    async def test_immediate_ordinary_sends_each_tweet_after_ai_prepare(self):
        events = []
        media = _RecordingMedia(events)
        sender = _RecordingSender(events=events)
        nitter = _MultiUserNitter(
            {
                "NASA": [
                    self._make_tweet("NASA", "102"),
                    self._make_tweet("NASA", "101"),
                    self._make_tweet("NASA", "100"),
                ],
            },
            events=events,
        )
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "watch_users": ["NASA"],
                "push_targets": ["telegram:FriendMessage:1"],
                "scheduled_fetch_limit": 3,
            },
            nitter=nitter,
            media=media,
            sender=sender,
            translator=_RecordingTranslator(events),
            enricher=_RecordingEnricher(events),
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )
        await scheduler.storage.add_seen_ids("global", "NASA", ["100"])

        result = await scheduler.run_check(reason="test_per_tweet_immediate")

        self.assertEqual(
            events,
            [
                "fetch:NASA",
                "translate:101",
                "media:101",
                "enrich:101",
                "send:telegram:FriendMessage:1:NASA:101",
                "cleanup:101",
                "translate:102",
                "media:102",
                "enrich:102",
                "send:telegram:FriendMessage:1:NASA:102",
                "cleanup:102",
            ],
        )
        self.assertEqual(result.new_tweet_count, 2)
        self.assertEqual(
            sender.sent,
            [
                (
                    "telegram:FriendMessage:1",
                    "NASA",
                    "https://nitter.test",
                    ["101"],
                ),
                (
                    "telegram:FriendMessage:1",
                    "NASA",
                    "https://nitter.test",
                    ["102"],
                ),
            ],
        )
        self.assertEqual(media.cleaned, 2)

    async def test_concurrent_prepare_preserves_send_order_after_out_of_order_prepare(self):
        events = []
        media = _RecordingMedia(events)
        sender = _RecordingSender(events=events)
        nitter = _MultiUserNitter(
            {
                "NASA": [
                    self._make_tweet("NASA", "102"),
                    self._make_tweet("NASA", "101"),
                    self._make_tweet("NASA", "100"),
                ],
            },
            events=events,
        )
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "watch_users": ["NASA"],
                "push_targets": ["telegram:FriendMessage:1"],
                "scheduled_fetch_limit": 3,
                "concurrent_prepare_enabled": True,
                "prepare_concurrency": 2,
            },
            nitter=nitter,
            media=media,
            sender=sender,
            translator=_OutOfOrderTranslator(events),
            enricher=_RecordingEnricher(events),
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )
        await scheduler.storage.add_seen_ids("global", "NASA", ["100"])

        result = await scheduler.run_check(reason="test_concurrent_prepare_order")

        self.assertEqual(result.new_tweet_count, 2)
        self.assertTrue(
            events.index("translate_done:102")
            < events.index("translate_done:101")
        )
        self.assertEqual(
            sender.sent,
            [
                (
                    "telegram:FriendMessage:1",
                    "NASA",
                    "https://nitter.test",
                    ["101"],
                ),
                (
                    "telegram:FriendMessage:1",
                    "NASA",
                    "https://nitter.test",
                    ["102"],
                ),
            ],
        )

    async def test_immediate_per_tweet_prepare_failure_does_not_mark_seen(self):
        events = []
        media = _RecordingMedia(events)
        sender = _RecordingSender(events=events)
        nitter = _MultiUserNitter(
            {
                "NASA": [
                    self._make_tweet("NASA", "102"),
                    self._make_tweet("NASA", "101"),
                    self._make_tweet("NASA", "100"),
                ],
            },
            events=events,
        )
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "watch_users": ["NASA"],
                "push_targets": ["telegram:FriendMessage:1"],
                "scheduled_fetch_limit": 3,
            },
            nitter=nitter,
            media=media,
            sender=sender,
            translator=_RecordingTranslator(events),
            enricher=_RecordingEnricher(events, fail_status_ids={"102"}),
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )
        await scheduler.storage.add_seen_ids("global", "NASA", ["100"])

        result = await scheduler.run_check(reason="test_per_tweet_seen_failure")
        seen_ids = await scheduler.storage.get_seen_ids("global", "NASA")

        self.assertEqual(result.new_tweet_count, 1)
        self.assertIn("NASA:102", result.failed_users)
        self.assertIn("101", seen_ids)
        self.assertIn("100", seen_ids)
        self.assertNotIn("102", seen_ids)
        self.assertEqual(
            sender.sent,
            [
                (
                    "telegram:FriendMessage:1",
                    "NASA",
                    "https://nitter.test",
                    ["101"],
                )
            ],
        )

    async def test_concurrent_prepare_failure_does_not_mark_seen(self):
        events = []
        media = _RecordingMedia(events)
        sender = _RecordingSender(events=events)
        nitter = _MultiUserNitter(
            {
                "NASA": [
                    self._make_tweet("NASA", "102"),
                    self._make_tweet("NASA", "101"),
                    self._make_tweet("NASA", "100"),
                ],
            },
            events=events,
        )
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "watch_users": ["NASA"],
                "push_targets": ["telegram:FriendMessage:1"],
                "scheduled_fetch_limit": 3,
                "concurrent_prepare_enabled": True,
                "prepare_concurrency": 2,
            },
            nitter=nitter,
            media=media,
            sender=sender,
            translator=_RecordingTranslator(events),
            enricher=_RecordingEnricher(events, fail_status_ids={"102"}),
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )
        await scheduler.storage.add_seen_ids("global", "NASA", ["100"])

        result = await scheduler.run_check(reason="test_concurrent_prepare_failure")
        seen_ids = await scheduler.storage.get_seen_ids("global", "NASA")

        self.assertEqual(result.new_tweet_count, 1)
        self.assertIn("NASA:102", result.failed_users)
        self.assertIn("101", seen_ids)
        self.assertNotIn("102", seen_ids)
        self.assertEqual(
            sender.sent,
            [
                (
                    "telegram:FriendMessage:1",
                    "NASA",
                    "https://nitter.test",
                    ["101"],
                )
            ],
        )

    async def test_ordinary_targets_send_per_account_but_qq_merges_at_end(self):
        events = []
        media = _Media()
        sender = _Sender(
            merge_targets={"aiocqhttp:GroupMessage:1"},
            events=events,
        )
        nitter = _MultiUserNitter(
            {
                "NASA": [
                    self._make_tweet("NASA", "100"),
                    self._make_tweet("NASA", "101"),
                ],
                "NASAHubble": [
                    self._make_tweet("NASAHubble", "200"),
                    self._make_tweet("NASAHubble", "201"),
                ],
            },
            events=events,
        )
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "watch_users": ["NASA", "NASAHubble"],
                "push_targets": [
                    "telegram:FriendMessage:1",
                    "aiocqhttp:GroupMessage:1",
                ],
                "scheduled_fetch_limit": 2,
                "merge_tweet_threshold": 2,
            },
            nitter=nitter,
            media=media,
            sender=sender,
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )
        await scheduler.storage.add_seen_ids("global", "NASA", ["100"])
        await scheduler.storage.add_seen_ids("global", "NASAHubble", ["200"])

        result = await scheduler.run_check(reason="test_immediate_mixed_merge")

        self.assertEqual(
            events,
            [
                "fetch:NASA",
                "fetch:NASAHubble",
                "send:telegram:FriendMessage:1:NASA",
                "send:telegram:FriendMessage:1:NASAHubble",
                "merged:aiocqhttp:GroupMessage:1",
            ],
        )
        self.assertEqual(result.push_mode, "mixed")
        self.assertEqual(result.new_tweet_count, 2)
        self.assertEqual(result.pushed_target_successes, 3)
        self.assertEqual(result.pushed_target_attempts, 3)
        self.assertEqual(
            sender.merged_sent,
            [
                (
                    "aiocqhttp:GroupMessage:1",
                    [
                        ("NASA", "https://nitter.test", ["101"]),
                        ("NASAHubble", "https://nitter.test", ["201"]),
                    ],
                )
            ],
        )
        self.assertEqual(media.cleaned, 2)
        self.assertEqual(len(sender.merged_batch_summaries), 1)
        merged_summary = sender.merged_batch_summaries[0][1]
        self.assertIn("Nitter 本次检查发现 2 条新推文", merged_summary)
        self.assertIn("分组：默认分组", merged_summary)
        self.assertIn("更新账号：@NASA 1 条，@NASAHubble 1 条", merged_summary)

    async def test_merged_batch_summary_includes_fetch_failures(self):
        sender = _Sender(merge_targets={"aiocqhttp:GroupMessage:1"})
        nitter = _PartiallyFailingNitter(
            {
                "NASA": [
                    self._make_tweet("NASA", "100"),
                    self._make_tweet("NASA", "101"),
                ],
            },
            {
                "baamgu": (
                    "已尝试 2/2 个 Nitter 实例，未获得可用 RSS；"
                    "错误: https://nitter.net: HTTP 404; "
                    "http://nitter.top: HTTP 404"
                )
            },
        )
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "watch_users": ["NASA", "baamgu"],
                "push_targets": ["aiocqhttp:GroupMessage:1"],
                "scheduled_fetch_limit": 2,
                "merge_tweet_threshold": 1,
            },
            nitter=nitter,
            sender=sender,
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )
        await scheduler.storage.add_seen_ids("global", "NASA", ["100"])

        result = await scheduler.run_check(reason="test_fetch_failure_summary")

        self.assertEqual(result.push_mode, "merged")
        self.assertIn("baamgu", result.failed_users)
        self.assertEqual(len(sender.merged_batch_summaries), 1)
        merged_summary = sender.merged_batch_summaries[0][1]
        self.assertIn("Nitter 本次检查发现 1 条新推文", merged_summary)
        self.assertIn("更新账号：@NASA 1 条", merged_summary)
        self.assertIn("抓取失败：@baamgu:", merged_summary)
        self.assertIn("HTTP 404", merged_summary)

    async def test_first_ordinary_push_includes_batch_summary_once(self):
        sender = _Sender()
        nitter = _MultiUserNitter(
            {
                "NASA": [
                    self._make_tweet("NASA", "100"),
                    self._make_tweet("NASA", "101"),
                ],
                "OpenAI": [
                    self._make_tweet("OpenAI", "200"),
                    self._make_tweet("OpenAI", "201"),
                ],
            }
        )
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "watch_users": ["NASA", "OpenAI"],
                "push_targets": ["telegram:FriendMessage:1"],
                "scheduled_fetch_limit": 2,
            },
            nitter=nitter,
            sender=sender,
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )
        await scheduler.storage.add_seen_ids("global", "NASA", ["100"])
        await scheduler.storage.add_seen_ids("global", "OpenAI", ["200"])

        result = await scheduler.run_check(reason="test_batch_summary")

        self.assertEqual(result.new_tweet_count, 2)
        self.assertEqual(len(sender.summary_sends), 1)
        summary = sender.summary_sends[0][1]
        self.assertIn("Nitter 本次检查发现 2 条新推文", summary)
        self.assertIn("分组：默认分组", summary)
        self.assertIn("更新账号：@NASA 1 条，@OpenAI 1 条", summary)
        self.assertEqual(len(sender.batch_summaries), 2)
        self.assertEqual([item[2] for item in sender.batch_summaries], ["", ""])

    async def test_first_ordinary_push_header_includes_fetch_failures_once(self):
        sender = _Sender()
        nitter = _PartiallyFailingNitter(
            {
                "NASA": [
                    self._make_tweet("NASA", "100"),
                    self._make_tweet("NASA", "101"),
                ],
                "OpenAI": [
                    self._make_tweet("OpenAI", "200"),
                    self._make_tweet("OpenAI", "201"),
                ],
            },
            {"baamgu": "HTTP 404"},
        )
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "watch_users": ["NASA", "baamgu", "OpenAI"],
                "push_targets": ["telegram:FriendMessage:1"],
                "scheduled_fetch_limit": 2,
            },
            nitter=nitter,
            sender=sender,
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )
        await scheduler.storage.add_seen_ids("global", "NASA", ["100"])
        await scheduler.storage.add_seen_ids("global", "OpenAI", ["200"])

        result = await scheduler.run_check(reason="test_fetch_failure_header")

        self.assertIn("baamgu", result.failed_users)
        self.assertEqual(len(sender.summary_sends), 1)
        summary = sender.summary_sends[0][1]
        self.assertIn("Nitter 本次检查发现 2 条新推文", summary)
        self.assertIn("更新账号：@NASA 1 条，@OpenAI 1 条", summary)
        self.assertIn("抓取失败：@baamgu: HTTP 404", summary)
        self.assertEqual(len(sender.batch_summaries), 2)
        self.assertEqual([item[2] for item in sender.batch_summaries], ["", ""])

    async def test_first_successful_ordinary_push_gets_batch_summary_after_prepare_failure(self):
        events = []
        media = _RecordingMedia(events)
        sender = _RecordingSender(events=events)
        nitter = _MultiUserNitter(
            {
                "NASA": [
                    self._make_tweet("NASA", "100"),
                    self._make_tweet("NASA", "101"),
                    self._make_tweet("NASA", "102"),
                ],
                "OpenAI": [
                    self._make_tweet("OpenAI", "200"),
                    self._make_tweet("OpenAI", "201"),
                ],
            },
            events=events,
        )
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "watch_users": ["NASA", "OpenAI"],
                "push_targets": ["telegram:FriendMessage:1"],
                "scheduled_fetch_limit": 3,
            },
            nitter=nitter,
            media=media,
            sender=sender,
            translator=_RecordingTranslator(events),
            enricher=_RecordingEnricher(events, fail_status_ids={"101"}),
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )
        await scheduler.storage.add_seen_ids("global", "NASA", ["100"])
        await scheduler.storage.add_seen_ids("global", "OpenAI", ["200"])

        result = await scheduler.run_check(reason="test_batch_summary_after_failure")

        self.assertEqual(result.new_tweet_count, 2)
        self.assertIn("NASA:101", result.failed_users)
        self.assertEqual(
            [item[3] for item in sender.sent],
            [["102"], ["201"]],
        )
        self.assertEqual(len(sender.summary_sends), 1)
        summary = sender.summary_sends[0][1]
        self.assertIn("Nitter 本次检查发现 3 条新推文", summary)
        self.assertIn("更新账号：@NASA 2 条，@OpenAI 1 条", summary)
        self.assertEqual([item[2] for item in sender.batch_summaries], ["", ""])

    async def test_chunked_merged_forward_includes_batch_summary_only_once(self):
        captured_summaries = []
        sender = TweetSender({})

        class _Renderer:
            def build_merged_nodes_for_uin(
                self,
                uin,
                batches,
                start_index=1,
                exclude_videos=False,
                group_label="",
                batch_summary="",
            ):
                captured_summaries.append(batch_summary)
                return object()

        sender.renderer = _Renderer()

        async def send_success(context, umo, chain, label):
            return SendAttempt(success=True)

        sender._send_context_message = send_success
        tweets = [self._make_tweet("NASA", str(index)) for index in range(1, 10)]

        outcome = await sender._send_merged_forward_chunks_to_umo(
            context=None,
            umo="aiocqhttp:GroupMessage:1",
            batches=[("NASA", "https://nitter.test", tweets)],
            group_label="默认分组",
            batch_summary="overall summary",
        )

        self.assertTrue(outcome.success)
        self.assertEqual(captured_summaries, ["overall summary", ""])

    async def test_telegram_flood_control_waits_and_retries_same_message(self):
        sender = TweetSender({})
        calls = []
        sleep_calls = []

        class _Context:
            async def send_message(self, umo, chain):
                del chain
                calls.append(umo)
                if len(calls) == 1:
                    raise RuntimeError("Flood control exceeded. Retry in 18 seconds")
                return True

        async def fake_sleep(seconds):
            sleep_calls.append(seconds)

        with patch.object(telegram_delivery_module.asyncio, "sleep", fake_sleep):
            attempt = await sender._send_context_message(
                _Context(),
                "telegram:GroupMessage:-1001",
                _MessageChain([_Plain("hello")]),
                "direct scheduled tweets",
            )

        self.assertTrue(attempt.success)
        self.assertEqual(calls, ["telegram:GroupMessage:-1001"] * 2)
        self.assertEqual(sleep_calls, [19.0])

    async def test_telegram_flood_control_retry_failure_skips_fallback(self):
        sender = TweetSender({})
        calls = []
        sleep_calls = []

        class _Context:
            async def send_message(self, umo, chain):
                del chain
                calls.append(umo)
                raise RuntimeError("Flood control exceeded. Retry in 18 seconds")

        async def fake_sleep(seconds):
            sleep_calls.append(seconds)

        with patch.object(telegram_delivery_module.asyncio, "sleep", fake_sleep):
            outcome = await sender._send_direct_to_umo(
                _Context(),
                "telegram:GroupMessage:-1001",
                "NASA",
                "https://nitter.test",
                [self._make_tweet("NASA", "110")],
            )

        self.assertFalse(outcome.success)
        self.assertIn("Telegram 限流仍未解除", outcome.warning)
        self.assertEqual(calls, ["telegram:GroupMessage:-1001"] * 2)
        self.assertEqual(sleep_calls, [19.0])

    async def test_custom_platform_id_uses_metadata_type_for_onebot_forward(self):
        class _Meta:
            id = "cat"
            type = "aiocqhttp"
            name = "cat"

        class _Platform:
            def meta(self):
                return _Meta()

        class _Context:
            def get_platform_inst(self, platform_id):
                return _Platform() if platform_id == "cat" else None

        resolver = PlatformResolver()
        profile = resolver.from_umo(_Context(), "cat:FriendMessage:2519706243")

        self.assertIn("aiocqhttp", profile.platform_types)
        self.assertTrue(profile.is_onebot)
        self.assertTrue(
            TweetSender({}).supports_merged_forward_for_umo(
                _Context(), "cat:FriendMessage:2519706243"
            )
        )

    async def test_custom_platform_id_uses_call_action_as_onebot_capability(self):
        class _Bot:
            async def call_action(self, action, **payload):
                return None

        class _Platform:
            bot = _Bot()

        class _Context:
            def get_platform_inst(self, platform_id):
                return _Platform() if platform_id == "cat" else None

        profile = PlatformResolver().from_umo(_Context(), "cat:GroupMessage:123456")

        self.assertTrue(callable(profile.call_action))
        self.assertTrue(profile.is_onebot)
        self.assertTrue(
            TweetSender({}).supports_merged_forward_for_umo(
                _Context(), "cat:GroupMessage:123456"
            )
        )

    async def test_custom_onebot_event_uses_platform_call_action(self):
        sender = TweetSender({"send_video_attachments": True})
        calls = []

        class _Meta:
            id = "cat"
            type = "onebot"
            name = "cat"

        class _Bot:
            async def call_action(self, action, **payload):
                calls.append((action, payload))

        class _Platform:
            bot = _Bot()

            def meta(self):
                return _Meta()

        class _Event:
            platform = _Platform()
            bot = None

            def get_platform_id(self):
                return "cat"

            def get_group_id(self):
                return "123456"

        sent = await sender._send_onebot_forward(_Event(), [{"type": "node"}])

        self.assertTrue(sent)
        self.assertEqual(calls[0][0], "send_group_forward_msg")
        self.assertEqual(calls[0][1]["group_id"], 123456)

    async def test_known_non_onebot_platforms_do_not_use_call_action_fallback(self):
        class _Meta:
            id = "telegram"
            type = "telegram"
            name = "telegram"

        class _Bot:
            async def call_action(self, action, **payload):
                return None

        class _Platform:
            bot = _Bot()

            def meta(self):
                return _Meta()

        class _Context:
            def get_platform_inst(self, platform_id):
                return _Platform() if platform_id == "telegram" else None

        profile = PlatformResolver().from_umo(
            _Context(), "telegram:FriendMessage:1"
        )

        self.assertTrue(callable(profile.call_action))
        self.assertFalse(profile.is_onebot)
        self.assertFalse(
            TweetSender({}).supports_merged_forward_for_umo(
                _Context(), "telegram:FriendMessage:1"
            )
        )

    async def test_custom_onebot_private_merged_video_uses_raw_forward(self):
        sender = TweetSender({"send_video_attachments": True})
        calls = []

        class _Meta:
            id = "cat"
            type = "onebot"
            name = "cat"

        class _Bot:
            async def call_action(self, action, **payload):
                calls.append((action, payload))

        class _Platform:
            bot = _Bot()

            def meta(self):
                return _Meta()

        class _Context:
            def get_platform_inst(self, platform_id):
                return _Platform() if platform_id == "cat" else None

        tweet = self._make_tweet("NASA", "107")
        video_path = Path(self.temp_dir.name) / "clip-cat-private.mp4"
        video_path.write_bytes(b"mp4")
        tweet.media.append(
            TweetMedia("video", "https://video.example.test/clip-cat-private.mp4", video_path)
        )

        outcome = await sender._send_merged_forward_chunk_to_umo(
            context=_Context(),
            umo="cat:FriendMessage:2519706243",
            batches=[("NASA", "https://nitter.test", [tweet])],
        )

        self.assertTrue(outcome.success)
        self.assertEqual(outcome.mode, "raw_forward")
        self.assertEqual(calls[0][0], "send_private_forward_msg")
        self.assertEqual(calls[0][1]["user_id"], 2519706243)

    async def test_custom_onebot_group_merged_video_uses_raw_forward(self):
        sender = TweetSender({"send_video_attachments": True})
        calls = []

        class _Bot:
            async def call_action(self, action, **payload):
                calls.append((action, payload))

        class _Platform:
            bot = _Bot()

        class _Context:
            def get_platform_inst(self, platform_id):
                return _Platform() if platform_id == "cat" else None

        tweet = self._make_tweet("NASA", "108")
        video_path = Path(self.temp_dir.name) / "clip-cat-group.mp4"
        video_path.write_bytes(b"mp4")
        tweet.media.append(
            TweetMedia("video", "https://video.example.test/clip-cat-group.mp4", video_path)
        )

        outcome = await sender._send_merged_forward_chunk_to_umo(
            context=_Context(),
            umo="cat:GroupMessage:123456",
            batches=[("NASA", "https://nitter.test", [tweet])],
        )

        self.assertTrue(outcome.success)
        self.assertEqual(outcome.mode, "raw_forward")
        self.assertEqual(calls[0][0], "send_group_forward_msg")
        self.assertEqual(calls[0][1]["group_id"], 123456)

    async def test_custom_onebot_direct_umo_splits_text_and_videos(self):
        sender = TweetSender(
            {"send_video_attachments": True, "merge_tweet_threshold": 0}
        )
        sent_chains = []

        class _Bot:
            async def call_action(self, action, **payload):
                return None

        class _Platform:
            bot = _Bot()

        class _Context:
            def get_platform_inst(self, platform_id):
                return _Platform() if platform_id == "cat" else None

            async def send_message(self, umo, chain):
                sent_chains.append((umo, chain))

        tweet = self._make_tweet("NASA", "109")
        video_path = Path(self.temp_dir.name) / "clip-cat-direct.mp4"
        video_path.write_bytes(b"mp4")
        tweet.media.append(
            TweetMedia("video", "https://video.example.test/clip-cat-direct.mp4", video_path)
        )

        outcome = await sender._send_direct_to_umo(
            _Context(),
            "cat:GroupMessage:123456",
            "NASA",
            "https://nitter.test",
            [tweet],
        )

        self.assertTrue(outcome.success)
        self.assertEqual([umo for umo, _ in sent_chains], ["cat:GroupMessage:123456"] * 2)
        self.assertTrue(any(isinstance(c, _Plain) for c in sent_chains[0][1].components))
        self.assertFalse(any(isinstance(c, _Video) for c in sent_chains[0][1].components))
        self.assertEqual(len(sent_chains[1][1].components), 1)
        self.assertTrue(isinstance(sent_chains[1][1].components[0], _Video))

    async def test_qq_merged_forward_with_video_uses_onebot_raw_nodes(self):
        sender = TweetSender({"send_video_attachments": True})
        calls = []

        class _Bot:
            async def call_action(self, action, **payload):
                calls.append((action, payload))

        class _Platform:
            bot = _Bot()

        class _Context:
            def get_platform_inst(self, platform_id):
                return _Platform() if platform_id == "aiocqhttp" else None

        tweet = self._make_tweet("NASA", "101")
        video_path = Path(self.temp_dir.name) / "clip.mp4"
        video_path.write_bytes(b"mp4")
        tweet.media.append(
            TweetMedia("video", "https://video.example.test/clip.mp4", video_path)
        )

        outcome = await sender._send_merged_forward_chunk_to_umo(
            context=_Context(),
            umo="aiocqhttp:GroupMessage:123456",
            batches=[("NASA", "https://nitter.test", [tweet])],
            group_label="榛樿鍒嗙粍",
            batch_summary="overall summary",
        )

        self.assertTrue(outcome.success)
        self.assertEqual(outcome.mode, "raw_forward")
        self.assertEqual(calls[0][0], "send_group_forward_msg")
        self.assertEqual(calls[0][1]["group_id"], 123456)
        messages = calls[0][1]["messages"]
        self.assertEqual(len(messages), 3)
        text_segments = messages[1]["data"]["content"]
        video_segments = messages[2]["data"]["content"]
        self.assertTrue(any(segment["type"] == "text" for segment in text_segments))
        self.assertFalse(any(segment["type"] == "video" for segment in text_segments))
        self.assertEqual(
            [segment["type"] for segment in video_segments],
            ["text", "video"],
        )
        text = "\n".join(
            segment["data"]["text"]
            for segment in text_segments
            if segment["type"] == "text"
        )
        video_text = "\n".join(
            segment["data"]["text"]
            for segment in video_segments
            if segment["type"] == "text"
        )
        self.assertIn("#1 @NASA", text)
        self.assertIn("nitter.test", text)
        self.assertIn("queued 101", video_text)
        self.assertIn("nitter.test", video_text)
        self.assertIn("视频/GIF 附件", video_text)
        self.assertIn(tweet.x_url, video_text)

    async def test_qq_raw_video_retry_keeps_omitted_video_notice(self):
        sender = TweetSender({"send_video_attachments": True})
        calls = []

        class _Bot:
            async def call_action(self, action, **payload):
                calls.append((action, payload))
                if len(calls) == 1:
                    raise RuntimeError("video forward failed")

        class _Platform:
            bot = _Bot()

        class _Context:
            def get_platform_inst(self, platform_id):
                return _Platform() if platform_id == "aiocqhttp" else None

        tweet = self._make_tweet("NASA", "102")
        video_path = Path(self.temp_dir.name) / "clip-retry.mp4"
        video_path.write_bytes(b"mp4")
        tweet.media.append(
            TweetMedia("video", "https://video.example.test/clip-retry.mp4", video_path)
        )

        outcome = await sender._send_merged_forward_chunk_to_umo(
            context=_Context(),
            umo="aiocqhttp:GroupMessage:123456",
            batches=[("NASA", "https://nitter.test", [tweet])],
            group_label="默认分组",
            batch_summary="overall summary",
        )

        self.assertTrue(outcome.success)
        self.assertEqual(outcome.mode, "raw_forward_without_videos")
        self.assertEqual(len(calls), 2)
        retry_segments = [
            segment
            for node in calls[1][1]["messages"]
            for segment in node["data"]["content"]
        ]
        self.assertFalse(any(segment["type"] == "video" for segment in retry_segments))
        retry_text = "\n".join(
            segment["data"]["text"]
            for segment in retry_segments
            if segment["type"] == "text"
        )
        self.assertIn("视频/GIF 附件未作为消息发送", retry_text)
        self.assertIn(tweet.x_url, retry_text)

    async def test_qq_direct_forward_fallback_labels_video_node(self):
        sender = TweetSender({"send_video_attachments": True})

        class _Event:
            def get_group_id(self):
                return "123456"

        tweet = self._make_tweet("NASA", "103")
        video_path = Path(self.temp_dir.name) / "clip-direct.mp4"
        video_path.write_bytes(b"mp4")
        tweet.media.append(
            TweetMedia("video", "https://video.example.test/clip-direct.mp4", video_path)
        )

        raw_nodes = sender.renderer.build_onebot_nodes(
            _Event(),
            "NASA",
            "https://nitter.test",
            [tweet],
            start_index=1,
        )

        self.assertEqual(len(raw_nodes), 3)
        text_segments = raw_nodes[1]["data"]["content"]
        video_segments = raw_nodes[2]["data"]["content"]
        self.assertTrue(any(segment["type"] == "text" for segment in text_segments))
        self.assertFalse(any(segment["type"] == "video" for segment in text_segments))
        self.assertEqual(
            [segment["type"] for segment in video_segments],
            ["text", "video"],
        )
        video_text = "\n".join(
            segment["data"]["text"]
            for segment in video_segments
            if segment["type"] == "text"
        )
        self.assertIn("视频/GIF 附件", video_text)
        self.assertIn("queued 103", video_text)
        self.assertIn("nitter.test", video_text)
        self.assertIn(tweet.x_url, video_text)

    async def test_qq_forward_nodes_split_video_into_separate_node(self):
        sender = TweetSender({"send_video_attachments": True})

        tweet = self._make_tweet("NASA", "106")
        video_path = Path(self.temp_dir.name) / "clip-node.mp4"
        video_path.write_bytes(b"mp4")
        tweet.media.append(
            TweetMedia("video", "https://video.example.test/clip-node.mp4", video_path)
        )

        nodes = sender.renderer.build_nodes_for_uin(
            10000,
            "NASA",
            "https://nitter.test",
            [tweet],
            start_index=1,
        )

        self.assertEqual(len(nodes.nodes), 3)
        text_components = nodes.nodes[1].content
        video_components = nodes.nodes[2].content
        self.assertTrue(any(isinstance(component, _Plain) for component in text_components))
        self.assertFalse(any(isinstance(component, _Video) for component in text_components))
        self.assertEqual(
            [type(component) for component in video_components],
            [_Plain, _Video],
        )

    async def test_qq_forward_nodes_split_images_into_separate_node(self):
        sender = TweetSender({})

        tweet = self._make_tweet("NASA", "107")
        image_path = Path(self.temp_dir.name) / "image-node.jpg"
        image_path.write_bytes(b"jpg")
        tweet.media.append(
            TweetMedia("image", "https://image.example.test/image-node.jpg", image_path)
        )

        nodes = sender.renderer.build_nodes_for_uin(
            10000,
            "NASA",
            "https://nitter.test",
            [tweet],
            start_index=1,
        )

        self.assertEqual(len(nodes.nodes), 3)
        text_components = nodes.nodes[1].content
        image_components = nodes.nodes[2].content
        self.assertTrue(any(isinstance(component, _Plain) for component in text_components))
        self.assertFalse(any(isinstance(component, _Image) for component in text_components))
        self.assertEqual(
            [type(component) for component in image_components],
            [_Plain, _Image],
        )

    async def test_qq_raw_forward_nodes_split_images_into_separate_node(self):
        sender = TweetSender({})

        tweet = self._make_tweet("NASA", "108")
        image_path = Path(self.temp_dir.name) / "image-raw.jpg"
        image_path.write_bytes(b"jpg")
        tweet.media.append(
            TweetMedia("image", "https://image.example.test/image-raw.jpg", image_path)
        )

        raw_nodes = sender.renderer.build_merged_onebot_nodes_for_uin(
            10000,
            [("NASA", "https://nitter.test", [tweet])],
            start_index=1,
        )

        self.assertEqual(len(raw_nodes), 3)
        text_segments = raw_nodes[1]["data"]["content"]
        image_segments = raw_nodes[2]["data"]["content"]
        self.assertFalse(any(segment["type"] == "image" for segment in text_segments))
        self.assertEqual(
            [segment["type"] for segment in image_segments],
            ["text", "image"],
        )

    async def test_qq_direct_event_splits_text_and_videos_without_forward(self):
        sender = TweetSender(
            {"send_video_attachments": True, "merge_tweet_threshold": 0}
        )
        sent_chains = []

        class _Event:
            def get_platform_name(self):
                return "qq"

            async def send(self, chain):
                sent_chains.append(chain)

        tweet = self._make_tweet("NASA", "104")
        video_path = Path(self.temp_dir.name) / "clip-event.mp4"
        video_path.write_bytes(b"mp4")
        tweet.media.append(
            TweetMedia("video", "https://video.example.test/clip-event.mp4", video_path)
        )

        ok = await sender._send_direct_event(
            _Event(),
            "NASA",
            "https://nitter.test",
            [tweet],
        )

        self.assertTrue(ok)
        self.assertEqual(len(sent_chains), 2)
        self.assertTrue(any(isinstance(c, _Plain) for c in sent_chains[0].components))
        self.assertFalse(any(isinstance(c, _Video) for c in sent_chains[0].components))
        self.assertEqual(len(sent_chains[1].components), 1)
        self.assertTrue(isinstance(sent_chains[1].components[0], _Video))

    async def test_qq_direct_event_splits_text_and_images_without_forward(self):
        sender = TweetSender({"merge_tweet_threshold": 0})
        sent_chains = []

        class _Event:
            def get_platform_name(self):
                return "qq"

            async def send(self, chain):
                sent_chains.append(chain)

        tweet = self._make_tweet("NASA", "109")
        image_path = Path(self.temp_dir.name) / "image-event.jpg"
        image_path.write_bytes(b"jpg")
        tweet.media.append(
            TweetMedia("image", "https://image.example.test/image-event.jpg", image_path)
        )

        ok = await sender._send_direct_event(
            _Event(),
            "NASA",
            "https://nitter.test",
            [tweet],
        )

        self.assertTrue(ok)
        self.assertEqual(len(sent_chains), 2)
        self.assertTrue(any(isinstance(c, _Plain) for c in sent_chains[0].components))
        self.assertFalse(any(isinstance(c, _Image) for c in sent_chains[0].components))
        self.assertEqual(len(sent_chains[1].components), 1)
        self.assertTrue(isinstance(sent_chains[1].components[0], _Image))

    async def test_qq_direct_umo_splits_text_and_videos_without_forward(self):
        sender = TweetSender(
            {"send_video_attachments": True, "merge_tweet_threshold": 0}
        )
        sent_chains = []

        class _Context:
            async def send_message(self, umo, chain):
                sent_chains.append((umo, chain))

        tweet = self._make_tweet("NASA", "105")
        video_path = Path(self.temp_dir.name) / "clip-umo.mp4"
        video_path.write_bytes(b"mp4")
        tweet.media.append(
            TweetMedia("video", "https://video.example.test/clip-umo.mp4", video_path)
        )

        outcome = await sender._send_direct_to_umo(
            _Context(),
            "qq:GroupMessage:123456",
            "NASA",
            "https://nitter.test",
            [tweet],
        )

        self.assertTrue(outcome.success)
        self.assertEqual([umo for umo, _ in sent_chains], ["qq:GroupMessage:123456"] * 2)
        self.assertTrue(any(isinstance(c, _Plain) for c in sent_chains[0][1].components))
        self.assertFalse(any(isinstance(c, _Video) for c in sent_chains[0][1].components))
        self.assertEqual(len(sent_chains[1][1].components), 1)
        self.assertTrue(isinstance(sent_chains[1][1].components[0], _Video))

    async def test_qq_direct_umo_splits_text_and_images_without_forward(self):
        sender = TweetSender({"merge_tweet_threshold": 0})
        sent_chains = []

        class _Context:
            async def send_message(self, umo, chain):
                sent_chains.append((umo, chain))

        tweet = self._make_tweet("NASA", "110")
        image_path = Path(self.temp_dir.name) / "image-umo.jpg"
        image_path.write_bytes(b"jpg")
        tweet.media.append(
            TweetMedia("image", "https://image.example.test/image-umo.jpg", image_path)
        )

        outcome = await sender._send_direct_to_umo(
            _Context(),
            "qq:GroupMessage:123456",
            "NASA",
            "https://nitter.test",
            [tweet],
        )

        self.assertTrue(outcome.success)
        self.assertEqual([umo for umo, _ in sent_chains], ["qq:GroupMessage:123456"] * 2)
        self.assertTrue(any(isinstance(c, _Plain) for c in sent_chains[0][1].components))
        self.assertFalse(any(isinstance(c, _Image) for c in sent_chains[0][1].components))
        self.assertEqual(len(sent_chains[1][1].components), 1)
        self.assertTrue(isinstance(sent_chains[1][1].components[0], _Image))

    async def test_buffered_qq_sends_per_user_at_end_below_merge_threshold(self):
        events = []
        media = _Media()
        sender = _Sender(
            merge_targets={"aiocqhttp:GroupMessage:1"},
            events=events,
        )
        nitter = _MultiUserNitter(
            {
                "NASA": [
                    self._make_tweet("NASA", "100"),
                    self._make_tweet("NASA", "101"),
                ],
                "NASAHubble": [
                    self._make_tweet("NASAHubble", "200"),
                    self._make_tweet("NASAHubble", "201"),
                ],
            },
            events=events,
        )
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "watch_users": ["NASA", "NASAHubble"],
                "push_targets": [
                    "telegram:FriendMessage:1",
                    "aiocqhttp:GroupMessage:1",
                ],
                "scheduled_fetch_limit": 2,
                "merge_tweet_threshold": 3,
            },
            nitter=nitter,
            media=media,
            sender=sender,
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )
        await scheduler.storage.add_seen_ids("global", "NASA", ["100"])
        await scheduler.storage.add_seen_ids("global", "NASAHubble", ["200"])

        result = await scheduler.run_check(reason="test_immediate_mixed_no_merge")

        self.assertEqual(
            events,
            [
                "fetch:NASA",
                "fetch:NASAHubble",
                "send:telegram:FriendMessage:1:NASA",
                "send:telegram:FriendMessage:1:NASAHubble",
                "send:aiocqhttp:GroupMessage:1:NASA",
                "send:aiocqhttp:GroupMessage:1:NASAHubble",
            ],
        )
        self.assertEqual(result.push_mode, "per_user")
        self.assertEqual(result.new_tweet_count, 2)
        self.assertEqual(result.pushed_target_successes, 4)
        self.assertEqual(result.pushed_target_attempts, 4)
        self.assertEqual(sender.merged_sent, [])
        self.assertEqual(media.cleaned, 2)
        self.assertEqual(
            sender.tweet_start_indexes,
            [
                ("telegram:FriendMessage:1", "NASA", 1),
                ("telegram:FriendMessage:1", "NASAHubble", 1),
                ("aiocqhttp:GroupMessage:1", "NASA", 1),
                ("aiocqhttp:GroupMessage:1", "NASAHubble", 1),
            ],
        )

    async def test_push_stats_do_not_merge_different_batches_with_same_count(self):
        sender = _Sender()
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "watch_users": ["NASA"],
                "push_targets": ["telegram:FriendMessage:1"],
            },
            sender=sender,
        )
        result = scheduler_module.ScheduledCheckResult(reason="test_batch_stats")
        first_batch = scheduler_module.PendingTweetBatch(
            username="NASA",
            instance="https://nitter.one",
            tweets=[self._make_tweet("NASA", "101")],
            fetched_ids=["101"],
            seen_ids=[],
        )
        second_batch = scheduler_module.PendingTweetBatch(
            username="NASA",
            instance="https://nitter.two",
            tweets=[self._make_tweet("NASA", "201")],
            fetched_ids=["201"],
            seen_ids=[],
        )

        await scheduler._send_per_user_updates(
            [first_batch],
            result,
            ["telegram:FriendMessage:1"],
            0.0,
            0.0,
            merge_existing_stats=True,
        )
        await scheduler._send_per_user_updates(
            [second_batch],
            result,
            ["aiocqhttp:GroupMessage:1"],
            0.0,
            0.0,
            merge_existing_stats=True,
        )

        self.assertEqual(len(result.pushes), 2)
        self.assertEqual(result.new_tweet_count, 2)
        self.assertEqual(result.pushed_target_successes, 2)
        self.assertEqual(result.pushed_target_attempts, 2)

    async def test_brief_log_enabled_defaults_to_true_and_reads_grouped_value(self):
        scheduler = self._create_scheduler({})
        self.assertTrue(scheduler.brief_log_enabled)

        scheduler = self._create_scheduler(
            {"logging": {"brief_log_enabled": False}}
        )
        self.assertFalse(scheduler.brief_log_enabled)

    async def test_scheduled_result_brief_log_lines_include_result_details(self):
        result = scheduler_module.ScheduledCheckResult(
            reason="interval:30m",
            group_id="tech",
            group_name="科技",
            users=["NASA", "OpenAI"],
            targets=["telegram:FriendMessage:1", "aiocqhttp:GroupMessage:1"],
            invalid_targets=["bad-target"],
            failed_users={"NASA": "fetch failed", "publish": "send failed"},
            push_mode="mixed",
            delivery_warnings=["uncertain delivery", "uncertain delivery"],
        )
        result.pushes.append(
            scheduler_module.ScheduledPushResult(
                username="OpenAI",
                new_count=2,
                success_targets=1,
                total_targets=2,
            )
        )
        result.merged_push_success_targets = 1
        result.merged_push_total_targets = 1

        lines = result.format_brief_log_lines()

        self.assertIn("group=科技(tech)", lines[0])
        self.assertIn("reason=interval:30m", lines[0])
        self.assertIn("mode=mixed", lines[0])
        self.assertIn("new=2", lines[0])
        self.assertIn("push_success=2/3", lines[0])
        self.assertIn("failed=2", lines[0])
        self.assertTrue(any("失败详情" in line and "@NASA" in line for line in lines))
        self.assertTrue(any("publish: send failed" in line for line in lines))
        self.assertTrue(any("无效推送目标" in line for line in lines))
        self.assertTrue(any("发送状态提示" in line for line in lines))

    async def test_brief_mode_logs_summary_without_verbose_push_info(self):
        sender = _Sender()
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "watch_users": ["NASA"],
                "push_targets": ["telegram:FriendMessage:1"],
            },
            sender=sender,
        )
        result = scheduler_module.ScheduledCheckResult(reason="test_brief")
        batch = scheduler_module.PendingTweetBatch(
            username="NASA",
            instance="https://nitter.test",
            tweets=[self._make_tweet("NASA", "101")],
            fetched_ids=["101"],
            seen_ids=[],
        )

        with patch.object(scheduler_module.logger, "info") as info_log:
            await scheduler._send_per_user_updates(
                [batch],
                result,
                ["telegram:FriendMessage:1"],
                0.0,
                0.0,
            )
            scheduler._log_check_result(result)

        logged = "\n".join(str(call.args[0]) for call in info_log.call_args_list)
        self.assertIn("推送结果", logged)
        self.assertNotIn("推送完成: username=NASA", logged)

    async def test_detailed_mode_keeps_verbose_push_info(self):
        sender = _Sender()
        scheduler = self._create_scheduler(
            {
                "logging": {"brief_log_enabled": False},
                "schedule_enabled": True,
                "watch_users": ["NASA"],
                "push_targets": ["telegram:FriendMessage:1"],
            },
            sender=sender,
        )
        result = scheduler_module.ScheduledCheckResult(reason="test_verbose")
        batch = scheduler_module.PendingTweetBatch(
            username="NASA",
            instance="https://nitter.test",
            tweets=[self._make_tweet("NASA", "101")],
            fetched_ids=["101"],
            seen_ids=[],
        )

        with patch.object(scheduler_module.logger, "info") as info_log:
            await scheduler._send_per_user_updates(
                [batch],
                result,
                ["telegram:FriendMessage:1"],
                0.0,
                0.0,
            )

        logged = "\n".join(str(call.args[0]) for call in info_log.call_args_list)
        self.assertIn("推送完成: username=NASA", logged)

    async def test_immediate_send_cleanup_on_cancel_without_buffered_targets(self):
        media = _Media()
        sender = _CancelingSender()
        nitter = _MultiUserNitter(
            {
                "NASA": [
                    self._make_tweet("NASA", "100"),
                    self._make_tweet("NASA", "101"),
                ],
            },
        )
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "watch_users": ["NASA"],
                "push_targets": ["telegram:FriendMessage:1"],
                "scheduled_fetch_limit": 2,
            },
            nitter=nitter,
            media=media,
            sender=sender,
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )
        await scheduler.storage.add_seen_ids("global", "NASA", ["100"])

        with self.assertRaises(scheduler_module.asyncio.CancelledError):
            await scheduler.run_check(reason="test_immediate_cancel_cleanup")

        self.assertEqual(media.cleaned, 1)

    async def test_immediate_send_cleanup_on_cancel_with_buffered_qq_target(self):
        media = _Media()
        sender = _CancelingSender(merge_targets={"aiocqhttp:GroupMessage:1"})
        nitter = _MultiUserNitter(
            {
                "NASA": [
                    self._make_tweet("NASA", "100"),
                    self._make_tweet("NASA", "101"),
                ],
            },
        )
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "watch_users": ["NASA"],
                "push_targets": [
                    "telegram:FriendMessage:1",
                    "aiocqhttp:GroupMessage:1",
                ],
                "scheduled_fetch_limit": 2,
                "merge_tweet_threshold": 2,
            },
            nitter=nitter,
            media=media,
            sender=sender,
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )
        await scheduler.storage.add_seen_ids("global", "NASA", ["100"])

        with self.assertRaises(scheduler_module.asyncio.CancelledError):
            await scheduler.run_check(reason="test_immediate_buffered_cancel_cleanup")

        self.assertEqual(media.cleaned, 1)

    async def test_deferred_check_queues_without_sending(self):
        config = {
            "schedule_enabled": True,
            "watch_users": ["NASA"],
            "push_targets": ["aiocqhttp:GroupMessage:1"],
            "scheduled_fetch_limit": 2,
            "deferred_publish_enabled": True,
            "deferred_publish_times": ["08:00"],
        }
        media = _Media()
        sender = _Sender()
        scheduler = NitterTweetScheduler(
            _Owner(),
            context=None,
            config=config,
            nitter=_Nitter(),
            media=media,
            sender=sender,
            translator=_Translator(),
            enricher=None,
        )
        self.schedulers.append(scheduler)
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )
        await scheduler.storage.add_seen_ids("global", "NASA", ["100"])

        result = await scheduler.run_check(reason="test")
        summary = await scheduler.storage.get_pending_queue_summary("global")

        self.assertEqual(result.push_mode, "deferred")
        self.assertEqual(result.queued_tweets, {"NASA": 1})
        self.assertEqual(summary.pending_count, 1)
        self.assertEqual(sender.sent, [])
        self.assertEqual(media.moved, 1)

    async def test_deferred_check_without_prefetch_does_not_download_media(self):
        config = {
            "schedule_enabled": True,
            "watch_users": ["NASA"],
            "push_targets": ["aiocqhttp:GroupMessage:1"],
            "scheduled_fetch_limit": 2,
            "deferred_publish_enabled": True,
            "deferred_prefetch_media": False,
            "deferred_publish_times": ["08:00"],
        }
        media = _Media()
        sender = _Sender()
        scheduler = NitterTweetScheduler(
            _Owner(),
            context=None,
            config=config,
            nitter=_Nitter(),
            media=media,
            sender=sender,
            translator=_Translator(),
            enricher=None,
        )
        self.schedulers.append(scheduler)
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )
        await scheduler.storage.add_seen_ids("global", "NASA", ["100"])

        result = await scheduler.run_check(reason="test")
        summary = await scheduler.storage.get_pending_queue_summary("global")

        self.assertEqual(result.queued_tweets, {"NASA": 1})
        self.assertEqual(summary.pending_count, 1)
        self.assertEqual(summary.media_count, 0)
        self.assertEqual(media.attached, 0)
        self.assertEqual(media.moved, 0)

    async def test_check_pending_brief_includes_queue_state_and_global_commands(self):
        scheduler = await self._create_scheduler_with_deferred_publish_enabled()
        await self._enqueue_deferred_tweets(
            scheduler,
            {
                "NASA": [
                    self._make_tweet("NASA", "201"),
                    self._make_tweet("NASA", "202"),
                ],
                "OpenAI": [self._make_tweet("OpenAI", "301")],
            },
        )
        records = await scheduler.storage.get_pending_tweets("global", 10)
        await scheduler.storage.mark_pending_tweets_failed(
            [records[0].id], "send failed"
        )
        group = scheduler._schedule_group("global")

        summary = await scheduler.check_pending_brief(group)

        self.assertIn("当前分组暂存:", summary)
        self.assertIn("待发布: 3 条", summary)
        self.assertIn("失败待重试: 1 条", summary)
        self.assertIn("@NASA 2 条", summary)
        self.assertIn("@OpenAI 1 条", summary)
        self.assertIn("下次发布时间:", summary)
        self.assertIn("\n /推文队列\n", summary)
        self.assertIn("\n /推文发布", summary)

    async def test_check_pending_brief_uses_custom_group_command_suffix(self):
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "watch_users": [],
                "push_targets": [],
                "tweet_groups": [
                    {
                        "name": "Tech",
                        "group_id": "tech",
                        "watch_users": ["OpenAI"],
                        "push_targets": ["telegram:FriendMessage:1"],
                        "deferred_publish_enabled": True,
                        "deferred_publish_times": ["08:00"],
                    }
                ],
            }
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )
        group = scheduler._schedule_group("tech")

        summary = await scheduler.check_pending_brief(group)

        self.assertIn("待发布: 0 条", summary)
        self.assertIn("暂存账号: 无", summary)
        self.assertIn("\n /推文队列 Tech\n", summary)
        self.assertIn("\n /推文发布 Tech", summary)

    async def test_publish_pending_sends_and_marks_queue_sent(self):
        config = {
            "schedule_enabled": True,
            "watch_users": ["NASA"],
            "push_targets": ["aiocqhttp:GroupMessage:1"],
            "deferred_publish_enabled": True,
            "deferred_publish_times": ["08:00"],
        }
        media = _Media()
        sender = _Sender()
        scheduler = NitterTweetScheduler(
            _Owner(),
            context=None,
            config=config,
            nitter=_Nitter(),
            media=media,
            sender=sender,
            translator=_Translator(),
            enricher=None,
        )
        self.schedulers.append(scheduler)
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )
        tweet = TweetItem(
            text="queued",
            link="https://x.com/NASA/status/102",
            published="",
        )
        await scheduler.storage.enqueue_pending_tweets(
            "global", "NASA", "https://nitter.test", [tweet]
        )

        result = await scheduler.publish_pending(reason="test_publish")
        summary = await scheduler.storage.get_pending_queue_summary("global")

        self.assertEqual(result.new_tweet_count, 1)
        self.assertEqual(summary.pending_count, 0)
        self.assertEqual(
            sender.sent,
            [("aiocqhttp:GroupMessage:1", "NASA", "https://nitter.test", ["102"])],
        )
        self.assertEqual(len(sender.summary_sends), 1)
        self.assertIn("Nitter 本次发布 1 条新推文", sender.summary_sends[0][1])
        self.assertIn("更新账号：@NASA 1 条", sender.summary_sends[0][1])
        self.assertEqual(len(sender.batch_summaries), 1)
        self.assertEqual(sender.batch_summaries[0][2], "")
        self.assertEqual(media.staged_cleaned, 1)

    async def test_publish_pending_success_records_history(self):
        sender = _Sender()
        scheduler = await self._create_scheduler_with_deferred_publish_enabled(
            sender=sender
        )
        await scheduler.storage.enqueue_pending_tweets(
            "default",
            "NASA",
            "https://nitter.test",
            [self._make_tweet("NASA", "202")],
        )

        await scheduler.publish_pending(reason="test_publish_history")
        records = await scheduler.storage.get_push_history()

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].group_id, "default")
        self.assertEqual(records[0].username, "NASA")
        self.assertEqual(records[0].status_id, "202")
        self.assertEqual(records[0].target_umo, "aiocqhttp:GroupMessage:1")
        self.assertEqual(records[0].source, "publish")

    async def test_publish_pending_merged_success_records_each_tweet_history(self):
        sender = _Sender(merge_targets={"aiocqhttp:GroupMessage:1"})
        scheduler = await self._create_scheduler_with_deferred_publish_enabled(
            sender=sender,
            extra_config={"merge_tweet_threshold": 1},
        )
        await scheduler.storage.enqueue_pending_tweets(
            "default",
            "NASA",
            "https://nitter.test",
            [self._make_tweet("NASA", "205"), self._make_tweet("NASA", "206")],
        )

        await scheduler.publish_pending(reason="test_publish_merged_history")
        records = await scheduler.storage.get_push_history("default", "NASA", 10)

        self.assertEqual([record.status_id for record in reversed(records)], ["205", "206"])
        self.assertEqual({record.target_umo for record in records}, {"aiocqhttp:GroupMessage:1"})
        self.assertEqual({record.source for record in records}, {"publish"})

    async def test_publish_pending_does_not_resend_already_delivered_tweet_to_target(self):
        sender = _Sender()
        scheduler = await self._create_scheduler_with_deferred_publish_enabled(
            push_targets=["telegram:FriendMessage:1", "lark:GroupMessage:2"],
            sender=sender,
        )
        await scheduler.storage.enqueue_pending_tweets(
            "default",
            "NASA",
            "https://nitter.test",
            [
                self._make_tweet("NASA", "301"),
                self._make_tweet("NASA", "302"),
            ],
        )
        records = await scheduler.storage.get_pending_tweets("default", 10)
        old_record = next(record for record in records if record.tweet.status_id == "301")
        await scheduler.storage.mark_pending_tweets_delivered(
            [old_record.id],
            "telegram:FriendMessage:1",
        )

        result = await scheduler.publish_pending(reason="test_partial_delivered")
        records_after = await scheduler.storage.get_push_history("default", "NASA", 20)

        self.assertEqual(result.pushed_target_attempts, 2)
        self.assertEqual(
            sender.sent,
            [
                ("telegram:FriendMessage:1", "NASA", "https://nitter.test", ["302"]),
                (
                    "lark:GroupMessage:2",
                    "NASA",
                    "https://nitter.test",
                    ["301", "302"],
                ),
            ],
        )
        sent_history = sorted(
            (record.target_umo, record.status_id) for record in records_after
        )
        self.assertEqual(
            sent_history,
            [
                ("lark:GroupMessage:2", "301"),
                ("lark:GroupMessage:2", "302"),
                ("telegram:FriendMessage:1", "302"),
            ],
        )

    async def test_replay_push_history_uses_current_group_targets(self):
        sender = _Sender()
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "tweet_groups": [
                    {
                        "name": "Tech",
                        "group_id": "tech",
                        "watch_users": ["NASA"],
                        "push_targets": ["telegram:FriendMessage:2"],
                    }
                ],
            },
            sender=sender,
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )
        record_id = await scheduler.storage.record_push_history(
            "tech",
            "NASA",
            self._make_tweet("NASA", "203"),
            "telegram:FriendMessage:old",
            "scheduled",
            "https://nitter.test",
        )

        result = await scheduler.replay_push_history(record_id)
        records = await scheduler.storage.get_push_history("tech", "NASA", 10)

        self.assertTrue(result["success"])
        self.assertEqual(result["total_targets"], 1)
        self.assertEqual(result["success_targets"], 1)
        self.assertEqual(
            sender.sent,
            [("telegram:FriendMessage:2", "NASA", "https://nitter.test", ["203"])],
        )
        self.assertEqual(records[0].target_umo, "telegram:FriendMessage:2")
        self.assertEqual(records[0].source, "replay")

    async def test_replay_push_history_redownloads_recorded_media(self):
        events = []
        sender = _Sender(events=events)
        media = _RecordingMedia(events)
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "tweet_groups": [
                    {
                        "name": "Tech",
                        "group_id": "tech",
                        "watch_users": ["NASA"],
                        "push_targets": ["telegram:FriendMessage:2"],
                    }
                ],
            },
            media=media,
            sender=sender,
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )
        tweet = self._make_tweet("NASA", "209")
        tweet.media.append(
            TweetMedia(
                "image",
                "https://media.example.test/209.jpg",
                Path("C:/tmp/209.jpg"),
            )
        )
        record_id = await scheduler.storage.record_push_history(
            "tech",
            "NASA",
            tweet,
            "telegram:FriendMessage:old",
            "scheduled",
            "https://nitter.test",
        )

        result = await scheduler.replay_push_history(record_id)
        records = await scheduler.storage.get_push_history("tech", "NASA", 10)

        self.assertTrue(result["success"])
        self.assertIn("media:209", events)
        self.assertEqual(media.attached, 1)
        self.assertEqual(media.cleaned, 1)
        self.assertEqual(sender.sent, [("telegram:FriendMessage:2", "NASA", "https://nitter.test", ["209"])])
        self.assertEqual(records[0].source, "replay")
        self.assertEqual(len(records[0].tweet.media), 1)
        self.assertEqual(records[0].tweet.media[0].url, "https://media.example.test/209.jpg")
        self.assertIsNone(records[0].tweet.media[0].path)

    async def test_replay_push_history_uses_selected_current_targets(self):
        sender = _Sender()
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "tweet_groups": [
                    {
                        "name": "Tech",
                        "group_id": "tech",
                        "watch_users": ["NASA"],
                        "push_targets": [
                            "telegram:FriendMessage:2",
                            "lark:GroupMessage:3",
                        ],
                    }
                ],
            },
            sender=sender,
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )
        record_id = await scheduler.storage.record_push_history(
            "tech",
            "NASA",
            self._make_tweet("NASA", "207"),
            "telegram:FriendMessage:old",
            "scheduled",
            "https://nitter.test",
        )

        result = await scheduler.replay_push_history(
            record_id,
            target_umos=["lark:GroupMessage:3"],
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["total_targets"], 1)
        self.assertEqual(
            sender.sent,
            [("lark:GroupMessage:3", "NASA", "https://nitter.test", ["207"])],
        )

    async def test_replay_push_history_deduplicates_selected_targets(self):
        sender = _Sender()
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "tweet_groups": [
                    {
                        "name": "Tech",
                        "group_id": "tech",
                        "watch_users": ["NASA"],
                        "push_targets": [
                            "telegram:FriendMessage:2",
                            "lark:GroupMessage:3",
                        ],
                    }
                ],
            },
            sender=sender,
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )
        record_id = await scheduler.storage.record_push_history(
            "tech",
            "NASA",
            self._make_tweet("NASA", "210"),
            "telegram:FriendMessage:old",
            "scheduled",
            "https://nitter.test",
        )

        result = await scheduler.replay_push_history(
            record_id,
            target_umos=[
                "lark:GroupMessage:3",
                "lark:GroupMessage:3",
                "telegram:FriendMessage:2",
                "lark:GroupMessage:3",
            ],
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["total_targets"], 2)
        self.assertEqual(
            sender.sent,
            [
                ("lark:GroupMessage:3", "NASA", "https://nitter.test", ["210"]),
                ("telegram:FriendMessage:2", "NASA", "https://nitter.test", ["210"]),
            ],
        )

    async def test_replay_push_history_rejects_targets_outside_current_group(self):
        sender = _Sender()
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "tweet_groups": [
                    {
                        "name": "Tech",
                        "group_id": "tech",
                        "watch_users": ["NASA"],
                        "push_targets": ["telegram:FriendMessage:2"],
                    }
                ],
            },
            sender=sender,
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )
        record_id = await scheduler.storage.record_push_history(
            "tech",
            "NASA",
            self._make_tweet("NASA", "208"),
            "telegram:FriendMessage:old",
            "scheduled",
            "https://nitter.test",
        )

        result = await scheduler.replay_push_history(
            record_id,
            target_umos=["telegram:FriendMessage:old"],
        )

        self.assertFalse(result["success"])
        self.assertIn("当前分组", result["error"])
        self.assertEqual(sender.sent, [])

    async def test_replay_push_history_rejects_group_without_current_targets(self):
        scheduler = self._create_scheduler(
            {
                "schedule_enabled": True,
                "tweet_groups": [
                    {
                        "name": "Tech",
                        "group_id": "tech",
                        "watch_users": ["NASA"],
                        "push_targets": [],
                    }
                ],
            }
        )
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )
        record_id = await scheduler.storage.record_push_history(
            "tech",
            "NASA",
            self._make_tweet("NASA", "204"),
            "telegram:FriendMessage:old",
            "scheduled",
            "https://nitter.test",
        )

        result = await scheduler.replay_push_history(record_id)
        records = await scheduler.storage.get_push_history("tech", "NASA", 10)

        self.assertFalse(result["success"])
        self.assertIn("推送目标", result["error"])
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].source, "scheduled")

    async def test_publish_pending_skipped_no_push_targets(self):
        scheduler = await self._create_scheduler_with_deferred_publish_enabled(
            push_targets=[]
        )

        with patch.object(scheduler_module.logger, "info") as info_log:
            result = await scheduler.publish_pending(reason="test_no_targets")

        self.assertEqual(result.skipped_reason, "no_push_targets")
        logged = "\n".join(str(call.args[0]) for call in info_log.call_args_list)
        self.assertIn("reason=no_push_targets", logged)

    async def test_publish_pending_skipped_no_pending_tweets(self):
        scheduler = await self._create_scheduler_with_deferred_publish_enabled()

        with patch.object(scheduler_module.logger, "info") as info_log:
            result = await scheduler.publish_pending(reason="test_empty_queue")

        self.assertEqual(result.skipped_reason, "no_pending_tweets")
        logged = "\n".join(str(call.args[0]) for call in info_log.call_args_list)
        self.assertIn("reason=no_pending_tweets", logged)

    async def test_publish_pending_removes_sent_rows_after_success(self):
        config = {
            "schedule_enabled": True,
            "watch_users": ["NASA"],
            "push_targets": ["aiocqhttp:GroupMessage:1"],
            "deferred_publish_enabled": True,
            "deferred_publish_times": ["08:00"],
        }
        scheduler = NitterTweetScheduler(
            _Owner(),
            context=None,
            config=config,
            nitter=_Nitter(),
            media=_Media(),
            sender=_Sender(),
            translator=_Translator(),
            enricher=None,
        )
        self.schedulers.append(scheduler)
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )
        tweet = TweetItem(
            text="queued",
            link="https://x.com/NASA/status/104",
            published="",
        )
        await scheduler.storage.enqueue_pending_tweets(
            "global", "NASA", "https://nitter.test", [tweet]
        )

        await scheduler.publish_pending(reason="test_publish")
        inserted_again = await scheduler.storage.enqueue_pending_tweets(
            "global", "NASA", "https://nitter.test", [tweet]
        )
        summary = await scheduler.storage.get_pending_queue_summary("global")

        self.assertEqual(inserted_again, 1)
        self.assertEqual(summary.pending_count, 1)

    async def test_deferred_publish_mixed_push_mode_cleans_media(self):
        media = _Media()
        sender = _Sender(merge_targets={"aiocqhttp:GroupMessage:1"})
        scheduler = await self._create_scheduler_with_deferred_publish_enabled(
            push_targets=[
                "aiocqhttp:GroupMessage:1",
                "aiocqhttp:GroupMessage:2",
            ],
            watch_users=["NASA", "NASAHubble"],
            media=media,
            sender=sender,
            extra_config={
                "merge_tweet_threshold": 1,
                "deferred_publish_batch_limit": 10,
            },
        )
        await self._enqueue_deferred_tweets(
            scheduler,
            {
                "NASA": [
                    self._make_tweet("NASA", "201"),
                    self._make_tweet("NASA", "202"),
                ],
                "NASAHubble": [
                    self._make_tweet("NASAHubble", "301"),
                    self._make_tweet("NASAHubble", "302"),
                ],
            },
        )

        result = await scheduler.publish_pending(reason="test_mixed_push_mode")
        summary = await scheduler.storage.get_pending_queue_summary("global")

        self.assertEqual(result.push_mode, "mixed")
        self.assertEqual(result.new_tweet_count, 4)
        self.assertEqual(result.pushed_target_successes, 3)
        self.assertEqual(result.pushed_target_attempts, 3)
        self.assertEqual(
            sender.sent,
            [
                (
                    "aiocqhttp:GroupMessage:2",
                    "NASA",
                    "https://nitter.test",
                    ["201", "202"],
                ),
                (
                    "aiocqhttp:GroupMessage:2",
                    "NASAHubble",
                    "https://nitter.test",
                    ["301", "302"],
                ),
            ],
        )
        self.assertEqual(
            sender.merged_sent,
            [
                (
                    "aiocqhttp:GroupMessage:1",
                    [
                        ("NASA", "https://nitter.test", ["201", "202"]),
                        ("NASAHubble", "https://nitter.test", ["301", "302"]),
                    ],
                )
            ],
        )
        self.assertEqual(summary.pending_count, 0)
        self.assertEqual(summary.failed_count, 0)
        self.assertEqual(media.staged_cleaned, 4)

    async def test_publish_pending_keeps_queue_when_all_targets_fail(self):
        config = {
            "schedule_enabled": True,
            "watch_users": ["NASA"],
            "push_targets": ["aiocqhttp:GroupMessage:1"],
            "deferred_publish_enabled": True,
            "deferred_publish_times": ["08:00"],
        }
        media = _Media()
        sender = _Sender(success=False)
        scheduler = NitterTweetScheduler(
            _Owner(),
            context=None,
            config=config,
            nitter=_Nitter(),
            media=media,
            sender=sender,
            translator=_Translator(),
            enricher=None,
        )
        self.schedulers.append(scheduler)
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )
        tweet = TweetItem(
            text="queued",
            link="https://x.com/NASA/status/103",
            published="",
        )
        await scheduler.storage.enqueue_pending_tweets(
            "global", "NASA", "https://nitter.test", [tweet]
        )

        result = await scheduler.publish_pending(reason="test_publish")
        summary = await scheduler.storage.get_pending_queue_summary("global")

        self.assertIn("publish", result.failed_users)
        self.assertEqual(summary.pending_count, 1)
        self.assertEqual(summary.failed_count, 1)
        self.assertEqual(media.staged_cleaned, 0)

    async def test_publish_pending_keeps_queue_when_any_target_fails(self):
        config = {
            "schedule_enabled": True,
            "watch_users": ["NASA"],
            "push_targets": [
                "aiocqhttp:GroupMessage:1",
                "aiocqhttp:GroupMessage:2",
            ],
            "deferred_publish_enabled": True,
            "deferred_publish_times": ["08:00"],
        }
        media = _Media()
        sender = _Sender(failed_targets={"aiocqhttp:GroupMessage:2"})
        scheduler = NitterTweetScheduler(
            _Owner(),
            context=None,
            config=config,
            nitter=_Nitter(),
            media=media,
            sender=sender,
            translator=_Translator(),
            enricher=None,
        )
        self.schedulers.append(scheduler)
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )
        tweet = TweetItem(
            text="queued",
            link="https://x.com/NASA/status/105",
            published="",
        )
        await scheduler.storage.enqueue_pending_tweets(
            "global", "NASA", "https://nitter.test", [tweet]
        )

        result = await scheduler.publish_pending(reason="test_publish")
        summary = await scheduler.storage.get_pending_queue_summary("global")
        records = await scheduler.storage.get_pending_tweets("global", 10)

        self.assertIn("publish", result.failed_users)
        self.assertEqual(result.pushed_target_successes, 1)
        self.assertEqual(result.pushed_target_attempts, 2)
        self.assertEqual(summary.pending_count, 1)
        self.assertEqual(summary.failed_count, 1)
        self.assertEqual(records[0].delivered_targets, ("aiocqhttp:GroupMessage:1",))
        self.assertEqual(media.staged_cleaned, 0)
        self.assertEqual(
            sender.sent,
            [
                (
                    "aiocqhttp:GroupMessage:1",
                    "NASA",
                    "https://nitter.test",
                    ["105"],
                ),
                (
                    "aiocqhttp:GroupMessage:2",
                    "NASA",
                    "https://nitter.test",
                    ["105"],
                ),
            ],
        )

        sender.failed_targets.clear()
        retry_result = await scheduler.publish_pending(reason="test_publish_retry")
        retry_summary = await scheduler.storage.get_pending_queue_summary("global")

        self.assertNotIn("publish", retry_result.failed_users)
        self.assertEqual(retry_result.pushed_target_successes, 1)
        self.assertEqual(retry_result.pushed_target_attempts, 1)
        self.assertEqual(retry_summary.pending_count, 0)
        self.assertEqual(media.staged_cleaned, 1)
        self.assertEqual(
            sender.sent,
            [
                (
                    "aiocqhttp:GroupMessage:1",
                    "NASA",
                    "https://nitter.test",
                    ["105"],
                ),
                (
                    "aiocqhttp:GroupMessage:2",
                    "NASA",
                    "https://nitter.test",
                    ["105"],
                ),
                (
                    "aiocqhttp:GroupMessage:2",
                    "NASA",
                    "https://nitter.test",
                    ["105"],
                ),
            ],
        )


if __name__ == "__main__":
    unittest.main()
