from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

_TESTS_DIR = Path(__file__).resolve().parent
_ROOT = _TESTS_DIR.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

import test_scheduler_delivery as base  # noqa: E402

from plugin_api.target_blacklist import WebAPITargetBlacklistMixin  # noqa: E402
from scheduler.config import SchedulerConfigReader  # noqa: E402
from storage import SQLiteStorage, StorageAdapter  # noqa: E402


class _WebAPITargetBlacklist(WebAPITargetBlacklistMixin):
    """Minimal mixin host with the scheduler/config wiring the real API uses."""

    def __init__(self, scheduler, config):
        self.scheduler = scheduler
        self.config = config

    @staticmethod
    def _ok(**payload):
        return {"success": True, "error": "", **payload}

    @staticmethod
    def _error(error):
        return {"success": False, "error": str(error or "操作失败")}


def _check_config_integrity(refer_conf: dict, conf: dict) -> bool:
    """Reproduce AstrBot's config integrity check (prunes unknown keys)."""
    has_new = False
    new_conf = {}
    for key, value in refer_conf.items():
        if key not in conf:
            new_conf[key] = value
            has_new = True
        elif conf[key] is None:
            new_conf[key] = value
            has_new = True
        elif isinstance(value, dict):
            if not isinstance(conf[key], dict):
                new_conf[key] = value
                has_new = True
            else:
                child_has_new = _check_config_integrity(value, conf[key])
                new_conf[key] = conf[key]
                has_new |= child_has_new
        else:
            new_conf[key] = conf[key]
    for key in list(conf.keys()):
        if key not in refer_conf:
            has_new = True
    conf.clear()
    conf.update(new_conf)
    return has_new


