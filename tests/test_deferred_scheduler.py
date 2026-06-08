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
        pass


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


if not hasattr(astrbot_api_module, "logger"):
    astrbot_api_module.logger = _Logger()
astrbot_api_all_module.At = getattr(astrbot_api_all_module, "At", _At)
astrbot_api_all_module.AstrBotConfig = getattr(
    astrbot_api_all_module, "AstrBotConfig", dict
)
astrbot_api_all_module.Context = getattr(
    astrbot_api_all_module, "Context", object
)
astrbot_api_all_module.MessageChain = getattr(
    astrbot_api_all_module, "MessageChain", _MessageChain
)
astrbot_api_all_module.Plain = getattr(astrbot_api_all_module, "Plain", _Plain)
astrbot_api_all_module.Star = getattr(astrbot_api_all_module, "Star", _Star)
astrbot_api_all_module.logger = astrbot_api_module.logger
astrbot_api_event_module.MessageChain = getattr(
    astrbot_api_event_module, "MessageChain", _MessageChain
)
astrbot_api_event_module.AstrMessageEvent = getattr(
    astrbot_api_event_module, "AstrMessageEvent", object
)
astrbot_api_event_module.filter = getattr(
    astrbot_api_event_module, "filter", _Filter
)
astrbot_api_message_components_module.Plain = getattr(
    astrbot_api_message_components_module, "Plain", _Plain
)
astrbot_api_message_components_module.Image = getattr(
    astrbot_api_message_components_module, "Image", _Image
)
astrbot_api_message_components_module.Video = getattr(
    astrbot_api_message_components_module, "Video", _Video
)
astrbot_api_message_components_module.Node = getattr(
    astrbot_api_message_components_module, "Node", _Node
)
astrbot_api_message_components_module.Nodes = getattr(
    astrbot_api_message_components_module, "Nodes", _Nodes
)
astrbot_api_star_module.register = getattr(
    astrbot_api_star_module, "register", _register
)
astrbot_core_command_module.GreedyStr = getattr(
    astrbot_core_command_module, "GreedyStr", str
)
astrbot_core_message_components_module.Image = getattr(
    astrbot_core_message_components_module, "Image", _Image
)
astrbot_core_message_components_module.Video = getattr(
    astrbot_core_message_components_module, "Video", _Video
)
astrbot_core_message_components_module.Node = getattr(
    astrbot_core_message_components_module, "Node", _Node
)
astrbot_core_message_components_module.Nodes = getattr(
    astrbot_core_message_components_module, "Nodes", _Nodes
)
astrbot_core_message_components_module.Plain = getattr(
    astrbot_core_message_components_module, "Plain", _Plain
)
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


from scheduler import NitterTweetScheduler  # noqa: E402
from sqlite_storage import SQLiteStorage  # noqa: E402
from storage_adapter import StorageAdapter  # noqa: E402
from utils import TweetItem  # noqa: E402


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

    async def fetch_tweets(self, username, limit):
        return "https://nitter.test", self.tweets[:limit]


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


class _Translator:
    async def attach_translations(self, tweets, target):
        for tweet in tweets:
            tweet.translation = "translated"


class _Sender:
    def __init__(self, success=True, failed_targets=None):
        self.sent = []
        self.success = success
        self.failed_targets = set(failed_targets or [])

    def supports_merged_forward_for_umo(self, context, umo):
        return False

    async def send_to_umo_with_outcome(self, context, umo, username, instance, tweets):
        self.sent.append((umo, username, instance, [tweet.status_id for tweet in tweets]))
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
        self.assertEqual(media.staged_cleaned, 1)

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

        self.assertIn("publish", result.failed_users)
        self.assertEqual(result.pushed_target_successes, 1)
        self.assertEqual(result.pushed_target_attempts, 2)
        self.assertEqual(summary.pending_count, 1)
        self.assertEqual(summary.failed_count, 1)
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


if __name__ == "__main__":
    unittest.main()
