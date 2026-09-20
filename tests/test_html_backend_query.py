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
    query, limit, _sort, error = host._parse_search_args(
        SimpleNamespace(get_message_str=lambda: ""),
        "x" * (MAX_QUERY_LENGTH + 1),
    )
    assert query == ""
    assert limit == 0
    assert str(MAX_QUERY_LENGTH) in error


def test_parse_search_args_top_keyword_extracts_sort():
    host = ManualCommandMixin()
    host.default_limit = 5
    host.search_max_limit = 10
    query, limit, sort, error = host._parse_search_args(
        SimpleNamespace(get_message_str=lambda: ""),
        "纳西妲 top 5",
    )
    assert query == "纳西妲"
    assert limit == 5
    assert sort == "top"
    assert not error


def test_parse_search_args_hot_keyword_extracts_sort():
    host = ManualCommandMixin()
    host.default_limit = 5
    host.search_max_limit = 10
    query, limit, sort, error = host._parse_search_args(
        SimpleNamespace(get_message_str=lambda: ""),
        "纳西妲 热门",
    )
    assert query == "纳西妲"
    assert sort == "top"
    assert not error


def test_parse_search_args_top_in_query_not_stripped():
    """'top' inside a query word like 'toproad' must not be stripped."""
    host = ManualCommandMixin()
    host.default_limit = 5
    host.search_max_limit = 10
    query, limit, sort, error = host._parse_search_args(
        SimpleNamespace(get_message_str=lambda: ""),
        "toproad 5",
    )
    assert query == "toproad"
    assert sort == ""
    assert not error


def test_parse_search_args_top_gear_not_stripped():
    """'top gear' as a multi-word query must not lose 'top'."""
    host = ManualCommandMixin()
    host.default_limit = 5
    host.search_max_limit = 10
    query, limit, sort, error = host._parse_search_args(
        SimpleNamespace(get_message_str=lambda: ""),
        "top gear 5",
    )
    assert query == "top gear"
    assert sort == ""
    assert not error


# --- CLI flag extraction tests ---


def _parse(text, default_limit=5, max_limit=10):
    host = ManualCommandMixin()
    host.default_limit = default_limit
    host.search_max_limit = max_limit
    return host._parse_search_args(
        SimpleNamespace(get_message_str=lambda: ""),
        text,
    )


def test_flag_preserves_query_with_top_and_number():
    """hltv top 10 — 'top' and '10' are part of the query, flags extract cleanly."""
    query, limit, sort, error = _parse("hltv top 10 -n 10 -top")
    assert query == "hltv top 10"
    assert limit == 10
    assert sort == "top"
    assert not error


def test_flag_limit_with_pure_number_query():
    """1984 -n 5 — book title '1984' must not be consumed as a limit."""
    query, limit, sort, error = _parse("1984 -n 5")
    assert query == "1984"
    assert limit == 5
    assert sort == ""
    assert not error


def test_flag_preceding_query():
    """Flags before the query text."""
    query, limit, sort, error = _parse("-top -n 8 蔚蓝档案")
    assert query == "蔚蓝档案"
    assert limit == 8
    assert sort == "top"
    assert not error


def test_flag_trailing_query():
    """Flags after the query text."""
    query, limit, sort, error = _parse("蔚蓝档案 -top -n 8")
    assert query == "蔚蓝档案"
    assert limit == 8
    assert sort == "top"
    assert not error


def test_flag_preserves_twitter_exclude_syntax():
    """csgo -valorant — Twitter exclusion '-valorant' must stay in query."""
    query, limit, sort, error = _parse("csgo -valorant -n 5 -top")
    assert query == "csgo -valorant"
    assert limit == 5
    assert sort == "top"
    assert not error


def test_flag_not_partial_match_in_larger_word():
    """-topgear must not be consumed as the -top flag."""
    query, limit, sort, error = _parse("-topgear -n 3")
    # -topgear is not a known flag → branch B (no flags detected)
    # -topgear stays in query, -n 3 is also not detected because
    # -topgear consumes the - prefix so limit_re won't find -n
    # Actually: limit_re scans the whole text independently,
    # so -n 3 IS found. -topgear is NOT in sort_re (token boundary).
    assert query == "-topgear"
    assert limit == 3
    assert sort == ""
    assert not error


