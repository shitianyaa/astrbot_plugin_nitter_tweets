"""Tests for FxTwitterClient."""

from __future__ import annotations

import io
from typing import Any
from unittest.mock import MagicMock
from urllib.error import HTTPError

import pytest

from media_support.fxtwitter_client import (
    DEFAULT_FXTWITTER_BASE_URL,
    FxTwitterClient,
    FxTwitterError,
    FxTwitterNotFoundError,
)


def _make_response(data: bytes, status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status = status
    resp.geturl = MagicMock(return_value="https://api.fxtwitter.com/test")
    bio = io.BytesIO(data)
    resp.read = bio.read
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    return resp


class TestFxTwitterClientRoutesAndGuards:
    def test_default_base_url(self):
        client = FxTwitterClient()
        assert client.base_url == DEFAULT_FXTWITTER_BASE_URL

    def test_user_timeline_routing_plain_reposts_true(self, monkeypatch):
        """skip_plain_text=False, filter_reposts=True -> calls /statuses, filters retweets."""
        client = FxTwitterClient()
        requested_urls: list[str] = []

        sample_data = {
            "code": 200,
            "results": [
                {
                    "type": "status",
                    "id": "1",
                    "text": "Hello world",
                    "url": "https://x.com/user/status/1",
                    "created_at": "Wed Oct 10 20:19:24 +0000 2018",
                    "reposted_by": {"screen_name": "user"},  # is_retweet = True
                },
                {
                    "type": "status",
                    "id": "2",
                    "text": "Original tweet",
                    "url": "https://x.com/user/status/2",
                    "created_at": "Wed Oct 10 20:20:24 +0000 2018",
                },
            ],
            "cursor": {"top": "cur_top", "bottom": "cur_bottom"},
        }

        def mock_fetch_json(url: str, **kwargs) -> dict[str, Any]:
            requested_urls.append(url)
            return sample_data

        monkeypatch.setattr(client, "_fetch_json", mock_fetch_json)

        tweets, next_cursor = client.fetch_user_timeline(
            "@user", count=1, skip_plain_text=False, filter_reposts=True
        )

        assert len(requested_urls) == 1
        assert "/2/profile/user/statuses" in requested_urls[0]
        assert "count=1" in requested_urls[0]
        assert next_cursor == "cur_bottom"
        assert len(tweets) == 1
        assert tweets[0].status_id == "2"
        assert tweets[0].is_retweet is False

    def test_user_timeline_routing_plain_reposts_false(self, monkeypatch):
        """skip_plain_text=False, filter_reposts=False -> calls /statuses, keeps retweets."""
        client = FxTwitterClient()
        requested_urls: list[str] = []

        sample_data = {
            "code": 200,
            "results": [
                {
                    "type": "status",
                    "id": "1",
                    "text": "Hello retweet",
                    "url": "https://x.com/author/status/1",
                    "created_at": "Wed Oct 10 20:19:24 +0000 2018",
                    "reposted_by": {"screen_name": "user"},
                },
                {
                    "type": "status",
                    "id": "2",
                    "text": "Original tweet",
                    "url": "https://x.com/user/status/2",
                    "created_at": "Wed Oct 10 20:20:24 +0000 2018",
                },
            ],
        }

        def mock_fetch_json(url: str, **kwargs) -> dict[str, Any]:
            requested_urls.append(url)
            return sample_data

        monkeypatch.setattr(client, "_fetch_json", mock_fetch_json)

        tweets, next_cursor = client.fetch_user_timeline(
            "user", count=10, skip_plain_text=False, filter_reposts=False
        )

        assert "/2/profile/user/statuses" in requested_urls[0]
        assert len(tweets) == 2
        assert tweets[0].is_retweet is True
        assert tweets[1].is_retweet is False

    def test_user_timeline_routing_media_reposts_true(self, monkeypatch):
        """skip_plain_text=True, filter_reposts=True -> calls /media."""
        client = FxTwitterClient()
        requested_urls: list[str] = []

        sample_data = {
            "code": 200,
            "results": [
                {
                    "type": "status",
                    "id": "1",
                    "text": "Photo tweet",
                    "url": "https://x.com/user/status/1",
                    "media": {
                        "all": [{"type": "photo", "url": "https://pbs.twimg.com/m.jpg"}]
                    },
                }
            ],
        }

        def mock_fetch_json(url: str, **kwargs) -> dict[str, Any]:
            requested_urls.append(url)
            return sample_data

        monkeypatch.setattr(client, "_fetch_json", mock_fetch_json)

        tweets, _ = client.fetch_user_timeline(
            "user", count=10, skip_plain_text=True, filter_reposts=True
        )

        assert len(requested_urls) == 1
        assert "/2/profile/user/media" in requested_urls[0]
        assert len(tweets) == 1
        assert len(tweets[0].media) == 1

    def test_user_timeline_retweet_guard_skip_plain_reposts_false(self, monkeypatch):
        """RETWEET GUARD: skip_plain_text=True, filter_reposts=False.

        MUST call /statuses (NOT /media) and filter plain text locally, so that
        retweets containing media are preserved!
        """
        client = FxTwitterClient()
        requested_urls: list[str] = []

        sample_data = {
            "code": 200,
            "results": [
                # 1. Plain text tweet (should be filtered out by skip_plain_text)
                {
                    "type": "status",
                    "id": "1",
                    "text": "Plain text tweet",
                    "url": "https://x.com/user/status/1",
                },
                # 2. Retweet with media (MUST be kept!)
                {
                    "type": "status",
                    "id": "2",
                    "text": "Retweet with media",
                    "url": "https://x.com/artist/status/2",
                    "reposted_by": {"screen_name": "user"},
                    "media": {
                        "all": [
                            {"type": "photo", "url": "https://pbs.twimg.com/art.jpg"}
                        ]
                    },
                },
                # 3. Plain text retweet (filtered out by skip_plain_text)
                {
                    "type": "status",
                    "id": "3",
                    "text": "Plain text retweet",
                    "url": "https://x.com/other/status/3",
                    "reposted_by": {"screen_name": "user"},
                },
                # 4. Own tweet with media (kept)
                {
                    "type": "status",
                    "id": "4",
                    "text": "Own photo",
                    "url": "https://x.com/user/status/4",
                    "media": {
                        "all": [
                            {"type": "photo", "url": "https://pbs.twimg.com/own.jpg"}
                        ]
                    },
                },
            ],
        }

        def mock_fetch_json(url: str, **kwargs) -> dict[str, Any]:
            requested_urls.append(url)
            return sample_data

        monkeypatch.setattr(client, "_fetch_json", mock_fetch_json)

        tweets, _ = client.fetch_user_timeline(
            "user", count=10, skip_plain_text=True, filter_reposts=False
        )

        assert len(requested_urls) == 1
        # Crucial: verify it routed to /statuses and NOT /media!
        assert "/2/profile/user/statuses" in requested_urls[0]
        assert "/2/profile/user/media" not in requested_urls[0]

        # Plain text tweets (id 1 and 3) must be filtered out locally
        assert len(tweets) == 2
        status_ids = [t.status_id for t in tweets]
        assert status_ids == ["2", "4"]

        # Tweet 2 is a retweet with media that was preserved
        assert tweets[0].is_retweet is True
        assert len(tweets[0].media) == 1
        assert tweets[0].media[0].url == "https://pbs.twimg.com/art.jpg"

        # Tweet 4 is an original tweet with media
        assert tweets[1].is_retweet is False
        assert len(tweets[1].media) == 1

    def test_user_timeline_empty_username(self):
        client = FxTwitterClient()
        tweets, cursor = client.fetch_user_timeline("", count=10)
        assert tweets == []
        assert cursor is None

    def test_user_timeline_with_cursor(self, monkeypatch):
        client = FxTwitterClient()
        requested_urls: list[str] = []

        def mock_fetch_json(url: str, **kwargs) -> dict[str, Any]:
            requested_urls.append(url)
            return {"code": 200, "results": []}

        monkeypatch.setattr(client, "_fetch_json", mock_fetch_json)
        client.fetch_user_timeline("user", cursor="cur_xyz")
        assert "cursor=cur_xyz" in requested_urls[0]

    def test_user_timeline_pagination_skip_plain_text(self, monkeypatch):
        """skip_plain_text=True: overfetches (count=20) and follows cursor when accumulated < count."""
        client = FxTwitterClient()
        requested_urls: list[str] = []

        page1_data = {
            "code": 200,
            "results": [
                {
                    "type": "status",
                    "id": "1",
                    "text": "Photo 1",
                    "url": "https://x.com/user/status/1",
                    "media": {
                        "all": [{"type": "photo", "url": "https://pbs.twimg.com/1.jpg"}]
                    },
                }
            ],
            "cursor": {"bottom": "cursor_p2"},
        }
        page2_data = {
            "code": 200,
            "results": [
                {
                    "type": "status",
                    "id": "2",
                    "text": "Photo 2",
                    "url": "https://x.com/user/status/2",
                    "media": {
                        "all": [{"type": "photo", "url": "https://pbs.twimg.com/2.jpg"}]
                    },
                }
            ],
            "cursor": {"bottom": "cursor_p3"},
        }

        def mock_fetch_json(url: str, **kwargs) -> dict[str, Any]:
            requested_urls.append(url)
            if "cursor=cursor_p2" in url:
                return page2_data
            return page1_data

        monkeypatch.setattr(client, "_fetch_json", mock_fetch_json)

        tweets, next_cursor = client.fetch_user_timeline(
            "user", count=2, skip_plain_text=True, filter_reposts=True
        )

        assert len(requested_urls) == 2
        assert "count=20" in requested_urls[0]
        assert "/2/profile/user/media" in requested_urls[0]
        assert "cursor=cursor_p2" in requested_urls[1]
        assert next_cursor == "cursor_p3"
        assert len(tweets) == 2
        assert [t.status_id for t in tweets] == ["1", "2"]

    def test_user_timeline_pagination_stops_at_max_pages(self, monkeypatch):
        """Pagination terminates after max_pages even if accumulated < count."""
        client = FxTwitterClient()
        requested_urls: list[str] = []

        page_counter = 0

        def mock_fetch_json(url: str, **kwargs) -> dict[str, Any]:
            nonlocal page_counter
            page_counter += 1
            requested_urls.append(url)
            return {
                "code": 200,
                "results": [
                    {
                        "type": "status",
                        "id": str(page_counter),
                        "text": f"Photo {page_counter}",
                        "url": f"https://x.com/user/status/{page_counter}",
                        "media": {
                            "all": [
                                {
                                    "type": "photo",
                                    "url": f"https://pbs.twimg.com/{page_counter}.jpg",
                                }
                            ]
                        },
                    }
                ],
                "cursor": {"bottom": f"cursor_p{page_counter + 1}"},
            }

        monkeypatch.setattr(client, "_fetch_json", mock_fetch_json)

        tweets, next_cursor = client.fetch_user_timeline(
            "user", count=10, skip_plain_text=True, filter_reposts=True, max_pages=2
        )

        assert len(requested_urls) == 2
        assert len(tweets) == 2
        assert next_cursor == "cursor_p3"

    def test_user_timeline_media_filter_video_and_image(self, monkeypatch):
        """media_filter='video' only keeps video tweets; media_filter='image' only keeps image tweets."""
        client = FxTwitterClient()
        data = {
            "code": 200,
            "results": [
                {
                    "type": "status",
                    "id": "1",
                    "text": "Photo tweet",
                    "url": "https://x.com/u/status/1",
                    "media": {
                        "all": [{"type": "photo", "url": "https://pbs.twimg.com/1.jpg"}]
                    },
                },
                {
                    "type": "status",
                    "id": "2",
                    "text": "Video tweet",
                    "url": "https://x.com/u/status/2",
                    "media": {
                        "all": [
                            {"type": "video", "url": "https://video.twimg.com/2.mp4"}
                        ]
                    },
                },
            ],
            "cursor": {"bottom": "cur_same"},
        }
        monkeypatch.setattr(client, "_fetch_json", lambda url, **kw: data)

        videos, _ = client.fetch_user_timeline(
            "u", count=5, cursor="cur_same", media_filter="video"
        )
        assert len(videos) == 1
        assert videos[0].status_id == "2"

        images, _ = client.fetch_user_timeline(
            "u", count=5, cursor="cur_same", media_filter="image"
        )
        assert len(images) == 1
        assert images[0].status_id == "1"

    def test_user_timeline_stalled_cursor_returns_none_next_cursor(self, monkeypatch):
        client = FxTwitterClient()
        data = {
            "code": 200,
            "results": [
                {
                    "type": "status",
                    "id": "1",
                    "text": "Hi",
                    "url": "https://x.com/u/status/1",
                }
            ],
            "cursor": {"bottom": "cur_same"},
        }
        monkeypatch.setattr(client, "_fetch_json", lambda url, **kw: data)
        tweets, next_cursor = client.fetch_user_timeline(
            "u", count=10, cursor="cur_same"
        )
        assert len(tweets) == 1
        assert next_cursor is None


class TestFxTwitterClientSearch:
    def test_search_tweets_normal(self, monkeypatch):
        client = FxTwitterClient()
        requested_urls: list[str] = []

        sample_data = {
            "code": 200,
            "results": [
                {
                    "type": "status",
                    "id": "100",
                    "text": "Search result 1",
                    "url": "https://x.com/a/status/100",
                },
                {
                    "type": "status",
                    "id": "101",
                    "text": "Search result 2",
                    "url": "https://x.com/b/status/101",
                },
            ],
            "cursor": "next_page_cursor",
        }

        def mock_fetch_json(url: str, **kwargs) -> dict[str, Any]:
            requested_urls.append(url)
            return sample_data

        monkeypatch.setattr(client, "_fetch_json", mock_fetch_json)

        tweets, next_cursor = client.search_tweets("SpaceX", count=5)
        assert len(requested_urls) == 1
        assert "/2/search" in requested_urls[0]
        assert "q=SpaceX" in requested_urls[0]
        assert "feed=latest" in requested_urls[0]
        assert len(tweets) == 2
        assert next_cursor == "next_page_cursor"

    def test_search_tweets_supports_feed_parameter(self, monkeypatch):
        client = FxTwitterClient()
        requested_urls: list[str] = []

        sample_data = {
            "code": 200,
            "results": [],
            "cursor": {"top": None, "bottom": None},
        }

        def mock_fetch_json(url: str, **kwargs):
            requested_urls.append(url)
            return sample_data

        monkeypatch.setattr(client, "_fetch_json", mock_fetch_json)

        client.search_tweets("SpaceX", feed="top")
        assert len(requested_urls) == 1
        assert "feed=top" in requested_urls[0]

    def test_search_tweets_is_media_appends_filter(self, monkeypatch):
        client = FxTwitterClient()
        requested_urls: list[str] = []

        sample_data = {
            "code": 200,
            "results": [
                {
                    "type": "status",
                    "id": "200",
                    "text": "Media tweet",
                    "url": "https://x.com/a/status/200",
                    "media": {
                        "all": [
                            {"type": "photo", "url": "https://pbs.twimg.com/pic.jpg"}
                        ]
                    },
                },
                {
                    "type": "status",
                    "id": "201",
                    "text": "No media tweet",
                    "url": "https://x.com/b/status/201",
                },
            ],
        }

        def mock_fetch_json(url: str, **kwargs) -> dict[str, Any]:
            requested_urls.append(url)
            return sample_data

        monkeypatch.setattr(client, "_fetch_json", mock_fetch_json)

        tweets, _ = client.search_tweets("#art", is_media=True)
        assert (
            "filter%3Amedia" in requested_urls[0] or "filter:media" in requested_urls[0]
        )
        # Only the tweet with media is kept
        assert len(tweets) == 1
        assert tweets[0].status_id == "200"

    def test_search_tweets_empty_query(self):
        client = FxTwitterClient()
        tweets, cursor = client.search_tweets("")
        assert tweets == []
        assert cursor is None

    def test_search_tweets_404_raises_fxtwitter_not_found(self, monkeypatch):
        client = FxTwitterClient()

        def mock_fetch_json(url: str, **kwargs):
            raise FxTwitterNotFoundError("404 Not Found")

        monkeypatch.setattr(client, "_fetch_json", mock_fetch_json)

        with pytest.raises(FxTwitterNotFoundError) as exc_info:
            client.search_tweets("test_query")
        assert "404" in str(exc_info.value)


class TestFxTwitterClientFetchTrends:
    def test_fetch_trends_success(self, monkeypatch):
        client = FxTwitterClient()
        raw_trends = [
            {"name": "Topic 1", "rank": None, "context": "Trending in Japan"},
            {"name": "Topic 2", "rank": 2, "context": "Sports · Trending"},
            {"name": "Topic 3", "rank": "3"},
        ]

        def mock_fetch_json(url: str, **kwargs) -> dict[str, Any]:
            assert url == f"{DEFAULT_FXTWITTER_BASE_URL}/2/trends"
            return {
                "code": 200,
                "timeline_type": "trends",
                "trends": raw_trends,
            }

        monkeypatch.setattr(client, "_fetch_json", mock_fetch_json)

        trends = client.fetch_trends()
        assert len(trends) == 3
        assert trends[0]["name"] == "Topic 1"
        assert trends[0]["rank"] is None
        assert trends[0]["context"] == "Trending in Japan"

    def test_fetch_trends_raises_exception_for_caller_audit(self, monkeypatch):
        client = FxTwitterClient()

        def mock_fetch_json(url: str, **kwargs):
            raise FxTwitterError("Network error")

        monkeypatch.setattr(client, "_fetch_json", mock_fetch_json)

        # fetch_trends must raise FxTwitterError so caller can log failure audit
        with pytest.raises(FxTwitterError):
            client.fetch_trends()

    def test_fetch_trends_missing_trends_field(self, monkeypatch):
        client = FxTwitterClient()
        monkeypatch.setattr(client, "_fetch_json", lambda url, **kwargs: {"code": 200})
        trends = client.fetch_trends()
        assert trends == []


class TestFxTwitterClientFetchJson:
    def test_fetch_json_http_404(self, monkeypatch):
        client = FxTwitterClient()

        def mock_safe_urlopen(req, timeout):
            raise HTTPError(
                req.full_url, 404, "Not Found", hdrs=None, fp=io.BytesIO(b"")
            )

        monkeypatch.setattr(
            "media_support.fxtwitter_client.safe_urlopen", mock_safe_urlopen
        )

        with pytest.raises(FxTwitterNotFoundError) as exc_info:
            client._fetch_json("https://api.fxtwitter.com/2/search?q=test")
        assert "404" in str(exc_info.value)

    def test_fetch_json_payload_code_404(self, monkeypatch):
        client = FxTwitterClient()
        resp = _make_response(b'{"code": 404, "message": "Not Found"}', status=200)

        monkeypatch.setattr(
            "media_support.fxtwitter_client.safe_urlopen", lambda req, timeout: resp
        )

        with pytest.raises(FxTwitterNotFoundError) as exc_info:
            client._fetch_json("https://api.fxtwitter.com/2/search?q=test")
        assert "404" in str(exc_info.value)

    def test_fetch_json_other_http_error(self, monkeypatch):
        client = FxTwitterClient()

        def mock_safe_urlopen(req, timeout):
            raise HTTPError(
                req.full_url,
                500,
                "Internal Server Error",
                hdrs=None,
                fp=io.BytesIO(b""),
            )

        monkeypatch.setattr(
            "media_support.fxtwitter_client.safe_urlopen", mock_safe_urlopen
        )

        with pytest.raises(FxTwitterError) as exc_info:
            client._fetch_json("https://api.fxtwitter.com/2/trends")
        assert "500" in str(exc_info.value)

    def test_fetch_json_invalid_json(self, monkeypatch):
        client = FxTwitterClient()
        resp = _make_response(b"not a json", status=200)
        monkeypatch.setattr(
            "media_support.fxtwitter_client.safe_urlopen", lambda req, timeout: resp
        )

        with pytest.raises(FxTwitterError) as exc_info:
            client._fetch_json("https://api.fxtwitter.com/2/trends")
        assert "json" in str(exc_info.value).lower()
