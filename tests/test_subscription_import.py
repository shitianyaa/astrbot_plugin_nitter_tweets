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


class _Scheduler:
    def __init__(self, config):
        self.config_reader = SchedulerConfigReader(config, context=None)
        self.storage = _Storage()

    def watch_users_info(self):
        return self.config_reader.watch_users_info()


class _Event:
    def __init__(self):
        self.messages: list[str] = []
        self.stopped = False

    def stop_event(self):
        self.stopped = True

    def plain_result(self, text):
        return text

    async def send(self, message):
        self.messages.append(message)


def _plugin(config):
    plugin = object.__new__(NitterTweetsPlugin)
    plugin.config = config
    plugin.scheduler = _Scheduler(config)
    return plugin


class SubscriptionImportTest(unittest.IsolatedAsyncioTestCase):
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

    async def test_import_without_group_allows_space_after_comma(self):
        config = _Config({"watch_users": ["NASA"], "tweet_groups": []})
        plugin = _plugin(config)
        event = _Event()

        await plugin.cmd_tweets_import(event, "BBCWorld, @SpaceX")

        self.assertTrue(config.saved)
        self.assertEqual(config["watch_users"], ["NASA", "BBCWorld", "SpaceX"])
        self.assertIn("导入分组: 全局分组 (global)", event.messages[-1])

    async def test_import_without_group_allows_comma_and_space_separators(self):
        config = _Config({"watch_users": ["NASA"], "tweet_groups": []})
        plugin = _plugin(config)
        event = _Event()

        await plugin.cmd_tweets_import(event, "BBCWorld,@SpaceX @OpenAI")

        self.assertTrue(config.saved)
        self.assertEqual(
            config["watch_users"],
            ["NASA", "BBCWorld", "SpaceX", "OpenAI"],
        )

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
