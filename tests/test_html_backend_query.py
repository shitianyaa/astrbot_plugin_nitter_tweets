from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from command_handlers.manual import ManualCommandMixin
from media_support.html_backend.parser import parse_timeline_html
from media_support.html_backend.query import (
    MAX_QUERY_LENGTH,
    decode_watch_query,
    encode_watch_query,
    normalize_query,
    normalize_watch_query,
    query_kind,
    seen_account_key_for_query,
)
from media_support.html_backend.rate_limit import RateLimitConfig, RateLimiter
from plugin_api.api import NitterWebAPI
from shared.utils import TweetItem


def test_query_kind_leading_hash_is_tag():
    assert query_kind("#圣娅") == "tag"
    assert query_kind("  #a ") == "tag"


def test_query_kind_no_leading_hash_is_phrase():
    assert query_kind("python programming") == "phrase"
    assert query_kind("foo #bar") == "phrase"
    assert query_kind("蔚蓝档案 攻略") == "phrase"


def test_normalize_query_never_auto_hash():
    assert normalize_query("  hello  ") == "hello"
    assert not normalize_query("hello").startswith("#")


def test_normalize_watch_query_tag_fixup_and_phrase_no_hash():
    q, kind = normalize_watch_query("圣娅", "tag")
    assert kind == "tag"
    assert q == "#圣娅"
    q2, kind2 = normalize_watch_query("python", "phrase")
    assert kind2 == "phrase"
    assert q2 == "python"
    assert not q2.startswith("#")


def test_normalize_watch_query_infers_type_when_missing():
    q, kind = normalize_watch_query("#x", None)
    assert kind == "tag" and q == "#x"
    q2, kind2 = normalize_watch_query("x", None)
    assert kind2 == "phrase" and q2 == "x"


def test_seen_account_key_casefold():
    assert seen_account_key_for_query("#AB") == "q:#ab"
    assert seen_account_key_for_query("  Hello ") == "q:hello"


def test_explicit_query_type_round_trips_through_string_storage():
    encoded = encode_watch_query("#literal", "phrase")
    assert encoded.startswith("nitter-query:phrase:")
    assert normalize_watch_query(encoded) == ("#literal", "phrase")
    assert decode_watch_query(encoded) == ("#literal", "phrase")

    encoded_tag = encode_watch_query("literal", "tag")
    assert normalize_watch_query(encoded_tag) == ("#literal", "tag")


def test_query_length_is_rejected_without_truncating_seen_keys():
    too_long = "x" * (MAX_QUERY_LENGTH + 1)
    assert normalize_query(too_long) == ""
    assert normalize_watch_query(too_long)[0] == ""
    assert seen_account_key_for_query(too_long) == ""


def test_manual_search_reports_query_length_before_network_call():
    host = ManualCommandMixin()
    host.default_limit = 5
    host.search_max_limit = 10
    query, limit, error = host._parse_search_args(
        SimpleNamespace(get_message_str=lambda: ""),
        "x" * (MAX_QUERY_LENGTH + 1),
    )
    assert query == ""
    assert limit == 0
    assert str(MAX_QUERY_LENGTH) in error


def test_web_probe_reports_query_length_before_backend_call():
    plugin = MagicMock()
    plugin.config = {}
    result = asyncio.run(
        NitterWebAPI(plugin).probe_mirror(
            {
                "instance": "https://mirror.example",
                "mode": "search",
                "query": "x" * (MAX_QUERY_LENGTH + 1),
            }
        )
    )
    assert result["success"] is False
    assert str(MAX_QUERY_LENGTH) in result["error"]
    plugin.html_backend.search.assert_not_called()


def _probe_tweet(status_id: str = "1") -> TweetItem:
    return TweetItem(
        text=f"tweet {status_id}",
        link=f"https://x.com/nasa/status/{status_id}",
        published="",
    )


