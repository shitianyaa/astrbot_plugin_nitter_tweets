from __future__ import annotations

import sys
import types
import unittest
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse


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
            if len(calls) < 3:
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
        self.assertEqual(len(calls), 3)

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


if __name__ == "__main__":
    unittest.main()
