"""Merged multi-user RSS: batching, URL construction, author splitting."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlsplit

import pytest

from media_support.client import NitterClient
from scheduler.config import SchedulerConfigReader
from scheduler.runner_fetch import SchedulerFetchMixin


def _rss_xml(tweets: list[tuple[str, str, str] | tuple[str, str, str, str]]) -> bytes:
    items = []
    for author, sid, text, *titles in tweets:
        link = f"https://x.com/{author}/status/{sid}"
        title = titles[0] if titles else text
        items.append(
            "<item>"
            f"<title>{title}</title>"
            f"<description>{text}</description>"
            f"<link>{link}</link>"
            "<pubDate>Mon, 01 Jan 2026 00:00:00 GMT</pubDate>"
            "</item>"
        )
    body = "".join(items)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss version="2.0"><channel>'
        "<title>Merged</title>"
        f"{body}"
        "</channel></rss>"
    ).encode()


def _client() -> NitterClient:
    config = MagicMock()
    config.get = MagicMock(
        side_effect=lambda key, default=None: {
            "instances": ["http://nitter:8080"],
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


def _mock_rss_pages(monkeypatch, pages):
    requested = []

    def fake_urlopen(request, timeout, *, proxy_url=None):
        url = urlsplit(request.full_url)
        key = (url.path, parse_qs(url.query).get("cursor", [""])[0])
        requested.append(key)
        tweets, cursor = pages[key]
        response = MagicMock()
        response.headers = {"Min-Id": cursor}
        response.read.return_value = _rss_xml(tweets)
        response.__enter__.return_value = response
        return response

    monkeypatch.setattr("media_support.client.compat_urlopen", fake_urlopen)
    return requested


def test_merged_rss_url_construction():
    """_merged_rss_url joins usernames with raw commas."""
    url = NitterClient._merged_rss_url("http://nitter:8080", ["alice", "bob", "carol"])
    assert url == "http://nitter:8080/alice,bob,carol/rss"


def test_merged_rss_url_with_cursor():
    url = NitterClient._merged_rss_url(
        "http://nitter:8080", ["alice", "bob"], cursor="abc"
    )
    assert "cursor=abc" in url
    assert "alice,bob/rss" in url


def test_batch_usernames_single_batch():
    """Few short usernames fit in one batch."""
    batches = NitterClient.batch_usernames_by_path_length(["alice", "bob", "carol"])
    assert len(batches) == 1
    assert batches[0] == ["alice", "bob", "carol"]


def test_batch_usernames_splits_by_path_length():
    """Long usernames get split when path would exceed the limit."""
    # 15 chars each + comma: "user_long_001,user_long_002,..."
    # 20 users * ~15 chars + 19 commas = ~319 chars > 250
    users = [f"user_long_{i:03d}" for i in range(20)]
    batches = NitterClient.batch_usernames_by_path_length(users)
    assert len(batches) > 1
    # Every batch's comma-joined path must be <= 250
    for batch in batches:
        path = ",".join(batch)
        assert len(path) <= 250
    # All users accounted for
    flat = [u for batch in batches for u in batch]
    assert flat == users


def test_batch_usernames_empty_input():
    batches = NitterClient.batch_usernames_by_path_length([])
    assert batches == []


def test_fetch_merged_splits_by_author(monkeypatch):
    """Merged RSS returns mixed-author tweets; results split per user."""
    client = _client()
    tweets_data = [
        ("alice", "100", "alice tweet 1"),
        ("bob", "200", "bob tweet 1"),
        ("alice", "101", "alice tweet 2"),
        ("outside", "300", "retweet by alice of outside"),
    ]
    xml = _rss_xml(tweets_data)

    captured_urls: list[str] = []

    def fake_urlopen(request, timeout, *, proxy_url=None):
        captured_urls.append(request.full_url)
        resp = MagicMock()
        resp.headers = {"Min-Id": ""}
        resp.read = MagicMock(return_value=xml)
        resp.__enter__ = MagicMock(return_value=resp)
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    monkeypatch.setattr("media_support.client.compat_urlopen", fake_urlopen)

    instance, results = asyncio.run(
        client.fetch_merged_for_scheduler(["alice", "bob"], {})
    )

    # URL should contain comma-joined path
    assert any("alice,bob/rss" in url for url in captured_urls)

    # Each user gets their own tweets
    assert "alice" in results
    assert "bob" in results

    alice_result = results["alice"]
    assert len(alice_result.tweets) == 2
    assert alice_result.tweets[0].text == "alice tweet 1"
    assert alice_result.tweets[1].text == "alice tweet 2"

    bob_result = results["bob"]
    assert len(bob_result.tweets) == 1
    assert bob_result.tweets[0].text == "bob tweet 1"

    # "outside" tweets (retweets of non-batch accounts) are dropped
    assert "outside" not in results


def test_fetch_merged_with_watermark(monkeypatch):
    """A merged page can confirm both users' watermarks."""
    client = _client()
    # First page has tweets, watermark ID is in the page
    tweets_data = [
        ("alice", "100", "new alice"),
        ("bob", "200", "new bob"),
        ("alice", "099", "old alice watermark"),
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

    watermarks = {
        "alice": ["099"],
        "bob": ["200"],
    }

    instance, results = asyncio.run(
        client.fetch_merged_for_scheduler(["alice", "bob"], watermarks)
    )

    # The scan should have found the boundary and stopped
    alice_result = results["alice"]
    bob_result = results["bob"]
    assert alice_result.complete and alice_result.reached_watermark
    assert bob_result.complete and bob_result.reached_watermark


def test_fetch_merged_empty_feed(monkeypatch):
    """Empty merged feed returns empty results (runner falls back to per-user)."""
    client = _client()
    xml = _rss_xml([])

    def fake_urlopen(request, timeout, *, proxy_url=None):
        resp = MagicMock()
        resp.headers = {"Min-Id": ""}
        resp.read = MagicMock(return_value=xml)
        resp.__enter__ = MagicMock(return_value=resp)
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    monkeypatch.setattr("media_support.client.compat_urlopen", fake_urlopen)

    instance, results = asyncio.run(
        client.fetch_merged_for_scheduler(["alice", "bob"], {})
    )
    # Both users get empty results
    assert len(results["alice"].tweets) == 0
    assert len(results["bob"].tweets) == 0


def test_fetch_merged_boundary_collision(monkeypatch):
    """Scan past Alice's watermark until Bob's own watermark is confirmed."""
    client = _client()
    path = "/alice,bob/rss"
    bob_checkpoint = "RT by @alice: Bob's original text"
    requested = _mock_rss_pages(
        monkeypatch,
        {
            (path, ""): (
                [
                    ("alice", "1006", "alice new"),
                    ("bob", "1003", bob_checkpoint, f"RT by @alice: {bob_checkpoint}"),
                    ("alice", "1005", "alice watermark"),
                ],
                "2",
            ),
            (path, "2"): (
                [("bob", "1004", "bob new"), ("bob", "1003", bob_checkpoint)],
                "3",
            ),
        },
    )

    watermarks = {
        "alice": ["1005"],
        "bob": ["1003"],
    }

    _, results = asyncio.run(
        client.fetch_merged_for_scheduler(["alice", "bob"], watermarks)
    )

    assert requested == [(path, ""), (path, "2")]
    assert results["alice"].complete
    assert results["alice"].scanned_status_ids == ["1006", "1005"]
    assert results["bob"].complete
    assert results["bob"].scanned_status_ids == ["1004", "1003"]


def test_merged_first_scan_and_explicit_empty_watermark(monkeypatch):
    path = "/alice,bob,carol/rss"
    requested = _mock_rss_pages(
        monkeypatch,
        {
            (path, ""): (
                [("bob", "1200", "first scan"), ("carol", "1100", "old source")],
                "2",
            ),
            (path, "2"): (
                [("bob", "1050", "older post"), ("alice", "1000", "alice checkpoint")],
                "3",
            ),
        },
    )

    _, results = asyncio.run(
        _client().fetch_merged_for_scheduler(
            ["alice", "bob", "carol"], {"alice": ["1000"], "carol": []}
        )
    )

    assert requested == [(path, ""), (path, "2")]
    assert results["alice"].reached_watermark
    assert results["bob"].complete and not results["bob"].reached_watermark
    assert results["bob"].scanned_status_ids == ["1200"]
    assert not results["carol"].complete


@pytest.mark.parametrize("resumed_posting", [False, True])
def test_merged_page_budget_only_rechecks_unconfirmed_account(
    monkeypatch, resumed_posting
):
    path = "/alice,bob/rss"
    bob_new = [("bob", "1100", "newer post")] if resumed_posting else []
    bob_checkpoint = [("bob", "900", "old checkpoint")]
    requested = _mock_rss_pages(
        monkeypatch,
        {
            (path, ""): (
                bob_new
                + [
                    ("alice", "1006", "RT by @bob: written by Alice"),
                    ("bob", "900", "old checkpoint", "RT by @alice: old checkpoint"),
                    ("alice", "1005", "alice watermark"),
                ],
                "2",
            ),
            (path, "2"): ([("alice", "1004", "alice old")], "3"),
            (path, "3"): ([("alice", "1003", "alice older")], "4"),
            ("/bob/rss", ""): (
                bob_new,
                "2",
            )
            if resumed_posting
            else (bob_checkpoint, ""),
            ("/bob/rss", "2"): (
                [("bob", "950", "new post outside budget")] + bob_checkpoint,
                "",
            ),
        },
    )
    runner = SchedulerFetchMixin()
    runner.nitter = _client()
    runner.config = {
        "fetch_backend": "nitter",
        "tweet_groups": [{"watch_users": ["alice", "bob"], "send_user_interval": 0}],
    }
    runner._log_verbose_info = MagicMock()
    group = SchedulerConfigReader(runner.config, context=None).schedule_groups()[0]

    alice, bob = asyncio.run(
        runner._fetch_group_users(group, 20, False, {"alice": ["1005"], "bob": ["900"]})
    )

    assert requested == [
        (path, ""),
        (path, "2"),
        (path, "3"),
        ("/bob/rss", ""),
        *([("/bob/rss", "2")] if resumed_posting else []),
    ]
    assert alice.scan_complete and alice.host_attempts == ["合并RSS=成功"]
    assert alice.tweets[0].status_id == "1006"
    assert bob.scan_complete
    assert bob.host_attempts == ["合并RSS=未命中该账号水位", "单账号RSS=成功"]
    assert bob.scanned_status_ids == (
        ["1100", "950", "900"] if resumed_posting else ["900"]
    )


def test_fetch_merged_media_flag_appends_media_path(monkeypatch):
    """When media=True the merged URL gets a /media suffix."""
    client = _client()
    xml = _rss_xml([("alice", "100", "alice media tweet")])

    captured_urls: list[str] = []

    def fake_urlopen(request, timeout, *, proxy_url=None):
        captured_urls.append(request.full_url)
        resp = MagicMock()
        resp.headers = {"Min-Id": ""}
        resp.read = MagicMock(return_value=xml)
        resp.__enter__ = MagicMock(return_value=resp)
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    monkeypatch.setattr("media_support.client.compat_urlopen", fake_urlopen)

    asyncio.run(client.fetch_merged_for_scheduler(["alice", "bob"], {}, media=True))
    assert any("alice,bob/media/rss" in url for url in captured_urls)

    # Without media flag the path has no /media suffix
    captured_urls.clear()
    asyncio.run(client.fetch_merged_for_scheduler(["alice", "bob"], {}, media=False))
    assert any("alice,bob/rss" in url for url in captured_urls)
    assert not any("/media/rss" in url for url in captured_urls)
