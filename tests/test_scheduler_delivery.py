from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


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
from scheduler import NitterTweetScheduler  # noqa: E402
from delivery import TweetSender  # noqa: E402
from storage import SQLiteStorage  # noqa: E402
from storage import StorageAdapter  # noqa: E402
from shared import TweetItem  # noqa: E402


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



class SchedulerDeliveryTest(unittest.IsolatedAsyncioTestCase):
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
    ):
        scheduler = NitterTweetScheduler(
            _Owner(),
            context=None,
            config=config,
            nitter=nitter or _Nitter(),
            media=media or _Media(),
            sender=sender or _Sender(),
            translator=translator or _Translator(),
        )
        self.schedulers.append(scheduler)
        return scheduler

    def _make_tweet(self, username, status_id):
        return TweetItem(
            text=f"tweet {status_id}",
            link=f"https://x.com/{username}/status/{status_id}",
            published="",
        )

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

    async def test_failed_scheduled_push_does_not_mark_seen(self):
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

        await scheduler.run_check(reason="test_failed_seen")
        seen_ids = await scheduler.storage.get_seen_ids("global", "NASA")

        self.assertNotIn("201", seen_ids)

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


