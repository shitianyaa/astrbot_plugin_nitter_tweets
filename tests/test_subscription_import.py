from __future__ import annotations

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

    class _Video:
        def __init__(self, *args, **kwargs):
            pass

    class _Node:
        def __init__(self, *args, **kwargs):
            pass

    class _Nodes:
        def __init__(self, *args, **kwargs):
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


from main import NitterTweetsPlugin
from scheduler_config import SchedulerConfigReader


class _Config(dict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.saved = False

    def save_config(self):
        self.saved = True


class _Storage:
    def __init__(self):
        self.synced_groups = []

    async def migrate_and_sync(self, schedule_groups):
        self.synced_groups = schedule_groups


class _CheckResult:
    def format_message(self):
        return "检查结果"


class _Scheduler:
    def __init__(self, config):
        self.config_reader = SchedulerConfigReader(config, context=None)
        self.storage = _Storage()
        self.started = []
        self.run_check_calls = []
        self.check_pending_brief_calls = []

    def watch_users_info(self):
        return self.config_reader.watch_users_info()

    def start(self, reason=""):
        self.started.append(reason)

    async def run_check(self, **kwargs):
        self.run_check_calls.append(kwargs)
        return _CheckResult()

    async def check_pending_brief(self, group):
        self.check_pending_brief_calls.append(group.group_id)
        return "当前分组暂存: 已关闭"


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
    plugin.enricher = None
    plugin.sender = None
    plugin._cooldowns = {}
    plugin.cooldown_seconds = 0
    return plugin


class SubscriptionImportTest(unittest.IsolatedAsyncioTestCase):
    async def test_manual_tweets_uses_default_limit_without_quantity(self):
        plugin = _manual_plugin(_Config({"default_limit": 5, "max_limit": 1}))
        event = _Event()

        await plugin.cmd_tweets(event, "NASA", "")

        self.assertEqual(plugin.nitter.calls, [("fetch_tweets", "NASA", 5)])
        self.assertIn("最近 5 条", event.messages[0])

    async def test_manual_tweets_does_not_clamp_requested_quantity(self):
        plugin = _manual_plugin(_Config({"default_limit": 5, "max_limit": 1}))
        event = _Event()

        await plugin.cmd_tweets(event, "NASA", "50")

        self.assertEqual(plugin.nitter.calls, [("fetch_tweets", "NASA", 50)])
        self.assertIn("最近 50 条", event.messages[0])

    async def test_manual_tweets_rejects_non_positive_quantity(self):
        plugin = _manual_plugin(_Config({"default_limit": 5}))
        event = _Event()

        await plugin.cmd_tweets(event, "NASA", "0")

        self.assertEqual(plugin.nitter.calls, [])
        self.assertIn("数量需要大于 0", event.messages[-1])

    async def test_mirror_probe_uses_default_limit_without_quantity(self):
        plugin = _manual_plugin(_Config({"default_limit": 5, "max_limit": 1}))
        event = _Event()

        await plugin.cmd_mirror_probe(event, "nitter.top")

        self.assertEqual(
            plugin.nitter.calls,
            [("fetch_tweets_from_instance", "nitter.top", "nasa", 5)],
        )
        self.assertIn("最近 5 条", event.messages[0])

    async def test_mirror_probe_does_not_clamp_requested_quantity(self):
        plugin = _manual_plugin(_Config({"default_limit": 5, "max_limit": 1}))
        event = _Event()

        await plugin.cmd_mirror_probe(event, "NASA 50 nitter.top")

        self.assertEqual(
            plugin.nitter.calls,
            [("fetch_tweets_from_instance", "nitter.top", "NASA", 50)],
        )
        self.assertIn("最近 50 条", event.messages[0])

    async def test_mirror_probe_rejects_non_positive_quantity(self):
        plugin = _manual_plugin(_Config({"default_limit": 5}))
        event = _Event()

        await plugin.cmd_mirror_probe(event, "0 nitter.top")

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
                "force_immediate": True,
            },
        )
        self.assertEqual(plugin.scheduler.check_pending_brief_calls, ["tech"])
        self.assertIn("Tech (tech)", event.messages[0])
        self.assertEqual(event.messages[-1], "检查结果\n\n当前分组暂存: 已关闭")

    async def test_check_without_group_rejects_unknown_current_target(self):
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
        self.assertIn("不在任何已启用推文分组", event.messages[-1])

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
        self.assertIn("全局分组 (global)", event.messages[-1])
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

    async def test_import_without_group_appends_global_watch_users(self):
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
        self.assertEqual(config["watch_users"], ["NASA", "BBCWorld", "SpaceX"])
        self.assertEqual(config["tweet_groups"][0]["watch_users"], [])
        self.assertIn("导入分组: 全局分组 (global)", event.messages[-1])

    async def test_export_bloggers_outputs_grouped_comma_lists(self):
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

        await plugin.cmd_tweets_export_bloggers(event)

        self.assertTrue(event.stopped)
        self.assertEqual(
            event.messages[-1],
            "全局分组: NASA\n科技: OpenAI,SpaceX\n新闻: BBCWorld",
        )

    async def test_import_rejects_more_than_50_accounts(self):
        config = _Config({"watch_users": [], "tweet_groups": []})
        plugin = _plugin(config)
        event = _Event()

        raw_users = [f"user{index}" for index in range(1, 52)]
        await plugin.cmd_tweets_import(event, ",".join(raw_users))

        self.assertTrue(event.stopped)
        self.assertFalse(config.saved)
        self.assertEqual(config["watch_users"], [])
        self.assertIn("50", event.messages[-1])

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
        self.assertEqual(config["watch_users"], ["nasa", "space_x"])

    async def test_import_without_group_allows_space_after_comma(self):
        config = _Config({"watch_users": ["NASA"], "tweet_groups": []})
        plugin = _plugin(config)
        event = _Event()

        await plugin.cmd_tweets_import(event, "BBCWorld, @SpaceX")

        self.assertTrue(config.saved)
        self.assertEqual(config["watch_users"], ["NASA", "BBCWorld", "SpaceX"])
        self.assertIn("导入分组: 全局分组 (global)", event.messages[-1])

    async def test_import_without_group_only_splits_accounts_on_commas(self):
        config = _Config({"watch_users": ["NASA"], "tweet_groups": []})
        plugin = _plugin(config)
        event = _Event()

        await plugin.cmd_tweets_import(event, "BBCWorld,@SpaceX @OpenAI")

        self.assertTrue(config.saved)
        self.assertEqual(
            config["watch_users"],
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
        self.assertEqual(config["watch_users"], ["NASA"])
        self.assertEqual(
            config["tweet_groups"][0]["watch_users"],
            ["OpenAI", "BBCWorld", "SpaceX"],
        )
        self.assertIn("导入分组: 科技 (tech)", event.messages[-1])
        self.assertIn("保存结果: 已写入 tweet_groups[tech].watch_users。", event.messages[-1])
        self.assertEqual(
            [group.group_id for group in plugin.scheduler.storage.synced_groups],
            ["global", "tech"],
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
        self.assertEqual(config["watch_users"], ["NASA"])
        self.assertEqual(config["tweet_groups"][0]["watch_users"], [])
        self.assertIn("未找到分组：不存在", event.messages[-1])
        self.assertIn("科技 (tech)", event.messages[-1])


if __name__ == "__main__":
    unittest.main()
