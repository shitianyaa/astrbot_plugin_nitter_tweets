from __future__ import annotations

import threading
import unittest

from media_support.client import NitterClient, TransientFetchError
from media_support.html_backend.rate_limit import RateLimiter
from media_support.rss_run_skip import RssRunHostSkip


class RssRunHostSkipTest(unittest.TestCase):
    def test_mark_and_filter(self):
        skip = RssRunHostSkip()
        skip.mark("https://nitter.example/a")
        skip.mark("https://nitter.example/b")
        remaining = skip.filter_instances(
            [
                "https://nitter.example/a",
                "https://other.example/",
                "https://nitter.example/b",
            ]
        )
        self.assertEqual(remaining, ["https://other.example/"])

    def test_empty_feed_not_marked_as_skip(self):
        client = NitterClient(
            {
                "instances": ["https://a.example", "https://b.example"],
                "retry_attempts": 2,
                "retry_delay_seconds": 0,
            }
        )
        client.begin_run_host_skip()
        client._mark_run_host_skip("https://a.example", TransientFetchError("HTTP 429"))
        from media_support.client import EmptyFeedError

        client._mark_run_host_skip("https://b.example", EmptyFeedError("empty"))
        self.assertTrue(client._run_host_skip.is_skipped("https://a.example"))
        self.assertFalse(client._run_host_skip.is_skipped("https://b.example"))
        client.end_run_host_skip()
        self.assertIsNone(client._run_host_skip)

    def test_instances_for_run_skips_marked(self):
        client = NitterClient(
            {
                "instances": ["https://a.example", "https://b.example"],
            }
        )
        client.begin_run_host_skip()
        client._run_host_skip.mark("https://a.example")
        filtered = client._instances_for_run(["https://a.example", "https://b.example"])
        self.assertEqual(filtered, ["https://b.example"])
        client.end_run_host_skip()

    def test_retry_config_from_schema_defaults(self):
        client = NitterClient(
            {
                "instances": ["https://a.example"],
                "retry_attempts": 4,
                "retry_delay_seconds": 1.5,
            }
        )
        self.assertEqual(client.retry_attempts, 4)
        self.assertEqual(client.retry_delay_seconds, 1.5)


class RateLimiterLockTest(unittest.TestCase):
    def test_concurrent_punish_does_not_raise(self):
        limiter = RateLimiter()
        errors: list[BaseException] = []

        def worker():
            try:
                for _ in range(20):
                    limiter.punish("host.example")
                    limiter.is_cooling("host.example")
                    limiter.reward("host.example")
            except BaseException as exc:  # pragma: no cover
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)
        self.assertEqual(errors, [])


class WatchQueriesHealTest(unittest.TestCase):
    def test_schedule_groups_heals_missing_type(self):
        from scheduler.config import SchedulerConfigReader

        saved = {"calls": 0}

        class Cfg(dict):
            def get(self, key, default=None):
                return super().get(key, default)

            def save_config(self):
                saved["calls"] += 1

        cfg = Cfg(
            {
                "tweet_groups": [
                    {
                        "name": "t",
                        "group_id": "t1",
                        "group_type": "tag",
                        # Object form on disk is healed to plain strings for WebUI.
                        "watch_queries": [{"query": "#foo", "type": "tag"}],
                        "enabled": True,
                        "push_targets": ["telegram:FriendMessage:1"],
                    }
                ]
            }
        )
        reader = SchedulerConfigReader(cfg, None)
        groups = reader.schedule_groups(log_invalid_targets=False)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].queries_info.queries[0].type, "tag")
        raw = cfg.get("tweet_groups")[0]["watch_queries"]
        self.assertEqual(raw, ["#foo"])
        self.assertGreaterEqual(saved["calls"], 1)

    def test_heal_matches_normalized_group_id_case(self):
        from scheduler.config import SchedulerConfigReader

        saved = {"calls": 0}

        class Cfg(dict):
            def get(self, key, default=None):
                return super().get(key, default)

            def save_config(self):
                saved["calls"] += 1

        cfg = Cfg(
            {
                "tweet_groups": [
                    {
                        "name": "Tags",
                        "group_id": "T1",
                        "group_type": "tag",
                        "watch_queries": [{"query": "#bar", "type": "tag"}],
                        "enabled": True,
                        "push_targets": ["telegram:FriendMessage:1"],
                    }
                ]
            }
        )
        reader = SchedulerConfigReader(cfg, None)
        groups = reader.schedule_groups(log_invalid_targets=False)
        self.assertEqual(groups[0].group_id, "t1")
        raw = cfg.get("tweet_groups")[0]["watch_queries"]
        self.assertEqual(raw, ["#bar"])
        self.assertGreaterEqual(saved["calls"], 1)

    def test_nested_begin_end_restores_skip(self):
        client = NitterClient({"instances": ["https://a.example"]})
        outer = client.begin_run_host_skip()
        outer.mark("https://a.example")
        inner = client.begin_run_host_skip()
        self.assertFalse(inner.is_skipped("https://a.example"))
        client.end_run_host_skip()
        self.assertTrue(client._run_host_skip.is_skipped("https://a.example"))
        client.end_run_host_skip()
        self.assertIsNone(client._run_host_skip)


if __name__ == "__main__":
    unittest.main()
