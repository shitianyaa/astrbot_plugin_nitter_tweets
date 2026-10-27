"""Merged multi-user RSS: batching, URL construction, author splitting."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock


from media_support.client import NitterClient


def _rss_xml(tweets: list[tuple[str, str, str]]) -> bytes:
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

    def fake_urlopen(request, timeout):
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
    """Merged scan uses the oldest user's watermark as the boundary."""
    client = _client()
    # First page has tweets, watermark ID is in the page
    tweets_data = [
        ("alice", "100", "new alice"),
        ("bob", "200", "new bob"),
        ("alice", "099", "old alice watermark"),
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
    # Both users have tweets
    assert len(alice_result.tweets) >= 1
    assert len(bob_result.tweets) >= 1


def test_fetch_merged_empty_feed(monkeypatch):
    """Empty merged feed returns empty results (runner falls back to per-user)."""
    client = _client()
    xml = _rss_xml([])

    def fake_urlopen(request, timeout):
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
    """Divergent watermarks: scan must reach the OLDEST boundary, not stop
    at the freshest, so tweets between the two watermarks are not lost.

    Scenario:
      alice watermark 1005 (active, higher)
      bob   watermark 1003 (slightly older)
      bob has a new tweet 1004 that sits BETWEEN the two watermarks in the
      merged feed.

    With the old union approach the scan would hit 1005 (alice's) first
    and truncate, silently dropping bob's 1004.  The fix passes only the
    oldest user's watermark so the scan continues past 1005 to 1003.
    """
    client = _client()
    tweets_data = [
        ("alice", "1006", "alice new"),
        ("alice", "1005", "alice watermark"),
        ("bob", "1004", "bob new between watermarks"),
        ("bob", "1003", "bob watermark"),
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

    watermarks = {
        "alice": ["1005"],
        "bob": ["1003"],
    }

    instance, results = asyncio.run(
        client.fetch_merged_for_scheduler(["alice", "bob"], watermarks)
    )

    # bob's tweet 1004 (between the two watermarks) must NOT be truncated
    bob_ids = [t.status_id for t in results["bob"].tweets]
    assert "1004" in bob_ids, f"bob's 1004 was lost: {bob_ids}"

    # alice's new tweet is also captured
    alice_ids = [t.status_id for t in results["alice"].tweets]
    assert "1006" in alice_ids


def test_fetch_merged_media_flag_appends_media_path(monkeypatch):
    """When media=True the merged URL gets a /media suffix."""
    client = _client()
    xml = _rss_xml([("alice", "100", "alice media tweet")])

    captured_urls: list[str] = []

    def fake_urlopen(request, timeout):
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
