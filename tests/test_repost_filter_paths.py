# -*- coding: utf-8 -*-
"""Repost filtering: search always on; manual /推文 forced off."""
from __future__ import annotations

from media_support.html_backend.parser import is_pure_retweet_chunk, parse_timeline_html
from media_support.client import NitterClient
from shared.utils import TweetItem


def test_is_pure_retweet_chunk_detects_header():
    rt = '''<div class="timeline-item">
      <div class="retweet-header"><span>foo retweeted</span></div>
      <a href="/orig/status/1">x</a>
      <div class="tweet-content">hi</div>
    </div>'''
    assert is_pure_retweet_chunk(rt) is True
    normal = '''<div class="timeline-item">
      <a href="/u/status/2">x</a>
      <div class="tweet-content">hello</div>
    </div>'''
    assert is_pure_retweet_chunk(normal) is False


def test_parse_timeline_marks_is_retweet():
    html = '''
    <div class="timeline-item">
      <div class="retweet-header">Someone retweeted</div>
      <a class="tweet-date" href="/other/status/11" title="t"></a>
      <div class="tweet-content">rt body</div>
    </div>
    <div class="timeline-item">
      <a class="tweet-date" href="/real/status/22" title="t"></a>
      <div class="tweet-content">orig body</div>
    </div>
    '''
    page = parse_timeline_html(html, "https://nitter.example")
    assert len(page.tweets) == 2
    by_id = {t.status_id: t for t in page.tweets}
    assert by_id["11"].is_retweet is True
    assert by_id["22"].is_retweet is False


def test_filter_reposts_enabled_override():
    client = NitterClient.__new__(NitterClient)
    client.filter_reposts_enabled = True
    tweets = [
        TweetItem(text="a", link="https://x.com/watched/status/1", published=""),
        TweetItem(text="b", link="https://x.com/other/status/2", published=""),
    ]
    kept, n = client._filter_reposts(tweets, "watched", enabled=True)
    assert n == 1 and len(kept) == 1 and kept[0].status_id == "1"
    kept2, n2 = client._filter_reposts(tweets, "watched", enabled=False)
    assert n2 == 0 and len(kept2) == 2


def test_paginate_search_drops_is_retweet():
    from media_support.html_backend.pool import HtmlNitterPool, PoolConfig

    pool = HtmlNitterPool.__new__(HtmlNitterPool)
    pool.config = PoolConfig(instances=["https://nitter.example"], max_pages=1)

    page_tweets = [
        TweetItem(
            text="rt",
            link="https://x.com/a/status/1",
            published="",
            is_retweet=True,
        ),
        TweetItem(
            text="ok",
            link="https://x.com/b/status/2",
            published="",
            is_retweet=False,
        ),
    ]

    class Page:
        tweets = page_tweets
        next_cursor = ""

    calls = {"n": 0}

    def fake_get(base, path):
        calls["n"] += 1
        return b"<html></html>"

    pool._get_html = fake_get  # type: ignore

    import media_support.html_backend.pool as pool_mod
    original = pool_mod.parse_timeline_html

    def fake_parse(html, instance, **kwargs):
        return Page()

    pool_mod.parse_timeline_html = fake_parse  # type: ignore
    try:
        # bind method
        out = HtmlNitterPool._paginate_search(
            pool, "https://nitter.example", "#tag", 10, kind="tag"
        )
    finally:
        pool_mod.parse_timeline_html = original

    assert len(out) == 1
    assert out[0].status_id == "2"
    assert out.raw_item_count == 2
    assert out.retweet_filtered == 1

def test_retweet_header_inside_tweet_body_not_killed_by_icon():
    # Real Nitter: retweet-header is inside tweet-body, before tweet-content.
    # Footer icon-retweet alone must not mark originals.
    from media_support.html_backend.parser import is_pure_retweet_chunk, parse_timeline_html

    rt = (
        '<div class="timeline-item">'
        '<div class="tweet-body">'
        '<div class="retweet-header"><span class="icon-retweet"></span>Someone retweeted</div>'
        '<a href="/bob/status/2">x</a>'
        '<div class="tweet-content">political long post</div>'
        '<span class="icon-retweet"></span>'
        '</div></div>'
    )
    orig = (
        '<div class="timeline-item">'
        '<div class="tweet-body">'
        '<a href="/alice/status/1">x</a>'
        '<div class="tweet-content">明日方舟 铃兰 cos</div>'
        '<span class="icon-retweet"></span>'
        '</div></div>'
    )
    assert is_pure_retweet_chunk(rt) is True
    assert is_pure_retweet_chunk(orig) is False
    page = parse_timeline_html(rt + orig, "https://nitter.example")
    assert [t.is_retweet for t in page.tweets] == [True, False]

