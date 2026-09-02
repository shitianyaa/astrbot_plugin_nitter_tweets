"""Tweet message layout: TG author link, URL policy, empty body, block order."""

from __future__ import annotations

from pathlib import Path
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


def test_omit_false_removes_current_nitter_mirror_links_only():
    out = R.format_tweet(
        0,
        "nasa",
        _tw(
            text=(
                "RT @AsumuInori: 名古屋...哭 https://nitter.top/t.co/abc "
                "https://example.com/keep"
            )
        ),
        source="https://nitter.top",
        omit_status_url=False,
        link_style="qq_official_md",
    )

    assert "https://nitter.top/t.co/abc" not in out
    assert "https://example.com/keep" in out


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


def test_build_direct_components_strips_source_instance_links():
    tweet = _tw(
        text="Check status at https://nitter.example.com/nasa/status/123 and extern https://example.com/page",
        media=[],
    )
    r = R(send_image_attachments=False, send_video_attachments=False)
    comps = r.build_direct_components(
        username="nasa",
        instance="https://nitter.example.com",
        tweets=[tweet],
        omit_status_url=False,
    )
    assert comps
    text = getattr(comps[0], "text", "")
    assert "https://nitter.example.com" not in text
    assert "https://example.com/page" in text


def test_build_nodes_for_uin_strips_source_instance_links():
    tweet = _tw(
        text="Check status at https://nitter.example.com/nasa/status/123 and extern https://example.com/page",
        media=[],
    )
    r = R(send_image_attachments=False, send_video_attachments=False)
    nodes = r.build_nodes_for_uin(
        uin="10001",
        username="nasa",
        instance="https://nitter.example.com",
        tweets=[tweet],
        omit_status_url=False,
    )
    assert nodes and len(nodes.nodes) >= 1
    # Check text content in node
    node_content = nodes.nodes[0].content
    text = "".join(getattr(c, "text", "") for c in node_content)
    assert "https://nitter.example.com" not in text
    assert "https://example.com/page" in text


def _img_media(path="a.jpg"):
    return SimpleNamespace(
        path=Path(path),
        url="https://pbs.twimg.com/media/a.jpg",
        is_image=True,
        is_video=False,
    )


def _vid_media(path="v.mp4"):
    return SimpleNamespace(
        path=Path(path),
        url="https://example.com/v.mp4",
        is_image=False,
        is_video=True,
    )


def _kind(component) -> str:
    """Lowercased component kind, tolerant of stubbed astrbot classes (_Plain)."""
    return type(component).__name__.lower().lstrip("_")


def test_forward_nodes_merge_images_into_tweet_node():
    tweet = _tw(media=[_img_media(), _img_media("b.jpg")])
    r = R(send_image_attachments=True, send_video_attachments=False)
    nodes = r.build_nodes_for_uin(
        uin="10000", username="nasa", instance="", tweets=[tweet]
    )
    # No header args -> no header node; the whole tweet is a single node.
    assert len(nodes.nodes) == 1
    node = nodes.nodes[0]
    kinds = [_kind(c) for c in node.content]
    assert kinds == ["plain", "image", "image"]
    assert (node.uin, node.name) == ("@nasa", "@nasa")


def test_forward_node_identity_prefers_tweet_author():
    tweets = [
        _tw(
            username="cat_a",
            x_url="https://x.com/cat_a/status/1",
            link="https://x.com/cat_a/status/1",
        ),
        _tw(
            username="cat_b",
            x_url="https://x.com/cat_b/status/2",
            link="https://x.com/cat_b/status/2",
        ),
    ]
    r = R(send_image_attachments=False, send_video_attachments=False)
    nodes = r.build_nodes_for_uin(
        uin="10000", username="q:cats", instance="", tweets=tweets
    )
    assert [node.name for node in nodes.nodes] == ["@cat_a", "@cat_b"]
    assert [node.uin for node in nodes.nodes] == ["@cat_a", "@cat_b"]


