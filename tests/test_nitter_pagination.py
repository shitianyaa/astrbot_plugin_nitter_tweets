from __future__ import annotations

import sys
import types
import unittest
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch


if "astrbot.api" not in sys.modules:
    astrbot_module = types.ModuleType("astrbot")
    astrbot_api_module = types.ModuleType("astrbot.api")

    class _Logger:
        def info(self, *args, **kwargs):
            pass

        def warning(self, *args, **kwargs):
            pass

    astrbot_api_module.logger = _Logger()
    sys.modules["astrbot"] = astrbot_module
    sys.modules["astrbot.api"] = astrbot_api_module


import media
import media_support.client as client_module
from media import NitterClient


class _FakeResponse:
    def __init__(self, body: bytes, headers: dict[str, str] | None = None):
        self._body = body
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self, limit: int = -1) -> bytes:
        return self._body


def _rss_page(start_id: int, count: int) -> bytes:
    items = []
    for status_id in range(start_id, start_id - count, -1):
        items.append(
            f"""
            <item>
              <title>tweet {status_id}</title>
              <description>tweet {status_id}</description>
              <link>/nasa/status/{status_id}</link>
              <pubDate>Mon, 08 Jun 2026 12:00:00 GMT</pubDate>
            </item>
            """
        )
    return (
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
        "<rss><channel>"
        + "".join(items)
        + "</channel></rss>"
    ).encode("utf-8")


def _rss_from_links(links: list[str]) -> bytes:
    items = []
    for index, link in enumerate(links, 1):
        items.append(
            f"""
            <item>
              <title>tweet {index}</title>
              <description>tweet {index}</description>
              <link>{link}</link>
              <pubDate>Mon, 08 Jun 2026 12:00:00 GMT</pubDate>
            </item>
            """
        )
    return (
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
        "<rss><channel>"
        + "".join(items)
        + "</channel></rss>"
    ).encode("utf-8")


def _rss_with_descriptions(items: list[tuple[str, str, str]]) -> bytes:
    """Build an RSS feed with explicit description HTML.

    items: [(link, title, description_html), ...]. Description is wrapped in
    CDATA so embedded HTML (<img>/<video>) does not break XML parsing.
    """
    parts = []
    for link, title, desc in items:
        parts.append(
            f"""
            <item>
              <title>{title}</title>
              <description><![CDATA[{desc}]]></description>
              <link>{link}</link>
              <pubDate>Mon, 08 Jun 2026 12:00:00 GMT</pubDate>
            </item>
            """
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<rss><channel>"
        + "".join(parts)
        + "</channel></rss>"
    ).encode("utf-8")