class TargetBlacklistTest(unittest.IsolatedAsyncioTestCase):
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

    def _create_scheduler(self, config, nitter, sender):
        scheduler = base.NitterTweetScheduler(
            base._Owner(),
            context=None,
            config=config,
            nitter=nitter,
            media=base._Media(),
            sender=sender,
            translator=base._Translator(),
        )
        self.schedulers.append(scheduler)
        return scheduler

    def test_target_blacklist_parser_normalizes_and_deduplicates(self):
        config = {
            "target_blocked_users": {
                "group:123": ["@NASA", "nasa", "bad-name"],
                "telegram:FriendMessage:9": ["OpenAI"],
            }
        }
        info = SchedulerConfigReader(config, context=None).parse_target_blocked_users()

        self.assertEqual(info.blocked_users["aiocqhttp:GroupMessage:123"], ["NASA"])
        self.assertEqual(info.blocked_users["telegram:FriendMessage:9"], ["OpenAI"])
        self.assertEqual(info.invalid_users["aiocqhttp:GroupMessage:123"], ["bad-name"])
        self.assertEqual(info.duplicate_users["aiocqhttp:GroupMessage:123"], ["nasa"])

    def test_raw_entries_preserves_invalid_and_duplicate_items(self):
        config = {
            "target_blocked_users": {
                "group:123": ["@NASA", "nasa", "bad-name"],
                "not-a-target": ["user_ok"],
                "telegram:FriendMessage:9": ["OpenAI"],
            }
        }
        reader = SchedulerConfigReader(config, context=None)
        info = reader.parse_target_blocked_users()

        # raw_entries keeps every entry, including the invalid target.
        self.assertEqual(len(info.raw_entries), 3)
        raw_by_target = {
            persist_text: (normalized, raw_users)
            for normalized, persist_text, raw_users in info.raw_entries
        }
        self.assertEqual(
            raw_by_target["aiocqhttp:GroupMessage:123"],
            ("aiocqhttp:GroupMessage:123", ["@NASA", "nasa", "bad-name"]),
        )
        # Invalid target: normalized is None, raw users preserved verbatim.
        self.assertIn("not-a-target", raw_by_target)
        self.assertEqual(
            raw_by_target["not-a-target"],
            (None, ["user_ok"]),
        )
        self.assertEqual(
            raw_by_target["telegram:FriendMessage:9"],
            ("telegram:FriendMessage:9", ["OpenAI"]),
        )

        # Serializing raw_entries rebuilds the full configuration (sorting by
        # target text), including the invalid target and duplicate users.
        serialized = reader.serialize_target_blocked_users(
            [
                (persist_text, raw_users)
                for _, persist_text, raw_users in info.raw_entries
            ]
        )
        self.assertEqual(
            serialized,
            [
                {
                    "target_umo": "aiocqhttp:GroupMessage:123",
                    "blocked_users": ["@NASA", "nasa", "bad-name"],
                },
                {"target_umo": "not-a-target", "blocked_users": ["user_ok"]},
                {"target_umo": "telegram:FriendMessage:9", "blocked_users": ["OpenAI"]},
            ],
        )
        # Round-trips back through the parser, still preserving the invalid
        # target and the duplicate/invalid usernames.
        reparsed = reader.parse_target_blocked_users(serialized)
        self.assertEqual(reparsed.invalid_targets, ["not-a-target"])
        self.assertEqual(
            reparsed.invalid_users["aiocqhttp:GroupMessage:123"], ["bad-name"]
        )
        self.assertEqual(
            reparsed.duplicate_users["aiocqhttp:GroupMessage:123"], ["nasa"]
        )

    def test_plugin_schema_defines_items_for_object_nodes(self):
        schema_path = _ROOT / "_conf_schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))

        def assert_object_items(node, path="schema"):
            if not isinstance(node, dict):
                return
            if node.get("type") == "object":
                self.assertIn("items", node, path)
                assert_object_items(node["items"], f"{path}.items")
            for key, value in node.items():
                if key != "items":
                    assert_object_items(value, f"{path}.{key}")

        assert_object_items(schema)

    def test_plugin_schema_declares_target_blacklist_as_list(self):
        schema = json.loads((_ROOT / "_conf_schema.json").read_text(encoding="utf-8"))
        self.assertEqual(
            schema["push"]["items"]["target_blocked_users"]["type"], "list"
        )
        self.assertEqual(schema["target_blocked_users"]["type"], "list")
        self.assertEqual(schema["_target_blocked_users_list_migrated"]["type"], "bool")
        self.assertTrue(schema["_target_blocked_users_list_migrated"]["invisible"])

    def test_serialize_target_blocked_users_round_trips_through_parser(self):
        reader = SchedulerConfigReader({}, context=None)
        blocked = {
            "aiocqhttp:GroupMessage:123": ["NASA", "OpenAI"],
            "telegram:FriendMessage:9": ["OpenAI"],
        }
        serialized = reader.serialize_target_blocked_users(blocked)
        self.assertEqual(
            serialized,
            [
                {
                    "target_umo": "aiocqhttp:GroupMessage:123",
                    "blocked_users": ["NASA", "OpenAI"],
                },
                {"target_umo": "telegram:FriendMessage:9", "blocked_users": ["OpenAI"]},
            ],
        )
        parsed = reader.parse_target_blocked_users(serialized).blocked_users
        self.assertEqual(parsed, blocked)

    def test_astrbot_config_integrity_keeps_list_blacklist(self):
        """Reproduce AstrBot's check_config_integrity on the list shape."""
        reader = SchedulerConfigReader({}, context=None)
        stored = reader.serialize_target_blocked_users(
            {
                "aiocqhttp:GroupMessage:123": ["NASA"],
                "telegram:FriendMessage:9": ["OpenAI"],
            }
        )

        # Leaf-level check: refer value is the list default ([]), conf is the
        # stored list. A list is not recursed, so the data must survive.
        refer = {"target_blocked_users": []}
        conf = {"target_blocked_users": list(stored)}
        changed = _check_config_integrity(refer, conf)

        self.assertFalse(changed)
        self.assertEqual(conf["target_blocked_users"], stored)

    def test_astrbot_config_integrity_keeps_legacy_dict_blacklist(self):
        """A dict value also survives a list-typed schema (no recursion)."""
        stored = {
            "aiocqhttp:GroupMessage:123": ["NASA"],
            "telegram:FriendMessage:9": ["OpenAI"],
        }
        refer = {"target_blocked_users": []}
        conf = {"target_blocked_users": dict(stored)}
        changed = _check_config_integrity(refer, conf)

        self.assertFalse(changed)
        self.assertEqual(conf["target_blocked_users"], stored)

    def test_migrate_target_blocked_users_converts_dict_to_list(self):
        from config.compat import _migrate_target_blocked_users_to_list

        config = {
            "push": {
                "target_blocked_users": {
                    "aiocqhttp:GroupMessage:123": ["NASA"],
                }
            }
        }
        changed = _migrate_target_blocked_users_to_list(config)
        self.assertTrue(changed)
        self.assertEqual(
            config["push"]["target_blocked_users"],
            [{"target_umo": "aiocqhttp:GroupMessage:123", "blocked_users": ["NASA"]}],
        )
        # Second call is a no-op.
        self.assertFalse(_migrate_target_blocked_users_to_list(config))

    def test_migrate_target_blocked_users_normalizes_raw_values(self):
        from config.compat import _migrate_target_blocked_users_to_list

        config = {
            "push": {
                "target_blocked_users": {
                    "aiocqhttp:GroupMessage:123": "NASA\nOpenAI，SpaceX",
                    "telegram:FriendMessage:9": None,
                    "lark:GroupMessage:chat-1": "NASA",
                    "weixin_oc:FriendMessage:8": ["A", "B"],
                }
            }
        }
        changed = _migrate_target_blocked_users_to_list(config)
        self.assertTrue(changed)
        self.assertEqual(
            config["push"]["target_blocked_users"],
            [
                {
                    "target_umo": "aiocqhttp:GroupMessage:123",
                    "blocked_users": ["NASA", "OpenAI", "SpaceX"],
                },
                {
                    "target_umo": "telegram:FriendMessage:9",
                    "blocked_users": [],
                },
                {
                    "target_umo": "lark:GroupMessage:chat-1",
                    "blocked_users": ["NASA"],
                },
                {
                    "target_umo": "weixin_oc:FriendMessage:8",
                    "blocked_users": ["A", "B"],
                },
            ],
        )

    def test_migrate_target_blacklist_promotes_non_empty_legacy_value(self):
        from config.compat import (
            LEGACY_CONFIG_MIGRATION_KEY,
            MAX_VIDEO_DURATION_GROUP_MIGRATION_KEY,
            TARGET_BLOCKED_USERS_LIST_MIGRATION_KEY,
            config_get,
            migrate_legacy_grouped_config,
        )

        class SavingConfig(dict):
            save_calls = 0

            def save_config(self):
                self.save_calls += 1

        config = SavingConfig(
            {
                "push": {"target_blocked_users": []},
                "target_blocked_users": {"aiocqhttp:GroupMessage:123": "NASA\nOpenAI"},
                LEGACY_CONFIG_MIGRATION_KEY: True,
                MAX_VIDEO_DURATION_GROUP_MIGRATION_KEY: True,
            }
        )

        self.assertTrue(migrate_legacy_grouped_config(config))
        expected = [
            {
                "target_umo": "aiocqhttp:GroupMessage:123",
                "blocked_users": ["NASA", "OpenAI"],
            }
        ]
        self.assertEqual(config["push"]["target_blocked_users"], expected)
        self.assertEqual(config_get(config, "target_blocked_users"), expected)
        self.assertTrue(config[TARGET_BLOCKED_USERS_LIST_MIGRATION_KEY])
        self.assertEqual(config.save_calls, 1)

    def test_migrate_target_blacklist_keeps_non_empty_canonical_value(self):
        from config.compat import (
            MAX_VIDEO_DURATION_GROUP_MIGRATION_KEY,
            migrate_legacy_grouped_config,
        )

        canonical = [
            {
                "target_umo": "aiocqhttp:GroupMessage:123",
                "blocked_users": ["NASA"],
            }
        ]
        config = {
            "push": {"target_blocked_users": list(canonical)},
            "target_blocked_users": {
                "aiocqhttp:GroupMessage:123": ["OpenAI"],
            },
            MAX_VIDEO_DURATION_GROUP_MIGRATION_KEY: True,
        }

        self.assertTrue(migrate_legacy_grouped_config(config))
        self.assertEqual(config["push"]["target_blocked_users"], canonical)

    def test_migrate_target_blacklist_persists_marker_for_current_list(self):
        from config.compat import (
            LEGACY_CONFIG_MIGRATION_KEY,
            MAX_VIDEO_DURATION_GROUP_MIGRATION_KEY,
            TARGET_BLOCKED_USERS_LIST_MIGRATION_KEY,
            migrate_legacy_grouped_config,
        )

        class SavingConfig(dict):
            save_calls = 0

            def save_config(self):
                self.save_calls += 1

        config = SavingConfig(
            {
                "push": {"target_blocked_users": []},
                "target_blocked_users": [],
                LEGACY_CONFIG_MIGRATION_KEY: True,
                MAX_VIDEO_DURATION_GROUP_MIGRATION_KEY: True,
            }
        )

        self.assertTrue(migrate_legacy_grouped_config(config))
        self.assertTrue(config[TARGET_BLOCKED_USERS_LIST_MIGRATION_KEY])
        self.assertEqual(config.save_calls, 1)
        self.assertFalse(migrate_legacy_grouped_config(config))
        self.assertEqual(config.save_calls, 1)

    def test_bare_digit_is_not_treated_as_target_umo(self):
        """Bare digits stay usernames, not group targets (no ambiguity)."""
        from command_handlers.target_blacklist import TargetBlacklistCommandMixin

        self.assertFalse(TargetBlacklistCommandMixin._looks_like_target_umo("123"))
        self.assertTrue(TargetBlacklistCommandMixin._looks_like_target_umo("group:123"))
        self.assertTrue(
            TargetBlacklistCommandMixin._looks_like_target_umo(
                "aiocqhttp:GroupMessage:123"
            )
        )

    async def test_dashboard_update_preserves_unrelated_invalid_entries(self):
        class SavingConfig(dict):
            def save_config(self):
                pass

        config = SavingConfig(
            {
                "push": {
                    "target_blocked_users": [
                        {
                            "target_umo": "telegram:FriendMessage:1",
                            "blocked_users": ["user1"],
                        },
                        {
                            "target_umo": "not-a-target",
                            "blocked_users": ["user_ok"],
                        },
                        {
                            "target_umo": "telegram:FriendMessage:2",
                            "blocked_users": ["bad user", "user2"],
                        },
                    ]
                }
            }
        )
        scheduler = self._create_scheduler(
            config, base._SchedulerNitter({}), base._Sender()
        )
        api = _WebAPITargetBlacklist(scheduler, config)

        result = await api.update_target_blacklist(
            {
                "target_umo": "telegram:FriendMessage:1",
                "blocked_users": ["user1", "user3"],
            }
        )
        self.assertTrue(result["success"])

        stored = config["push"]["target_blocked_users"]
        by_target = {item["target_umo"]: item["blocked_users"] for item in stored}
        # Updated target keeps its new normalized users.
        self.assertEqual(by_target["telegram:FriendMessage:1"], ["user1", "user3"])
        # Unrelated invalid target and invalid usernames survive.
        self.assertIn("not-a-target", by_target)
        self.assertEqual(by_target["not-a-target"], ["user_ok"])
        self.assertEqual(by_target["telegram:FriendMessage:2"], ["bad user", "user2"])

    async def test_dashboard_update_adds_new_target(self):
        class SavingConfig(dict):
            def save_config(self):
                pass

        config = SavingConfig(
            {
                "push": {
                    "target_blocked_users": [
                        {
                            "target_umo": "telegram:FriendMessage:1",
                            "blocked_users": ["user1"],
                        },
                    ]
                }
            }
        )
        scheduler = self._create_scheduler(
            config, base._SchedulerNitter({}), base._Sender()
        )
        api = _WebAPITargetBlacklist(scheduler, config)

        result = await api.update_target_blacklist(
            {
                "target_umo": "telegram:FriendMessage:9",
                "blocked_users": ["newuser"],
            }
        )
        self.assertTrue(result["success"])

        stored = config["push"]["target_blocked_users"]
        by_target = {item["target_umo"]: item["blocked_users"] for item in stored}
        self.assertIn("telegram:FriendMessage:9", by_target)
        self.assertEqual(by_target["telegram:FriendMessage:9"], ["newuser"])
        self.assertEqual(by_target["telegram:FriendMessage:1"], ["user1"])

    async def test_dashboard_update_collapses_duplicate_target_entries(self):
        class SavingConfig(dict):
            def save_config(self):
                pass

        config = SavingConfig(
            {
                "push": {
                    "target_blocked_users": [
                        {
                            "target_umo": "telegram:FriendMessage:1",
                            "blocked_users": ["user1"],
                        },
                        {
                            "target_umo": "telegram:FriendMessage:1",
                            "blocked_users": ["user2"],
                        },
                    ]
                }
            }
        )
        scheduler = self._create_scheduler(
            config, base._SchedulerNitter({}), base._Sender()
        )
        api = _WebAPITargetBlacklist(scheduler, config)

        result = await api.update_target_blacklist(
            {
                "target_umo": "telegram:FriendMessage:1",
                "blocked_users": ["user1", "user3"],
            }
        )
        self.assertTrue(result["success"])

        stored = config["push"]["target_blocked_users"]
        matches = [
            item for item in stored if item["target_umo"] == "telegram:FriendMessage:1"
        ]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["blocked_users"], ["user1", "user3"])

    async def test_dashboard_update_rollback_restores_original_config(self):
        class FailingConfig(dict):
            def save_config(self):
                raise RuntimeError("disk full")

        config = FailingConfig(
            {
                "push": {
                    "target_blocked_users": [
                        {
                            "target_umo": "telegram:FriendMessage:1",
                            "blocked_users": ["user1"],
                        },
                        {
                            "target_umo": "not-a-target",
                            "blocked_users": ["user_ok"],
                        },
                    ]
                }
            }
        )
        scheduler = self._create_scheduler(
            config, base._SchedulerNitter({}), base._Sender()
        )
        api = _WebAPITargetBlacklist(scheduler, config)

        result = await api.update_target_blacklist(
            {
                "target_umo": "telegram:FriendMessage:1",
                "blocked_users": ["user1", "user3"],
            }
        )
        self.assertFalse(result["success"])
        self.assertIn("保存失败", result["error"])

        # Rollback restores the original full configuration, invalid entries
        # included.
        stored = config["push"]["target_blocked_users"]
        by_target = {item["target_umo"]: item["blocked_users"] for item in stored}
        self.assertEqual(by_target["telegram:FriendMessage:1"], ["user1"])
        self.assertIn("not-a-target", by_target)

    async def test_scheduler_filters_per_target_and_keeps_seen_shared(self):
        target_one = "telegram:FriendMessage:1"
        target_two = "telegram:FriendMessage:2"
        config = {
            "schedule_enabled": True,
            "target_blocked_users": {target_one: ["blocked"]},
            "tweet_groups": [
                {
                    "name": "目标黑名单",
                    "group_id": "target_blacklist",
                    "group_type": "blogger",
                    "watch_users": ["source"],
                    "push_targets": [target_one, target_two],
                    "enabled": True,
                }
            ],
            "send_target_interval": 0,
            "send_user_interval": 0,
        }
        scans = base._SchedulerNitter(
            {
                "source": [
                    {
                        "tweets": [
                            base.TweetItem(
                                "seed", "https://x.com/source/status/100", ""
                            )
                        ],
                        "scanned_status_ids": ["100"],
                    },
                    {
                        "tweets": [
                            base.TweetItem(
                                "allowed", "https://x.com/source/status/102", ""
                            ),
                            base.TweetItem(
                                "blocked", "https://x.com/blocked/status/101", ""
                            ),
                            base.TweetItem(
                                "seed", "https://x.com/source/status/100", ""
                            ),
                        ],
                        "scanned_status_ids": ["102", "101", "100"],
                    },
                ]
            }
        )
        sender = base._Sender()
        scheduler = self._create_scheduler(config, scans, sender)
        await scheduler.storage.migrate_and_sync(
            scheduler._schedule_groups(log_invalid_targets=False)
        )

        await scheduler.run_check(
            reason="blacklist_init", group_name="target_blacklist"
        )
        result = await scheduler.run_check(
            reason="blacklist_new", group_name="target_blacklist"
        )

        sent_by_target = {
            target: [
                status_id
                for umo, _, _, status_ids in sender.sent
                if umo == target
                for status_id in status_ids
            ]
            for target in (target_one, target_two)
        }
        self.assertEqual(sent_by_target[target_one], ["102"])
        self.assertEqual(sent_by_target[target_two], ["102", "101"])
        self.assertEqual(result.target_blocked_filtered, 1)
        seen = await scheduler.storage.get_seen_ids("target_blacklist", "source")
        self.assertIn("101", seen)
        self.assertIn("102", seen)

    async def test_blacklist_parse_failure_does_not_abort_delivery(self):
        target = "telegram:FriendMessage:3"
        scheduler = self._create_scheduler(
            {"target_blocked_users": {}},
            base._SchedulerNitter({}),
            base._Sender(),
        )
        scheduler.config_reader.target_blocked_users = lambda: (_ for _ in ()).throw(
            RuntimeError("invalid blacklist")
        )
        batch = SimpleNamespace(
            username="source",
            tweets=[base.TweetItem("source", "https://x.com/source/status/1", "")],
        )
        result = SimpleNamespace(target_blocked_filtered=0)

        allowed, filtered = scheduler._tweets_for_target(batch, target, result)

        self.assertEqual(allowed, batch.tweets)
        self.assertEqual(filtered, 0)
        self.assertEqual(result.target_blocked_filtered, 0)

    async def test_status_reports_blacklist_parse_failure(self):
        config = {
            "tweet_groups": [
                {
                    "name": "状态黑名单",
                    "group_id": "blacklist_status",
                    "group_type": "blogger",
                    "watch_users": ["source"],
                    "push_targets": ["telegram:FriendMessage:3"],
                    "enabled": True,
                }
            ]
        }
        scheduler = self._create_scheduler(
            config,
            base._SchedulerNitter({}),
            base._Sender(),
        )
        scheduler.config_reader.parse_target_blocked_users = lambda: (
            _ for _ in ()
        ).throw(RuntimeError("invalid blacklist"))

        summary = await scheduler.status_summary()

        self.assertIn("目标作者黑名单: 读取失败", summary)
