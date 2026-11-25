"""RSS rotation-first retries and per-run failed-host isolation."""

from unittest.mock import AsyncMock, call

import pytest

from media_support.client import (
    EmptyFeedError,
    InstanceFetchResult,
    NitterClient,
    SchedulerFetchResult,
    TransientFetchError,
)
from media_support.rss_run_skip import RssRunHostSkip


@pytest.mark.asyncio
@pytest.mark.parametrize("scheduled", [False, True], ids=["manual", "scheduler"])
@pytest.mark.parametrize("succeeds", [False, True], ids=["exhausted", "early-success"])
async def test_rotation_first_order_and_delay(monkeypatch, scheduled, succeeds):
    hosts = ["https://a.example", "https://b.example", "https://c.example"]
    client = NitterClient({"instances": hosts})
    attempts = []
    sleep = AsyncMock()
    monkeypatch.setattr("media_support.client.asyncio.sleep", sleep)

    def fetch(instance, *args, **kwargs):
        attempts.append(instance)
        if scheduled:
            assert args[-1] is False  # Keep the explicit repost filter through retries.
            assert kwargs == {"path_override": ""}
        if succeeds and instance == hosts[1]:
            if scheduled:
                return SchedulerFetchResult(
                    tweets=["tweet"], scanned_status_ids=["1"], complete=True
                )
            return InstanceFetchResult(tweets=["tweet"], saw_items=True)
        raise RuntimeError(f"{instance} failed")

    if scheduled:
        monkeypatch.setattr(client, "_fetch_for_scheduler_from_instance", fetch)
        operation = client._fetch_tweets_for_scheduler_from_instances(
            "test_user", None, hosts, retry_attempts=2, filter_reposts=False
        )
    else:
        monkeypatch.setattr(client, "_fetch_from_instance", fetch)
        operation = client._fetch_tweets_with_stats_from_instances(
            "test_user", 10, hosts, retry_attempts=2
        )

    if succeeds:
        instance, *_ = await operation
        assert instance == hosts[1]
    else:
        with pytest.raises(RuntimeError, match="failed"):
            await operation
    assert attempts == (hosts[:2] if succeeds else hosts * 2)
    assert sleep.await_args_list == ([] if succeeds else [call(5.0)])


def test_host_skip_mark_and_filter():
    skip = RssRunHostSkip()
    skip.mark("https://nitter.example/a")
    skip.mark("https://nitter.example/b")
    assert skip.filter_instances(
        [
            "https://nitter.example/a",
            "https://other.example/",
            "https://nitter.example/b",
        ]
    ) == ["https://other.example/"]


def test_empty_feed_is_not_marked_as_skip():
    client = NitterClient({"instances": ["https://a.example", "https://b.example"]})
    client.begin_run_host_skip()
    client._mark_run_host_skip("https://a.example", TransientFetchError("HTTP 429"))
    client._mark_run_host_skip("https://b.example", EmptyFeedError("empty"))
    assert client._run_host_skip.is_skipped("https://a.example")
    assert not client._run_host_skip.is_skipped("https://b.example")
    client.end_run_host_skip()
    assert client._run_host_skip is None


def test_instances_for_run_skips_marked():
    client = NitterClient({"instances": ["https://a.example", "https://b.example"]})
    client.begin_run_host_skip()
    client._run_host_skip.mark("https://a.example")
    assert client._instances_for_run(client.instances) == ["https://b.example"]
    client.end_run_host_skip()


def test_nested_begin_end_restores_skip():
    client = NitterClient({"instances": ["https://a.example"]})
    outer = client.begin_run_host_skip()
    outer.mark("https://a.example")
    inner = client.begin_run_host_skip()
    assert not inner.is_skipped("https://a.example")
    client.end_run_host_skip()
    assert client._run_host_skip.is_skipped("https://a.example")
    client.end_run_host_skip()
    assert client._run_host_skip is None
