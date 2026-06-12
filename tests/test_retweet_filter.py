"""
测试转帖过滤 (deduplicate_retweets) 逻辑。

覆盖:
- _parse_rss 的转帖判断逻辑
- 关闭时不过滤转帖
- 开启时正确跳过转帖并计数
- 全是转帖时返回空列表
- 无转帖时 skipped=0
- 过滤后推文顺序保持不变

用法:
    pytest tests/test_retweet_filter.py -v
"""
from __future__ import annotations

import sys
import types
import unittest

if "astrbot.api" not in sys.modules:
    import sys
    astrbot_mod = types.ModuleType("astrbot")
    api_mod = types.ModuleType("astrbot.api")
    class _Logger:
        def info(self, *a, **kw): pass
        def warning(self, *a, **kw): pass
        def error(self, *a, **kw): pass
        def debug(self, *a, **kw): pass
    api_mod.logger = _Logger()
    sys.modules["astrbot"] = astrbot_mod
    sys.modules["astrbot.api"] = api_mod

from group_config import GroupConfig, PushTargetParseResult, WatchUsersInfo
from media import NitterClient


def _build_group_config(skip_retweets: bool = False) -> GroupConfig:
    return GroupConfig(
        group_id="default",
        name="默认分组",
        deduplicate_retweets=skip_retweets,
        watch_users_info=WatchUsersInfo(raw_count=0),
        push_targets_info=PushTargetParseResult(),
    )


def _make_rss_xml(items: list[dict], instance: str = "https://nitter.net") -> bytes:
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0"><channel><title>Test</title>',
    ]
    for item in items:
        link = item.get("link", "")
        if link and not link.startswith("http"):
            link = f"{instance}/{link.lstrip('/')}"
        parts.append(f'<item><title>{item.get("title", "")}</title>')
        parts.append(f'<description>{item.get("description", "")}</description>')
        parts.append(f'<link>{link}</link>')
        parts.append(f'<pubDate>{item.get("pubDate", "Mon, 01 Jan 2024 00:00:00 GMT")}</pubDate>')
        parts.append('</item>')
    parts.append('</channel></rss>')
    return "\n".join(parts).encode("utf-8")


class TestRetweetFilter(unittest.TestCase):
    def setUp(self):
        self.instance = "https://nitter.net"

    def _parse(self, items, username="NASA", skip_retweets=False, limit=20):
        gc = _build_group_config(skip_retweets=skip_retweets)
        client = NitterClient(gc)
        data = _make_rss_xml(items, self.instance)
        return client._parse_rss(data, self.instance, limit, username, skip_retweets)

    def test_skip_off_returns_all(self):
        items = [
            {"link": "/NASA/status/100", "description": "original"},
            {"link": "/ElonMusk/status/200", "description": "retweet"},
        ]
        tweets, skipped = self._parse(items, username="NASA", skip_retweets=False)
        self.assertEqual(len(tweets), 2)
        self.assertEqual(skipped, 0)

    def test_skip_on_filters_retweets(self):
        items = [
            {"link": "/NASA/status/100", "description": "original"},
            {"link": "/ElonMusk/status/200", "description": "retweet"},
            {"link": "/SpaceX/status/300", "description": "another retweet"},
        ]
        tweets, skipped = self._parse(items, username="NASA", skip_retweets=True)
        self.assertEqual(len(tweets), 1)
        self.assertEqual(tweets[0].text, "original")
        self.assertEqual(skipped, 2)

    def test_no_retweets_skipped_is_zero(self):
        items = [
            {"link": "/NASA/status/100", "description": "first"},
            {"link": "/NASA/status/101", "description": "second"},
        ]
        tweets, skipped = self._parse(items, username="NASA", skip_retweets=True)
        self.assertEqual(len(tweets), 2)
        self.assertEqual(skipped, 0)

    def test_all_retweets_returns_empty(self):
        items = [
            {"link": "/ElonMusk/status/200", "description": "retweet1"},
            {"link": "/SpaceX/status/300", "description": "retweet2"},
        ]
        tweets, skipped = self._parse(items, username="NASA", skip_retweets=True)
        self.assertEqual(len(tweets), 0)
        self.assertEqual(skipped, 2)

    def test_order_preserved_after_filtering(self):
        items = [
            {"link": "/NASA/status/001", "description": "A"},
            {"link": "/SpaceX/status/002", "description": "retweet"},
            {"link": "/NASA/status/003", "description": "B"},
            {"link": "/ElonMusk/status/004", "description": "retweet2"},
            {"link": "/NASA/status/005", "description": "C"},
        ]
        tweets, skipped = self._parse(items, username="NASA", skip_retweets=True)
        self.assertEqual(len(tweets), 3)
        self.assertEqual([t.text for t in tweets], ["A", "B", "C"])
        self.assertEqual(skipped, 2)

    def test_case_insensitive_username_comparison(self):
        items = [
            {"link": "/nasa/status/100", "description": "lowercase"},
            {"link": "/NASA/status/101", "description": "uppercase"},
            {"link": "/SpaceX/status/200", "description": "different"},
        ]
        tweets, skipped = self._parse(items, username="NASA", skip_retweets=True)
        self.assertEqual(len(tweets), 2)
        self.assertEqual(skipped, 1)

    def test_username_with_at_prefix(self):
        items = [
            {"link": "/@NASA/status/100", "description": "with at"},
            {"link": "/SpaceX/status/200", "description": "different"},
        ]
        tweets, skipped = self._parse(items, username="NASA", skip_retweets=True)
        self.assertEqual(len(tweets), 1)
        self.assertEqual(skipped, 1)

    def test_empty_feed_returns_zero_skipped(self):
        items = []
        tweets, skipped = self._parse(items, username="NASA", skip_retweets=True)
        self.assertEqual(len(tweets), 0)
        self.assertEqual(skipped, 0)

    def test_skip_off_with_mixed_tweets(self):
        items = [
            {"link": "/NASA/status/100", "description": "orig"},
            {"link": "/SpaceX/status/200", "description": "rt"},
            {"link": "/NASA/status/101", "description": "orig2"},
        ]
        tweets, skipped = self._parse(items, username="NASA", skip_retweets=False)
        self.assertEqual(len(tweets), 3)
        self.assertEqual(skipped, 0)


if __name__ == "__main__":
    unittest.main()
