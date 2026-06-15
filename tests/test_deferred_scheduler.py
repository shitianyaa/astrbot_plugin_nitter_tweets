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


import scheduler as scheduler_module  # noqa: E402
from scheduler import NitterTweetScheduler  # noqa: E402
from sender import SendAttempt, TweetSender  # noqa: E402
from sqlite_storage import SQLiteStorage  # noqa: E402
from storage_adapter import StorageAdapter  # noqa: E402
from tweet_rendering import TweetMessageRenderer  # noqa: E402
from utils import TweetItem, TweetMedia  # noqa: E402


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


class _MultiUserNitter:
    def __init__(self, tweets_by_user, events=None):
        self.tweets_by_user = tweets_by_user
        self.events = events if events is not None else []

    async def fetch_tweets(self, username, limit):
        self.events.append(f"fetch:{username}")
        return "https://nitter.test", self.tweets_by_user.get(username, [])[:limit]


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
        self.batch_summaries = []
        self.merged_batch_summaries = []
        self.success = success
        self.failed_targets = set(failed_targets or [])
        self.merge_targets = set(merge_targets or [])
        self.events = events if events is not None else []

    def supports_merged_forward_for_umo(self, context, umo):
        return umo in self.merge_targets

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
    ):
        self.events.append(f"send:{umo}:{username}")
        self.sent.append((umo, username, instance, [tweet.status_id for tweet in tweets]))
        self.group_labels.append((umo, username, group_label))
        self.headers.append((umo, username, header_text))
        self.batch_summaries.append((umo, username, batch_summary))
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
    ):
        status_ids = ",".join(tweet.status_id for tweet in tweets)
        self.events.append(f"send:{umo}:{username}:{status_ids}")
        self.sent.append((umo, username, instance, [tweet.status_id for tweet in tweets]))
        self.group_labels.append((umo, username, group_label))
        self.headers.append((umo, username, header_text))
        self.batch_summaries.append((umo, username, batch_summary))
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
        self.assertEqual(len(sender.batch_summaries), 2)
        first_summary = sender.batch_summaries[0][2]
        second_summary = sender.batch_summaries[1][2]
        self.assertIn("Nitter 本次检查发现 2 条新推文", first_summary)
        self.assertIn("分组：默认分组", first_summary)
        self.assertIn("更新账号：@NASA 1 条，@OpenAI 1 条", first_summary)
        self.assertEqual(second_summary, "")

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
        first_summary = sender.batch_summaries[0][2]
        second_summary = sender.batch_summaries[1][2]
        self.assertIn("Nitter 本次检查发现 3 条新推文", first_summary)
        self.assertIn("更新账号：@NASA 2 条，@OpenAI 1 条", first_summary)
        self.assertEqual(second_summary, "")

    async def test_chunked_merged_forward_includes_batch_summary_only_once(self):
        captured_summaries = []
        sender = TweetSender({})

        class _Renderer:
            def build_merged_nodes_for_uin(
                self,
                uin,
                batches,
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
        node_contents = [
            segment
            for node in calls[0][1]["messages"]
            for segment in node["data"]["content"]
        ]
        self.assertTrue(any(segment["type"] == "video" for segment in node_contents))

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
        self.assertEqual(len(sender.batch_summaries), 1)
        self.assertIn("Nitter 本次发布 1 条新推文", sender.batch_summaries[0][2])
        self.assertIn("更新账号：@NASA 1 条", sender.batch_summaries[0][2])
        self.assertEqual(media.staged_cleaned, 1)

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
