"""Status link extract/resolve helpers and link-preview handler behavior."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from command_handlers.link_preview import (
    LINK_PREVIEW_MAX_LINKS,
    LinkPreviewMixin,
)
from delivery.sender import TweetSender
from media_support.service import MediaService
from media_support.status_link import (
    STATUS_LINK_REGEX,
    StatusLink,
    extract_status_links,
    parse_status_link,
)
from media_support.status_resolve import (
    StatusResolveError,
    _tweet_from_fx,
    resolve_status_tweet,
)
from rendering.tweets import TweetMessageRenderer
from shared.utils import TweetItem, TweetMedia


def test_extract_accepts_common_hosts_and_strips_query():
    text = (
        "see https://x.com/ErroR_eroi/status/2081668333762687236?s=20 "
        "and http://twitter.com/nasa/status/1 "
        "and www.x.com/foo/status/2 "
        "and mobile.twitter.com/bar/status/3"
    )
    links = extract_status_links(text)
    assert [x.status_id for x in links] == [
        "2081668333762687236",
        "1",
        "2",
        "3",
    ]
    assert links[0].canonical_url == (
        "https://x.com/ErroR_eroi/status/2081668333762687236"
    )


def test_extract_dedupes_and_preserves_order():
    text = (
        "https://x.com/a/status/11 "
        "https://twitter.com/a/status/11?s=1 "
        "https://x.com/b/status/22"
    )
    links = extract_status_links(text)
    assert [x.status_id for x in links] == ["11", "22"]


def test_extract_rejects_evil_hosts_and_bad_ids():
    assert extract_status_links("https://evil-x.com/a/status/1") == []
    assert extract_status_links("https://x.com.evil.test/a/status/1") == []
    assert parse_status_link("https://x.com/a/status/not-a-number") is None
    assert parse_status_link("https://x.com/a/statuses/") is None


def test_status_link_regex_matches_message():
    import re

    assert re.search(
        STATUS_LINK_REGEX,
        "看这个 https://x.com/ErroR_eroi/status/2081668333762687236 啊",
    )


def test_fx_media_only_empty_text_not_raw_dict():
    """Fx often sets text='' and puts media URL blob in raw_text — do not str(dict)."""
    link = StatusLink(
        "xxiaoyi0721",
        "2081477182787092643",
        "https://x.com/xxiaoyi0721/status/2081477182787092643",
    )
    payload = {
        "tweet": {
            "text": "",
            "raw_text": {
                "text": "https://t.co/kGl5sBFerM",
                "display_text_range": [0, 0],
                "facets": [{"type": "media", "indices": [0, 23]}],
            },
            "url": link.canonical_url,
            "created_at": "Sun Jul 26 20:30:07 +0000 2026",
            "author": {"screen_name": "xxiaoyi0721"},
            "media": {
                "all": [
                    {
                        "type": "photo",
                        "url": "https://pbs.twimg.com/media/HOLkdg8bsAAIBz-.jpg?name=orig",
                    }
                ]
            },
        }
    }
    tweet = _tweet_from_fx(link, payload)
    assert tweet is not None
    assert tweet.text == ""
    assert "raw_text" not in tweet.text
    assert "facets" not in tweet.text
    assert len(tweet.media) == 1


def test_fx_media_only_status_with_video_keeps_empty_body():
    """A video-only status must not expose author/player metadata as body text."""
    link = StatusLink(
        "yureiyks",
        "2081959562219794868",
        "https://x.com/yureiyks/status/2081959562219794868",
    )
    payload = {
        "tweet": {
            "text": "",
            "raw_text": {
                "text": "https://t.co/rnKeFYWAqs",
                "display_text_range": [0, 0],
            },
            "url": link.canonical_url,
            "author": {"screen_name": "yureiyks"},
            "media": {
                "all": [
                    {
                        "type": "video",
                        "url": "https://video.twimg.com/video.mp4",
                        "variants": [
                            {
                                "content_type": "video/mp4",
                                "bitrate": 1,
                                "url": "https://video.twimg.com/video.mp4",
                            }
                        ],
                    }
                ]
            },
        }
    }

    tweet = _tweet_from_fx(link, payload)

    assert tweet is not None
    assert tweet.text == ""
    assert tweet.translation == ""
    assert len(tweet.media) == 1


def test_user_status_payloads_keep_media_only_and_text_photo_distinct():
    yurei_link = StatusLink(
        "yureiyks",
        "2082364407330341030",
        "https://x.com/yureiyks/status/2082364407330341030",
    )
    yurei = _tweet_from_fx(
        yurei_link,
        {
            "tweet": {
                "text": "",
                "raw_text": {
                    "text": "https://t.co/R53nVq6QL8",
                    "display_text_range": [0, 0],
                },
                "url": yurei_link.canonical_url,
                "created_at": "Wed Jul 29 07:15:37 +0000 2026",
                "author": {"screen_name": "yureiyks"},
                "media": {
                    "all": [
                        {
                            "type": "video",
                            "url": "https://video.twimg.com/video.mp4",
                            "variants": [
                                {
                                    "content_type": "video/mp4",
                                    "bitrate": 1,
                                    "url": "https://video.twimg.com/video.mp4",
                                }
                            ],
                        }
                    ]
                },
            }
        },
    )

    yoda_link = StatusLink(
        "Yodachipoi",
        "2082072289068351718",
        "https://x.com/Yodachipoi/status/2082072289068351718",
    )
    yoda = _tweet_from_fx(
        yoda_link,
        {
            "tweet": {
                "text": "狼群之名终将响彻大地！",
                "raw_text": {
                    "text": "狼群之名终将响彻大地！ https://t.co/0TCaUvtsqi",
                    "display_text_range": [0, 11],
                },
                "url": yoda_link.canonical_url,
                "created_at": "Tue Jul 28 11:54:51 +0000 2026",
                "author": {"screen_name": "Yodachipoi"},
                "media": {
                    "all": [
                        {
                            "type": "photo",
                            "url": "https://pbs.twimg.com/media/HOOD.jpg?name=orig",
                        }
                    ]
                },
            }
        },
    )

    assert yurei is not None
    assert yurei.text == ""
    assert [media.kind for media in yurei.media] == ["video"]
    yurei_output = TweetMessageRenderer.format_tweet(
        0, "yureiyks", yurei, omit_status_url=True
    )
    assert yurei_output == "@yureiyks · 2026-07-29 15:15:37\n\n📎 视频/GIF 1 个"
    assert "Yūrei" not in yurei_output
    assert "启用 HLS 播放" not in yurei_output

    assert yoda is not None
    assert yoda.text == "狼群之名终将响彻大地！"
    assert [media.kind for media in yoda.media] == ["image"]
    yoda_output = TweetMessageRenderer.format_tweet(
        0, "Yodachipoi", yoda, omit_status_url=True
    )
    assert "狼群之名终将响彻大地！" in yoda_output
    assert "📎 图片 1 张" in yoda_output


def test_fx_payload_maps_photo_tweet():
    link = StatusLink(
        "ErroR_eroi",
        "2081668333762687236",
        "https://x.com/ErroR_eroi/status/2081668333762687236",
    )
    payload = {
        "tweet": {
            "text": "#ブルアカ",
            "url": link.canonical_url,
            "created_at": "Mon Jul 27 09:09:40 +0000 2026",
            "author": {"screen_name": "ErroR_eroi"},
            "media": {
                "all": [
                    {
                        "type": "photo",
                        "url": "https://pbs.twimg.com/media/HOOSGslacAAx1Ci.jpg?name=orig",
                    }
                ]
            },
        }
    }
    tweet = _tweet_from_fx(link, payload)
    assert tweet is not None
    assert tweet.text == "#ブルアカ"
    assert tweet.username == "ErroR_eroi"
    assert len(tweet.media) == 1
    assert tweet.media[0].is_image


def test_resolve_falls_back_across_sources(monkeypatch):
    link = StatusLink("u", "9", "https://x.com/u/status/9")
    calls: list[str] = []

    def fake_fetch(url: str, *, timeout: float):
        calls.append(url)
        if "fxtwitter" in url:
            raise StatusResolveError("fx down")
        if "vxtwitter" in url:
            raise StatusResolveError("vx down")
        return {
            "text": "hello from syn",
            "user": {"screen_name": "u"},
            "created_at": "t",
            "photos": [{"url": "https://pbs.twimg.com/media/x.jpg"}],
        }

    monkeypatch.setattr("media_support.status_resolve._fetch_json", fake_fetch)
    tweet = resolve_status_tweet(link, timeout=1)
    assert tweet.text == "hello from syn"
    assert len(calls) == 3
    assert "syndication" in calls[-1]


@pytest.mark.asyncio
async def test_force_media_ignores_global_disable_and_max_zero(tmp_path, monkeypatch):
    config = {
        "send_image_attachments": False,
        "send_video_attachments": False,
        "max_media_per_tweet": 0,
        "media_timeout": 5,
        "media_max_size_mb": 25,
    }
    service = MediaService(config)
    service.cache_dir = tmp_path

    async def fake_download(media):
        path = tmp_path / "a.jpg"
        path.write_bytes(b"img")
        return path

    monkeypatch.setattr(service, "_download_media_path", fake_download)
    tweet = TweetItem(
        text="hi",
        link="https://x.com/u/status/1",
        published="t",
        media=[TweetMedia("image", "https://pbs.twimg.com/media/a.jpg")],
    )
    # Without force: policy skip
    results = await service.attach_media_with_results([tweet])
    assert results[0].status == "policy_skipped"
    assert tweet.media[0].path is None

    tweet2 = TweetItem(
        text="hi",
        link="https://x.com/u/status/1",
        published="t",
        media=[TweetMedia("image", "https://pbs.twimg.com/media/a.jpg")],
    )
    results2 = await service.attach_media_with_results([tweet2], force_all_media=True)
    assert results2[0].prepared_count == 1
    assert tweet2.media[0].path is not None


def test_renderer_force_flags_emit_image_component(tmp_path):
    path = tmp_path / "a.jpg"
    path.write_bytes(b"x")
    tweet = TweetItem(
        text="#tag",
        link="https://x.com/ErroR_eroi/status/2081668333762687236",
        published="Mon Jul 27 09:09:40 +0000 2026",
        media=[TweetMedia("image", "https://example.com/a.jpg", path=path)],
    )

    def _is_plain(component) -> bool:
        name = type(component).__name__
        return name == "Plain" or name.endswith("Plain")

    def _is_image(component) -> bool:
        name = type(component).__name__
        if name == "Image" or name.endswith("Image"):
            return True
        for attr in ("file", "path"):
            value = getattr(component, attr, None)
            if value and str(path) in str(value):
                return True
        return False

    # Global media off on renderer
    r = TweetMessageRenderer(send_image_attachments=False, send_video_attachments=False)
    comps_off = r.build_components(1, "ErroR_eroi", tweet, link_style="plain")
    assert len(comps_off) == 1
    assert _is_plain(comps_off[0])

    r.send_image_attachments = True
    r.send_video_attachments = True
    comps_on = r.build_components(1, "ErroR_eroi", tweet, link_style="plain")
    assert len(comps_on) >= 2
    assert _is_plain(comps_on[0])
    assert any(_is_image(c) for c in comps_on[1:])
    text = comps_on[0].text
    assert text.startswith("@ErroR_eroi")
    assert "#tag" in text
    assert "原文" not in text  # plain R1: no section title
    assert "📎" in text


@pytest.mark.asyncio
async def test_force_media_uses_isolated_sender_renderer(monkeypatch):
    sender = TweetSender(
        {
            "send_image_attachments": False,
            "send_video_attachments": False,
        }
    )
    original_renderer = sender.renderer
    gate = asyncio.Event()
    observed = []

    async def fake_send(self, *args, **kwargs):
        observed.append(self)
        await gate.wait()
        return True

    monkeypatch.setattr(TweetSender, "_send_with_current_media_flags", fake_send)
    task = asyncio.create_task(sender.send(object(), "u", "i", [], force_media=True))
    for _ in range(100):
        if observed:
            break
        await asyncio.sleep(0)
    assert observed

    forced_sender = observed[0]
    assert forced_sender is not sender
    assert forced_sender.send_image_attachments is True
    assert forced_sender.send_video_attachments is True
    assert sender.renderer is original_renderer
    assert sender.send_image_attachments is False
    assert sender.send_video_attachments is False

    normal_task = asyncio.create_task(
        sender.send(object(), "u", "i", [], force_media=False)
    )
    for _ in range(100):
        if len(observed) >= 2:
            break
        await asyncio.sleep(0)
    assert len(observed) >= 2
    assert observed[1] is sender
    gate.set()
    assert await task is True
    assert await normal_task is True


class _FakePlugin(LinkPreviewMixin):
    def __init__(self, enabled: bool = True):
        self.config = {"auto_parse_tweet_links_enabled": enabled}
        self.translator = SimpleNamespace(
            attach_translations=AsyncMock(return_value=None)
        )
        self.media = SimpleNamespace(
            attach_media_with_results=AsyncMock(return_value=[]),
            cleanup_after_send=MagicMock(),
        )
        self.sender = SimpleNamespace(send=AsyncMock(return_value=True))


def _make_event(*, text: str, sender: str = "100", self_id: str = "200"):
    event = MagicMock()
    event.get_message_str.return_value = text
    event.message_str = text
    event.get_sender_id.return_value = sender
    event.get_self_id.return_value = self_id
    event.unified_msg_origin = "aiocqhttp:GroupMessage:1"
    event.stop_event = MagicMock()
    event.plain_result = lambda s: s
    event.send = AsyncMock()
    return event


@pytest.mark.asyncio
async def test_handler_disabled_no_stop(monkeypatch):
    plugin = _FakePlugin(enabled=False)
    event = _make_event(text="https://x.com/a/status/1")
    await plugin._cmd_link_preview_impl(event)
    event.stop_event.assert_not_called()
    plugin.sender.send.assert_not_called()


@pytest.mark.asyncio
async def test_handler_ignores_bot_self(monkeypatch):
    plugin = _FakePlugin(enabled=True)
    event = _make_event(text="https://x.com/a/status/1", sender="42", self_id="42")
    await plugin._cmd_link_preview_impl(event)
    event.stop_event.assert_not_called()
    plugin.sender.send.assert_not_called()


@pytest.mark.asyncio
async def test_handler_no_valid_link_no_stop(monkeypatch):
    plugin = _FakePlugin(enabled=True)
    event = _make_event(text="hello only")
    await plugin._cmd_link_preview_impl(event)
    event.stop_event.assert_not_called()


@pytest.mark.asyncio
async def test_handler_processes_and_sends(monkeypatch):
    plugin = _FakePlugin(enabled=True)
    event = _make_event(text="看 https://x.com/ErroR_eroi/status/2081668333762687236")

    async def fake_resolve(link, *, timeout=20.0, media_quality="high"):
        return TweetItem(
            text="#ブルアカ",
            link=link.canonical_url,
            published="t",
            media=[],
        )

    monkeypatch.setattr(
        "command_handlers.link_preview.resolve_status_tweet_async",
        fake_resolve,
    )
    await plugin._cmd_link_preview_impl(event)
    event.stop_event.assert_called_once()
    plugin.translator.attach_translations.assert_awaited()
    plugin.media.attach_media_with_results.assert_awaited()
    kwargs = plugin.media.attach_media_with_results.await_args.kwargs
    assert kwargs.get("force_all_media") is True
    plugin.sender.send.assert_awaited()
    send_kwargs = plugin.sender.send.await_args.kwargs
    assert send_kwargs.get("force_media") is True
    assert send_kwargs.get("omit_status_url") is True
    plugin.media.cleanup_after_send.assert_called()


@pytest.mark.asyncio
async def test_handler_forwards_media_quality_to_resolver(monkeypatch):
    # status 渠道曾经完全绕过 media_quality，拿到的恒是 pbs 原图。
    plugin = _FakePlugin(enabled=True)
    plugin.config["media_quality"] = "low"
    seen: list[str] = []

    async def fake_resolve(link, *, timeout=20.0, media_quality="high"):
        seen.append(media_quality)
        return TweetItem(text="t", link=link.canonical_url, published="t", media=[])

    monkeypatch.setattr(
        "command_handlers.link_preview.resolve_status_tweet_async",
        fake_resolve,
    )
    await plugin._cmd_link_preview_impl(_make_event(text="https://x.com/u/status/77"))
    assert seen == ["low"]


@pytest.mark.asyncio
async def test_handler_caps_links_and_debounces(monkeypatch):
    plugin = _FakePlugin(enabled=True)
    ids = [str(i) for i in range(1, LINK_PREVIEW_MAX_LINKS + 3)]
    text = " ".join(f"https://x.com/u/status/{i}" for i in ids)
    event = _make_event(text=text)
    seen: list[str] = []

    async def fake_resolve(link, *, timeout=20.0, media_quality="high"):
        seen.append(link.status_id)
        return TweetItem(text="t", link=link.canonical_url, published="t", media=[])

    monkeypatch.setattr(
        "command_handlers.link_preview.resolve_status_tweet_async",
        fake_resolve,
    )
    await plugin._cmd_link_preview_impl(event)
    assert seen == ids[:LINK_PREVIEW_MAX_LINKS]

    # Second call same links should debounce all
    seen.clear()
    event2 = _make_event(text=text)
    await plugin._cmd_link_preview_impl(event2)
    assert seen == []


@pytest.mark.asyncio
async def test_handler_deduplicates_concurrent_same_link(monkeypatch):
    plugin = _FakePlugin(enabled=True)
    link_text = "https://x.com/u/status/9"
    resolve_started = asyncio.Event()
    release_resolve = asyncio.Event()
    calls = 0

    async def resolve(link, *, timeout=20.0, media_quality="high"):
        nonlocal calls
        calls += 1
        resolve_started.set()
        await release_resolve.wait()
        return TweetItem(text="ok", link=link.canonical_url, published="t", media=[])

    monkeypatch.setattr(
        "command_handlers.link_preview.resolve_status_tweet_async",
        resolve,
    )
    first = asyncio.create_task(
        plugin._cmd_link_preview_impl(_make_event(text=link_text))
    )
    await resolve_started.wait()
    second = asyncio.create_task(
        plugin._cmd_link_preview_impl(_make_event(text=link_text))
    )
    await asyncio.sleep(0)
    release_resolve.set()
    await asyncio.gather(first, second)

    assert calls == 1
    plugin.sender.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_handler_can_retry_after_resolve_failure(monkeypatch):
    plugin = _FakePlugin(enabled=True)
    link_text = "https://x.com/u/status/9"
    calls = 0

    async def flaky_resolve(link, *, timeout=20.0, media_quality="high"):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise StatusResolveError("temporary failure")
        return TweetItem(text="ok", link=link.canonical_url, published="t", media=[])

    monkeypatch.setattr(
        "command_handlers.link_preview.resolve_status_tweet_async",
        flaky_resolve,
    )
    await plugin._cmd_link_preview_impl(_make_event(text=link_text))
    await plugin._cmd_link_preview_impl(_make_event(text=link_text))

    assert calls == 2
    plugin.sender.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_handler_can_retry_after_send_failure(monkeypatch):
    plugin = _FakePlugin(enabled=True)
    plugin.sender.send = AsyncMock(side_effect=[False, True])
    link_text = "https://x.com/u/status/9"

    async def resolve(link, *, timeout=20.0, media_quality="high"):
        return TweetItem(text="ok", link=link.canonical_url, published="t", media=[])

    monkeypatch.setattr(
        "command_handlers.link_preview.resolve_status_tweet_async",
        resolve,
    )
    await plugin._cmd_link_preview_impl(_make_event(text=link_text))
    await plugin._cmd_link_preview_impl(_make_event(text=link_text))

    assert plugin.sender.send.await_count == 2
