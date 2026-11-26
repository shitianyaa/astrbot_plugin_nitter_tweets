"""HTML global retry delays, stop conditions, and rate-limiter thread safety."""

import threading
from unittest.mock import MagicMock, call

import pytest

from media_support.html_backend.pool import HtmlNitterPool, PoolConfig
from media_support.html_backend.rate_limit import RateLimiter


@pytest.mark.parametrize("operation", ["search", "fetch_user"])
@pytest.mark.parametrize("cooldown", [False, True], ids=["failure", "cooldown"])
def test_global_retry_recovers_with_expected_delay(monkeypatch, operation, cooldown):
    sleep = MagicMock()
    monkeypatch.setattr("media_support.html_backend.pool.time.sleep", sleep)
    pool = HtmlNitterPool(
        PoolConfig(
            instances=["https://a.example", "https://b.example"],
            max_global_retries=2,
            retry_delay_base=5.0,
            retry_delay_on_cooldown=30.0,
        )
    )
    once = MagicMock(
        side_effect=[
            RuntimeError(
                "all instances in cooldown" if cooldown else "all instances failed"
            ),
            ("https://a.example", []),
        ]
    )
    monkeypatch.setattr(
        pool, "_search_once" if operation == "search" else "_fetch_user_once", once
    )
    assert getattr(pool, operation)("test", limit=5) == ("https://a.example", [])
    assert once.call_count == 2
    assert sleep.call_args_list == [call(30.0 if cooldown else 5.0)]


@pytest.mark.parametrize("operation", ["search", "fetch_user"])
def test_global_retry_exhausts_budget_and_propagates_final_error(
    monkeypatch, operation
):
    sleep = MagicMock()
    monkeypatch.setattr("media_support.html_backend.pool.time.sleep", sleep)
    pool = HtmlNitterPool(
        PoolConfig(
            instances=["https://a.example"], max_global_retries=2, retry_delay_base=5.0
        )
    )
    once = MagicMock(side_effect=RuntimeError("persistent failure"))
    monkeypatch.setattr(
        pool, "_search_once" if operation == "search" else "_fetch_user_once", once
    )
    with pytest.raises(RuntimeError, match="persistent failure"):
        getattr(pool, operation)("test", limit=5)
    assert once.call_count == 2
    assert sleep.call_args_list == [call(5.0)]


@pytest.mark.parametrize(
    "probe", [False, True], ids=["validation-error", "explicit-instance"]
)
def test_search_does_not_retry_validation_or_explicit_instance(monkeypatch, probe):
    sleep = MagicMock()
    monkeypatch.setattr("media_support.html_backend.pool.time.sleep", sleep)
    pool = HtmlNitterPool(
        PoolConfig(instances=["https://a.example"], max_global_retries=2)
    )
    error = RuntimeError("instance failed") if probe else ValueError("empty query")
    once = MagicMock(side_effect=error)
    monkeypatch.setattr(pool, "_search_once", once)
    with pytest.raises(type(error), match=str(error)):
        pool.search(
            "test", limit=5, **({"instance": "https://probe.example"} if probe else {})
        )
    assert once.call_count == 1
    sleep.assert_not_called()


def test_global_retry_delay_increases_progressively(monkeypatch):
    sleep = MagicMock()
    monkeypatch.setattr("media_support.html_backend.pool.time.sleep", sleep)
    pool = HtmlNitterPool(
        PoolConfig(
            instances=["https://a.example"], max_global_retries=3, retry_delay_base=5.0
        )
    )
    once = MagicMock(
        side_effect=[
            RuntimeError("fail"),
            RuntimeError("fail"),
            ("https://a.example", []),
        ]
    )
    monkeypatch.setattr(pool, "_search_once", once)
    pool.search("test", limit=5)
    assert once.call_count == 3
    assert sleep.call_args_list == [call(5.0), call(10.0)]


def test_rate_limiter_concurrent_punish_reward_and_cooling():
    limiter = RateLimiter()
    errors = []

    def worker():
        try:
            for _ in range(20):
                limiter.punish("host.example")
                limiter.is_cooling("host.example")
                limiter.reward("host.example")
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
    assert all(not thread.is_alive() for thread in threads)
    assert errors == []
