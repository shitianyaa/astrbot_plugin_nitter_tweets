"""List RSS pipeline: client fetches /i/lists/<id>/rss, runner RSS-first."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import parse_qs, urlsplit
from xml.sax.saxutils import escape

import pytest

from media_support.client import NitterClient


def _rss_xml(tweets: list[tuple[str, str, str] | tuple[str, str, str, str]]) -> bytes:
    items = []
    for author, sid, text, *title in tweets:
        link = f"https://x.com/{author}/status/{sid}"
        items.append(
            "<item>"
            f"<title>{escape(title[0] if title else text)}</title>"
            f"<description><![CDATA[{text}]]></description>"
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

    def fake_urlopen(request, timeout, *, proxy_url=None):
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


def _mock_list_rss(monkeypatch, pages):
    def fake_urlopen(request, timeout, *, proxy_url=None):
        url = urlsplit(request.full_url)
        assert url.path == "/i/lists/12345/rss"
        cursor = parse_qs(url.query).get("cursor", [""])[0]
        rows, next_cursor = pages[cursor]
        response = MagicMock()
        response.headers = {"Min-Id": next_cursor}
        response.read.return_value = _rss_xml(rows)
        response.__enter__.return_value = response
        return response

    monkeypatch.setattr("media_support.client.compat_urlopen", fake_urlopen)


@pytest.mark.parametrize("global_enabled", [False, True])
@pytest.mark.parametrize("group_enabled", [False, True])
def test_list_rss_applies_both_repost_switches(
    monkeypatch, global_enabled, group_enabled
):
    from scheduler.runner_fetch import SchedulerFetchMixin

    _mock_list_rss(
        monkeypatch,
        {
            "": (
                [
                    ("alice", "104", "original"),
                    ("bob", "103", "old post", "RT by @alice: old post"),
                    ("carol", "102", "my comment<blockquote>quoted post</blockquote>"),
                    ("bob", "101", "reply", "R to @alice: reply"),
                    ("carol", "100", "RT by @alice: literal text"),
                ],
                "",
            )
        },
    )
    runner = SchedulerFetchMixin()
    runner.config = {"basic": {"filter_reposts_enabled": global_enabled}}
    runner.nitter = _client_with_instance()
    runner._log_verbose_info = MagicMock()
    group = SimpleNamespace(
        group_id="g", group_type="list", filter_reposts_enabled=group_enabled
    )

    result = asyncio.run(
        runner._fetch_group_list(
            group,
            0,
            "list:12345",
            20,
            None,
            filter_reposts=runner._effective_filter_reposts(group),
        )
    )
    applies = global_enabled and group_enabled
    expected = (
        ["104", "102", "101", "100"] if applies else ["104", "103", "102", "101", "100"]
    )
    assert [tweet.status_id for tweet in result.tweets] == expected
    assert result.anchor_status_ids == expected
    assert result.retweet_filtered == int(applies)


@pytest.mark.parametrize("watermark", [None, ["100"]])
def test_list_rss_skips_repost_only_page_and_matches_original(monkeypatch, watermark):
    client = _client_with_instance()
    _mock_list_rss(
        monkeypatch,
        {
            "": ([("alice", "100", "old", "RT by @bob: old")], "more"),
            "more": (
                [
                    ("bob", "120", '<img src="/pic/media/example.jpg">'),
                    ("alice", "100", "old"),
                ],
                "later",
            ),
        },
    )
    _, result = asyncio.run(
        client.fetch_list_for_scheduler(
            "12345", watermark, skip_plain_text=True, filter_reposts=True
        )
    )
    assert [tweet.status_id for tweet in result.tweets] == ["120"]
    assert result.scanned_status_ids == result.anchor_status_ids == ["120", "100"]
    assert result.plain_text_filtered == result.reposts_filtered == 1
    assert result.complete and result.reached_watermark is (watermark is not None)


@pytest.mark.parametrize("watermark", [None, ["100"]])
def test_list_rss_entire_feed_filtered_stays_successful(monkeypatch, watermark):
    from scheduler.runner_fetch import SchedulerFetchMixin, SourceStatus

    _mock_list_rss(
        monkeypatch, {"": ([("alice", "100", "old", "RT by @bob: old")], "")}
    )
    runner = SchedulerFetchMixin()
    runner.nitter = _client_with_instance()
    runner._log_verbose_info = MagicMock()
    group = SimpleNamespace(group_id="g", group_type="list")
    result = asyncio.run(
        runner._fetch_group_list(group, 0, "list:12345", 20, watermark)
    )
    assert result.fetch_status == SourceStatus.FILTERED_EMPTY
    assert result.scan_complete and result.retweet_filtered == 1
    assert (
        not result.tweets
        and not result.anchor_status_ids
        and not result.scanned_status_ids
    )


# --- runner_fetch: List RSS success guard & fallback tests ---


def test_fetch_group_list_empty_tweets_complete_does_not_fallback():
    """When RSS returns 0 tweets but scan is complete (e.g. calm period,
    watermark reached), do NOT fallback to HTML — return empty result directly.
    """
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
    with patch("shared.observability.logger.debug") as mock_warn:
        asyncio.run(runner._fetch_group_list(group, 0, "list:12345", 20, ["100"]))
        assert mock_warn.called
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
    runner._fetch_group_user = AsyncMock(
        side_effect=lambda *args, **kwargs: SimpleNamespace(host_attempts=[])
    )

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
    with patch("shared.observability.logger.debug") as mock_warn:
        asyncio.run(
            runner._fetch_group_users_merged(
                group,
                ["user1", "user2"],
                20,
                skip_plain_text=False,
                scan_watermarks={},
            )
        )
        assert mock_warn.called
        warning_msg = mock_warn.call_args[0][0]
        assert "pass@" not in warning_msg
        assert "secret123" not in warning_msg
        assert "实例地址" in warning_msg