class NitterPaginationTest(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_tweets_paginates_after_nitter_first_page_limit(self):
        client = NitterClient(
            {
                "instances": ["https://nitter.example"],
                "request_timeout": 12,
            }
        )
        calls: list[str] = []

        def fake_urlopen(request, timeout):
            del timeout
            calls.append(request.full_url)
            parsed = urlparse(request.full_url)
            cursor = parse_qs(parsed.query).get("cursor", [""])[0]
            if not cursor:
                return _FakeResponse(_rss_page(100, 16), {"Min-Id": "84"})
            if cursor == "84":
                return _FakeResponse(_rss_page(84, 16), {"Min-Id": "68"})
            raise AssertionError(f"unexpected cursor: {cursor}")

        original_urlopen = media.urlopen
        media.urlopen = fake_urlopen
        try:
            instance, tweets = await client.fetch_tweets("nasa", 20)
        finally:
            media.urlopen = original_urlopen

        self.assertEqual(instance, "https://nitter.example")
        self.assertEqual(len(tweets), 20)
        self.assertEqual([tweet.status_id for tweet in tweets[:3]], ["100", "99", "98"])
        self.assertEqual([tweet.status_id for tweet in tweets[-3:]], ["83", "82", "81"])
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0], "https://nitter.example/nasa/rss")
        self.assertEqual(
            calls[1],
            "https://nitter.example/nasa/rss?cursor=84",
        )

    async def test_fetch_tweets_filters_reposts_by_item_author(self):
        client = NitterClient(
            {
                "instances": ["https://nitter.example"],
                "request_timeout": 12,
            }
        )

        def fake_urlopen(request, timeout):
            del request, timeout
            return _FakeResponse(
                _rss_from_links(
                    [
                        "/nasa/status/100",
                        "/BBCWorld/status/200",
                        "/NaSa/status/101",
                        "https://example.test/unparsed-link",
                    ]
                )
            )

        original_urlopen = media.urlopen
        media.urlopen = fake_urlopen
        try:
            instance, tweets = await client.fetch_tweets("NASA", 10)
        finally:
            media.urlopen = original_urlopen

        self.assertEqual(instance, "https://nitter.example")
        self.assertEqual([tweet.status_id for tweet in tweets], ["100", "101", ""])
        self.assertEqual(tweets[-1].link, "https://example.test/unparsed-link")

    async def test_fetch_tweets_keeps_reposts_when_filter_is_disabled(self):
        client = NitterClient(
            {
                "instances": ["https://nitter.example"],
                "request_timeout": 12,
                "basic": {"filter_reposts_enabled": False},
            }
        )

        def fake_urlopen(request, timeout):
            del request, timeout
            return _FakeResponse(
                _rss_from_links(["/nasa/status/100", "/BBCWorld/status/200"])
            )

        original_urlopen = media.urlopen
        media.urlopen = fake_urlopen
        try:
            _, tweets = await client.fetch_tweets("nasa", 10)
        finally:
            media.urlopen = original_urlopen

        self.assertEqual([tweet.username for tweet in tweets], ["nasa", "BBCWorld"])

    async def test_fetch_tweets_continues_after_page_filtered_to_reposts(self):
        client = NitterClient(
            {
                "instances": ["https://nitter.example"],
                "request_timeout": 12,
            }
        )
        calls: list[str] = []

        def fake_urlopen(request, timeout):
            del timeout
            calls.append(request.full_url)
            parsed = urlparse(request.full_url)
            cursor = parse_qs(parsed.query).get("cursor", [""])[0]
            if not cursor:
                return _FakeResponse(_rss_from_links(["/BBCWorld/status/200"]), {"Min-Id": "next"})
            if cursor == "next":
                return _FakeResponse(_rss_from_links(["/nasa/status/100"]))
            raise AssertionError(f"unexpected cursor: {cursor}")

        original_urlopen = media.urlopen
        media.urlopen = fake_urlopen
        try:
            _, tweets = await client.fetch_tweets("nasa", 5)
        finally:
            media.urlopen = original_urlopen

        self.assertEqual(len(calls), 2)
        self.assertEqual([tweet.status_id for tweet in tweets], ["100"])

    async def test_fetch_tweets_returns_empty_when_all_items_are_filtered(self):
        client = NitterClient(
            {
                "instances": ["https://nitter.example"],
                "request_timeout": 12,
            }
        )

        def fake_urlopen(request, timeout):
            del request, timeout
            return _FakeResponse(_rss_from_links(["/BBCWorld/status/200"]))

        original_urlopen = media.urlopen
        media.urlopen = fake_urlopen
        try:
            instance, tweets = await client.fetch_tweets("nasa", 5)
        finally:
            media.urlopen = original_urlopen

        self.assertEqual(instance, "https://nitter.example")
        self.assertEqual(tweets, [])

    async def test_fetch_tweets_still_rejects_truly_empty_feed(self):
        client = NitterClient(
            {
                "instances": ["https://nitter.example"],
                "request_timeout": 12,
            }
        )

        def fake_urlopen(request, timeout):
            del request, timeout
            return _FakeResponse(b"<rss><channel></channel></rss>")

        original_urlopen = media.urlopen
        media.urlopen = fake_urlopen
        try:
            with self.assertRaisesRegex(RuntimeError, "empty feed"):
                await client.fetch_tweets("nasa", 5)
        finally:
            media.urlopen = original_urlopen

    async def test_fetch_tweets_retries_transient_http_errors(self):
        client = NitterClient(
            {
                "instances": ["https://nitter.example"],
                "request_timeout": 12,
            }
        )
        client.retry_delay_seconds = 0
        calls: list[str] = []

        def fake_urlopen(request, timeout):
            del timeout
            calls.append(request.full_url)
            if len(calls) < 2:
                raise HTTPError(
                    request.full_url, 503, "Service Unavailable", {}, None
                )
            return _FakeResponse(_rss_page(100, 1))

        original_urlopen = media.urlopen
        media.urlopen = fake_urlopen
        try:
            instance, tweets = await client.fetch_tweets("nasa", 1)
        finally:
            media.urlopen = original_urlopen

        self.assertEqual(instance, "https://nitter.example")
        self.assertEqual(len(tweets), 1)
        self.assertEqual(len(calls), 2)

    async def test_brief_log_suppresses_transient_retry_warning(self):
        client = NitterClient(
            {
                "instances": ["https://nitter.example"],
                "request_timeout": 12,
            }
        )
        client.retry_delay_seconds = 0
        calls: list[str] = []

        def fake_urlopen(request, timeout):
            del timeout
            calls.append(request.full_url)
            if len(calls) < 2:
                raise HTTPError(
                    request.full_url, 503, "Service Unavailable", {}, None
                )
            return _FakeResponse(_rss_page(100, 1))

        original_urlopen = media.urlopen
        media.urlopen = fake_urlopen
        try:
            with patch.object(client_module.logger, "warning") as warning_log:
                await client.fetch_tweets("nasa", 1)
        finally:
            media.urlopen = original_urlopen

        warning_log.assert_not_called()

    async def test_detailed_log_keeps_transient_retry_warning(self):
        client = NitterClient(
            {
                "instances": ["https://nitter.example"],
                "request_timeout": 12,
                "logging": {"brief_log_enabled": False},
            }
        )
        client.retry_delay_seconds = 0
        calls: list[str] = []

        def fake_urlopen(request, timeout):
            del timeout
            calls.append(request.full_url)
            if len(calls) < 2:
                raise HTTPError(
                    request.full_url, 503, "Service Unavailable", {}, None
                )
            return _FakeResponse(_rss_page(100, 1))

        original_urlopen = media.urlopen
        media.urlopen = fake_urlopen
        try:
            with patch.object(client_module.logger, "warning") as warning_log:
                await client.fetch_tweets("nasa", 1)
        finally:
            media.urlopen = original_urlopen

        logged = "\n".join(str(call.args[0]) for call in warning_log.call_args_list)
        self.assertIn("RSS 抓取失败，准备重试", logged)

    async def test_fetch_tweets_tries_next_instance_after_transient_errors(self):
        client = NitterClient(
            {
                "instances": [
                    "https://broken.example",
                    "https://working.example",
                ],
                "request_timeout": 12,
            }
        )
        client.retry_delay_seconds = 0
        calls: list[str] = []

        def fake_urlopen(request, timeout):
            del timeout
            calls.append(request.full_url)
            if request.full_url.startswith("https://broken.example/"):
                raise HTTPError(
                    request.full_url, 503, "Service Unavailable", {}, None
                )
            return _FakeResponse(_rss_page(100, 1))

        original_urlopen = media.urlopen
        media.urlopen = fake_urlopen
        try:
            with (
                patch.object(client_module.logger, "warning") as warning_log,
                patch.object(client_module.logger, "info") as info_log,
            ):
                instance, tweets = await client.fetch_tweets("nasa", 1)
        finally:
            media.urlopen = original_urlopen

        self.assertEqual(instance, "https://working.example")
        self.assertEqual(len(tweets), 1)
        warning_text = "\n".join(
            str(call.args[0]) for call in warning_log.call_args_list
        )
        info_text = "\n".join(str(call.args[0]) for call in info_log.call_args_list)
        self.assertIn("RSS 实例失败，尝试下一个实例", warning_text)
        self.assertIn("instance=https://broken.example", warning_text)
        self.assertIn("next_instance=https://working.example", warning_text)
        self.assertIn("error=HTTP 503", warning_text)
        self.assertIn("RSS 实例成功，已完成实例切换", info_text)
        self.assertIn("instance=https://working.example", info_text)
        self.assertIn("tweets=1", info_text)
        self.assertEqual(
            calls,
            [
                "https://broken.example/nasa/rss",
                "https://broken.example/nasa/rss",
                "https://working.example/nasa/rss",
            ],
        )

    async def test_fetch_tweets_does_not_retry_non_transient_http_errors(self):
        client = NitterClient(
            {
                "instances": ["https://nitter.example"],
                "request_timeout": 12,
            }
        )
        client.retry_delay_seconds = 0
        calls: list[str] = []

        def fake_urlopen(request, timeout):
            del timeout
            calls.append(request.full_url)
            raise HTTPError(request.full_url, 404, "Not Found", {}, None)

        original_urlopen = media.urlopen
        media.urlopen = fake_urlopen
        try:
            with self.assertRaisesRegex(RuntimeError, "HTTP 404"):
                await client.fetch_tweets("nasa", 1)
        finally:
            media.urlopen = original_urlopen

        self.assertEqual(len(calls), 1)


