"""Asia/Shanghai normalization for tweet published timestamps."""

from __future__ import annotations

from types import SimpleNamespace

from media_support.html_backend.parser import parse_timeline_html
from media_support.status_link import StatusLink
from media_support.status_resolve import _tweet_from_fx
from rendering.tweets import TweetMessageRenderer as R
from shared.utils import format_tweet_published


def test_twitter_utc_string_to_shanghai():
    # 05:15:34 UTC -> 13:15:34 CST
    assert (
        format_tweet_published("Tue Jul 28 05:15:34 +0000 2026")
        == "2026-07-28 13:15:34"
    )


def test_already_display_form_not_double_shifted():
    assert format_tweet_published("2026-07-28 13:15:34") == "2026-07-28 13:15:34"


def test_nitter_list_title_with_utc():
    assert format_tweet_published("Jul 28, 2026 · 5:15 AM UTC") == "2026-07-28 13:15:00"


def test_nitter_date_only_assumes_utc_midnight():
    # Jul 23 00:00 UTC -> Jul 23 08:00 Shanghai
    assert format_tweet_published("Jul 23, 2026") == "2026-07-23 08:00:00"


def test_empty_and_garbage():
    assert format_tweet_published("") == ""
    assert format_tweet_published("not-a-date") == "not-a-date"


def test_status_resolve_fx_uses_shanghai():
    link = StatusLink("Moliww", "1", "https://x.com/Moliww/status/1")
    tw = _tweet_from_fx(
        link,
        {
            "tweet": {
                "text": "#BlueArchive",
                "created_at": "Tue Jul 28 05:15:34 +0000 2026",
                "author": {"screen_name": "Moliww"},
                "url": link.canonical_url,
                "media": {"all": []},
            }
        },
    )
    assert tw is not None
    assert tw.published == "2026-07-28 13:15:34"


def test_html_list_parser_normalizes_title():
    html = """
    <div class="timeline-item">
      <a href="/Moliww/status/2081971805074620572">link</a>
      <div class="tweet-content">#BlueArchive</div>
      <span class="tweet-date"><a title="Jul 28, 2026 · 5:15 AM UTC">date</a></span>
    </div>
    """
    page = parse_timeline_html(html, "https://nitter.example")
    assert page.tweets, "expected at least one parsed item"
    assert page.tweets[0].published == "2026-07-28 13:15:00"


def test_client_rss_format_pub_date_delegates_to_shared():
    from media_support.client import NitterClient

    assert (
        NitterClient._format_pub_date("Tue Jul 28 05:15:34 +0000 2026")
        == "2026-07-28 13:15:34"
    )
    assert NitterClient._format_pub_date("2026-07-28 13:15:34") == "2026-07-28 13:15:34"
    assert NitterClient._format_pub_date("") == ""


def test_display_form_documented_as_shanghai_not_utc_wall():
    """Bare display form must not be re-interpreted as UTC (no second +8)."""
    assert format_tweet_published("2026-07-28 05:15:34") == "2026-07-28 05:15:34"


def test_renderer_header_converts_utc_string():
    tw = SimpleNamespace(
        status_id="1",
        username="nasa",
        text="hi",
        x_url="https://x.com/nasa/status/1",
        link="https://x.com/nasa/status/1",
        published="Tue Jul 28 05:15:34 +0000 2026",
        media=[],
        translation="",
        ai_warnings=[],
        media_warnings=[],
        is_repost=False,
    )
    out = R.format_tweet(0, "nasa", tw, omit_status_url=True, link_style="plain")
    assert out.startswith("@nasa · 2026-07-28 13:15:34")
