from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys
import types
import unittest


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
        def __init__(self, *args, **kwargs):
            pass

        @classmethod
        def fromFileSystem(cls, path):
            return cls(path)

    class _Video:
        def __init__(self, *args, **kwargs):
            pass

        @classmethod
        def fromFileSystem(cls, path):
            return cls(path)

    class _Node:
        def __init__(self, *args, **kwargs):
            pass

    class _Nodes:
        def __init__(self, *args, **kwargs):
            self.nodes = []

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


from main import NitterTweetsPlugin
from config import (
    DEFAULT_GROUP_CONFIG_MIGRATION_KEY,
    DEFAULT_MAX_VIDEO_DURATION_MINUTES,
    LEGACY_CONFIG_MIGRATION_KEY,
    MEDIA_CACHE_CLEANUP_MIGRATION_KEY,
    MEDIA_CACHE_SEND_DELETE_MIGRATION_KEY,
    TWEET_GROUP_TEMPLATE_KEY,
    TWEET_GROUP_TEMPLATE_KEY_FIELD,
    config_get,
    config_set,
    migrate_default_group_config,
    migrate_legacy_grouped_config,
    sanitize_removed_feature_config,
)
from scheduler import ScheduledCheckResult, SchedulerConfigReader
from shared import TweetItem