def test_flag_n_must_be_standalone_number():
    """-n 5G should not match (5G is not a standalone number)."""
    query, limit, sort, error = _parse("蔚蓝档案 -n 5G")
    # No valid flag → branch B backward-compat: "蔚蓝档案 -n 5G"
    # rsplit last token "5G" is not digit → query = whole text
    assert query == "蔚蓝档案 -n 5G"
    assert sort == ""
    assert not error


def test_flag_backward_compat_trailing_hot():
    """Old-style '纳西妲 5 热门' still works without flags."""
    query, limit, sort, error = _parse("纳西妲 5 热门")
    assert query == "纳西妲"
    assert limit == 5
    assert sort == "top"
    assert not error


def test_flag_backward_compat_top_before_number():
    """Old-style '纳西妲 top 5' still works without flags."""
    query, limit, sort, error = _parse("纳西妲 top 5")
    assert query == "纳西妲"
    assert limit == 5
    assert sort == "top"
    assert not error


# --- bare -<number> and -last flag tests ---


def test_flag_bare_number_limit():
    """-3 is a shorthand for -n 3."""
    query, limit, sort, error = _parse("deepseek娘 -3")
    assert query == "deepseek娘"
    assert limit == 3
    assert sort == ""
    assert not error


def test_flag_bare_number_with_sort():
    """The original bug report: 'deepseek娘 -3 -top' must not leak -3 into query."""
    query, limit, sort, error = _parse("deepseek娘 -3 -top")
    assert query == "deepseek娘"
    assert limit == 3
    assert sort == "top"
    assert not error


def test_flag_last_sort():
    """-last explicitly forces chronological (f=tweets) sort."""
    query, limit, sort, error = _parse("deepseek娘 -last")
    assert query == "deepseek娘"
    assert sort == "latest"
    assert not error


def test_flag_last_sort_chinese():
    """-最新 is the Chinese alias for -last."""
    query, limit, sort, error = _parse("deepseek娘 -最新")
    assert query == "deepseek娘"
    assert sort == "latest"
    assert not error


def test_flag_last_overrides_top():
    """Last sort flag wins: -top -last → latest."""
    query, limit, sort, error = _parse("deepseek娘 -top -last")
    assert query == "deepseek娘"
    assert sort == "latest"
    assert not error


def test_flag_top_overrides_last():
    """Last sort flag wins: -last -top → top."""
    query, limit, sort, error = _parse("deepseek娘 -last -top")
    assert query == "deepseek娘"
    assert sort == "top"
    assert not error


def test_flag_bare_number_preserves_twitter_exclude():
    """csgo -valorant -3 — Twitter exclude stays, -3 is the limit."""
    query, limit, sort, error = _parse("csgo -valorant -3")
    assert query == "csgo -valorant"
    assert limit == 3
    assert not error


def test_flag_bare_number_not_partial_in_word():
    """-5G is not a standalone number, must not match bare limit."""
    query, limit, sort, error = _parse("deepseek娘 -5G")
    # No valid flag → branch B backward-compat
    assert query == "deepseek娘 -5G"
    assert sort == ""
    assert not error


def test_flag_bare_number_zero_rejected():
    """-0 → limit 0 → '数量至少为 1。'"""
    _q, _l, _s, error = _parse("deepseek娘 -0")
    assert "数量至少为 1" in error


def test_flag_dash_letter_not_consumed_as_limit():
    """-min_faves:100 stays in query; -3 still works as limit."""
    query, limit, sort, error = _parse("白丝 -min_faves:100 -3")
    assert "min_faves:100" in query
    assert limit == 3
    assert not error


def test_flag_bare_and_n_combined_last_wins():
    """-3 -n 5 → last (5) wins; -n 5 -3 → last (3) wins."""
    _q, limit_a, _s, _e = _parse("deepseek娘 -3 -n 5")
    assert limit_a == 5
    _q, limit_b, _s, _e = _parse("deepseek娘 -n 5 -3")
    assert limit_b == 3


# --- _search_query_key isolation tests ---


def test_search_query_key_latest_gets_suffix():
    """Explicit -last (sort='latest') must not share key with no-flag (sort='')."""
    host = ManualCommandMixin()
    key_none = host._search_query_key("deepseek娘", "")
    key_latest = host._search_query_key("deepseek娘", "latest")
    key_top = host._search_query_key("deepseek娘", "top")
    assert key_none != key_latest
    assert key_none != key_top
    assert key_latest != key_top


