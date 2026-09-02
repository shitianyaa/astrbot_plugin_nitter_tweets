"""Unified user timeline: RSS first, HTML automatic fallback."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from media_support.html_backend.service import HtmlBackendConfig, HtmlNitterService
from media_support.nitter import NitterService
from shared.utils import TweetItem


def _tweet(status_id: str) -> TweetItem:
    return TweetItem(
        text="tweet",
        link=f"https://x.com/test/status/{status_id}",
        published="",
    )


def test_html_service_has_one_shared_instance_pool():
    service = HtmlNitterService(
        HtmlBackendConfig(instances=["https://a.example", "https://b.example"])
    )

    assert service.pool.instances == ["https://a.example", "https://b.example"]
    assert service.pool.limiter is service.limiter
    assert service.pool.session is service.session


def test_html_fetch_user_always_uses_the_shared_pool():
    service = HtmlNitterService(HtmlBackendConfig(instances=["https://a.example"]))
    service.pool.fetch_user = MagicMock(return_value=("https://a.example", []))

    assert service.fetch_user("testuser", limit=5) == ("https://a.example", [])
    service.pool.fetch_user.assert_called_once_with(
        "testuser", 5, instance=None, filter_reposts=None
    )


def test_unified_user_fetch_returns_rss_without_html_request():
    service = NitterService({"instances": ["https://a.example"]})
    tweet = _tweet("1")
    service.fetch_tweets = AsyncMock(return_value=("https://a.example", [tweet]))
    service.fetch_user_html = MagicMock(side_effect=AssertionError("unexpected HTML"))

    assert asyncio.run(service.fetch_user("testuser", 5)) == (
        "https://a.example",
        [tweet],
    )


def test_unified_user_fetch_falls_back_to_html_automatically():
    service = NitterService({"instances": ["https://a.example"]})
    tweet = _tweet("2")
    service.fetch_tweets = AsyncMock(return_value=("https://a.example", []))
    service.fetch_user_html = MagicMock(return_value=("https://a.example", [tweet]))

    assert asyncio.run(service.fetch_user("testuser", 5)) == (
        "https://a.example",
        [tweet],
    )
    service.fetch_user_html.assert_called_once_with("testuser", 5, filter_reposts=None)
