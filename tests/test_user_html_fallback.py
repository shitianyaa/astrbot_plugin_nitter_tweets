# -*- coding: utf-8 -*-
"""Test user_html_fallback: RSS failure → HTML blogger fallback."""

from __future__ import annotations

import pytest

from media_support.html_backend.service import HtmlBackendConfig, HtmlNitterService


def test_user_html_fallback_disabled_by_default():
    """Default: user_html_fallback=false, blogger_html pool empty."""
    config = HtmlBackendConfig(
        user_html_fallback=False,
        search_instances=["https://a.example", "https://b.example"],
    )
    service = HtmlNitterService(config)

    assert service.config.user_html_fallback is False
    assert service.blogger_html.instances == []
    assert len(service.search_pool.instances) == 2


def test_user_html_fallback_enabled_shares_search_instances():
    """user_html_fallback=true → blogger_html shares search_instances."""
    config = HtmlBackendConfig(
        user_html_fallback=True,
        search_instances=["https://a.example", "https://b.example"],
    )
    service = HtmlNitterService(config)

    assert service.config.user_html_fallback is True
    assert service.blogger_html.instances == [
        "https://a.example",
        "https://b.example",
    ]
    assert service.search_pool.instances == ["https://a.example", "https://b.example"]


def test_fetch_user_returns_empty_when_disabled():
    """user_html_fallback=false → fetch_user returns empty immediately."""
    config = HtmlBackendConfig(
        user_html_fallback=False,
        search_instances=["https://a.example"],
    )
    service = HtmlNitterService(config)

    base, tweets = service.fetch_user("testuser", limit=5)
    assert base == ""
    assert tweets == []


def test_fetch_user_attempts_pool_when_enabled():
    """user_html_fallback=true → fetch_user uses blogger_html pool."""
    config = HtmlBackendConfig(
        user_html_fallback=True,
        search_instances=["https://a.example"],
    )
    service = HtmlNitterService(config)

    # Mock _fetch_user_once to verify it's called
    call_count = 0

    def mock_fetch(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return "https://a.example", []

    service.blogger_html._fetch_user_once = mock_fetch

    base, tweets = service.fetch_user("testuser", limit=5)
    assert call_count == 1  # Pool was used
    assert base == "https://a.example"


def test_shared_limiter_and_session():
    """blogger_html and search_pool share limiter and session."""
    config = HtmlBackendConfig(
        user_html_fallback=True,
        search_instances=["https://a.example"],
    )
    service = HtmlNitterService(config)

    assert service.blogger_html.limiter is service.limiter
    assert service.blogger_html.session is service.session
    assert service.search_pool.limiter is service.limiter
    assert service.search_pool.session is service.session