def test_media_search_appended_filter_media_exceeds_max_length():
    """195-char query passes regular search parse, but when is_media_search=True,
    appending ' filter:media' (208 chars > 200) is gracefully rejected with a warning.
    """
    host = ManualCommandMixin()
    host.default_limit = 5
    host.search_max_limit = 10

    raw_query = "x" * 195
    # In regular search, parsing passes without length error:
    q, limit, sort, error = host._parse_search_args(
        SimpleNamespace(get_message_str=lambda: ""),
        raw_query,
    )
    assert error == ""
    assert q == raw_query

    # In media search via _cmd_tweet_search_impl, appending filter:media causes len > 200
    # and sends a graceful error message without throwing:
    event = SimpleNamespace(
        stop_event=MagicMock(),
        get_message_str=lambda: "",
        send=AsyncMock(),
        plain_result=lambda s: s,
    )
    asyncio.run(host._cmd_tweet_search_impl(event, raw_query, is_media_search=True))

    event.send.assert_awaited_once()
    sent_msg = event.send.call_args[0][0]
    assert f"加上搜图过滤后最多 {MAX_QUERY_LENGTH} 字符" in sent_msg


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
    plugin.nitter.search.assert_not_called()


def _probe_tweet(status_id: str = "1") -> TweetItem:
    return TweetItem(
        text=f"tweet {status_id}",
        link=f"https://x.com/nasa/status/{status_id}",
        published="",
    )