def test_forward_video_keeps_own_node_with_author_identity():
    tweet = _tw(media=[_img_media(), _vid_media()])
    r = R(send_image_attachments=True, send_video_attachments=True)
    nodes = r.build_nodes_for_uin(
        uin="10000", username="nasa", instance="", tweets=[tweet]
    )
    assert len(nodes.nodes) == 2
    tweet_node, video_node = nodes.nodes
    assert [_kind(c) for c in tweet_node.content] == ["plain", "image"]
    video_text = "".join(getattr(c, "text", "") for c in video_node.content)
    assert "视频/GIF 附件" in video_text
    assert _kind(video_node.content[-1]) == "video"
    assert (video_node.uin, video_node.name) == ("@nasa", "@nasa")


def test_forward_exclude_videos_notice_stays_in_tweet_node():
    tweet = _tw(media=[_vid_media()])
    r = R(send_image_attachments=True, send_video_attachments=True)
    nodes = r.build_nodes_for_uin(
        uin="10000",
        username="nasa",
        instance="",
        tweets=[tweet],
        exclude_videos=True,
    )
    assert len(nodes.nodes) == 1
    texts = "".join(getattr(c, "text", "") for c in nodes.nodes[0].content)
    # 降级去视频是发送失败被省略，不是用户关掉了发送开关
    assert "视频/GIF 附件发送失败，本次已省略" in texts
    assert "已关闭" not in texts


def test_video_disabled_notice_keeps_disabled_wording():
    tweet = _tw(media=[_vid_media()])
    r = R(send_image_attachments=True, send_video_attachments=False)
    nodes = r.build_nodes_for_uin(
        uin="10000",
        username="nasa",
        instance="",
        tweets=[tweet],
    )
    assert len(nodes.nodes) == 1
    texts = "".join(getattr(c, "text", "") for c in nodes.nodes[0].content)
    assert "视频/GIF 发送已关闭，已跳过下载" in texts
    assert "发送失败" not in texts


def test_video_omitted_notice_uses_failed_wording():
    tweet = _tw(
        media=[_vid_media()],
        username="nasa",
        x_url="https://x.com/nasa/status/1",
        link="https://x.com/nasa/status/1",
    )
    r = R(send_image_attachments=True, send_video_attachments=True)
    comps = r.build_video_omitted_notice_components([tweet])
    assert len(comps) == 1
    text = getattr(comps[0], "text", "")
    assert "视频/GIF 附件发送失败，本次已省略" in text
    assert "已关闭" not in text


def test_merged_onebot_nodes_merge_images_and_use_author_identity():
    tweet = _tw(
        username="cat_a",
        x_url="https://x.com/cat_a/status/1",
        link="https://x.com/cat_a/status/1",
        media=[_img_media(), _img_media("b.jpg")],
    )
    r = R(send_image_attachments=True, send_video_attachments=False)
    nodes = r.build_merged_onebot_nodes_for_uin(10000, [("q:cats", "", [tweet])])
    # Merged builders always lead with a header node.
    assert len(nodes) == 2
    assert nodes[0]["data"]["name"] == "Nitter"
    node = nodes[1]["data"]
    assert (node["uin"], node["name"]) == ("@cat_a", "@cat_a")
    assert [seg["type"] for seg in node["content"]] == ["text", "image", "image"]


def test_onebot_nodes_merge_images_and_use_author_identity():
    tweet = _tw(media=[_img_media()])
    r = R(send_image_attachments=True, send_video_attachments=False)
    event = SimpleNamespace(get_self_id=lambda: "10001", get_sender_id=lambda: None)
    nodes = r.build_onebot_nodes(event, "nasa", "", [tweet])
    assert len(nodes) == 1
    node = nodes[0]["data"]
    assert (node["uin"], node["name"]) == ("@nasa", "@nasa")
    assert [seg["type"] for seg in node["content"]] == ["text", "image"]


def test_merged_nodes_media_only_single_node_with_author():
    tweet = _tw(text="", media=[_img_media()])
    r = R(send_image_attachments=True, send_video_attachments=False)
    nodes = r.build_merged_nodes_for_uin(
        10000, [("q:cats", "", [tweet])], media_only=True
    )
    assert len(nodes.nodes) == 2
    node = nodes.nodes[1]
    kinds = [_kind(c) for c in node.content]
    assert kinds == ["plain", "image"]
    assert (node.uin, node.name) == ("@nasa", "@nasa")
