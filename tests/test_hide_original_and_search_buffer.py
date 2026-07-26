# -*- coding: utf-8 -*-
from __future__ import annotations

from types import SimpleNamespace

from media_support.search_session_buffer import SessionSearchBuffer
from rendering.tweets import TweetMessageRenderer


def _tweet(**kw):
    base = dict(
        status_id="1",
        username="realuser",
        text="hello world https://example.com/x",
        x_url="https://x.com/realuser/status/1",
        link="https://x.com/realuser/status/1",
        published="",
        media=[],
        translation="",
        ai_warnings=[],
        media_warnings=[],
        is_repost=False,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_hide_original_when_translated_hides_body():
    t = _tweet(translation="你好世界")
    out = TweetMessageRenderer.format_tweet(
        0,
        "realuser",
        t,
        omit_status_url=True,
        hide_original_when_translated=True,
    )
    assert "翻译" in out
    assert "你好世界" in out
    assert "原文" not in out
    assert "hello world" not in out


def test_hide_original_keeps_body_without_translation():
    t = _tweet(translation="")
    out = TweetMessageRenderer.format_tweet(
        0,
        "realuser",
        t,
        omit_status_url=True,
        hide_original_when_translated=True,
    )
    assert "原文" in out
    assert "hello world" in out
    assert "翻译" not in out


def test_hide_original_false_shows_both():
    t = _tweet(translation="你好世界")
    out = TweetMessageRenderer.format_tweet(
        0,
        "realuser",
        t,
        omit_status_url=True,
        hide_original_when_translated=False,
    )
    assert "原文" in out
    assert "翻译" in out


def test_search_buffer_known_ids_skip_same_page():
    buf = SessionSearchBuffer()
    items = [SimpleNamespace(status_id=str(i), link="", text="t") for i in range(1, 6)]
    assert buf.add_tweets(items) == 5
    assert [x.status_id for x in buf.take(5)] == ["1", "2", "3", "4", "5"]
    assert buf.add_tweets(items) == 0
    assert len(buf) == 0


def test_search_buffer_accepts_new_ids_after_exhaust():
    buf = SessionSearchBuffer()
    first = [SimpleNamespace(status_id=str(i), link="", text="t") for i in range(1, 4)]
    buf.add_tweets(first)
    buf.take(3)
    second = [SimpleNamespace(status_id=str(i), link="", text="t") for i in range(3, 7)]
    # 3 known, 4-6 new
    assert buf.add_tweets(second) == 3
    assert [x.status_id for x in buf.take(10)] == ["4", "5", "6"]


def test_display_username_prefers_tweet_author_for_query():
    t = _tweet(username="realuser")
    assert TweetMessageRenderer.display_username("#标签", t) == "realuser"
    assert TweetMessageRenderer.display_username("q:#tag", t) == "realuser"