class NitterPlainTextFilterTest(unittest.IsolatedAsyncioTestCase):
    def _patch_urlopen(self, body_fn):
        def fake_urlopen(request, timeout):
            del timeout
            response = body_fn(request)
            if isinstance(response, _FakeResponse):
                return response
            return _FakeResponse(response)

        original_urlopen = media.urlopen
        media.urlopen = fake_urlopen
        return original_urlopen

    async def test_skip_plain_text_keeps_media_tweets(self):
        client = NitterClient(
            {"instances": ["https://nitter.example"], "request_timeout": 12}
        )

        def body(request):
            del request
            return _rss_with_descriptions(
                [
                    (
                        "/nasa/status/100",
                        "t1",
                        '<img src="https://nitter.net/pic/media%2Fabcd.jpg" />',
                    ),
                    ("/nasa/status/101", "t2", "纯文本无图"),
                ]
            )

        original_urlopen = self._patch_urlopen(body)
        try:
            _, tweets = await client.fetch_tweets("nasa", 10, skip_plain_text=True)
        finally:
            media.urlopen = original_urlopen

        self.assertEqual([tweet.status_id for tweet in tweets], ["100"])

    async def test_skip_plain_text_filters_card_img_only(self):
        client = NitterClient(
            {"instances": ["https://nitter.example"], "request_timeout": 12}
        )

        def body(request):
            del request
            return _rss_with_descriptions(
                [
                    (
                        "/nasa/status/100",
                        "t1",
                        '<a href="https://example.test">'
                        '<img src="https://nitter.net/pic/card_img%2Fxyz.jpg" />'
                        "</a>",
                    ),
                    (
                        "/nasa/status/101",
                        "t2",
                        '<img src="https://nitter.net/pic/media%2Fabc.jpg" />',
                    ),
                ]
            )

        original_urlopen = self._patch_urlopen(body)
        try:
            _, tweets = await client.fetch_tweets("nasa", 10, skip_plain_text=True)
        finally:
            media.urlopen = original_urlopen

        self.assertEqual([tweet.status_id for tweet in tweets], ["101"])

    async def test_skip_plain_text_filters_pure_text(self):
        client = NitterClient(
            {"instances": ["https://nitter.example"], "request_timeout": 12}
        )

        def body(request):
            del request
            return _rss_with_descriptions(
                [
                    ("/nasa/status/100", "t1", "只是文字"),
                    ("/nasa/status/101", "t2", "更多文字"),
                ]
            )

        original_urlopen = self._patch_urlopen(body)
        try:
            instance, tweets = await client.fetch_tweets(
                "nasa", 10, skip_plain_text=True
            )
        finally:
            media.urlopen = original_urlopen

        self.assertEqual(instance, "https://nitter.example")
        self.assertEqual(tweets, [])

    async def test_skip_plain_text_paginates_past_plain_text_page(self):
        client = NitterClient(
            {"instances": ["https://nitter.example"], "request_timeout": 12}
        )
        calls: list[str] = []

        def body(request):
            calls.append(request.full_url)
            parsed = urlparse(request.full_url)
            cursor = parse_qs(parsed.query).get("cursor", [""])[0]
            if not cursor:
                return _FakeResponse(
                    _rss_with_descriptions(
                        [
                            ("/nasa/status/200", "t1", "纯文本1"),
                            ("/nasa/status/201", "t2", "纯文本2"),
                        ]
                    ),
                    {"Min-Id": "next"},
                )
            if cursor == "next":
                return _FakeResponse(
                    _rss_with_descriptions(
                        [
                            (
                                "/nasa/status/100",
                                "t1",
                                '<img src="https://nitter.net/pic/media%2Fx.jpg" />',
                            ),
                        ]
                    )
                )
            raise AssertionError(f"unexpected cursor: {cursor}")

        original_urlopen = self._patch_urlopen(body)
        try:
            _, tweets = await client.fetch_tweets("nasa", 5, skip_plain_text=True)
        finally:
            media.urlopen = original_urlopen

        self.assertEqual(len(calls), 2)
        self.assertEqual([tweet.status_id for tweet in tweets], ["100"])

    async def test_skip_plain_text_false_keeps_all(self):
        client = NitterClient(
            {"instances": ["https://nitter.example"], "request_timeout": 12}
        )

        def body(request):
            del request
            return _rss_with_descriptions(
                [
                    ("/nasa/status/100", "t1", "纯文本"),
                    (
                        "/nasa/status/101",
                        "t2",
                        '<img src="https://nitter.net/pic/media%2Fa.jpg" />',
                    ),
                ]
            )

        original_urlopen = self._patch_urlopen(body)
        try:
            _, tweets = await client.fetch_tweets("nasa", 10)
        finally:
            media.urlopen = original_urlopen

        self.assertEqual([tweet.status_id for tweet in tweets], ["100", "101"])


if __name__ == "__main__":
    unittest.main()
