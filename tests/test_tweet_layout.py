# -*- coding: utf-8 -*-
"""Tweet message layout: TG author link, URL policy, empty body, block order."""
from __future__ import annotations

from types import SimpleNamespace

from rendering.tweets import TweetMessageRenderer as R


def _tw(**kw):
    base = dict(
        status_id="1",
        username="nasa",
        text="Hello #space https://t.co/abc world",
        x_url="https://x.com/nasa/status/1",
        link="https://x.com/nasa/status/1",
        published="2026-07-23 12:00:00",
        media=[],
        translation="",
        ai_warnings=[],
        media_warnings=[],
        is_repost=False,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_telegram_header_is_author_link_not_body_preview():
    out = R.format_tweet(
        0,
        "nasa",
        _tw(),
        omit_status_url=True,
        link_style="telegram_md",
    )
    first = out.split("\n\n", 1)[0]
    assert first.startswith("[@nasa](https://x.com/nasa/status/1)")
    assert "Hello #space" not in first
    assert "原文：" in out
    assert "Hello #space world" in out  # body still present, URL stripped


def test_plain_header_is_at_author():
    out = R.format_tweet(0, "nasa", _tw(), omit_status_url=True, link_style="plain")
    assert out.startswith("@nasa\n")
    assert "[@" not in out.split("\n\n", 1)[0]


def test_omit_false_keeps_inline_urls_and_footer_link():
    out = R.format_tweet(
        0,
        "nasa",
        _tw(),
        omit_status_url=False,
        link_style="plain",
    )
    assert "https://t.co/abc" in out
    assert "Hello #space https://t.co/abc world" in out
    assert "原文链接：" in out
    assert "https://x.com/nasa/status/1" in out


def test_empty_body_placeholder():
    out = R.format_tweet(
        0,
        "nasa",
        _tw(text="   ", translation=""),
        omit_status_url=True,
    )
    assert "（无正文）" in out or "(无正文)" in out


def test_translation_block_before_original_when_both():
    out = R.format_tweet(
        0,
        "nasa",
        _tw(translation="你好世界"),
        omit_status_url=True,
        hide_original_when_translated=False,
    )
    i_tr = out.find("翻译：")
    i_orig = out.find("原文：")
    assert i_tr != -1 and i_orig != -1
    assert i_tr < i_orig


def test_hide_original_only_translation():
    out = R.format_tweet(
        0,
        "nasa",
        _tw(translation="你好世界"),
        omit_status_url=True,
        hide_original_when_translated=True,
    )
    assert "翻译：" in out
    assert "原文：" not in out


def test_time_is_separate_block_not_glued_only_to_author_line_semantics():
    """Author block then time as own section improves scanability."""
    out = R.format_tweet(0, "nasa", _tw(), omit_status_url=True)
    # After change: @nasa \n\n 时间：... \n\n 原文
    assert "时间：" in out
    parts = out.split("\n\n")
    assert any(p.startswith("@nasa") or p.startswith("[@nasa]") for p in parts[:2])
    assert any("时间：" in p for p in parts)


def test_media_only_telegram_author_link():
    # build_media_only returns components; check author plain text content
    class M:
        path = ""
        is_image = False
        is_video = False

    tweet = _tw(media=[])
    r = R(send_image_attachments=True, send_video_attachments=False)
    comps = r.build_media_only_components(
        "nasa",
        tweet,
        link_style="telegram_md",
        omit_status_url=True,
    )
    assert comps
    text = getattr(comps[0], "text", None) or str(comps[0])
    assert "[@nasa](https://x.com/nasa/status/1)" in text
    assert "Hello" not in text
