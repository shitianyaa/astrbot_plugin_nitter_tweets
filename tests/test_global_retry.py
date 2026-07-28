"""Test global retry mechanism in HtmlNitterPool."""

from __future__ import annotations

import time

import pytest

from media_support.html_backend.pool import HtmlNitterPool, PoolConfig


def test_search_global_retry_on_all_instances_fail():
    """All instances fail in round 1, succeed in round 2."""
    call_count = 0

    def mock_search_once(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count <= 1:  # First attempt: fail
            raise RuntimeError("all instances failed")
        # Second attempt: succeed
        return ("https://a.example", [])

    config = PoolConfig(
        instances=["https://a.example", "https://b.example"],
        max_global_retries=2,
        retry_delay_base=0.01,  # Fast for testing
    )
    pool = HtmlNitterPool(config)
    pool._search_once = mock_search_once

    start = time.time()
    base, _tweets = pool.search("#test", limit=5)
    elapsed = time.time() - start

    assert call_count == 2  # 1 failed + 1 success
    assert base == "https://a.example"
    assert elapsed >= 0.01  # At least one delay happened


def test_search_global_retry_respects_max_retries():
    """Exhaust max_global_retries and raise the final error."""
    call_count = 0

    def mock_search_once(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise RuntimeError("persistent failure")

    config = PoolConfig(
        instances=["https://a.example"],
        max_global_retries=2,
        retry_delay_base=0.01,
    )
    pool = HtmlNitterPool(config)
    pool._search_once = mock_search_once

    with pytest.raises(RuntimeError, match="persistent failure"):
        pool.search("#test", limit=5)

    assert call_count == 2  # Tried max_global_retries times


def test_search_global_retry_on_cooldown_uses_longer_delay():
    """When all instances are cooling, use retry_delay_on_cooldown."""
    call_count = 0

    def mock_search_once(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("all instances in cooldown")
        return ("https://a.example", [])

    config = PoolConfig(
        instances=["https://a.example"],
        max_global_retries=2,
        retry_delay_base=0.01,
        retry_delay_on_cooldown=0.05,
    )
    pool = HtmlNitterPool(config)
    pool._search_once = mock_search_once

    start = time.time()
    _base, _tweets = pool.search("#test", limit=5)
    elapsed = time.time() - start

    assert call_count == 2
    assert elapsed >= 0.05  # Used longer cooldown delay


def test_fetch_user_global_retry_on_all_instances_fail():
    """fetch_user also retries globally on total failure."""
    call_count = 0

    def mock_fetch_once(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("all instances failed")
        return ("https://a.example", [])

    config = PoolConfig(
        instances=["https://a.example"],
        max_global_retries=2,
        retry_delay_base=0.01,
    )
    pool = HtmlNitterPool(config)
    pool._fetch_user_once = mock_fetch_once

    base, _tweets = pool.fetch_user("testuser", limit=5)
    assert call_count == 2
    assert base == "https://a.example"


def test_search_no_retry_on_explicit_instance():
    """Explicit instance (probe mode) skips global retry."""
    call_count = 0

    def mock_search_once(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise RuntimeError("instance failed")

    config = PoolConfig(
        instances=["https://a.example"],
        max_global_retries=2,
    )
    pool = HtmlNitterPool(config)
    pool._search_once = mock_search_once

    with pytest.raises(RuntimeError, match="instance failed"):
        pool.search("#test", limit=5, instance="https://probe.example")

    assert call_count == 1  # No retry, direct failure


def test_search_validation_error_no_retry():
    """ValueError (e.g. empty query) should not trigger retry."""
    call_count = 0

    def mock_search_once(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise ValueError("empty query")

    config = PoolConfig(
        instances=["https://a.example"],
        max_global_retries=2,
    )
    pool = HtmlNitterPool(config)
    pool._search_once = mock_search_once

    with pytest.raises(ValueError, match="empty query"):
        pool.search("#test", limit=5)

    assert call_count == 1  # No retry on validation error


def test_global_retry_delay_increases_progressively():
    """Retry delay increases: 5s, 10s, 15s..."""
    call_count = 0
    delays = []

    original_sleep = time.sleep

    def mock_sleep(seconds):
        delays.append(seconds)
        original_sleep(0.001)  # Actually sleep briefly for realism

    time.sleep = mock_sleep

    def mock_search_once(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            raise RuntimeError("fail")
        return ("https://a.example", [])

    try:
        config = PoolConfig(
            instances=["https://a.example"],
            max_global_retries=3,
            retry_delay_base=5.0,
        )
        pool = HtmlNitterPool(config)
        pool._search_once = mock_search_once

        _base, _tweets = pool.search("#test", limit=5)
        assert call_count == 3  # 2 failed + 1 success
        assert len(delays) == 2  # 2 retries = 2 delays
        assert delays[0] == 5.0  # First retry: 5s
        assert delays[1] == 10.0  # Second retry: 10s
    finally:
        time.sleep = original_sleep
