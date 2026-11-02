"""List RSS pipeline: client fetches /i/lists/<id>/rss, runner RSS-first."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock


from media_support.client import NitterClient


def _rss_xml(tweets: list[tuple[str, str, str]]) -> bytes:
    """Build minimal RSS XML. tweets = [(author, status_id, text), ...]."""
    items = []
    for author, sid, text in tweets:
        link = f"https://x.com/{author}/status/{sid}"
        items.append(
            "<item>"
            f"<title>{text}</title>"
            f"<description>{text}</description>"
            f"<link>{link}</link>"
            "<pubDate>Mon, 01 Jan 2026 00:00:00 GMT</pubDate>"
            "</item>"
        )
    body = "".join(items)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss version="2.0"><channel>'
        "<title>Test List</title>"
        f"{body}"
        "</channel></rss>"
    ).encode()


def _client_with_instance(instance: str = "http://nitter:8080") -> NitterClient:
    config = MagicMock()
    config.get = MagicMock(
        side_effect=lambda key, default=None: {
            "instances": [instance],
            "request_timeout": 12.0,
            "retry_attempts": 2,
            "retry_delay_seconds": 0.0,
            "filter_reposts_enabled": True,
        }.get(key, default)
    )
    config.__getitem__ = MagicMock(
        side_effect=lambda key: {"basic": {}, "performance": {}}.get(key, {})
    )
    return NitterClient(config)


def test_list_rss_url_construction():
    """_list_rss_url builds /i/lists/<id>/rss."""
    url = NitterClient._list_rss_url("http://nitter:8080", "2081623084780671084")
    assert url == "http://nitter:8080/i/lists/2081623084780671084/rss"


def test_list_rss_url_with_cursor():
    url = NitterClient._list_rss_url("http://nitter:8080", "123", cursor="abc")
    assert "cursor=abc" in url
    assert "/i/lists/123/rss" in url


def test_fetch_list_for_scheduler_initial_scan(monkeypatch):
    """Initial scan (no watermark) fetches first page and seeds."""
    client = _client_with_instance()
    tweets_data = [
        ("userA", "100", "hello"),
        ("userB", "200", "world"),
        ("userA", "101", "again"),
    ]
    xml = _rss_xml(tweets_data)

    def fake_urlopen(request, timeout):
        resp = MagicMock()
        resp.headers = {"Min-Id": ""}
        resp.read = MagicMock(return_value=xml)
        resp.__enter__ = MagicMock(return_value=resp)
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    monkeypatch.setattr("media_support.client.compat_urlopen", fake_urlopen)

    result = asyncio.run(client.fetch_list_for_scheduler("12345", None))
    instance, scan_result = result
    assert scan_result.complete is True
    assert len(scan_result.tweets) == 3
    assert scan_result.tweets[0].text == "hello"
    assert scan_result.anchor_status_ids  # seeded from first page


def test_fetch_list_for_scheduler_disables_repost_filter(monkeypatch):
    """List RSS must not filter reposts by a single username."""
    client = _client_with_instance()
    xml = _rss_xml([("userA", "100", "text")])

    captured: dict = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        resp = MagicMock()
        resp.headers = {"Min-Id": ""}
        resp.read = MagicMock(return_value=xml)
        resp.__enter__ = MagicMock(return_value=resp)
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    monkeypatch.setattr("media_support.client.compat_urlopen", fake_urlopen)

    # Pass filter_reposts=True; the method must override to False internally.
    result = asyncio.run(
        client.fetch_list_for_scheduler("12345", None, filter_reposts=True)
    )
    instance, scan_result = result
    # Tweet should be kept (no repost filtering applied)
    assert len(scan_result.tweets) == 1


# --- runner_fetch: List RSS success guard & fallback tests ---


def test_fetch_group_list_empty_tweets_complete_does_not_fallback():
    """When RSS returns 0 tweets but scan is complete (e.g. calm period,
    watermark reached), do NOT fallback to HTML — return empty result directly.
    """
    from types import SimpleNamespace

    from media_support.client import SchedulerFetchResult
    from scheduler.runner_fetch import SchedulerFetchMixin

    runner = SchedulerFetchMixin()
    runner._log_verbose_info = MagicMock()
    runner._effective_filter_reposts = MagicMock(return_value=True)

    scan_res = SchedulerFetchResult(
        tweets=[],
        scanned_status_ids=["100"],
        anchor_status_ids=["100"],
        latest_status_id="100",
        complete=True,
    )
    runner.nitter = MagicMock()
    runner.nitter.fetch_list_for_scheduler = AsyncMock(
        return_value=("http://nitter:8080", scan_res)
    )
    runner.nitter.fetch_list = MagicMock()

    group = SimpleNamespace(group_id="g1", group_type="list", is_list_group=True)
    res = asyncio.run(runner._fetch_group_list(group, 0, "list:12345", 20, ["100"]))

    assert res.tweets == []
    assert res.scan_complete is True
    runner.nitter.fetch_list_for_scheduler.assert_called_once()
    runner.nitter.fetch_list.assert_not_called()


def test_fetch_group_list_rss_error_falls_back_to_html():
    """When RSS raises an error, it must fallback to HTML fetch_list."""
    from types import SimpleNamespace

    from scheduler.runner_fetch import SchedulerFetchMixin

    runner = SchedulerFetchMixin()
    runner._log_verbose_info = MagicMock()
    runner._effective_filter_reposts = MagicMock(return_value=True)

    runner.nitter = MagicMock()
    runner.nitter.fetch_list_for_scheduler = AsyncMock(
        side_effect=RuntimeError("RSS failed")
    )
    mock_tweet = MagicMock(status_id="200")
    runner.nitter.fetch_list = MagicMock(
        return_value=("http://nitter:8080", [mock_tweet])
    )

    group = SimpleNamespace(group_id="g1", group_type="list", is_list_group=True)
    res = asyncio.run(runner._fetch_group_list(group, 0, "list:12345", 20, ["100"]))

    runner.nitter.fetch_list_for_scheduler.assert_called_once()
    runner.nitter.fetch_list.assert_called_once()
    assert len(res.tweets) == 1


def test_fetch_group_list_rss_error_sanitizes_log():
    """RSS failure warning log must sanitize sensitive text in exception."""
    from types import SimpleNamespace
    from unittest.mock import patch

    from scheduler.runner_fetch import SchedulerFetchMixin

    runner = SchedulerFetchMixin()
    runner._log_verbose_info = MagicMock()
    runner._effective_filter_reposts = MagicMock(return_value=True)

    runner.nitter = MagicMock()
    runner.nitter.fetch_list_for_scheduler = AsyncMock(
        side_effect=RuntimeError(
            "connection error to http://admin:pass@internal.net/?token=secret123"
        )
    )
    runner.nitter.fetch_list = MagicMock(return_value=("http://nitter:8080", []))

    group = SimpleNamespace(group_id="g1", group_type="list", is_list_group=True)
    with patch("scheduler.runner_fetch.logger.warning") as mock_warn:
        asyncio.run(runner._fetch_group_list(group, 0, "list:12345", 20, ["100"]))
        mock_warn.assert_called_once()
        warning_msg = mock_warn.call_args[0][0]
        assert "pass@" not in warning_msg
        assert "secret123" not in warning_msg
        assert "实例地址" in warning_msg


def test_fetch_group_users_merged_rss_error_sanitizes_log():
    """Merged RSS failure warning log must sanitize sensitive text in exception."""
    from types import SimpleNamespace
    from unittest.mock import patch

    from scheduler.runner_fetch import SchedulerFetchMixin

    runner = SchedulerFetchMixin()
    runner._log_verbose_info = MagicMock()
    runner._effective_filter_reposts = MagicMock(return_value=True)
    runner._fetch_group_user = AsyncMock()

    runner.nitter = MagicMock()
    runner.nitter.fetch_merged_for_scheduler = AsyncMock(
        side_effect=RuntimeError(
            "connection error to http://admin:pass@internal.net/?token=secret123"
        )
    )

    group = SimpleNamespace(
        group_id="g1",
        group_type="blogger",
        is_tag_group=False,
        is_list_group=False,
        is_blogger_group=True,
        send_user_interval=0,
    )
    with patch("scheduler.runner_fetch.logger.warning") as mock_warn:
        asyncio.run(
            runner._fetch_group_users_merged(
                group,
                ["user1", "user2"],
                20,
                skip_plain_text=False,
                scan_watermarks={},
            )
        )
        mock_warn.assert_called_once()
        warning_msg = mock_warn.call_args[0][0]
        assert "pass@" not in warning_msg
        assert "secret123" not in warning_msg
        assert "实例地址" in warning_msg
