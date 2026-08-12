"""Tweet message layout: TG author link, URL policy, empty body, block order."""

from __future__ import annotations

from types import SimpleNamespace

from rendering.tweets import TweetMessageRenderer as R


def _tw(**kw):
    base = {
        "status_id": "1",
        "username": "nasa",
        "text": "Hello #space https://t.co/abc world",
        "x_url": "https://x.com/nasa/status/1",
        "link": "https://x.com/nasa/status/1",
        "published": "2026-07-23 12:00:00",
        "media": [],
        "translation": "",
        "ai_warnings": [],
        "media_warnings": [],
        "is_repost": False,
    }
    base.update(kw)
    return SimpleNamespace(**base)


def test_telegram_header_has_explicit_status_link_not_body_preview():
    out = R.format_tweet(
        0,
        "nasa",
        _tw(),
        omit_status_url=True,
        link_style="telegram_md",
    )
    first = out.split("\n\n", 1)[0]
    assert first.startswith("@nasa · [🔗 查看推文](https://x.com/nasa/status/1)")
    assert "Hello #space" not in first
    assert "原文" not in out  # R1: no section title
    assert "Hello #space world" in out  # body still present, URL stripped


def test_telegram_header_escapes_author_markdown():
    out = R.format_tweet(
        0,
        "ignored",
        _tw(
            username="real_user",
            x_url="https://x.com/real_user/status/1",
            link="https://x.com/real_user/status/1",
        ),
        omit_status_url=True,
        link_style="telegram_md",
    )
    assert out.startswith(
        "@real\\_user · [🔗 查看推文](https://x.com/real_user/status/1)"
    )


def test_plain_header_is_at_author():
    out = R.format_tweet(0, "nasa", _tw(), omit_status_url=True, link_style="plain")
    assert out.startswith("@nasa")
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
    assert "🔗" in out
    assert "https://x.com/nasa/status/1" in out


def test_empty_body_plain_omits_placeholder():
    out = R.format_tweet(
        0,
        "nasa",
        _tw(text="   ", translation=""),
        omit_status_url=True,
        link_style="plain",
    )
    assert "（无正文）" not in out
    assert "(无正文)" not in out
    assert out.strip() == "@nasa · 2026-07-23 12:00:00"


def test_empty_body_telegram_omits_placeholder():
    out = R.format_tweet(
        0,
        "nasa",
        _tw(text="   ", translation=""),
        omit_status_url=True,
        link_style="telegram_md",
    )
    assert "（无正文）" not in out
    assert "(无正文)" not in out
    assert "查看推文" in out.split("\n\n", 1)[0]


def test_plain_r1_translation_main_original_quoted():
    """Non-TG: translation is main body; original is '>' quoted; no section titles."""
    out = R.format_tweet(
        0,
        "nasa",
        _tw(translation="你好世界"),
        omit_status_url=True,
        hide_original_when_translated=False,
        link_style="plain",
    )
    assert "翻译" not in out
    assert "原文" not in out
    parts = out.split("\n\n")
    assert parts[0] == "@nasa · 2026-07-23 12:00:00"
    assert parts[1] == "你好世界"
    assert parts[2].startswith("> ")
    assert "Hello #space world" in parts[2]
    assert parts[1].find("你好") < out.find("> ")


def test_plain_r1_hide_original_only_translation_body():
    out = R.format_tweet(
        0,
        "nasa",
        _tw(translation="你好世界"),
        omit_status_url=True,
        hide_original_when_translated=True,
        link_style="plain",
    )
    assert "翻译" not in out
    assert "原文" not in out
    assert ">" not in out
    assert "你好世界" in out
    assert "Hello #space" not in out


def test_plain_r1_no_translation_no_original_label():
    out = R.format_tweet(
        0,
        "nasa",
        _tw(),
        omit_status_url=True,
        link_style="plain",
    )
    assert "原文" not in out
    assert "Hello #space world" in out


def test_quote_blocks_skip_blank_source_lines():
    assert R._quote_plain_block("original\n\n#cos") == "> original\n> #cos"
    assert R._quote_markdown_block("original\n\n#cos") == "> original\n> \\#cos"


def test_plain_r1_media_only_no_empty_placeholder():
    media = SimpleNamespace(
        kind="image",
        url="https://pbs.twimg.com/media/a.jpg",
        is_image=True,
        is_video=False,
        is_dynamic=False,
        local_path=None,
    )
    tw = _tw(
        text="",
        username="u",
        published="t",
        media=[media],
        x_url="https://x.com/u/status/1",
        link="https://x.com/u/status/1",
    )
    out = R.format_tweet(
        0,
        "u",
        tw,
        omit_status_url=True,
        link_style="plain",
    )
    assert "（无正文）" not in out
    assert "(无正文)" not in out
    assert out.startswith("@u · t")
    assert "📎 图片 1 张" in out
    # author + media summary only
    assert out.count("\n\n") == 1


def test_telegram_r1_translation_body_keeps_header():
    out = R.format_tweet(
        0,
        "nasa",
        _tw(translation="你好世界"),
        omit_status_url=True,
        hide_original_when_translated=False,
        link_style="telegram_md",
    )
    assert out.startswith("@nasa · [🔗 查看推文](")
    assert "翻译" not in out
    assert "原文" not in out
    parts = out.split("\n\n")
    assert parts[1] == "你好世界"
    assert parts[2].startswith("> ")
    assert "Hello #space world" in parts[2]


def test_time_on_author_line_compact_header():
    """Compact layout: @author · time on one line, no standalone 时间： block."""
    out = R.format_tweet(0, "nasa", _tw(), omit_status_url=True)
    parts = out.split("\n\n")
    assert parts[0] == "@nasa · 2026-07-23 12:00:00"
    assert "时间：" not in out


def test_media_only_telegram_header_has_explicit_status_link():
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
    assert "@nasa · [🔗 查看推文](https://x.com/nasa/status/1)" in text
    assert "Hello" not in text
