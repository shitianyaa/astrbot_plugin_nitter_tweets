"""HTML search/user multi-mirror rotation retry."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from media_support.html_backend.pool import HtmlNitterPool, PoolConfig
from shared.utils import TweetItem


def _pool(hosts: list[str]) -> HtmlNitterPool:
    from media_support.host_score import HostScoreBook

    pool = HtmlNitterPool.__new__(HtmlNitterPool)
    pool.config = PoolConfig(instances=hosts, max_pages=1)
    pool.instances = [pool._norm(h) for h in hosts]
    pool.scores = HostScoreBook()
    pool.log = MagicMock()
    pool.session = MagicMock()
    pool.session.host_of = lambda base: base.replace("https://", "").split("/")[0]
    pool.limiter = MagicMock()
    pool.limiter.is_cooling = MagicMock(return_value=False)
    pool.limiter.cooldown_remaining = MagicMock(return_value=0.0)
    return pool


def _tweet(status_id: str) -> TweetItem:
    return TweetItem(
        text=f"t{status_id}",
        link=f"https://x.com/u/status/{status_id}",
        published="2026-07-24",
    )


def test_search_rotates_to_next_host_on_failure():
    pool = _pool(
        [
            "https://a.example",
            "https://b.example",
            "https://c.example",
        ]
    )
    tried: list[str] = []

    def paginate(base, query, limit, *, kind, max_pages=None, **kwargs):
        tried.append(base)
        if "a.example" in base:
            raise RuntimeError("a down")
        if "b.example" in base:
            return [_tweet("2")]
        return [_tweet("3")]

    pool._paginate_search = paginate  # type: ignore[method-assign]

    base, tweets = pool.search("#foo", 5, kind="tag")
    assert "b.example" in base
    assert [t.status_id for t in tweets] == ["2"]
    assert tried == [
        "https://a.example",
        "https://b.example",
    ]
    # Should log rotate and success-after-rotate
    log_text = " ".join(str(c) for c in pool.log.call_args_list)
    assert "rotate next" in log_text
    assert "ok after rotate" in log_text


def test_search_prefers_higher_success_score():
    hosts = ["https://a.example", "https://b.example", "https://c.example"]
    pool = _pool(hosts)
    pool.scores.record_success("https://c.example")
    starts: list[str] = []

    def paginate(base, query, limit, *, kind, max_pages=None, **kwargs):
        starts.append(base)
        return [_tweet("9")]

    pool._paginate_search = paginate  # type: ignore[method-assign]

    pool.search("q1", 3, kind="phrase")
    assert starts[0].endswith("c.example")


def test_search_tries_cooling_host_after_ready_fail():
    pool = _pool(["https://ready.example", "https://cool.example"])

    def is_cooling(host: str) -> bool:
        return "cool" in host

    pool.limiter.is_cooling = MagicMock(side_effect=is_cooling)
    tried: list[str] = []

    def paginate(base, query, limit, *, kind, max_pages=None, **kwargs):
        tried.append(base)
        if "ready" in base:
            raise RuntimeError("ready failed")
        return [_tweet("7")]

    pool._paginate_search = paginate  # type: ignore[method-assign]
    base, tweets = pool.search("x", 2, kind="phrase")
    assert "cool.example" in base
    assert tried[0].endswith("ready.example")
    assert tried[1].endswith("cool.example")
    assert tweets[0].status_id == "7"


def test_search_explicit_instance_does_not_rotate_pool():
    pool = _pool(["https://a.example", "https://b.example"])
    tried: list[str] = []

    def paginate(base, query, limit, *, kind, max_pages=None, **kwargs):
        tried.append(base)
        raise RuntimeError("only this host")

    pool._paginate_search = paginate  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="HTML search failed"):
        pool.search("q", 1, kind="phrase", instance="https://a.example")
    assert tried == ["https://a.example"]


def test_hosts_for_probe_alias():
    pool = _pool(["https://a.example", "https://b.example"])
    assert pool._hosts_for_probe("https://a.example") == ["https://a.example"]
    rotated = pool._hosts_for_probe(None)
    assert set(rotated) == {"https://a.example", "https://b.example"}
    assert len(rotated) == 2


def test_search_all_hosts_empty_returns_empty_not_raise():
    """Pure-RT-only / empty timelines must not hard-fail tag schedule."""
    pool = _pool(["https://a.example", "https://b.example"])
    tried: list[str] = []

    def paginate(base, query, limit, *, kind, max_pages=None, **kwargs):
        tried.append(base)
        return []

    pool._paginate_search = paginate  # type: ignore[method-assign]
    base, tweets = pool.search("#foo", 20, kind="tag")
    assert tweets == []
    assert base in {"https://a.example", "https://b.example"}
    assert len(tried) == 2
    assert tweets.host_attempts == ["#1=空结果", "#2=空结果"]


def test_search_empty_result_reports_mixed_host_attempts():
    pool = _pool(["https://a.example", "https://b.example"])

    def paginate(base, query, limit, *, kind, max_pages=None, **kwargs):
        del query, limit, kind, max_pages
        if "a.example" in base:
            raise RuntimeError("a.example HTTP 403")
        return []

    pool._paginate_search = paginate  # type: ignore[method-assign]
    _base, tweets = pool.search("#foo", 20, kind="tag")

    assert tweets.host_attempts == ["#1=HTTP 403", "#2=空结果"]


def test_search_empty_result_preserves_rt_filter_statistics():
    from media_support.html_backend.pool import HtmlSearchResult

    pool = _pool(["https://a.example", "https://b.example"])

    def paginate(base, query, limit, *, kind, max_pages=None, **kwargs):
        del base, query, limit, kind, max_pages
        return HtmlSearchResult([], raw_item_count=3, retweet_filtered=3)

    pool._paginate_search = paginate  # type: ignore[method-assign]
    _base, tweets = pool.search("#foo", 20, kind="tag")
    assert tweets == []
    assert tweets.raw_item_count == 6
    assert tweets.retweet_filtered == 6


def test_search_empty_then_hit_uses_later_host():
    pool = _pool(["https://empty.example", "https://hit.example"])

    def paginate(base, query, limit, *, kind, max_pages=None, **kwargs):
        if "empty" in base:
            return []
        return [_tweet("42")]

    pool._paginate_search = paginate  # type: ignore[method-assign]
    base, tweets = pool.search("phrase", 5, kind="phrase")
    assert "hit.example" in base
    assert [t.status_id for t in tweets] == ["42"]


def test_search_all_hosts_error_still_raises():
    pool = _pool(["https://a.example", "https://b.example"])

    def paginate(base, query, limit, *, kind, max_pages=None, **kwargs):
        raise RuntimeError(f"down {base}")

    pool._paginate_search = paginate  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="HTML search failed"):
        pool.search("q", 1, kind="phrase")


def test_fetch_user_all_hosts_empty_returns_empty_not_raise():
    pool = _pool(["https://a.example", "https://b.example"])

    def paginate(base, user, limit):
        return []

    pool._paginate_user = paginate  # type: ignore[method-assign]
    base, tweets = pool.fetch_user("nasa", 5)
    assert tweets == []
    assert base in {"https://a.example", "https://b.example"}


def test_host_failure_status_prefers_typed_exception():
    from media_support.html_backend.pool import HtmlFetchError, _format_host_failure

    # Typed errors report their own status, including the gate reason that the
    # message-matching fallback never recognised.
    assert (
        _format_host_failure(HtmlFetchError("a.example HTTP 503", "HTTP 503"))
        == "HTTP 503"
    )
    assert (
        _format_host_failure(
            HtmlFetchError("a.example unexpected HTML page", "异常页面")
        )
        == "异常页面"
    )
    # HtmlFetchError stays catchable as RuntimeError for the rotation paths.
    assert isinstance(HtmlFetchError("boom", "HTTP 403"), RuntimeError)


def test_host_failure_status_falls_back_to_message_matching():
    from media_support.html_backend.pool import _format_host_failure

    assert _format_host_failure(RuntimeError("a.example HTTP 403")) == "HTTP 403"
    assert _format_host_failure(TimeoutError("read timed out")) == "TimeoutError"


def test_pool_rotate_fail_logs_redact_instance_urls_and_sensitive_info():
    """Verify pool rotate failure logs redact raw instance URLs and sensitive parameters."""
    hosts = ["https://a.example"]
    pool = _pool(hosts)
    pool.config.max_global_retries = 1
    logged: list[str] = []
    pool.log = MagicMock(side_effect=lambda msg: logged.append(str(msg)))

    # 1. fetch_user
    pool._paginate_user = MagicMock(
        side_effect=RuntimeError(
            "connect failed to https://my-nitter.internal:8443/nasa?auth=supersecret"
        )
    )
    with pytest.raises(RuntimeError):
        pool.fetch_user("nasa", 5)
    user_fail_logs = [m for m in logged if "user fail" in m]
    assert len(user_fail_logs) == 1
    assert "https://my-nitter.internal:8443" not in user_fail_logs[0]
    assert "supersecret" not in user_fail_logs[0]
    assert "实例地址" in user_fail_logs[0]

    # 2. search
    logged.clear()
    pool._paginate_search = MagicMock(
        side_effect=RuntimeError(
            "connect failed to https://my-search.internal:8443/search?auth=supersecret"
        )
    )
    with pytest.raises(RuntimeError):
        pool.search("foo", 5, kind="phrase")
    search_fail_logs = [m for m in logged if "search fail" in m]
    assert len(search_fail_logs) == 1
    assert "https://my-search.internal:8443" not in search_fail_logs[0]
    assert "supersecret" not in search_fail_logs[0]
    assert "实例地址" in search_fail_logs[0]

    # 3. fetch_list
    logged.clear()
    pool._paginate_list = MagicMock(
        side_effect=RuntimeError(
            "connect failed to https://my-list.internal:8443/list?auth=supersecret"
        )
    )
    with pytest.raises(RuntimeError):
        pool.fetch_list("9999", 5)
    list_fail_logs = [m for m in logged if "list fail" in m]
    assert len(list_fail_logs) == 1
    assert "https://my-list.internal:8443" not in list_fail_logs[0]
    assert "supersecret" not in list_fail_logs[0]
    assert "实例地址" in list_fail_logs[0]
