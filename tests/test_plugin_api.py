from __future__ import annotations

import inspect
import sys
import types
import unittest
from pathlib import Path


if "astrbot.api.all" not in sys.modules:
    astrbot_module = sys.modules.get("astrbot", types.ModuleType("astrbot"))
    astrbot_api_module = sys.modules.get("astrbot.api", types.ModuleType("astrbot.api"))
    astrbot_api_all_module = types.ModuleType("astrbot.api.all")
    astrbot_api_event_module = types.ModuleType("astrbot.api.event")
    astrbot_api_star_module = types.ModuleType("astrbot.api.star")
    astrbot_api_message_components_module = types.ModuleType(
        "astrbot.api.message_components"
    )
    astrbot_core_module = types.ModuleType("astrbot.core")
    astrbot_core_message_module = types.ModuleType("astrbot.core.message")
    astrbot_core_message_components_module = types.ModuleType(
        "astrbot.core.message.components"
    )
    astrbot_core_command_module = types.ModuleType(
        "astrbot.core.star.filter.command"
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

    class _At:
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
            return cls(path)

    class _Video:
        @classmethod
        def fromFileSystem(cls, path):
            return cls(path)

    class _Node:
        pass

    class _Nodes:
        pass

    astrbot_api_module.logger = _Logger()
    astrbot_api_all_module.At = _At
    astrbot_api_all_module.AstrBotConfig = dict
    astrbot_api_all_module.Context = object
    astrbot_api_all_module.MessageChain = _MessageChain
    astrbot_api_all_module.Plain = _Plain
    astrbot_api_all_module.Star = _Star
    astrbot_api_all_module.logger = astrbot_api_module.logger
    astrbot_api_event_module.AstrMessageEvent = object
    astrbot_api_event_module.filter = _Filter
    astrbot_api_star_module.register = _register
    astrbot_api_message_components_module.Image = _Image
    astrbot_api_message_components_module.Node = _Node
    astrbot_api_message_components_module.Nodes = _Nodes
    astrbot_api_message_components_module.Plain = _Plain
    astrbot_api_message_components_module.Video = _Video
    astrbot_core_message_components_module.Image = _Image
    astrbot_core_message_components_module.Node = _Node
    astrbot_core_message_components_module.Nodes = _Nodes
    astrbot_core_message_components_module.Plain = _Plain
    astrbot_core_message_components_module.Video = _Video
    astrbot_core_command_module.GreedyStr = str

    sys.modules["astrbot"] = astrbot_module
    sys.modules["astrbot.api"] = astrbot_api_module
    sys.modules["astrbot.api.all"] = astrbot_api_all_module
    sys.modules["astrbot.api.event"] = astrbot_api_event_module
    sys.modules["astrbot.api.star"] = astrbot_api_star_module
    sys.modules["astrbot.api.message_components"] = (
        astrbot_api_message_components_module
    )
    sys.modules["astrbot.core"] = astrbot_core_module
    sys.modules["astrbot.core.message"] = astrbot_core_message_module
    sys.modules["astrbot.core.message.components"] = (
        astrbot_core_message_components_module
    )
    sys.modules["astrbot.core.star.filter.command"] = astrbot_core_command_module

if "quart" not in sys.modules:
    quart_module = types.ModuleType("quart")

    def _jsonify(payload=None, **kwargs):
        if kwargs:
            return kwargs
        return payload

    quart_module.jsonify = _jsonify
    quart_module.request = types.SimpleNamespace(args={}, get_json=lambda: {})
    sys.modules["quart"] = quart_module


from config_compat import config_get
from main import NitterTweetsPlugin
from plugin_api import NitterWebAPI
from scheduler_config import SchedulerConfigReader
from sqlite_storage import PendingQueueSummary, PendingTweetRecord, PushHistoryRecord
from utils import TweetItem, TweetMedia, configured_merge_tweet_threshold


class _Config(dict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.saved = False

    def save_config(self):
        self.saved = True


class _FailingSaveConfig(_Config):
    def save_config(self):
        raise RuntimeError("config locked")


class _Context:
    def __init__(self):
        self.routes = []

    def register_web_api(self, route, handler, methods, description):
        self.routes.append((route, handler, methods, description))


class _Storage:
    def __init__(self):
        self.summaries: dict[str, PendingQueueSummary] = {}
        self.records: dict[str, list[PendingTweetRecord]] = {}
        self.synced_groups = []
        self.clear_seen_calls = []
        self.delete_legacy_seen_kv_calls = 0
        self.delete_group_runtime_data_calls = []
        self.history: list[PushHistoryRecord] = []

    async def get_pending_queue_summary(self, group_id):
        return self.summaries.get(group_id, PendingQueueSummary(group_id=group_id))

    async def get_pending_tweets(self, group_id, limit):
        return list(self.records.get(group_id, []))[:limit]

    async def migrate_and_sync(self, schedule_groups):
        self.synced_groups = list(schedule_groups)

    async def clear_seen_records(self, group_id=None):
        self.clear_seen_calls.append(group_id)
        return 7

    async def delete_legacy_seen_kv(self):
        self.delete_legacy_seen_kv_calls += 1
        return True

    async def delete_group_runtime_data(self, group_id):
        self.delete_group_runtime_data_calls.append(group_id)
        return {
            "groups_deleted": 1,
            "users_deleted": 1,
            "targets_deleted": 1,
            "seen_deleted": 1,
            "pending_deleted": 2,
            "pending_media_deleted": 3,
        }

    async def get_push_history(self, group_id="", username="", limit=50, offset=0):
        rows = list(self.history)
        if group_id:
            rows = [row for row in rows if row.group_id == group_id]
        if username:
            query = username.lower().lstrip("@")
            rows = [row for row in rows if query in row.username.lower()]
        rows.sort(key=lambda row: (row.pushed_at, row.id), reverse=True)
        return rows[offset : offset + limit]


class _CheckResult:
    def __init__(self, message="检查结果"):
        self.message = message
        self.group_id = "tech"
        self.group_name = "科技"
        self.skipped_reason = ""
        self.new_tweet_count = 2
        self.queued_tweet_count = 0
        self.pushed_target_successes = 1
        self.pushed_target_attempts = 1

    def format_message(self, title="Nitter 定时检查结果"):
        return f"{title}\n{self.message}"


class _Scheduler:
    def __init__(self, config):
        self.config_reader = SchedulerConfigReader(config, context=None)
        self.storage = _Storage()
        self.is_running = True
        self.run_check_calls = []
        self.publish_pending_calls = []
        self.replay_push_history_calls = []

    @property
    def schedule_enabled(self):
        return bool(config_get(self.config_reader.config, "schedule_enabled", False))

    def start(self, reason=""):
        pass

    async def run_check(self, **kwargs):
        self.run_check_calls.append(kwargs)
        return _CheckResult("已执行检查")

    async def publish_pending(self, **kwargs):
        self.publish_pending_calls.append(kwargs)
        return _CheckResult("已发布暂存队列")

    async def replay_push_history(self, record_id, target_umos=None):
        self.replay_push_history_calls.append((record_id, target_umos))
        if record_id == 404:
            return {"success": False, "error": "未找到推送记录"}
        if record_id == 400:
            return {"success": False, "error": "当前分组没有有效推送目标"}
        return {
            "success": True,
            "record_id": record_id,
            "target_count": 2,
            "success_targets": 2,
            "total_targets": 2,
        }


class _Media:
    def __init__(self):
        self.clear_non_staged_cache_calls = 0
        self.delete_staged_media_group_calls = []

    def clear_non_staged_cache(self):
        self.clear_non_staged_cache_calls += 1
        return types.SimpleNamespace(
            removed=3,
            failed=0,
            skipped_dirs=1,
            images=2,
            videos=1,
            other=0,
            removed_empty_dirs=0,
        )

    def delete_staged_media_group(self, group_id):
        self.delete_staged_media_group_calls.append(group_id)
        return types.SimpleNamespace(
            removed=2,
            failed=0,
            skipped_dirs=0,
            removed_images=1,
            removed_videos=1,
            removed_other=0,
            removed_empty_dirs=2,
        )


class _FailingMedia:
    def clear_non_staged_cache(self):
        raise RuntimeError("disk denied")


class _Nitter:
    def __init__(self):
        self.instances = ["https://nitter.test"]
        self.calls = []

    async def fetch_tweets_from_instance(self, instance, username, limit):
        self.calls.append((instance, username, limit))
        return instance, [
            TweetItem(
                text="hello",
                link=f"https://x.com/{username}/status/123",
                published="2026-07-05",
            )
        ]


def _plugin(config):
    plugin = object.__new__(NitterTweetsPlugin)
    plugin.config = config
    plugin.scheduler = _Scheduler(config)
    plugin.media = _Media()
    plugin.nitter = _Nitter()
    plugin.default_limit = 5
    plugin.cooldown_seconds = 0
    plugin._cooldowns = {}
    return plugin


def _group_config(config, group_id):
    for group in config_get(config, "tweet_groups", []) or []:
        if isinstance(group, dict) and group.get("group_id") == group_id:
            return group
    raise AssertionError(f"group not found: {group_id}")


async def _response_payload(result):
    get_json = getattr(result, "get_json", None)
    if not callable(get_json):
        return result

    payload = get_json()
    if inspect.isawaitable(payload):
        payload = await payload
    return payload


async def _call_json_handler(handler):
    quart_module = sys.modules.get("quart")
    app_factory = getattr(quart_module, "Quart", None)
    if callable(app_factory):
        app = app_factory(__name__)
        async with app.app_context():
            return await _response_payload(await handler())
    return await _response_payload(await handler())


class NitterWebAPITest(unittest.IsolatedAsyncioTestCase):
    def test_registers_group_management_routes(self):
        api = NitterWebAPI(_plugin(_Config({})))
        context = _Context()

        api.register(context)

        routes = {item[0]: item[2] for item in context.routes}
        self.assertEqual(routes["/astrbot_plugin_nitter_tweets/web/groups/create"], ["POST"])
        self.assertEqual(routes["/astrbot_plugin_nitter_tweets/web/groups/update"], ["POST"])
        self.assertEqual(routes["/astrbot_plugin_nitter_tweets/web/groups/delete"], ["POST"])

    def test_registers_dashboard_routes_under_plugin_prefix(self):
        api = NitterWebAPI(_plugin(_Config({})))
        context = _Context()

        api.register(context)

        routes = {item[0]: item[2] for item in context.routes}
        self.assertEqual(
            routes,
            {
                "/astrbot_plugin_nitter_tweets/web/overview": ["GET"],
                "/astrbot_plugin_nitter_tweets/web/groups": ["GET"],
                "/astrbot_plugin_nitter_tweets/web/groups/create": ["POST"],
                "/astrbot_plugin_nitter_tweets/web/groups/update": ["POST"],
                "/astrbot_plugin_nitter_tweets/web/groups/delete": ["POST"],
                "/astrbot_plugin_nitter_tweets/web/history": ["GET"],
                "/astrbot_plugin_nitter_tweets/web/history/replay": ["POST"],
                "/astrbot_plugin_nitter_tweets/web/pending": ["GET"],
                "/astrbot_plugin_nitter_tweets/web/check": ["POST"],
                "/astrbot_plugin_nitter_tweets/web/publish": ["POST"],
                "/astrbot_plugin_nitter_tweets/web/cache/clear": ["POST"],
                "/astrbot_plugin_nitter_tweets/web/seen/clear": ["POST"],
                "/astrbot_plugin_nitter_tweets/web/subscriptions/import": ["POST"],
                "/astrbot_plugin_nitter_tweets/web/subscriptions/delete": ["POST"],
                "/astrbot_plugin_nitter_tweets/web/mirror/probe": ["POST"],
            },
        )

    async def test_create_group_uses_safe_defaults(self):
        config = _Config({"push": {"tweet_groups": []}})
        plugin = _plugin(config)

        payload = await NitterWebAPI(plugin).create_group({})

        self.assertTrue(payload["success"])
        group = payload["group"]
        self.assertEqual(group["group_id"], "group_1")
        self.assertEqual(group["name"], "新分组 1")
        self.assertFalse(group["enabled"])
        self.assertTrue(group["interval_check_enabled"])
        self.assertFalse(group["deferred_publish_enabled"])
        self.assertFalse(group["filter_plain_text_enabled"])
        self.assertEqual(group["watch_users"], [])
        self.assertEqual(group["push_targets"], [])
        self.assertEqual(group["pending_summary"]["pending_count"], 0)
        self.assertTrue(config.saved)

    async def test_update_group_rejects_group_id_mutation(self):
        config = _Config(
            {
                "push": {
                    "tweet_groups": [
                        {"name": "科技", "group_id": "tech", "watch_users": []}
                    ]
                }
            }
        )
        plugin = _plugin(config)

        payload = await NitterWebAPI(plugin).update_group(
            {"group_id": "tech", "new_group_id": "news", "name": "科技"}
        )

        self.assertFalse(payload["success"])
        self.assertIn("group_id", payload["error"])

    async def test_update_group_saves_editable_fields(self):
        config = _Config(
            {
                "push": {
                    "tweet_groups": [
                        {
                            "name": "科技",
                            "group_id": "tech",
                            "enabled": True,
                            "watch_users": ["OpenAI"],
                            "push_targets": ["telegram:FriendMessage:1"],
                            "interval_check_enabled": True,
                            "daily_check_times": [],
                            "deferred_publish_enabled": False,
                            "filter_plain_text_enabled": False,
                        }
                    ]
                }
            }
        )
        plugin = _plugin(config)

        payload = await NitterWebAPI(plugin).update_group(
            {
                "group_id": "tech",
                "name": "科技新闻",
                "enabled": False,
                "interval_check_enabled": False,
                "daily_check_times": ["08:30", "21:05"],
                "deferred_publish_enabled": True,
                "filter_plain_text_enabled": True,
            }
        )

        self.assertTrue(payload["success"])
        self.assertEqual(payload["group"]["name"], "科技新闻")
        self.assertFalse(payload["group"]["enabled"])
        self.assertFalse(payload["group"]["interval_check_enabled"])
        self.assertEqual(payload["group"]["daily_check_times"], ["08:30", "21:05"])
        self.assertTrue(payload["group"]["deferred_publish_enabled"])
        self.assertTrue(payload["group"]["filter_plain_text_enabled"])
        self.assertTrue(config.saved)
        self.assertEqual(_group_config(config, "tech")["name"], "科技新闻")

    async def test_update_group_saves_push_targets(self):
        config = _Config(
            {
                "push": {
                    "tweet_groups": [
                        {
                            "name": "科技",
                            "group_id": "tech",
                            "watch_users": ["OpenAI"],
                            "push_targets": ["telegram:FriendMessage:1"],
                        }
                    ]
                }
            }
        )
        plugin = _plugin(config)

        payload = await NitterWebAPI(plugin).update_group(
            {
                "group_id": "tech",
                "name": "科技",
                "push_targets": [
                    "telegram:FriendMessage:2",
                    "invalid target",
                ],
            }
        )

        self.assertTrue(payload["success"])
        self.assertEqual(payload["group"]["push_targets"], ["telegram:FriendMessage:2"])
        self.assertEqual(payload["group"]["invalid_push_targets"], ["invalid target"])
        self.assertEqual(
            _group_config(config, "tech")["push_targets"],
            ["telegram:FriendMessage:2", "invalid target"],
        )

    async def test_update_group_rejects_name_collision(self):
        config = _Config(
            {
                "push": {
                    "tweet_groups": [
                        {"name": "科技", "group_id": "tech", "watch_users": []},
                        {"name": "新闻", "group_id": "news", "watch_users": []},
                    ]
                }
            }
        )
        plugin = _plugin(config)

        payload = await NitterWebAPI(plugin).update_group(
            {"group_id": "tech", "name": "news"}
        )

        self.assertFalse(payload["success"])
        self.assertIn("冲突", payload["error"])

    async def test_delete_group_rejects_default_group(self):
        config = _Config(
            {
                "push": {
                    "tweet_groups": [
                        {"name": "默认分组", "group_id": "default", "watch_users": []}
                    ]
                }
            }
        )
        plugin = _plugin(config)

        payload = await NitterWebAPI(plugin).delete_group(
            {"group_id": "default", "confirm": "DELETE", "force": True}
        )

        self.assertFalse(payload["success"])
        self.assertIn("默认分组", payload["error"])

    async def test_delete_group_removes_config_and_reports_cleanup_summary(self):
        config = _Config(
            {
                "push": {
                    "tweet_groups": [
                        {"name": "默认分组", "group_id": "default", "watch_users": []},
                        {"name": "科技", "group_id": "tech", "watch_users": ["OpenAI"]},
                    ]
                }
            }
        )
        plugin = _plugin(config)

        payload = await NitterWebAPI(plugin).delete_group(
            {"group_id": "tech", "confirm": "DELETE", "force": True}
        )

        self.assertTrue(payload["success"])
        self.assertEqual(payload["group_id"], "tech")
        self.assertEqual(payload["group_name"], "科技")
        self.assertEqual(
            payload["runtime_summary"],
            {
                "groups_deleted": 1,
                "users_deleted": 1,
                "targets_deleted": 1,
                "seen_deleted": 1,
                "pending_deleted": 2,
                "pending_media_deleted": 3,
            },
        )
        self.assertEqual(payload["media_summary"]["removed"], 2)
        self.assertEqual(
            plugin.scheduler.storage.delete_group_runtime_data_calls, ["tech"]
        )
        self.assertEqual(plugin.media.delete_staged_media_group_calls, ["tech"])
        self.assertEqual(
            [group.group_id for group in plugin.scheduler.storage.synced_groups],
            ["default"],
        )
        self.assertEqual(
            [group["group_id"] for group in config_get(config, "tweet_groups", [])],
            ["default"],
        )

    async def test_create_group_rolls_back_when_save_fails(self):
        config = _FailingSaveConfig({"push": {"tweet_groups": []}})
        plugin = _plugin(config)

        payload = await NitterWebAPI(plugin).create_group({})

        self.assertFalse(payload["success"])
        self.assertIn("配置保存失败", payload["error"])
        self.assertEqual(config_get(config, "tweet_groups", []), [])

    async def test_overview_counts_groups_watch_users_push_targets_and_pending(self):
        config = _Config(
            {
                "basic": {"default_limit": 12},
                "schedule": {"schedule_enabled": True},
                "media": {"send_image_attachments": True, "send_video_attachments": False},
                "ai_translation": {"translate_enabled": True},
                "ai_vision": {"vision_enabled": False},
                "ai_comment": {"comment_enabled": True},
                "deferred": {"deferred_publish_batch_limit": 80},
                "performance": {
                    "concurrent_fetch_enabled": True,
                    "concurrent_prepare_enabled": False,
                },
                "push": {
                    "merge_tweet_threshold": 4,
                    "send_target_interval": 2.5,
                    "tweet_groups": [
                        {
                            "name": "默认分组",
                            "group_id": "default",
                            "enabled": True,
                            "watch_users": ["NASA", "@NASA", "bad user"],
                            "push_targets": [
                                "telegram:FriendMessage:1",
                                "bad-target",
                            ],
                            "deferred_publish_enabled": True,
                        },
                        {
                            "name": "科技",
                            "group_id": "tech",
                            "enabled": False,
                            "watch_users": ["OpenAI"],
                            "push_targets": ["aiocqhttp:GroupMessage:2"],
                        },
                    ]
                },
            }
        )
        plugin = _plugin(config)
        plugin.scheduler.storage.summaries = {
            "default": PendingQueueSummary(
                group_id="default",
                pending_count=4,
                failed_count=1,
                media_count=3,
            ),
            "tech": PendingQueueSummary(
                group_id="tech",
                pending_count=2,
                failed_count=0,
                media_count=1,
            ),
        }

        payload = await NitterWebAPI(plugin).build_overview()

        self.assertTrue(payload["success"])
        self.assertEqual(payload["scheduler"]["running"], True)
        self.assertEqual(payload["scheduler"]["schedule_enabled"], True)
        self.assertEqual(
            payload["counts"],
            {
                "groups": 2,
                "enabled_groups": 1,
                "watch_users": 2,
                "raw_watch_users": 4,
                "duplicate_watch_users": 1,
                "invalid_watch_users": 1,
                "push_targets": 2,
                "invalid_push_targets": 1,
                "pending_tweets": 6,
                "failed_pending_tweets": 1,
                "pending_media": 4,
            },
        )
        self.assertEqual(payload["features"]["deferred_publish_groups"], 1)
        self.assertEqual(
            payload["config_summary"],
            {
                "nitter_instance_count": 1,
                "default_limit": 12,
                "scheduled_fetch_limit": 5,
                "check_interval_minutes": 30,
                "merge_tweet_threshold": 4,
                "send_target_interval": 2.5,
                "deferred_publish_batch_limit": 80,
                "concurrent_fetch_enabled": True,
                "concurrent_prepare_enabled": False,
            },
        )
        self.assertEqual(payload["terminology"]["push_targets"], "推送目标")
        attention_keys = {item["key"] for item in payload["attention_items"]}
        self.assertIn("invalid_push_targets", attention_keys)
        self.assertIn("invalid_watch_users", attention_keys)
        self.assertIn("failed_pending_tweets", attention_keys)

    async def test_config_summary_uses_effective_scheduler_values(self):
        config = _Config(
            {
                "basic": {"default_limit": 250},
                "schedule": {
                    "check_interval_minutes": "bad",
                    "scheduled_fetch_limit": "bad",
                },
                "push": {
                    "merge_tweet_threshold": "bad",
                    "send_target_interval": "bad",
                    "tweet_groups": [
                        {
                            "name": "科技",
                            "group_id": "tech",
                            "watch_users": ["OpenAI"],
                            "push_targets": ["telegram:FriendMessage:1"],
                        }
                    ],
                },
                "deferred": {"deferred_publish_batch_limit": "bad"},
            }
        )
        plugin = _plugin(config)

        payload = await NitterWebAPI(plugin).build_overview()
        group = plugin.scheduler.config_reader.schedule_group(
            "tech", log_invalid_targets=False
        )

        self.assertIsNotNone(group)
        self.assertEqual(
            payload["config_summary"]["default_limit"],
            NitterTweetsPlugin._parse_positive_limit(
                config_get(config, "default_limit"), 5
            ),
        )
        self.assertEqual(
            payload["config_summary"]["scheduled_fetch_limit"],
            group.scheduled_fetch_limit,
        )
        self.assertEqual(
            payload["config_summary"]["check_interval_minutes"],
            group.check_interval_minutes,
        )
        self.assertEqual(
            payload["config_summary"]["send_target_interval"],
            group.send_target_interval,
        )
        self.assertEqual(
            payload["config_summary"]["merge_tweet_threshold"],
            configured_merge_tweet_threshold(config),
        )
        self.assertEqual(
            payload["config_summary"]["deferred_publish_batch_limit"],
            group.deferred_publish_batch_limit,
        )

    async def test_groups_payload_serializes_push_target_details(self):
        config = _Config(
            {
                "push": {
                    "tweet_groups": [
                        {
                            "name": "科技",
                            "group_id": "tech",
                            "aliases": ["tech-news"],
                            "enabled": True,
                            "watch_users": ["OpenAI"],
                            "push_targets": [
                                "telegram:FriendMessage:1",
                                "invalid target",
                            ],
                            "interval_check_enabled": True,
                            "daily_check_times": ["08:30"],
                            "deferred_publish_enabled": True,
                            "filter_plain_text_enabled": True,
                        }
                    ]
                }
            }
        )

        payload = await NitterWebAPI(_plugin(config)).build_groups()

        group = payload["groups"][0]
        self.assertEqual(group["name"], "科技")
        self.assertEqual(group["group_id"], "tech")
        self.assertEqual(group["watch_users"], ["OpenAI"])
        self.assertEqual(group["push_targets"], ["telegram:FriendMessage:1"])
        self.assertEqual(group["invalid_push_targets"], ["invalid target"])
        self.assertEqual(group["aliases"], ["tech-news"])
        self.assertTrue(group["interval_check_enabled"])
        self.assertTrue(group["deferred_publish_enabled"])
        self.assertTrue(group["filter_plain_text_enabled"])
        self.assertEqual(group["push_target_count"], 1)
        self.assertEqual(group["invalid_push_target_count"], 1)

    async def test_groups_payload_includes_attention_items(self):
        config = _Config(
            {
                "push": {
                    "tweet_groups": [
                        {
                            "name": "异常分组",
                            "group_id": "broken",
                            "enabled": False,
                            "watch_users": ["bad user"],
                            "push_targets": ["invalid target"],
                        }
                    ]
                }
            }
        )
        plugin = _plugin(config)
        plugin.scheduler.storage.summaries["broken"] = PendingQueueSummary(
            group_id="broken",
            pending_count=3,
            failed_count=2,
            media_count=1,
        )

        payload = await NitterWebAPI(plugin).build_groups()

        attention_keys = {
            item["key"] for item in payload["groups"][0]["attention_items"]
        }
        self.assertEqual(
            attention_keys,
            {
                "group_disabled",
                "no_watch_users",
                "no_push_targets",
                "invalid_watch_users",
                "invalid_push_targets",
                "failed_pending_tweets",
            },
        )

    async def test_pending_payload_does_not_expose_local_media_paths(self):
        config = _Config(
            {
                "push": {
                    "tweet_groups": [
                        {
                            "name": "科技",
                            "group_id": "tech",
                            "watch_users": ["OpenAI"],
                            "push_targets": ["telegram:FriendMessage:1"],
                        }
                    ]
                }
            }
        )
        plugin = _plugin(config)
        local_path = Path("D:/secret/cache/staged/tech/123/00_image.jpg")
        plugin.scheduler.storage.summaries["tech"] = PendingQueueSummary(
            group_id="tech",
            pending_count=1,
            failed_count=1,
            media_count=1,
        )
        plugin.scheduler.storage.records["tech"] = [
            PendingTweetRecord(
                id=9,
                group_id="tech",
                username="OpenAI",
                status_id="123",
                instance="https://nitter.test",
                tweet=TweetItem(
                    text="hello",
                    link="https://x.com/OpenAI/status/123",
                    published="2026-07-05",
                    media=[
                        TweetMedia(
                            "image",
                            "https://example.test/image.jpg",
                            local_path,
                        )
                    ],
                ),
                created_at=100,
                scheduled_at=200,
                failed_at=300,
                fail_count=2,
                last_error="send failed",
                delivered_targets=("telegram:FriendMessage:1",),
            )
        ]

        payload = await NitterWebAPI(plugin).build_pending("tech", 20)

        row = payload["records"][0]
        self.assertEqual(row["media_count"], 1)
        self.assertEqual(row["media_kinds"], ["image"])
        self.assertEqual(row["delivered_target_count"], 1)
        self.assertNotIn("path", row)
        self.assertNotIn("delivered_targets", row)
        self.assertNotIn("D:/secret", repr(payload))
        self.assertNotIn("telegram:FriendMessage:1", repr(payload))

    async def test_clear_cache_only_calls_non_staged_cache_cleanup(self):
        plugin = _plugin(_Config({}))

        payload = await NitterWebAPI(plugin).clear_cache()

        self.assertTrue(payload["success"])
        self.assertEqual(plugin.media.clear_non_staged_cache_calls, 1)
        self.assertEqual(plugin.scheduler.storage.clear_seen_calls, [])
        self.assertEqual(payload["result"]["removed"], 3)

    async def test_route_handler_returns_json_error_when_operation_raises(self):
        plugin = _plugin(_Config({}))
        plugin.media = _FailingMedia()

        try:
            payload = await _call_json_handler(
                NitterWebAPI(plugin).handle_cache_clear
            )
        except RuntimeError as exc:
            self.fail(f"route handler propagated exception: {exc}")

        self.assertFalse(payload["success"])
        self.assertIn("操作失败", payload["error"])

    async def test_clear_push_records_clears_seen_without_touching_config(self):
        config = _Config(
            {
                "push": {
                    "tweet_groups": [
                        {
                            "name": "科技",
                            "group_id": "tech",
                            "watch_users": ["OpenAI"],
                        }
                    ]
                }
            }
        )
        plugin = _plugin(config)

        payload = await NitterWebAPI(plugin).clear_seen("tech")

        self.assertTrue(payload["success"])
        self.assertEqual(plugin.scheduler.storage.clear_seen_calls, ["tech"])
        self.assertEqual(plugin.scheduler.storage.delete_legacy_seen_kv_calls, 1)
        self.assertFalse(config.saved)
        self.assertEqual(_group_config(config, "tech")["watch_users"], ["OpenAI"])

    async def test_seen_clear_handler_rejects_group_name_only_payload(self):
        config = _Config(
            {
                "push": {
                    "tweet_groups": [
                        {
                            "name": "科技",
                            "group_id": "tech",
                            "watch_users": ["OpenAI"],
                        }
                    ]
                }
            }
        )
        plugin = _plugin(config)
        api = NitterWebAPI(plugin)

        async def fake_request_json():
            return {"group_name": "tech"}

        original_request_json = api._request_json
        api._request_json = fake_request_json
        try:
            payload = await _call_json_handler(api.handle_seen_clear)
        finally:
            api._request_json = original_request_json

        self.assertFalse(payload["success"])
        self.assertIn("group_id", payload["error"])
        self.assertEqual(plugin.scheduler.storage.clear_seen_calls, [])

    async def test_run_check_rejects_disabled_group_without_starting_check(self):
        config = _Config(
            {
                "push": {
                    "tweet_groups": [
                        {
                            "name": "科技",
                            "group_id": "tech",
                            "enabled": False,
                            "watch_users": ["OpenAI"],
                            "push_targets": ["telegram:FriendMessage:1"],
                        }
                    ]
                }
            }
        )
        plugin = _plugin(config)

        payload = await NitterWebAPI(plugin).run_check({"group_id": "tech"})

        self.assertFalse(payload["success"])
        self.assertIn("分组已停用", payload["error"])
        self.assertEqual(plugin.scheduler.run_check_calls, [])

    async def test_subscription_import_and_delete_reuse_group_watch_user_behavior(self):
        config = _Config(
            {
                "push": {
                    "tweet_groups": [
                        {
                            "name": "科技",
                            "group_id": "tech",
                            "aliases": ["tech-news"],
                            "watch_users": ["OpenAI"],
                        }
                    ]
                }
            }
        )
        plugin = _plugin(config)
        api = NitterWebAPI(plugin)

        imported = await api.import_subscriptions(
            {"group_id": "tech", "entries": "BBCWorld,@SpaceX"}
        )
        deleted = await api.delete_subscriptions(
            {"group_id": "tech", "entries": "BBCWorld,Missing"}
        )

        self.assertTrue(imported["success"])
        self.assertTrue(deleted["success"])
        self.assertTrue(config.saved)
        self.assertEqual(
            _group_config(config, "tech")["watch_users"],
            ["OpenAI", "SpaceX"],
        )
        self.assertEqual(
            [group.group_id for group in plugin.scheduler.storage.synced_groups],
            ["tech"],
        )
        self.assertEqual(imported["summary"]["added"], ["BBCWorld", "SpaceX"])
        self.assertEqual(deleted["summary"]["removed"], ["BBCWorld"])
        self.assertEqual(deleted["summary"]["missing"], ["Missing"])

    async def test_push_history_query_filters_and_hides_media_paths(self):
        plugin = _plugin(
            _Config(
                {
                    "push": {
                        "tweet_groups": [
                            {"name": "科技", "group_id": "tech", "watch_users": []}
                        ]
                    }
                }
            )
        )
        plugin.scheduler.storage.history = [
            PushHistoryRecord(
                id=2,
                group_id="tech",
                username="OpenAI",
                status_id="200",
                original_link="https://x.com/OpenAI/status/200",
                target_umo="telegram:FriendMessage:2",
                source="scheduled",
                instance="https://nitter.test",
                pushed_at=2000,
                tweet=TweetItem(
                    text="model",
                    link="https://x.com/OpenAI/status/200",
                    published="",
                    media=[TweetMedia("image", "https://example.test/a.jpg", Path("C:/tmp/a.jpg"))],
                ),
            ),
            PushHistoryRecord(
                id=1,
                group_id="default",
                username="NASA",
                status_id="100",
                original_link="https://x.com/NASA/status/100",
                target_umo="telegram:FriendMessage:1",
                source="replay",
                instance="https://nitter.test",
                pushed_at=1000,
                tweet=TweetItem(
                    text="moon",
                    link="https://x.com/NASA/status/100",
                    published="",
                ),
            ),
        ]

        payload = await NitterWebAPI(plugin).build_history(
            group_id="tech",
            username="OpenAI",
            limit=50,
        )

        self.assertTrue(payload["success"])
        self.assertEqual(len(payload["records"]), 1)
        row = payload["records"][0]
        self.assertEqual(row["id"], 2)
        self.assertEqual(row["group_id"], "tech")
        self.assertEqual(row["username"], "OpenAI")
        self.assertEqual(row["target_umo"], "telegram:FriendMessage:2")
        self.assertNotIn("media", row)
        self.assertNotIn("C:/tmp/a.jpg", repr(row))

    async def test_push_history_paginates_and_partially_filters_usernames(self):
        plugin = _plugin(_Config({}))
        plugin.scheduler.storage.history = [
            PushHistoryRecord(
                id=index,
                group_id="default",
                username=username,
                status_id=str(index),
                original_link=f"https://x.com/{username}/status/{index}",
                target_umo="telegram:FriendMessage:1",
                source="scheduled",
                instance="https://nitter.test",
                pushed_at=1000 + index,
                tweet=TweetItem(
                    text=f"tweet {index}",
                    link=f"https://x.com/{username}/status/{index}",
                    published="",
                ),
            )
            for index, username in enumerate(
                ["Gongye_11", "OpenAI", "oioioi525", "mamania1008"], start=1
            )
        ]

        first_page = await NitterWebAPI(plugin).build_history(limit=2, offset=0)
        second_page = await NitterWebAPI(plugin).build_history(limit=2, offset=2)
        filtered = await NitterWebAPI(plugin).build_history(username="@oi", limit=10)

        self.assertEqual(first_page["limit"], 2)
        self.assertEqual(first_page["offset"], 0)
        self.assertEqual(first_page["page"], 1)
        self.assertTrue(first_page["has_next"])
        self.assertFalse(first_page["has_prev"])
        self.assertEqual(first_page["next_offset"], 2)
        self.assertEqual(
            [row["username"] for row in first_page["records"]],
            ["mamania1008", "oioioi525"],
        )
        self.assertEqual(second_page["page"], 2)
        self.assertTrue(second_page["has_prev"])
        self.assertFalse(second_page["has_next"])
        self.assertEqual(second_page["prev_offset"], 0)
        self.assertEqual(
            [row["username"] for row in second_page["records"]],
            ["OpenAI", "Gongye_11"],
        )
        self.assertEqual([row["username"] for row in filtered["records"]], ["oioioi525"])
        self.assertEqual(filtered["selected_username"], "oi")

    async def test_push_history_groups_multiple_targets_for_same_tweet(self):
        plugin = _plugin(
            _Config(
                {
                    "push": {
                        "tweet_groups": [
                            {
                                "name": "coser",
                                "group_id": "coser",
                                "watch_users": ["xixikawaii"],
                                "push_targets": [
                                    "default:GroupMessage:1",
                                    "lark:GroupMessage:2",
                                ],
                            }
                        ]
                    }
                }
            )
        )
        plugin.scheduler.storage.history = [
            PushHistoryRecord(
                id=11,
                group_id="coser",
                username="xixikawaii",
                status_id="207",
                original_link="https://x.com/xixikawaii/status/207",
                target_umo=target,
                source="scheduled",
                instance="https://nitter.test",
                pushed_at=2000 + index,
                tweet=TweetItem(
                    text="same tweet",
                    link="https://x.com/xixikawaii/status/207",
                    published="",
                ),
            )
            for index, target in enumerate(
                ["default:GroupMessage:1", "lark:GroupMessage:2"]
            )
        ]

        payload = await NitterWebAPI(plugin).build_history(limit=10)

        self.assertTrue(payload["success"])
        self.assertEqual(len(payload["records"]), 1)
        record = payload["records"][0]
        self.assertEqual(record["target_count"], 2)
        self.assertEqual(
            record["target_umos"],
            ["lark:GroupMessage:2", "default:GroupMessage:1"],
        )
        self.assertEqual(
            record["replay_target_options"],
            [
                {
                    "umo": "default:GroupMessage:1",
                    "historical": True,
                    "available": True,
                },
                {
                    "umo": "lark:GroupMessage:2",
                    "historical": True,
                    "available": True,
                },
            ],
        )

    async def test_replay_push_history_uses_scheduler_result(self):
        plugin = _plugin(_Config({}))

        payload = await NitterWebAPI(plugin).replay_history(
            {"record_id": 12, "target_umos": ["telegram:FriendMessage:2"]}
        )

        self.assertTrue(payload["success"])
        self.assertEqual(
            plugin.scheduler.replay_push_history_calls,
            [(12, ["telegram:FriendMessage:2"])],
        )
        self.assertEqual(payload["target_count"], 2)

    async def test_replay_push_history_rejects_missing_current_targets(self):
        plugin = _plugin(_Config({}))

        payload = await NitterWebAPI(plugin).replay_history({"record_id": 400})

        self.assertFalse(payload["success"])
        self.assertIn("推送目标", payload["error"])

    async def test_subscription_import_reports_save_error_without_losing_runtime_update(self):
        config = _FailingSaveConfig(
            {
                "push": {
                    "tweet_groups": [
                        {
                            "name": "科技",
                            "group_id": "tech",
                            "watch_users": ["OpenAI"],
                        }
                    ]
                }
            }
        )
        plugin = _plugin(config)

        payload = await NitterWebAPI(plugin).import_subscriptions(
            {"group_id": "tech", "entries": "BBCWorld"}
        )

        self.assertTrue(payload["success"])
        self.assertEqual(payload["summary"]["added"], ["BBCWorld"])
        self.assertEqual(payload["summary"]["save_error"], "config locked")
        self.assertIn("配置保存失败", payload["message"])
        self.assertEqual(_group_config(config, "tech")["watch_users"], ["OpenAI", "BBCWorld"])
        self.assertEqual(
            [group.group_id for group in plugin.scheduler.storage.synced_groups],
            ["tech"],
        )

    async def test_subscription_delete_reports_save_error_without_losing_runtime_update(self):
        config = _FailingSaveConfig(
            {
                "push": {
                    "tweet_groups": [
                        {
                            "name": "科技",
                            "group_id": "tech",
                            "watch_users": ["OpenAI", "BBCWorld"],
                        }
                    ]
                }
            }
        )
        plugin = _plugin(config)

        payload = await NitterWebAPI(plugin).delete_subscriptions(
            {"group_id": "tech", "entries": "BBCWorld"}
        )

        self.assertTrue(payload["success"])
        self.assertEqual(payload["summary"]["removed"], ["BBCWorld"])
        self.assertEqual(payload["summary"]["save_error"], "config locked")
        self.assertIn("配置保存失败", payload["message"])
        self.assertEqual(_group_config(config, "tech")["watch_users"], ["OpenAI"])
        self.assertEqual(
            [group.group_id for group in plugin.scheduler.storage.synced_groups],
            ["tech"],
        )

    async def test_mirror_probe_requires_full_url_and_does_not_mutate_config(self):
        config = _Config({"default_limit": 5})
        plugin = _plugin(config)

        payload = await NitterWebAPI(plugin).probe_mirror(
            {"username": "NASA", "limit": 3, "instance": "nitter.test"}
        )

        self.assertFalse(payload["success"])
        self.assertIn("完整", payload["error"])
        self.assertEqual(plugin.nitter.calls, [])
        self.assertFalse(config.saved)


if __name__ == "__main__":
    unittest.main()