def test_web_probe_all_rss_instances_is_serial_and_keeps_partial_failures():
    nitter = SimpleNamespace(
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
        fetch_user_html=MagicMock(
            side_effect=[
                ("https://rss-a.example", [_probe_tweet("1")]),
                ("https://rss-b.example", [_probe_tweet("2")]),
            ]
        ),
        search=MagicMock(
            side_effect=[
                ("https://rss-a.example", [_probe_tweet("1")]),
                ("https://rss-b.example", [_probe_tweet("2")]),
            ]
        ),
    )
    plugin = SimpleNamespace(
        config={},
        default_limit=5,
        nitter=nitter,
    )

    result = asyncio.run(
        NitterWebAPI(plugin).probe_mirror(
            {
                "username": "nasa",
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
    assert result["results"][0]["checks"]["rss_user"]["tweet_count"] == 1
    assert result["results"][1]["success"] is False
    calls = plugin.nitter.fetch_tweets_from_instance.await_args_list
    assert [call.args[0] for call in calls] == [
        "https://rss-a.example",
        "https://rss-b.example",
    ]
    plugin.nitter.search.assert_not_called()
    assert "search" not in result["results"][0]["checks"]


def test_web_probe_all_instances_returns_all_failed_rows():
    nitter = SimpleNamespace(
        instances=["https://search-a.example"],
        fetch_tweets_from_instance=AsyncMock(side_effect=RuntimeError("rss")),
        fetch_user_html=MagicMock(side_effect=RuntimeError("html")),
        search=MagicMock(side_effect=RuntimeError("429")),
    )
    plugin = SimpleNamespace(
        config={},
        default_limit=5,
        nitter=nitter,
    )

    result = asyncio.run(
        NitterWebAPI(plugin).probe_mirror(
            {
                "query": "#AI",
                "instance": "",
            }
        )
    )

    assert result["success"] is True
    assert result["summary"] == {"total": 1, "succeeded": 0, "failed": 1}
    assert result["results"][0]["success"] is False
    assert "rss_user" not in result["results"][0]["checks"]
    assert "html_user" not in result["results"][0]["checks"]
    nitter.fetch_tweets_from_instance.assert_not_called()
    nitter.fetch_user_html.assert_not_called()
    nitter.search.assert_called_once_with(
        "#AI",
        5,
        kind="tag",
        instance="https://search-a.example",
    )


def test_web_probe_requires_at_least_one_target():
    plugin = SimpleNamespace(
        config={},
        default_limit=5,
        nitter=SimpleNamespace(instances=["https://mirror.example"]),
    )
    api = NitterWebAPI(plugin)
    res = asyncio.run(api.probe_mirror({"instance": "https://mirror.example"}))
    assert res["success"] is False
    assert "请至少填写一项测试目标" in res["error"]


def test_web_probe_list_only():
    nitter = SimpleNamespace(
        instances=["https://mirror.example"],
        fetch_tweets_from_instance=AsyncMock(),
        fetch_user_html=MagicMock(),
        search=MagicMock(),
        fetch_list=MagicMock(
            return_value=("https://mirror.example", [_probe_tweet("10")])
        ),
    )
    plugin = SimpleNamespace(
        config={},
        default_limit=5,
        nitter=nitter,
    )
    api = NitterWebAPI(plugin)
    res = asyncio.run(
        api.probe_mirror(
            {
                "list_id": "12345678",
                "instance": "https://mirror.example",
            }
        )
    )
    assert res["success"] is True
    assert res["results"][0]["success"] is True
    assert "list" in res["results"][0]["checks"]
    assert "rss_user" not in res["results"][0]["checks"]
    assert "html_user" not in res["results"][0]["checks"]
    assert "search" not in res["results"][0]["checks"]
    nitter.fetch_list.assert_called_once_with(
        "12345678", 5, instance="https://mirror.example"
    )
    nitter.fetch_tweets_from_instance.assert_not_called()
    nitter.fetch_user_html.assert_not_called()
    nitter.search.assert_not_called()


def test_web_probe_invalid_list_id_rejects():
    plugin = SimpleNamespace(
        config={},
        default_limit=5,
        nitter=SimpleNamespace(instances=["https://mirror.example"]),
    )
    api = NitterWebAPI(plugin)
    res = asyncio.run(
        api.probe_mirror(
            {
                "list_id": "not-digits",
                "instance": "https://mirror.example",
            }
        )
    )
    assert res["success"] is False
    assert "List ID 必须为纯数字" in res["error"]


def test_web_probe_all_requires_configured_instances_but_single_url_stays_compatible():
    plugin = SimpleNamespace(
        config={},
        default_limit=5,
        nitter=SimpleNamespace(instances=[]),
    )
    api = NitterWebAPI(plugin)

    empty = asyncio.run(api.probe_mirror({"username": "nasa"}))
    assert empty["success"] is False
    assert "未配置自建 Nitter 实例" in empty["error"]

    plugin.nitter.fetch_tweets_from_instance = AsyncMock(
        return_value=("https://single.example", [_probe_tweet("2")])
    )
    plugin.nitter.fetch_user_html = MagicMock(
        return_value=("https://single.example", [_probe_tweet("2")])
    )
    plugin.nitter.search = MagicMock(
        return_value=("https://single.example", [_probe_tweet("2")])
    )
    single = asyncio.run(
        api.probe_mirror(
            {
                "username": "nasa",
                "instance": "https://single.example",
            }
        )
    )
    assert single["success"] is True
    assert len(single["results"]) == 1
    assert single["results"][0]["instance"] == "https://single.example"


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


def test_parse_timeline_html_media_only_body_does_not_leak_page_chrome():
    html = """
    <div class="timeline-item">
      <div class="tweet-body">
        <div class="fullname">Yurei Display Name</div>
        <a class="username">@yureiyks</a>
        <div class="attachments">
          <a class="hls-button">启用 HLS 播放</a>
          <video src="/video/2082364407330341030.mp4"></video>
        </div>
      </div>
      <a href="/yureiyks/status/2082364407330341030">status</a>
    </div>
    """

    page = parse_timeline_html(html, "https://nitter.example")

    assert len(page.tweets) == 1
    tweet = page.tweets[0]
    assert tweet.text == "(无正文)"
    assert [(media.kind, media.url) for media in tweet.media] == [
        ("video", "https://nitter.example/video/2082364407330341030.mp4")
    ]


def test_parse_timeline_html_text_photo_status_keeps_body_and_media():
    html = """
    <div class="timeline-item">
      <div class="tweet-body">
        <div class="tweet-content media-body">狼群之名终将响彻大地！</div>
        <div class="attachments">
          <a class="still-image" href="/pic/orig/media%2FHOOD.jpg"></a>
        </div>
      </div>
      <span class="tweet-date"><a title="Jul 28, 2026 · 11:54 AM UTC">date</a></span>
      <a href="/Yodachipoi/status/2082072289068351718">status</a>
    </div>
    """

    page = parse_timeline_html(html, "https://nitter.example")

    assert len(page.tweets) == 1
    tweet = page.tweets[0]
    assert tweet.text == "狼群之名终将响彻大地！"
    assert [(media.kind, media.url) for media in tweet.media] == [
        ("image", "https://nitter.example/pic/orig/media%2FHOOD.jpg")
    ]