def test_web_probe_all_rss_instances_is_serial_and_keeps_partial_failures():
    plugin = SimpleNamespace(
        config={},
        default_limit=5,
        nitter=SimpleNamespace(
            instances=[
                "https://rss-a.example",
                "https://rss-b.example",
                "https://rss-a.example",
            ],
            fetch_tweets_from_instance=AsyncMock(
                side_effect=[
                    ("https://rss-a.example", [_probe_tweet("1")]),
                    RuntimeError("temporarily unavailable"),
                ]
            ),
        ),
        html_backend=None,
    )

    result = asyncio.run(
        NitterWebAPI(plugin).probe_mirror(
            {
                "mode": "blogger_rss",
                "username": "nasa",
                "probe_all": True,
                "instance": "",
            }
        )
    )

    assert result["success"] is True
    assert [item["instance"] for item in result["results"]] == [
        "https://rss-a.example",
        "https://rss-b.example",
    ]
    assert result["summary"] == {"total": 2, "succeeded": 1, "failed": 1}
    assert result["results"][0]["tweet_count"] == 1
    assert result["results"][1]["success"] is False
    calls = plugin.nitter.fetch_tweets_from_instance.await_args_list
    assert [call.args[0] for call in calls] == [
        "https://rss-a.example",
        "https://rss-b.example",
    ]


def test_web_probe_all_search_instances_returns_all_failed_rows():
    html_backend = SimpleNamespace(
        config=SimpleNamespace(search_instances=["https://search-a.example"]),
        search=MagicMock(side_effect=RuntimeError("429")),
    )
    plugin = SimpleNamespace(
        config={},
        default_limit=5,
        nitter=SimpleNamespace(instances=[]),
        html_backend=html_backend,
    )

    result = asyncio.run(
        NitterWebAPI(plugin).probe_mirror(
            {
                "mode": "search",
                "query": "#AI",
                "probe_all": True,
                "instance": "",
            }
        )
    )

    assert result["success"] is True
    assert result["summary"] == {"total": 1, "succeeded": 0, "failed": 1}
    assert result["results"][0]["success"] is False
    html_backend.search.assert_called_once_with(
        "#AI",
        5,
        kind="tag",
        instance="https://search-a.example",
    )


def test_web_probe_all_requires_configured_instances_but_single_url_stays_compatible():
    plugin = SimpleNamespace(
        config={},
        default_limit=5,
        nitter=SimpleNamespace(instances=[]),
        html_backend=None,
    )
    api = NitterWebAPI(plugin)

    empty = asyncio.run(
        api.probe_mirror({"mode": "blogger_rss", "username": "nasa", "probe_all": True})
    )
    assert empty["success"] is False
    assert "没有配置实例" in empty["error"]

    plugin.nitter.fetch_tweets_from_instance = AsyncMock(
        return_value=("https://single.example", [_probe_tweet("2")])
    )
    single = asyncio.run(
        api.probe_mirror(
            {
                "mode": "blogger_rss",
                "username": "nasa",
                "instance": "https://single.example",
            }
        )
    )
    assert single["success"] is True
    assert "results" not in single
    assert single["instance"] == "https://single.example"


def test_tag_prefix_is_included_in_length_limit():
    raw = "x" * MAX_QUERY_LENGTH
    assert normalize_watch_query(raw, "tag")[0] == ""
    assert encode_watch_query(raw, "tag") == ""


def test_casefold_expansion_is_included_in_storage_key_limit():
    assert normalize_query("ß" * 101) == ""


def test_rate_limiter_punish_doubles_until_cap():
    limiter = RateLimiter(
        RateLimitConfig(cooldown_base=30.0, cooldown_cap=300.0, global_min_interval=0)
    )
    assert limiter.punish("h.example") == 30.0
    assert limiter.punish("h.example") == 60.0
    assert limiter.punish("h.example") == 120.0
    assert limiter.punish("h.example") == 240.0
    assert limiter.punish("h.example") == 300.0
    assert limiter.is_cooling("h.example")
    limiter.reward("h.example")
    # strikes cleared; still cooling until old until expires is ok
    assert limiter._cooldown_strikes["h.example"] == 0


def test_parse_timeline_html_minimal_fixture():
    html = """
    <div class="timeline-item">
      <a href="/nasa/status/1234567890">link</a>
      <div class="tweet-content media-body">Hello world</div>
      <span class="tweet-date"><a title="Jul 23, 2026">date</a></span>
      <div class="attachments">
        <a class="still-image" href="https://pbs.twimg.com/media/ABC?name=small"></a>
      </div>
    </div>
    """
    page = parse_timeline_html(html, "https://nitter.example")
    assert page.raw_item_count == 1
    assert len(page.tweets) == 1
    tweet = page.tweets[0]
    assert tweet.status_id == "1234567890"
    assert tweet.username == "nasa"
    assert tweet.link == "https://x.com/nasa/status/1234567890"
    assert "Hello world" in tweet.text
    assert tweet.media and tweet.media[0].is_image
    assert "name=orig" in tweet.media[0].url