class _Config(dict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.saved = False

    def save_config(self):
        self.saved = True


class _Storage:
    def __init__(self):
        self.synced_groups = []
        self.clear_seen_calls = []
        self.delete_legacy_seen_kv_calls = 0

    async def migrate_and_sync(self, schedule_groups):
        self.synced_groups = schedule_groups

    async def clear_seen_records(self, group_id=None):
        self.clear_seen_calls.append(group_id)
        return 12

    async def delete_legacy_seen_kv(self):
        self.delete_legacy_seen_kv_calls += 1
        return True


class _CheckResult:
    def format_message(self):
        return "检查结果"


class _Scheduler:
    def __init__(self, config):
        self.config_reader = SchedulerConfigReader(config, context=None)
        self.storage = _Storage()
        self.started = []
        self.run_check_calls = []

    def watch_users_info(self):
        return self.config_reader.watch_users_info()

    def start(self, reason=""):
        self.started.append(reason)

    async def run_check(self, **kwargs):
        self.run_check_calls.append(kwargs)
        return _CheckResult()

class _Event:
    def __init__(
        self,
        unified_msg_origin="telegram:FriendMessage:1",
        group_id="1",
        sender_id="user",
    ):
        self.messages: list[str] = []
        self.stopped = False
        self.unified_msg_origin = unified_msg_origin
        self._group_id = group_id
        self._sender_id = sender_id

    def stop_event(self):
        self.stopped = True

    def plain_result(self, text):
        return text

    async def send(self, message):
        self.messages.append(message)

    def get_group_id(self):
        return self._group_id

    def get_sender_id(self):
        return self._sender_id


class _ManualNitter:
    def __init__(self):
        self.calls = []

    async def fetch_tweets(self, username, limit):
        self.calls.append(("fetch_tweets", username, limit))
        return "https://nitter.test", []

    async def fetch_tweets_from_instance(self, instance, username, limit):
        self.calls.append(("fetch_tweets_from_instance", instance, username, limit))
        return instance, []


class _ManualTranslator:
    def __init__(self, events):
        self.events = events

    async def attach_translations(self, tweets, umo=None):
        self.events.append(
            "translate:" + ",".join(tweet.status_id for tweet in tweets)
        )


class _ManualMedia:
    def __init__(self, events):
        self.events = events

    async def attach_media(self, tweets):
        self.events.append("media:" + ",".join(tweet.status_id for tweet in tweets))

    def cleanup_after_send(self, tweets):
        self.events.append(
            "cleanup:" + ",".join(tweet.status_id for tweet in tweets)
        )


class _StartupCleanupMedia:
    def __init__(self, *, failed=0):
        self.clear_cache_calls = 0
        self.failed = failed

    def clear_cache(self):
        self.clear_cache_calls += 1
        return types.SimpleNamespace(removed=2, failed=self.failed, skipped_dirs=1)


class _ManualRenderer:
    def format_plain(
        self,
        username,
        instance,
        tweets,
        start_index=1,
        notices=None,
        header_text="",
    ):
        ids = ",".join(tweet.status_id for tweet in tweets)
        return f"fallback:{username}:{ids}:{header_text}:{start_index}"


class _ManualSender:
    def __init__(self, events, should_merge=False):
        self.events = events
        self.renderer = _ManualRenderer()
        self._should_merge = should_merge
        self.start_indexes = []

    def should_merge_for_event(self, event, tweet_count):
        return self._should_merge

    async def send(
        self,
        event,
        username,
        instance,
        tweets,
        notices=None,
        header_text="",
        tweet_start_index=1,
    ):
        ids = ",".join(tweet.status_id for tweet in tweets)
        self.events.append(f"send:{username}:{ids}:{header_text}")
        self.start_indexes.append(tweet_start_index)
        return True


def _plugin(config):
    plugin = object.__new__(NitterTweetsPlugin)
    plugin.config = config
    plugin.scheduler = _Scheduler(config)
    return plugin


def _manual_plugin(config):
    plugin = _plugin(config)
    plugin.default_limit = NitterTweetsPlugin._parse_positive_limit(
        config.get("default_limit", 5), 5
    )
    plugin.nitter = _ManualNitter()
    plugin.translator = None
    plugin.media = None
    plugin.sender = None
    plugin._cooldowns = {}
    plugin.cooldown_seconds = 0
    return plugin


def _group_config(config, group_id: str):
    for group in config_get(config, "tweet_groups", []) or []:
        if isinstance(group, dict) and group.get("group_id") == group_id:
            return group
    raise AssertionError(f"group not found: {group_id}")


class CommandMetadataTest(unittest.TestCase):
    def test_command_handlers_have_ui_descriptions(self):
        command_methods = [
            "cmd_tweets",
            "cmd_mirror_probe",
            "cmd_tweets_status",
            "cmd_tweets_check",
            "cmd_tweets_clear_cache",
            "cmd_tweets_clear_seen",
            "cmd_tweets_list",
            "cmd_tweets_export_subscriptions",
            "cmd_tweets_delete_subscriptions",
            "cmd_tweets_dedup",
            "cmd_tweets_import",
        ]

        for method_name in command_methods:
            with self.subTest(method_name=method_name):
                doc = getattr(NitterTweetsPlugin, method_name).__doc__
                self.assertIsNotNone(doc)
                self.assertTrue(doc.strip())


class ConfigCompatTest(unittest.TestCase):
    def test_explicit_plugin_versions_are_0_16_0(self):
        root = Path(__file__).resolve().parents[1]
        metadata_text = (root / "metadata.yaml").read_text(encoding="utf-8")
        main_text = (root / "main.py").read_text(encoding="utf-8")
        readme_text = (root / "README.md").read_text(encoding="utf-8")
        changelog_text = (root / "CHANGELOG.md").read_text(encoding="utf-8")

        metadata_version = re.search(
            r"^version:\s*([^\s]+)$", metadata_text, re.MULTILINE
        )
        main_version = re.search(
            r'@register\(\s*"astrbot_plugin_nitter_tweets",\s*"[^"]+",\s*"[^"]+",\s*"([^"]+)"',
            main_text,
        )
        readme_version = re.search(
            r"version-([0-9]+\.[0-9]+\.[0-9]+)-blue", readme_text
        )
        changelog_version = re.search(
            r"^## \[([0-9]+\.[0-9]+\.[0-9]+)\]",
            changelog_text,
            re.MULTILINE,
        )

        self.assertIsNotNone(metadata_version)
        self.assertIsNotNone(main_version)
        self.assertIsNotNone(readme_version)
        self.assertIsNotNone(changelog_version)
        self.assertEqual(
            [
                metadata_version.group(1),
                main_version.group(1),
                readme_version.group(1),
                changelog_version.group(1),
            ],
            ["0.16.0"] * 4,
        )

    def test_conf_schema_is_grouped(self):
        schema_path = Path(__file__).resolve().parents[1] / "_conf_schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))

        self.assertEqual(
            list(schema)[:7],
            [
                "basic",
                "media",
                "ai_translation",
                "schedule",
                "push",
                "logging",
                "performance",
            ],
        )
        self.assertIn(LEGACY_CONFIG_MIGRATION_KEY, schema)
        for key in [
            LEGACY_CONFIG_MIGRATION_KEY,
            DEFAULT_GROUP_CONFIG_MIGRATION_KEY,
            MEDIA_CACHE_CLEANUP_MIGRATION_KEY,
            MEDIA_CACHE_SEND_DELETE_MIGRATION_KEY,
            "_max_video_duration_grouped_config_migrated",
        ]:
            self.assertIn(key, schema)
            self.assertTrue(schema[key]["invisible"])
        self.assertTrue(schema["watch_users"]["invisible"])
        self.assertEqual(schema["tweet_groups"]["type"], "list")
        self.assertIn("watch_users", schema["push"]["items"])
        self.assertIn("brief_log_enabled", schema["logging"]["items"])
        self.assertIn("filter_reposts_enabled", schema["basic"]["items"])
        self.assertNotIn("media_cache_retention_days", schema["media"]["items"])
        self.assertNotIn("media_cache_retention_days", schema)
        performance_items = schema["performance"]["items"]
        for key in [
            "concurrent_fetch_enabled",
            "fetch_concurrency",
            "concurrent_fetch_instances",
            "concurrent_prepare_enabled",
            "prepare_concurrency",
        ]:
            self.assertIn(key, performance_items)
            self.assertTrue(schema[key]["invisible"])
        self.assertFalse(performance_items["concurrent_fetch_enabled"]["default"])
        self.assertEqual(performance_items["fetch_concurrency"]["default"], 3)
        self.assertEqual(performance_items["concurrent_fetch_instances"]["default"], [])
        self.assertFalse(performance_items["concurrent_prepare_enabled"]["default"])
        self.assertEqual(performance_items["prepare_concurrency"]["default"], 2)
        self.assertIn(
            "filter_plain_text_enabled",
            schema["push"]["items"]["tweet_groups"]["templates"]["group"]["items"],
        )
        group_items = schema["push"]["items"]["tweet_groups"]["templates"]["group"]["items"]
        self.assertIn("group_id", group_items)
        self.assertTrue(group_items["group_id"]["invisible"])

    def test_max_video_duration_schema_defaults_match_runtime_default(self):
        schema_path = Path(__file__).resolve().parents[1] / "_conf_schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))

        for field in [
            schema["media"]["items"]["max_video_duration_minutes"],
            schema["max_video_duration_minutes"],
        ]:
            self.assertEqual(
                field["default"], DEFAULT_MAX_VIDEO_DURATION_MINUTES
            )

    def test_brief_log_config_defaults_enabled_for_old_configs(self):
        self.assertIs(config_get({}, "brief_log_enabled", True), True)

    def test_filter_reposts_config_defaults_enabled_for_old_configs(self):
        self.assertIs(config_get({}, "filter_reposts_enabled", True), True)

    def test_config_get_prefers_grouped_value(self):
        config = {
            "translate_enabled": False,
            "ai_translation": {"translate_enabled": True},
        }

        self.assertIs(config_get(config, "translate_enabled", False), True)

    def test_config_get_reads_grouped_brief_log_value(self):
        config = {"logging": {"brief_log_enabled": False}}

        self.assertIs(config_get(config, "brief_log_enabled", True), False)

    def test_config_get_reads_grouped_filter_reposts_value(self):
        config = {"basic": {"filter_reposts_enabled": False}}

        self.assertIs(config_get(config, "filter_reposts_enabled", True), False)

    def test_config_get_reads_grouped_max_video_duration(self):
        config = {
            "max_video_duration_minutes": 8.0,
            "media": {"max_video_duration_minutes": 3.0},
        }

        self.assertEqual(
            config_get(config, "max_video_duration_minutes", 8.0),
            3.0,
        )

    def test_config_get_reads_grouped_performance_values(self):
        config = {
            "fetch_concurrency": 1,
            "performance": {
                "concurrent_fetch_enabled": True,
                "fetch_concurrency": 4,
                "concurrent_fetch_instances": ["https://mirror.example"],
                "concurrent_prepare_enabled": True,
                "prepare_concurrency": 3,
            },
        }

        self.assertIs(config_get(config, "concurrent_fetch_enabled", False), True)
        self.assertEqual(config_get(config, "fetch_concurrency", 1), 4)
        self.assertEqual(
            config_get(config, "concurrent_fetch_instances", []),
            ["https://mirror.example"],
        )
        self.assertIs(config_get(config, "concurrent_prepare_enabled", False), True)
        self.assertEqual(config_get(config, "prepare_concurrency", 1), 3)

    def test_config_get_falls_back_to_flat_value(self):
        config = {"push_targets": ["telegram:FriendMessage:1"]}

        self.assertEqual(
            config_get(config, "push_targets", []),
            ["telegram:FriendMessage:1"],
        )

    def test_config_set_writes_grouped_value(self):
        config = {}

        config_set(config, "watch_users", ["NASA"])

        self.assertEqual(config, {"push": {"watch_users": ["NASA"]}})

    def test_migrate_legacy_grouped_config_copies_flat_values_once(self):
        config = _Config(
            {
                "default_limit": 9,
                "max_video_duration_minutes": 3.0,
                "schedule_enabled": True,
                "watch_users": ["NASA"],
                "push_targets": ["telegram:FriendMessage:1"],
                "basic": {"default_limit": 5},
                "media": {"max_video_duration_minutes": 8.0},
                "schedule": {"schedule_enabled": False},
                "push": {"watch_users": [], "push_targets": []},
            }
        )

        changed = migrate_legacy_grouped_config(config)
        config["watch_users"] = ["SHOULD_NOT_OVERWRITE"]
        config["push"]["watch_users"] = ["OpenAI"]
        second_changed = migrate_legacy_grouped_config(config)

        self.assertTrue(changed)
        self.assertFalse(second_changed)
        self.assertTrue(config.saved)
        self.assertTrue(config[LEGACY_CONFIG_MIGRATION_KEY])
        self.assertEqual(config["basic"]["default_limit"], 9)
        self.assertEqual(config["media"]["max_video_duration_minutes"], 3.0)
        self.assertTrue(config["schedule"]["schedule_enabled"])
        self.assertEqual(config["push"]["watch_users"], ["OpenAI"])
        self.assertEqual(
            config["push"]["push_targets"], ["telegram:FriendMessage:1"]
        )

    def test_removed_feature_config_is_cleaned_after_legacy_migration_completed(self):
        config = _Config(
            {
                LEGACY_CONFIG_MIGRATION_KEY: True,
                "ai_comment": {"comment_enabled": True},
                "ai_vision": {"vision_enabled": True},
                "deferred": {"deferred_publish_enabled": True},
                "comment_enabled": True,
                "vision_max_total": 6,
                "deferred_publish_times": ["08:00"],
                "ai_translation": {"translate_enabled": True},
                "push": {
                    "tweet_groups": [
                        {
                            "name": "科技",
                            "group_id": "tech",
                            "watch_users": ["OpenAI"],
                            "deferred_publish_enabled": True,
                        }
                    ]
                },
            }
        )

        changed = migrate_legacy_grouped_config(config)
        config.saved = False
        second_changed = sanitize_removed_feature_config(config)

        self.assertTrue(changed)
        self.assertFalse(second_changed)
        self.assertFalse(config.saved)
        self.assertNotIn("ai_comment", config)
        self.assertNotIn("ai_vision", config)
        self.assertNotIn("deferred", config)
        self.assertNotIn("comment_enabled", config)
        self.assertNotIn("vision_max_total", config)
        self.assertNotIn("deferred_publish_times", config)
        self.assertTrue(config["ai_translation"]["translate_enabled"])
        group = config["push"]["tweet_groups"][0]
        self.assertNotIn("deferred_publish_enabled", group)
        self.assertEqual(group["watch_users"], ["OpenAI"])

    def test_legacy_group_migration_repairs_late_video_duration_field_once(self):
        config = _Config(
            {
                LEGACY_CONFIG_MIGRATION_KEY: True,
                "max_video_duration_minutes": 3.0,
                "media": {"max_video_duration_minutes": 8.0},
            }
        )

        changed = migrate_legacy_grouped_config(config)
        config["media"]["max_video_duration_minutes"] = 4.0
        second_changed = migrate_legacy_grouped_config(config)

        self.assertTrue(changed)
        self.assertFalse(second_changed)
        self.assertTrue(config.saved)
        self.assertTrue(config["_max_video_duration_grouped_config_migrated"])
        self.assertEqual(config["media"]["max_video_duration_minutes"], 4.0)

    def test_late_video_duration_migration_preserves_custom_grouped_value(self):
        config = _Config(
            {
                LEGACY_CONFIG_MIGRATION_KEY: True,
                "max_video_duration_minutes": 8.0,
                "media": {"max_video_duration_minutes": 3.0},
            }
        )

        changed = migrate_legacy_grouped_config(config)

        self.assertTrue(changed)
        self.assertTrue(config["_max_video_duration_grouped_config_migrated"])
        self.assertEqual(config["media"]["max_video_duration_minutes"], 3.0)

    def test_late_video_duration_migration_saves_marker_only_once(self):
        config = _Config(
            {
                LEGACY_CONFIG_MIGRATION_KEY: True,
                "max_video_duration_minutes": 8.0,
                "media": {"max_video_duration_minutes": 3.0},
            }
        )

        changed = migrate_legacy_grouped_config(config)
        self.assertTrue(config.saved)
        config.saved = False
        second_changed = migrate_legacy_grouped_config(config)

        self.assertTrue(changed)
        self.assertFalse(second_changed)
        self.assertFalse(config.saved)
        self.assertTrue(config["_max_video_duration_grouped_config_migrated"])
        self.assertEqual(config["media"]["max_video_duration_minutes"], 3.0)

    def test_late_video_duration_migration_creates_missing_media_group(self):
        config = _Config(
            {
                LEGACY_CONFIG_MIGRATION_KEY: True,
                "max_video_duration_minutes": 3.0,
            }
        )

        changed = migrate_legacy_grouped_config(config)

        self.assertTrue(changed)
        self.assertTrue(config.saved)
        self.assertTrue(config["_max_video_duration_grouped_config_migrated"])
        self.assertEqual(config["media"], {"max_video_duration_minutes": 3.0})

    def test_late_video_duration_migration_replaces_malformed_media_group(self):
        config = _Config(
            {
                LEGACY_CONFIG_MIGRATION_KEY: True,
                "max_video_duration_minutes": 3.0,
                "media": "invalid",
            }
        )

        changed = migrate_legacy_grouped_config(config)

        self.assertTrue(changed)
        self.assertTrue(config.saved)
        self.assertTrue(config["_max_video_duration_grouped_config_migrated"])
        self.assertEqual(config["media"], {"max_video_duration_minutes": 3.0})

    def test_late_video_duration_migration_normalizes_malformed_media_without_legacy_value(
        self,
    ):
        config = _Config(
            {
                LEGACY_CONFIG_MIGRATION_KEY: True,
                "media": "invalid",
            }
        )

        changed = migrate_legacy_grouped_config(config)

        self.assertTrue(changed)
        self.assertTrue(config.saved)
        self.assertTrue(config["_max_video_duration_grouped_config_migrated"])
        self.assertEqual(config["media"], {})

    def test_first_group_migration_preserves_custom_video_duration(self):
        config = _Config(
            {
                "max_video_duration_minutes": 8.0,
                "media": {"max_video_duration_minutes": 3.0},
            }
        )

        changed = migrate_legacy_grouped_config(config)

        self.assertTrue(changed)
        self.assertTrue(config[LEGACY_CONFIG_MIGRATION_KEY])
        self.assertTrue(config["_max_video_duration_grouped_config_migrated"])
        self.assertEqual(config["media"]["max_video_duration_minutes"], 3.0)

    def test_default_group_migration_leaves_empty_groups_empty(self):
        config = _Config({"tweet_groups": []})

        changed = migrate_default_group_config(config)

        self.assertFalse(changed)
        self.assertFalse(config.saved)
        self.assertEqual(config_get(config, "tweet_groups"), [])

    def test_default_group_migration_moves_legacy_top_level_config(self):
        config = _Config(
            {
                "watch_users": ["NASA"],
                "push_targets": ["telegram:FriendMessage:1"],
                "schedule_enabled": True,
                "scheduled_fetch_limit": 7,
                "tweet_groups": [
                    {
                        "name": "Tech",
                        "group_id": "tech",
                        "watch_users": ["OpenAI"],
                    }
                ],
            }
        )

        changed = migrate_default_group_config(config)

        self.assertTrue(changed)
        self.assertTrue(config.saved)
        default_group = _group_config(config, "default")
        self.assertEqual(default_group["name"], "默认分组")
        self.assertEqual(default_group["watch_users"], ["NASA"])
        self.assertEqual(default_group["push_targets"], ["telegram:FriendMessage:1"])
        self.assertNotIn("schedule_enabled", default_group)
        self.assertNotIn("scheduled_fetch_limit", default_group)
        self.assertTrue(config_get(config, "schedule_enabled"))
        self.assertEqual(config_get(config, "scheduled_fetch_limit"), 7)
        self.assertEqual(_group_config(config, "tech")["watch_users"], ["OpenAI"])
        self.assertEqual(
            default_group[TWEET_GROUP_TEMPLATE_KEY_FIELD],
            TWEET_GROUP_TEMPLATE_KEY,
        )
        self.assertEqual(
            _group_config(config, "tech")[TWEET_GROUP_TEMPLATE_KEY_FIELD],
            TWEET_GROUP_TEMPLATE_KEY,
        )

    def test_default_group_migration_repairs_template_key_after_marker(self):
        config = _Config(
            {
                "_default_group_config_migrated": True,
                "tweet_groups": [
                    {
                        "name": "默认分组",
                        "group_id": "default",
                        "watch_users": ["NASA"],
                    },
                    {
                        "name": "Tech",
                        "group_id": "tech",
                        "watch_users": ["OpenAI"],
                    },
                ],
            }
        )

        changed = migrate_default_group_config(config)

        self.assertTrue(changed)
        self.assertTrue(config.saved)
        self.assertEqual(
            _group_config(config, "default")[TWEET_GROUP_TEMPLATE_KEY_FIELD],
            TWEET_GROUP_TEMPLATE_KEY,
        )
        self.assertEqual(
            _group_config(config, "tech")[TWEET_GROUP_TEMPLATE_KEY_FIELD],
            TWEET_GROUP_TEMPLATE_KEY,
        )

    def test_default_group_migration_assigns_missing_custom_group_ids(self):
        config = _Config(
            {
                "_default_group_config_migrated": True,
                "tweet_groups": [
                    {
                        "name": "Existing",
                        "group_id": "tech",
                        "watch_users": ["OpenAI"],
                    },
                    {
                        "name": "Legacy Without ID",
                        "watch_users": ["NASA"],
                    },
                    {
                        "name": "coser",
                        "watch_users": ["CoserAccount"],
                    },
                    {
                        "name": "Already Allocated",
                        "group_id": "group_1",
                        "watch_users": ["ESA"],
                    },
                    {
                        "name": "Another Legacy",
                        "watch_users": ["JAXA"],
                    },
                ],
            }
        )

        changed = migrate_default_group_config(config)

        self.assertTrue(changed)
        self.assertTrue(config.saved)
        groups = config_get(config, "tweet_groups")
        self.assertEqual([group["group_id"] for group in groups], [
            "tech",
            "group_2",
            "coser",
            "group_1",
            "group_3",
        ])
        self.assertEqual(_group_config(config, "tech")["watch_users"], ["OpenAI"])
        self.assertEqual(_group_config(config, "group_2")["name"], "Legacy Without ID")
        self.assertEqual(_group_config(config, "coser")["watch_users"], ["CoserAccount"])
        self.assertEqual(_group_config(config, "group_3")["watch_users"], ["JAXA"])

    def test_default_group_migration_preserves_existing_legacy_global_group_id(self):
        config = _Config(
            {
                "tweet_groups": [
                    {
                        "name": "Global",
                        "group_id": "global",
                        "watch_users": ["NASA"],
                    }
                ],
            }
        )

        changed = migrate_default_group_config(config)

        self.assertTrue(changed)
        self.assertTrue(config.saved)
        groups = config_get(config, "tweet_groups")
        self.assertEqual(groups[0]["group_id"], "global")
        self.assertEqual(groups[0]["watch_users"], ["NASA"])

    def test_startup_media_cache_upgrade_cleanup_runs_once(self):
        config = _Config({})
        media = _StartupCleanupMedia()
        plugin = object.__new__(NitterTweetsPlugin)
        plugin.config = config
        plugin.media = media

        NitterTweetsPlugin._cleanup_legacy_media_cache_once(plugin)
        self.assertEqual(media.clear_cache_calls, 1)
        self.assertTrue(config.saved)
        self.assertTrue(config[MEDIA_CACHE_SEND_DELETE_MIGRATION_KEY])

        config.saved = False
        NitterTweetsPlugin._cleanup_legacy_media_cache_once(plugin)
        self.assertEqual(media.clear_cache_calls, 1)
        self.assertFalse(config.saved)

    def test_startup_media_cache_cleanup_does_not_reuse_legacy_marker(self):
        # A truthy marker from the previous release must not skip the current
        # cleanup pass.
        config = _Config({"_media_cache_send_delete_migrated": True})
        media = _StartupCleanupMedia()
        plugin = object.__new__(NitterTweetsPlugin)
        plugin.config = config
        plugin.media = media

        NitterTweetsPlugin._cleanup_legacy_media_cache_once(plugin)

        self.assertEqual(media.clear_cache_calls, 1)
        self.assertTrue(config[MEDIA_CACHE_CLEANUP_MIGRATION_KEY])
        self.assertTrue(config[MEDIA_CACHE_SEND_DELETE_MIGRATION_KEY])

    def test_startup_media_cache_upgrade_cleanup_retries_after_failures(self):
        config = _Config({})
        media = _StartupCleanupMedia(failed=1)
        plugin = object.__new__(NitterTweetsPlugin)
        plugin.config = config
        plugin.media = media

        NitterTweetsPlugin._cleanup_legacy_media_cache_once(plugin)
        self.assertEqual(media.clear_cache_calls, 1)
        self.assertFalse(config.saved)
        self.assertNotIn(MEDIA_CACHE_SEND_DELETE_MIGRATION_KEY, config)

        media.failed = 0
        NitterTweetsPlugin._cleanup_legacy_media_cache_once(plugin)
        self.assertEqual(media.clear_cache_calls, 2)
        self.assertTrue(config.saved)
        self.assertTrue(config[MEDIA_CACHE_SEND_DELETE_MIGRATION_KEY])

    def test_default_group_migration_merges_legacy_global_group(self):
        config = _Config(
            {
                "watch_users": ["OpenAI"],
                "scheduled_fetch_limit": 3,
                "tweet_groups": [
                    {
                        "name": "默认分组",
                        "group_id": "default",
                        "watch_users": ["NASA"],
                        "scheduled_fetch_limit": 9,
                    },
                    {
                        "name": "全局分组",
                        "group_id": "global",
                        "watch_users": ["NASA", "ESA"],
                        "push_targets": ["telegram:FriendMessage:1"],
                        "scheduled_fetch_limit": 5,
                    },
                    {
                        "name": "Tech",
                        "group_id": "tech",
                        "watch_users": ["Anthropic"],
                    },
                ],
            }
        )

        changed = migrate_default_group_config(config)

        self.assertTrue(changed)
        default_group = _group_config(config, "default")
        self.assertEqual(default_group["watch_users"], ["NASA", "ESA", "OpenAI"])
        self.assertEqual(default_group["push_targets"], ["telegram:FriendMessage:1"])
        self.assertEqual(config_get(config, "scheduled_fetch_limit"), 3)
        self.assertIn("global", default_group["aliases"])
        self.assertEqual(
            [group["group_id"] for group in config_get(config, "tweet_groups")],
            ["default", "tech"],
        )

    def test_astrbot_config_upgrade_preserves_legacy_flat_values(self):
        repo = Path(__file__).resolve().parents[1]
        script = r"""
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from astrbot.core.config.astrbot_config import AstrBotConfig
from config import config_get, migrate_legacy_grouped_config

repo = Path.cwd()
schema = json.loads((repo / "_conf_schema.json").read_text(encoding="utf-8"))
legacy_config = {
    "schedule_enabled": True,
    "watch_users": ["NASA"],
    "push_targets": ["telegram:FriendMessage:1"],
    "default_limit": 9,
}
with TemporaryDirectory() as temp_dir:
    config_path = Path(temp_dir) / "plugin_config.json"
    config_path.write_text(
        json.dumps(legacy_config, ensure_ascii=False),
        encoding="utf-8-sig",
    )
    config = AstrBotConfig(config_path=str(config_path), schema=schema)
    migrate_legacy_grouped_config(config)
    print(
        "RESULT:"
        + json.dumps(
            {
                "schedule_enabled": config_get(config, "schedule_enabled"),
                "watch_users": config_get(config, "watch_users"),
                "push_targets": config_get(config, "push_targets"),
                "default_limit": config_get(config, "default_limit"),
            },
            ensure_ascii=False,
        )
    )
"""

        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        )
        result_line = next(
            line.removeprefix("RESULT:")
            for line in completed.stdout.splitlines()
            if line.startswith("RESULT:")
        )

        self.assertEqual(
            json.loads(result_line),
            {
                "schedule_enabled": True,
                "watch_users": ["NASA"],
                "push_targets": ["telegram:FriendMessage:1"],
                "default_limit": 9,
            },
        )

    def test_scheduler_reader_reads_grouped_config(self):
        config = {
            "schedule": {
                "schedule_enabled": True,
                "scheduled_fetch_limit": 7,
                "check_interval_minutes": 11,
                "check_on_startup": True,
                "notify_no_updates": True,
            },
            "push": {
                "watch_users": ["NASA"],
                "push_targets": ["telegram:FriendMessage:1"],
                "send_target_interval": 0.25,
                "send_user_interval": 0.5,
                "tweet_groups": [
                    {
                        "name": "Tech",
                        "group_id": "tech",
                        "watch_users": ["OpenAI"],
                        "push_targets": ["telegram:FriendMessage:2"],
                        "daily_check_times": ["08:30"],
                        
                        "scheduled_fetch_limit": 19,
                        "send_target_interval": 9,
                        "filter_plain_text_enabled": True,
                    }
                ],
            },
        }
        reader = SchedulerConfigReader(config, context=None)

        global_group, tech_group = reader.schedule_groups(log_invalid_targets=False)

        self.assertTrue(global_group.enabled)
        self.assertEqual(global_group.users, ["NASA"])
        self.assertEqual(global_group.targets, ["telegram:FriendMessage:1"])
        self.assertEqual(global_group.scheduled_fetch_limit, 7)
        self.assertEqual(global_group.check_interval_minutes, 11)
        self.assertTrue(global_group.check_on_startup)
        self.assertTrue(global_group.notify_no_updates)
        self.assertEqual(global_group.daily_check_times, [])
        self.assertEqual(tech_group.group_id, "tech")
        self.assertEqual(tech_group.users, ["OpenAI"])
        self.assertEqual(tech_group.targets, ["telegram:FriendMessage:2"])
        self.assertEqual(tech_group.daily_check_times, [(8, 30)])
        self.assertEqual(tech_group.scheduled_fetch_limit, 7)
        self.assertEqual(tech_group.send_target_interval, 0.25)
        self.assertEqual(tech_group.send_user_interval, 0.5)
        self.assertTrue(tech_group.filter_plain_text_enabled)
        self.assertFalse(global_group.concurrent_fetch_enabled)
        self.assertEqual(global_group.fetch_concurrency, 3)
        self.assertEqual(global_group.concurrent_fetch_instances, [])
        self.assertFalse(global_group.concurrent_prepare_enabled)
        self.assertEqual(global_group.prepare_concurrency, 2)

    def test_scheduler_reader_preserves_existing_legacy_global_group_id(self):
        config = {
            "daily_check_enabled": True,
            "daily_check_times": ["08:30"],
            "tweet_groups": [
                {
                    "name": "Global",
                    "group_id": "global",
                    "watch_users": ["NASA"],
                    "push_targets": ["telegram:FriendMessage:1"],
                }
            ],
        }
        reader = SchedulerConfigReader(config, context=None)

        group = reader.schedule_groups(log_invalid_targets=False)[0]

        self.assertEqual(group.group_id, "global")
        self.assertEqual(group.name, "默认分组")
        self.assertEqual(group.daily_check_times, [(8, 30)])

    def test_scheduler_reader_preserves_safe_english_name_as_missing_group_id(self):
        reader = SchedulerConfigReader({}, context=None)

        group = reader.parse_schedule_group(
            {
                "name": "Tech123",
                "watch_users": ["NASA"],
                "push_targets": ["telegram:FriendMessage:1"],
            },
            3,
            log_invalid_targets=False,
        )

        self.assertIsNotNone(group)
        self.assertEqual(group.group_id, "tech123")
        self.assertEqual(group.name, "Tech123")

    def test_scheduler_reader_does_not_use_display_name_with_spaces_as_group_id(self):
        reader = SchedulerConfigReader({}, context=None)

        group = reader.parse_schedule_group(
            {
                "name": "Legacy Without ID",
                "watch_users": ["NASA"],
                "push_targets": ["telegram:FriendMessage:1"],
            },
            3,
            log_invalid_targets=False,
        )

        self.assertIsNotNone(group)
        self.assertEqual(group.group_id, "group_3")
        self.assertEqual(group.name, "Legacy Without ID")

    def test_scheduler_reader_reads_grouped_performance_config(self):
        config = {
            "watch_users": ["NASA"],
            "push_targets": ["telegram:FriendMessage:1"],
            "performance": {
                "concurrent_fetch_enabled": True,
                "fetch_concurrency": 99,
                "concurrent_fetch_instances": [
                    "mirror-a.example/",
                    "https://mirror-b.example",
                ],
                "concurrent_prepare_enabled": True,
                "prepare_concurrency": 0,
            },
        }
        reader = SchedulerConfigReader(config, context=None)

        group = reader.schedule_groups(log_invalid_targets=False)[0]

        self.assertTrue(group.concurrent_fetch_enabled)
        self.assertEqual(group.fetch_concurrency, 8)
        self.assertEqual(
            group.concurrent_fetch_instances,
            ["https://mirror-a.example", "https://mirror-b.example"],
        )
        self.assertTrue(group.concurrent_prepare_enabled)
        self.assertEqual(group.prepare_concurrency, 1)


    def test_scheduler_reader_keeps_plain_text_switch_per_group(self):
        config = {
            "filter_plain_text_enabled": True,
            "watch_users": ["NASA"],
            "push_targets": ["telegram:FriendMessage:1"],
            "tweet_groups": [
                {
                    "name": "Tech",
                    "group_id": "tech",
                    "watch_users": ["OpenAI"],
                    "push_targets": ["telegram:FriendMessage:2"],
                }
            ],
        }
        reader = SchedulerConfigReader(config, context=None)

        default_group, tech_group = reader.schedule_groups(log_invalid_targets=False)

        self.assertTrue(default_group.filter_plain_text_enabled)
        self.assertFalse(tech_group.filter_plain_text_enabled)



