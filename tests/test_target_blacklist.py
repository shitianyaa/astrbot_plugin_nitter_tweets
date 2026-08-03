from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

_TESTS_DIR = Path(__file__).resolve().parent
_ROOT = _TESTS_DIR.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

import test_scheduler_delivery as base  # noqa: E402

from scheduler.config import SchedulerConfigReader  # noqa: E402
from storage import SQLiteStorage, StorageAdapter  # noqa: E402


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
