from __future__ import annotations

import dataclasses
import unittest

from rendering.tweets import TweetMessageRenderer
from scheduler.config import ScheduleGroup
from shared.utils import TweetItem


class OmitStatusUrlFormatTests(unittest.TestCase):
    def _tweet(self) -> TweetItem:
        return TweetItem(
            text="Hello https://x.com/a/status/1 world",
            link="https://x.com/nasa/status/1",
            published="2026-01-01",
            translation="hello https://t.co/x",
        )

    def test_omit_true_strips_urls_and_status_line(self) -> None:
        text = TweetMessageRenderer.format_tweet(1, "nasa", self._tweet())
        self.assertNotIn("https://", text)
        self.assertNotIn("原文链接", text)
        self.assertIn("Hello world", text)

    def test_omit_false_keeps_status_line(self) -> None:
        text = TweetMessageRenderer.format_tweet(
            1, "nasa", self._tweet(), omit_status_url=False
        )
        self.assertIn("原文链接", text)
        self.assertIn("https://x.com/nasa/status/1", text)
        self.assertIn("https://x.com/a/status/1", text)
        self.assertIn("https://t.co/x", text)

    def test_telegram_md_link_line(self) -> None:
        text = TweetMessageRenderer.format_tweet(
            1, "nasa", self._tweet(), link_style="telegram_md"
        )
        self.assertTrue(text.startswith("["))
        self.assertIn("](", text)
        self.assertIn("nasa/status/1", text)

    def test_schedule_group_has_omit_field(self) -> None:
        names = {f.name for f in dataclasses.fields(ScheduleGroup)}
        self.assertIn("omit_status_url", names)


if __name__ == "__main__":
    unittest.main()