class SchedulerModelFormattingTest(unittest.TestCase):
    def test_failure_label_formats_all_users_as_accounts(self):
        result = ScheduledCheckResult(reason="test")
        result.failed_users["NASA"] = "failed"
        result.failed_users["@OpenAI"] = "failed"

        lines = result.format_brief_log_lines()
        self.assertIn("@NASA: failed", lines[1])
        self.assertIn("@OpenAI: failed", lines[1])


class SubscriptionImportTest(unittest.IsolatedAsyncioTestCase):
    async def test_manual_tweets_uses_default_limit_without_quantity(self):
        plugin = _manual_plugin(_Config({"default_limit": 5, "max_limit": 1}))
        event = _Event()

        await plugin.cmd_tweets(event, "NASA", "")

        self.assertEqual(plugin.nitter.calls, [("fetch_tweets", "NASA", 5)])
        self.assertIn("最近最多 5 条", event.messages[0])

    async def test_manual_tweets_does_not_clamp_requested_quantity(self):
        plugin = _manual_plugin(_Config({"default_limit": 5, "max_limit": 1}))
        event = _Event()

        await plugin.cmd_tweets(event, "NASA", "50")

        self.assertEqual(plugin.nitter.calls, [("fetch_tweets", "NASA", 50)])
        self.assertIn("最近最多 50 条", event.messages[0])

    async def test_manual_tweets_rejects_non_positive_quantity(self):
        plugin = _manual_plugin(_Config({"default_limit": 5}))
        event = _Event()

        await plugin.cmd_tweets(event, "NASA", "0")

        self.assertEqual(plugin.nitter.calls, [])
        self.assertIn("数量需要大于 0", event.messages[-1])

    async def test_manual_tweets_send_each_tweet_after_translation_and_media_prepare(self):
        events = []
        plugin = _manual_plugin(_Config({"default_limit": 5}))
        plugin.translator = _ManualTranslator(events)
        plugin.media = _ManualMedia(events)
        plugin.sender = _ManualSender(events)
        event = _Event()
        tweets = [
            TweetItem(
                text="first",
                link="https://x.com/NASA/status/101",
                published="",
            ),
            TweetItem(
                text="second",
                link="https://x.com/NASA/status/102",
                published="",
            ),
        ]

        await plugin._send_tweets_response(
            event, "NASA", "https://nitter.test", tweets
        )

        self.assertEqual(
            events,
            [
                "translate:101",
                "media:101",
                "send:NASA:101:@NASA 本次结果 1/2",
                "cleanup:101",
                "translate:102",
                "media:102",
                "send:NASA:102:@NASA 本次结果 2/2",
                "cleanup:102",
            ],
        )
        self.assertEqual(plugin.sender.start_indexes, [1, 2])

    async def test_mirror_probe_uses_default_limit_without_quantity(self):
        plugin = _manual_plugin(_Config({"default_limit": 5, "max_limit": 1}))
        event = _Event()

        await plugin.cmd_mirror_probe(event, "https://nitter.top")

        self.assertEqual(
            plugin.nitter.calls,
            [("fetch_tweets_from_instance", "https://nitter.top", "nasa", 5)],
        )
        self.assertIn("最近最多 5 条", event.messages[0])

    async def test_mirror_probe_does_not_clamp_requested_quantity(self):
        plugin = _manual_plugin(_Config({"default_limit": 5, "max_limit": 1}))
        event = _Event()

        await plugin.cmd_mirror_probe(event, "NASA 50 https://nitter.top")

        self.assertEqual(
            plugin.nitter.calls,
            [("fetch_tweets_from_instance", "https://nitter.top", "NASA", 50)],
        )
        self.assertIn("最近最多 50 条", event.messages[0])

    async def test_mirror_probe_requires_full_url_instance(self):
        plugin = _manual_plugin(_Config({"default_limit": 5}))
        event = _Event()

        await plugin.cmd_mirror_probe(event, "nitter.top")

        self.assertEqual(plugin.nitter.calls, [])
        self.assertIn("完整 Nitter 镜像站地址", event.messages[-1])

    async def test_mirror_probe_rejects_non_positive_quantity(self):
        plugin = _manual_plugin(_Config({"default_limit": 5}))
        event = _Event()

        await plugin.cmd_mirror_probe(event, "0 https://nitter.top")

        self.assertEqual(plugin.nitter.calls, [])
        self.assertIn("数量需要大于 0", event.messages[-1])

    async def test_check_without_group_uses_current_target_group(self):
        config = _Config(
            {
                "schedule_enabled": True,
                "watch_users": ["NASA"],
                "push_targets": ["telegram:FriendMessage:global"],
                "tweet_groups": [
                    {
                        "name": "Tech",
                        "group_id": "tech",
                        "watch_users": ["OpenAI"],
                        "push_targets": ["telegram:FriendMessage:1"],
                    }
                ],
            }
        )
        plugin = _plugin(config)
        event = _Event(unified_msg_origin="telegram:FriendMessage:1")

        await plugin.cmd_tweets_check(event)

        self.assertTrue(event.stopped)
        self.assertEqual(plugin.scheduler.started, ["manual_check"])
        self.assertEqual(len(plugin.scheduler.run_check_calls), 1)
        self.assertEqual(
            plugin.scheduler.run_check_calls[0],
            {
                "reason": "manual_command",
                "notify_no_updates": False,
                "group_name": "tech",
                "target_override": ["telegram:FriendMessage:1"],
                            },
        )
        self.assertIn("Tech (tech)", event.messages[0])
        self.assertEqual(event.messages[-1], "检查结果")

    async def test_check_without_group_uses_default_when_current_target_listed(self):
        config = _Config(
            {
                "schedule_enabled": False,
                "watch_users": ["NASA"],
                "push_targets": ["telegram:FriendMessage:global"],
                "tweet_groups": [
                    {
                        "name": "Tech",
                        "group_id": "tech",
                        "watch_users": ["OpenAI"],
                        "push_targets": ["telegram:FriendMessage:1"],
                    }
                ],
            }
        )
        plugin = _plugin(config)
        event = _Event(unified_msg_origin="telegram:FriendMessage:global")

        await plugin.cmd_tweets_check(event)

        self.assertTrue(event.stopped)
        self.assertEqual(plugin.scheduler.started, ["manual_check"])
        self.assertEqual(
            plugin.scheduler.run_check_calls[0],
            {
                "reason": "manual_command",
                "notify_no_updates": False,
                "group_name": "default",
                "target_override": ["telegram:FriendMessage:global"],
                            },
        )
        self.assertIn("默认分组 (default)", event.messages[0])

    async def test_check_without_group_rejects_target_outside_all_push_targets(self):
        config = _Config(
            {
                "schedule_enabled": True,
                "watch_users": ["NASA"],
                "push_targets": ["telegram:FriendMessage:global"],
                "tweet_groups": [
                    {
                        "name": "Tech",
                        "group_id": "tech",
                        "watch_users": ["OpenAI"],
                        "push_targets": ["telegram:FriendMessage:1"],
                    }
                ],
            }
        )
        plugin = _plugin(config)
        event = _Event(unified_msg_origin="telegram:FriendMessage:missing")

        await plugin.cmd_tweets_check(event)

        self.assertTrue(event.stopped)
        self.assertEqual(plugin.scheduler.started, [])
        self.assertEqual(plugin.scheduler.run_check_calls, [])
        self.assertIn("不在任何已启用用户分组", event.messages[-1])

    async def test_check_without_group_rejects_ambiguous_current_target(self):
        config = _Config(
            {
                "schedule_enabled": True,
                "watch_users": ["NASA"],
                "push_targets": ["telegram:FriendMessage:1"],
                "tweet_groups": [
                    {
                        "name": "Tech",
                        "group_id": "tech",
                        "watch_users": ["OpenAI"],
                        "push_targets": ["telegram:FriendMessage:1"],
                    }
                ],
            }
        )
        plugin = _plugin(config)
        event = _Event(unified_msg_origin="telegram:FriendMessage:1")

        await plugin.cmd_tweets_check(event)

        self.assertEqual(plugin.scheduler.started, [])
        self.assertEqual(plugin.scheduler.run_check_calls, [])
        self.assertIn("匹配到多个推文分组", event.messages[-1])
        self.assertIn("默认分组 (default)", event.messages[-1])
        self.assertIn("Tech (tech)", event.messages[-1])

    async def test_check_with_group_rejects_target_outside_group(self):
        config = _Config(
            {
                "schedule_enabled": True,
                "watch_users": ["NASA"],
                "push_targets": [],
                "tweet_groups": [
                    {
                        "name": "Tech",
                        "group_id": "tech",
                        "watch_users": ["OpenAI"],
                        "push_targets": ["telegram:FriendMessage:1"],
                    }
                ],
            }
        )
        plugin = _plugin(config)
        event = _Event(unified_msg_origin="telegram:FriendMessage:2")

        await plugin.cmd_tweets_check(event, "tech")

        self.assertEqual(plugin.scheduler.started, [])
        self.assertEqual(plugin.scheduler.run_check_calls, [])
        self.assertIn("当前对话不属于分组：Tech (tech)", event.messages[-1])

    async def test_check_with_default_alias_requires_current_target_listed(self):
        config = _Config(
            {
                "schedule_enabled": True,
                "watch_users": ["NASA"],
                "push_targets": ["telegram:FriendMessage:global"],
            }
        )
        plugin = _plugin(config)
        event = _Event(unified_msg_origin="telegram:FriendMessage:missing")

        await plugin.cmd_tweets_check(event, "global")

        self.assertEqual(plugin.scheduler.started, [])
        self.assertEqual(plugin.scheduler.run_check_calls, [])
        self.assertIn("当前对话不属于分组：默认分组 (default)", event.messages[-1])

    async def test_import_without_group_appends_default_watch_users(self):
        config = _Config(
            {
                "watch_users": ["NASA"],
                "tweet_groups": [
                    {"name": "科技", "group_id": "tech", "watch_users": []}
                ],
            }
        )
        plugin = _plugin(config)
        event = _Event()

        await plugin.cmd_tweets_import(event, "BBCWorld,@SpaceX")

        self.assertTrue(event.stopped)
        self.assertTrue(config.saved)
        self.assertEqual(
            _group_config(config, "default")["watch_users"],
            ["NASA", "BBCWorld", "SpaceX"],
        )
        self.assertEqual(_group_config(config, "tech")["watch_users"], [])
        self.assertIn("导入分组: 默认分组 (default)", event.messages[-1])

    async def test_clear_seen_command_requires_confirmation(self):
        config = _Config({"watch_users": ["NASA"], "push_targets": []})
        plugin = _plugin(config)
        event = _Event()

        await plugin.cmd_tweets_clear_seen(event, "")

        self.assertTrue(event.stopped)
        self.assertEqual(plugin.scheduler.storage.clear_seen_calls, [])
        self.assertIn("/推文记录清理 确认", event.messages[-1])

    async def test_clear_seen_command_clears_all_seen_and_legacy_kv(self):
        config = _Config({"watch_users": ["NASA"], "push_targets": []})
        plugin = _plugin(config)
        event = _Event()

        await plugin.cmd_tweets_clear_seen(event, "确认")

        self.assertTrue(event.stopped)
        self.assertEqual(plugin.scheduler.storage.clear_seen_calls, [None])
        self.assertEqual(plugin.scheduler.storage.delete_legacy_seen_kv_calls, 1)
        self.assertIn("范围: 全部分组", event.messages[-1])
        self.assertIn("SQLite 推送记录删除: 12 条", event.messages[-1])

    async def test_clear_seen_command_clears_named_group(self):
        config = _Config(
            {
                "watch_users": ["NASA"],
                "tweet_groups": [
                    {"name": "科技", "group_id": "tech", "watch_users": ["OpenAI"]}
                ],
            }
        )
        plugin = _plugin(config)
        event = _Event()

        await plugin.cmd_tweets_clear_seen(event, "科技 确认")

        self.assertEqual(plugin.scheduler.storage.clear_seen_calls, ["tech"])
        self.assertIn("范围: 科技 (tech)", event.messages[-1])

    async def test_export_subscriptions_outputs_grouped_comma_lists(self):
        config = _Config(
            {
                "watch_users": ["NASA", "@NASA", "bad user"],
                "tweet_groups": [
                    {
                        "name": "科技",
                        "group_id": "tech",
                        "watch_users": ["OpenAI", "@SpaceX"],
                    },
                    {
                        "name": "新闻",
                        "group_id": "news",
                        "watch_users": ["BBCWorld"],
                    },
                ],
            }
        )
        plugin = _plugin(config)
        event = _Event()

        await plugin.cmd_tweets_export_subscriptions(event)

        self.assertTrue(event.stopped)
        self.assertEqual(
            event.messages[-1],
            "\n".join(
                [
                    "Nitter 订阅导出",
                    "分组数: 3 个",
                    "订阅账号: 4 个",
                    "分组账号:",
                    "默认分组 (default, 1 个): NASA",
                    "科技 (tech, 2 个): OpenAI,SpaceX",
                    "新闻 (news, 1 个): BBCWorld",
                ]
            ),
        )

    async def test_delete_subscriptions_without_group_removes_default_watch_users(self):
        config = _Config(
            {
                "watch_users": ["NASA", "BBCWorld", "SpaceX"],
                "tweet_groups": [
                    {"name": "科技", "group_id": "tech", "watch_users": ["OpenAI"]}
                ],
            }
        )
        plugin = _plugin(config)
        event = _Event()

        await plugin.cmd_tweets_delete_subscriptions(event, "BBCWorld,@Missing")

        self.assertTrue(event.stopped)
        self.assertTrue(config.saved)
        self.assertEqual(_group_config(config, "default")["watch_users"], ["NASA", "SpaceX"])
        self.assertEqual(_group_config(config, "tech")["watch_users"], ["OpenAI"])
        self.assertEqual(
            [group.group_id for group in plugin.scheduler.storage.synced_groups],
            ["default", "tech"],
        )
        self.assertIn("删除分组: 默认分组 (default)", event.messages[-1])
        self.assertIn("删除: 1 个", event.messages[-1])
        self.assertIn("原本未关注: 1 个", event.messages[-1])

    async def test_delete_subscriptions_with_group_removes_that_group_watch_users(self):
        config = _Config(
            {
                "watch_users": ["NASA"],
                "tweet_groups": [
                    {
                        "name": "科技",
                        "group_id": "tech",
                        "aliases": ["tech-news"],
                        "watch_users": ["OpenAI", "SpaceX"],
                    }
                ],
            }
        )
        plugin = _plugin(config)
        event = _Event()

        await plugin.cmd_tweets_delete_subscriptions(event, "spacex 科技")

        self.assertTrue(config.saved)
        self.assertEqual(config_get(config, "watch_users"), ["NASA"])
        self.assertEqual(
            _group_config(config, "tech")["watch_users"],
            ["OpenAI"],
        )
        self.assertIn("删除分组: 科技 (tech)", event.messages[-1])
        self.assertIn("已删除账号: @SpaceX", event.messages[-1])
        self.assertIn("保存结果: 已写入 tweet_groups[tech].watch_users。", event.messages[-1])

    async def test_delete_subscriptions_without_matches_does_not_save(self):
        config = _Config({"watch_users": ["NASA"], "tweet_groups": []})
        plugin = _plugin(config)
        event = _Event()

        await plugin.cmd_tweets_delete_subscriptions(event, "OpenAI")

        self.assertFalse(config.saved)
        self.assertEqual(plugin.scheduler.storage.synced_groups, [])
        self.assertEqual(config_get(config, "watch_users"), ["NASA"])
        self.assertIn("删除: 0 个", event.messages[-1])
        self.assertIn(
            "保存结果: 未改动配置，没有匹配到可删除账号。",
            event.messages[-1],
        )

    async def test_delete_subscriptions_with_unknown_group_after_comma_list_is_rejected(self):
        config = _Config(
            {
                "watch_users": ["NASA"],
                "tweet_groups": [
                    {"name": "科技", "group_id": "tech", "watch_users": ["OpenAI"]}
                ],
            }
        )
        plugin = _plugin(config)
        event = _Event()

        await plugin.cmd_tweets_delete_subscriptions(event, "NASA,OpenAI 不存在")

        self.assertFalse(config.saved)
        self.assertEqual(config_get(config, "watch_users"), ["NASA"])
        self.assertEqual(_group_config(config, "tech")["watch_users"], ["OpenAI"])
        self.assertIn("未找到分组：不存在", event.messages[-1])
        self.assertIn("科技 (tech)", event.messages[-1])

    async def test_import_allows_more_than_50_accounts(self):
        config = _Config({"watch_users": [], "tweet_groups": []})
        plugin = _plugin(config)
        event = _Event()

        raw_users = [f"user{index}" for index in range(1, 52)]
        await plugin.cmd_tweets_import(event, ",".join(raw_users))

        self.assertTrue(event.stopped)
        self.assertTrue(config.saved)
        self.assertEqual(_group_config(config, "default")["watch_users"], raw_users)
        self.assertIn("输入项: 51 个", event.messages[-1])
        self.assertIn("新增: 51 个", event.messages[-1])

    async def test_import_treats_last_token_as_username_when_group_not_found(self):
        config = _Config(
            {
                "watch_users": [],
                "tweet_groups": [
                    {"name": "科技", "group_id": "tech", "watch_users": []}
                ],
            }
        )
        plugin = _plugin(config)
        event = _Event()

        await plugin.cmd_tweets_import(event, "nasa, space_x")

        self.assertTrue(event.stopped)
        self.assertTrue(config.saved)
        self.assertEqual(
            _group_config(config, "default")["watch_users"],
            ["nasa", "space_x"],
        )

    async def test_import_without_group_allows_space_after_comma(self):
        config = _Config({"watch_users": ["NASA"], "tweet_groups": []})
        plugin = _plugin(config)
        event = _Event()

        await plugin.cmd_tweets_import(event, "BBCWorld, @SpaceX")

        self.assertTrue(config.saved)
        self.assertEqual(
            _group_config(config, "default")["watch_users"],
            ["NASA", "BBCWorld", "SpaceX"],
        )
        self.assertIn("导入分组: 默认分组 (default)", event.messages[-1])

    async def test_import_without_group_only_splits_accounts_on_commas(self):
        config = _Config({"watch_users": ["NASA"], "tweet_groups": []})
        plugin = _plugin(config)
        event = _Event()

        await plugin.cmd_tweets_import(event, "BBCWorld,@SpaceX @OpenAI")

        self.assertTrue(config.saved)
        self.assertEqual(
            _group_config(config, "default")["watch_users"],
            ["NASA", "BBCWorld"],
        )
        self.assertIn("无效: 1 个", event.messages[-1])
        self.assertIn("无效项: @SpaceX @OpenAI", event.messages[-1])

    async def test_import_with_group_appends_that_group_watch_users(self):
        config = _Config(
            {
                "watch_users": ["NASA"],
                "tweet_groups": [
                    {
                        "name": "科技",
                        "group_id": "tech",
                        "aliases": ["tech-news"],
                        "watch_users": ["OpenAI"],
                    }
                ],
            }
        )
        plugin = _plugin(config)
        event = _Event()

        await plugin.cmd_tweets_import(event, "BBCWorld,@SpaceX 科技")

        self.assertTrue(config.saved)
        self.assertEqual(config_get(config, "watch_users"), ["NASA"])
        self.assertEqual(
            _group_config(config, "tech")["watch_users"],
            ["OpenAI", "BBCWorld", "SpaceX"],
        )
        self.assertIn("导入分组: 科技 (tech)", event.messages[-1])
        self.assertIn("保存结果: 已写入 tweet_groups[tech].watch_users。", event.messages[-1])
        self.assertEqual(
            [group.group_id for group in plugin.scheduler.storage.synced_groups],
            ["default", "tech"],
        )

    async def test_import_with_unknown_group_after_comma_list_is_rejected(self):
        config = _Config(
            {
                "watch_users": ["NASA"],
                "tweet_groups": [
                    {"name": "科技", "group_id": "tech", "watch_users": []}
                ],
            }
        )
        plugin = _plugin(config)
        event = _Event()

        await plugin.cmd_tweets_import(event, "BBCWorld,SpaceX 不存在")

        self.assertFalse(config.saved)
        self.assertEqual(config_get(config, "watch_users"), ["NASA"])
        self.assertEqual(_group_config(config, "tech")["watch_users"], [])
        self.assertIn("未找到分组：不存在", event.messages[-1])
        self.assertIn("科技 (tech)", event.messages[-1])


if __name__ == "__main__":
    unittest.main()
