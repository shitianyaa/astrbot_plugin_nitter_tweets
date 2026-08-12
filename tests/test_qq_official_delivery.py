from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from delivery.outcomes import SendAttempt
from delivery.qq_official import QQOfficialDeliveryAdapter
from rendering.tweets import TweetMessageRenderer
from shared import TweetItem, TweetMedia


def _sender(*, images: bool = True, videos: bool = False):
    sender = SimpleNamespace(
        send_image_attachments=images,
        send_video_attachments=videos,
        renderer=TweetMessageRenderer(
            send_image_attachments=images,
            send_video_attachments=videos,
        ),
        _send_event_chain=AsyncMock(return_value=SendAttempt(success=True)),
        _send_context_message=AsyncMock(return_value=SendAttempt(success=True)),
        _status_ids_from_tweets=lambda tweets: tuple(
            tweet.status_id for tweet in tweets if tweet.status_id
        ),
    )
    return sender


def _chain_components(chain):
    return list(getattr(chain, "chain", getattr(chain, "components", ())) or ())


def _plain_text(chain):
    return "".join(
        str(getattr(component, "text", "") or "")
        for component in _chain_components(chain)
    )


def _tweet(*, media=None, text="hello *world*", translation="") -> TweetItem:
    return TweetItem(
        text=text,
        link="https://x.com/nasa/status/1",
        published="2026-08-10 12:00:00",
        media=list(media or []),
        translation=translation,
    )


def _adapter(sender):
    return QQOfficialDeliveryAdapter(
        sender,
        SimpleNamespace(
            should_split_qq_direct_images=True,
            should_split_qq_direct_videos=True,
        ),
    )


def _official_umo_adapter(sender, api, *, message_type="GroupMessage"):
    profile = SimpleNamespace(
        message_type=message_type,
        session_id=(
            "group-openid" if message_type == "GroupMessage" else "user-openid"
        ),
        platform=SimpleNamespace(client=SimpleNamespace(api=api)),
        should_split_qq_direct_images=True,
        should_split_qq_direct_videos=True,
    )
    adapter = QQOfficialDeliveryAdapter(sender, profile)

    async def send_context(context, umo, chain, label):
        handled = await adapter.send_context_chain(context, umo, chain, label)
        return handled or SendAttempt(success=True)

    sender._send_context_message = AsyncMock(side_effect=send_context)
    return adapter


def test_qq_official_markdown_layout_respects_link_and_translation_policy():
    tweet = _tweet(
        text="原文 *需要转义*\n> quote",
        translation="译文 [也需要转义]",
    )

    rendered = TweetMessageRenderer.format_tweet(
        1,
        "nasa",
        tweet,
        omit_status_url=False,
        link_style="qq_official_md",
    )

    assert rendered.startswith(
        "**@nasa** · 2026-08-10 12:00:00 · [查看原推](https://x.com/nasa/status/1)"
    )
    assert "译文 [也需要转义]" in rendered
    assert "> 原文 \\*需要转义\\*" in rendered
    assert "\\> quote" in rendered

    hidden = TweetMessageRenderer.format_tweet(
        1,
        "nasa",
        tweet,
        omit_status_url=True,
        hide_original_when_translated=True,
        link_style="qq_official_md",
    )
    assert "查看原推" not in hidden
    assert "https://x.com" not in hidden
    assert "原文" not in hidden


def test_qq_official_header_escapes_dynamic_markdown_fields():
    renderer = TweetMessageRenderer()

    components = renderer.build_direct_components(
        "nasa",
        "https://nitter.example",
        [_tweet()],
        notices=["notice *body*"],
        group_label="*group*",
        header_text="# custom\n> quoted",
        batch_summary="- summary",
        link_style="qq_official_md",
    )

    header = str(getattr(components[0], "text", ""))
    assert header == (
        "\\- summary\n\\# custom\n\\> quoted\n分组\uff1a\\*group\\*\n⚠️\n- notice \\*body\\*"
    )


@pytest.mark.asyncio
async def test_qq_official_text_event_uses_markdown():
    sender = _sender(images=False, videos=False)
    adapter = _adapter(sender)

    accepted = await adapter.send_event(
        object(),
        "nasa",
        "https://nitter.example",
        [_tweet()],
    )

    assert accepted is True
    chain = sender._send_event_chain.await_args.args[1]
    assert chain.use_markdown_ is True
    assert "**@nasa**" in _plain_text(chain)


@pytest.mark.asyncio
async def test_qq_official_umo_sends_markdown_by_official_group_api():
    sender = _sender(images=False, videos=False)
    api = SimpleNamespace(post_group_message=AsyncMock(return_value={"id": "1"}))
    adapter = _official_umo_adapter(sender, api)

    outcome = await adapter.send_to_umo(
        object(),
        "official:GroupMessage:group-openid",
        "nasa",
        "https://nitter.example",
        [_tweet()],
    )

    assert outcome.success is True
    api.post_group_message.assert_awaited_once()
    payload = api.post_group_message.await_args.kwargs
    assert payload["group_openid"] == "group-openid"
    assert payload["msg_type"] == 2
    assert payload["markdown"]["content"].startswith("**@nasa**")
    assert "content" not in payload
    assert "msg_id" not in payload
    assert "event_id" not in payload


@pytest.mark.asyncio
async def test_qq_official_umo_sends_markdown_by_official_c2c_api():
    sender = _sender(images=False, videos=False)
    api = SimpleNamespace(post_c2c_message=AsyncMock(return_value={"id": "1"}))
    adapter = _official_umo_adapter(sender, api, message_type="FriendMessage")

    outcome = await adapter.send_to_umo(
        object(),
        "official:FriendMessage:user-openid",
        "nasa",
        "https://nitter.example",
        [_tweet()],
    )

    assert outcome.success is True
    api.post_c2c_message.assert_awaited_once()
    payload = api.post_c2c_message.await_args.kwargs
    assert payload["openid"] == "user-openid"
    assert payload["msg_type"] == 2
    assert payload["markdown"]["content"].startswith("**@nasa**")
    assert "content" not in payload
    assert "msg_id" not in payload
    assert "event_id" not in payload


@pytest.mark.asyncio
async def test_qq_official_scheduled_summary_uses_markdown_api():
    sender = _sender(images=False, videos=False)
    api = SimpleNamespace(post_group_message=AsyncMock(return_value={"id": "1"}))
    adapter = _official_umo_adapter(sender, api)

    outcome = await adapter.send_summary_to_umo(
        object(),
        "official:GroupMessage:group-openid",
        "📬 *默认* 分组 · 1 个博主 · 1 条新推文",
    )

    assert outcome.success is True
    api.post_group_message.assert_awaited_once()
    payload = api.post_group_message.await_args.kwargs
    assert payload["group_openid"] == "group-openid"
    assert payload["msg_type"] == 2
    assert (
        payload["markdown"]["content"] == "📬 \\*默认\\* 分组 · 1 个博主 · 1 条新推文"
    )
    assert "content" not in payload


@pytest.mark.asyncio
async def test_qq_official_umo_markdown_rejection_falls_back_to_plain_text():
    sender = _sender(images=False, videos=False)
    api = SimpleNamespace(
        post_group_message=AsyncMock(
            side_effect=[
                RuntimeError("不允许发送原生 markdown"),
                {"id": "1"},
            ]
        )
    )
    adapter = _official_umo_adapter(sender, api)

    outcome = await adapter.send_to_umo(
        object(),
        "official:GroupMessage:group-openid",
        "nasa",
        "https://nitter.example",
        [_tweet(text="line 1\nline 2")],
    )

    assert outcome.success is True
    assert api.post_group_message.await_count == 2
    markdown_payload = api.post_group_message.await_args_list[0].kwargs
    plain_payload = api.post_group_message.await_args_list[1].kwargs
    assert markdown_payload["msg_type"] == 2
    assert "markdown" in markdown_payload
    assert plain_payload["msg_type"] == 0
    assert plain_payload["content"] == "@nasa · 2026-08-10 12:00:00\n\nline 1\nline 2"
    assert "**" not in plain_payload["content"]
    assert "markdown" not in plain_payload
    assert plain_payload["msg_seq"] == markdown_payload["msg_seq"] + 1


@pytest.mark.asyncio
async def test_qq_official_umo_without_client_falls_back_to_plain_chain():
    sender = _sender(images=False, videos=False)
    profile = SimpleNamespace(
        message_type="GroupMessage",
        session_id="group-openid",
        platform=None,
        should_split_qq_direct_images=True,
        should_split_qq_direct_videos=True,
    )
    adapter = QQOfficialDeliveryAdapter(sender, profile)
    context = SimpleNamespace(send_message=AsyncMock(return_value=True))

    async def send_context(context, umo, chain, label):
        handled = await adapter.send_context_chain(context, umo, chain, label)
        return handled or SendAttempt(success=True)

    sender._send_context_message = AsyncMock(side_effect=send_context)

    outcome = await adapter.send_to_umo(
        context,
        "official:GroupMessage:group-openid",
        "nasa",
        "https://nitter.example",
        [_tweet()],
    )

    assert outcome.success is True
    context.send_message.assert_awaited_once()
    chain = context.send_message.await_args.args[1]
    assert chain.use_markdown_ is False
    assert _plain_text(chain).startswith("@nasa")
    assert "**" not in _plain_text(chain)


@pytest.mark.asyncio
async def test_qq_official_umo_media_sends_markdown_body_before_media():
    sender = _sender(images=True, videos=False)
    api = SimpleNamespace(
        post_group_message=AsyncMock(return_value={"id": "text"}),
    )
    adapter = _official_umo_adapter(sender, api)
    tweet = _tweet(
        media=[
            TweetMedia("image", "https://pbs.example/1.jpg", Path("1.jpg")),
            TweetMedia("image", "https://pbs.example/2.jpg", Path("2.jpg")),
        ]
    )

    outcome = await adapter.send_to_umo(
        object(),
        "official:GroupMessage:group-openid",
        "nasa",
        "https://nitter.example",
        [tweet],
    )

    assert outcome.success is True
    api.post_group_message.assert_awaited_once()
    payload = api.post_group_message.await_args.kwargs
    assert payload["msg_type"] == 2
    assert payload["markdown"]["content"].startswith("**@nasa**")
    assert sender._send_context_message.await_count == 3
    assert sender._send_context_message.await_args_list[0].args[2].use_markdown_ is True
    assert all(
        "image" in type(_chain_components(call.args[2])[0]).__name__.lower()
        for call in sender._send_context_message.await_args_list[1:]
    )


@pytest.mark.asyncio
async def test_qq_official_media_event_sends_markdown_body_before_media():
    sender = _sender(images=True, videos=False)
    adapter = _adapter(sender)
    tweet = _tweet(
        media=[
            TweetMedia("image", "https://pbs.example/1.jpg", Path("1.jpg")),
            TweetMedia("image", "https://pbs.example/2.jpg", Path("2.jpg")),
        ]
    )

    accepted = await adapter.send_event(
        object(),
        "nasa",
        "https://nitter.example",
        [tweet],
    )

    assert accepted is True
    assert sender._send_event_chain.await_count == 3
    text_chain = sender._send_event_chain.await_args_list[0].args[1]
    first_image_chain = sender._send_event_chain.await_args_list[1].args[1]
    second_image_chain = sender._send_event_chain.await_args_list[2].args[1]
    assert text_chain.use_markdown_ is True
    assert _plain_text(text_chain).startswith("**@nasa**")
    assert all(
        "image" in type(_chain_components(chain)[0]).__name__.lower()
        and chain.use_markdown_ is False
        for chain in (first_image_chain, second_image_chain)
    )


@pytest.mark.asyncio
async def test_qq_official_media_only_event_escapes_author_markdown():
    sender = _sender(images=True, videos=False)
    adapter = _adapter(sender)
    tweet = TweetItem(
        text="",
        link="https://x.com/nasa_user/status/1",
        published="2026-08-10 12:00:00",
        media=[TweetMedia("image", "https://pbs.example/1.jpg", Path("1.jpg"))],
    )

    accepted = await adapter.send_event(
        object(),
        "nasa_user",
        "https://nitter.example",
        [tweet],
        media_only=True,
    )

    assert accepted is True
    assert sender._send_event_chain.await_count == 2
    text_chain = sender._send_event_chain.await_args_list[0].args[1]
    assert text_chain.use_markdown_ is True
    assert _plain_text(text_chain) == "**@nasa\\_user**"


@pytest.mark.asyncio
async def test_qq_official_media_only_counts_delivered_video_after_image_failure():
    sender = _sender(images=True, videos=True)
    sender._send_context_message = AsyncMock(
        side_effect=[
            SendAttempt(success=True),
            SendAttempt(success=False, retryable=False, error="image failed"),
            SendAttempt(success=True),
        ]
    )
    adapter = _adapter(sender)
    tweet = _tweet(
        media=[
            TweetMedia("image", "https://pbs.example/1.jpg", Path("1.jpg")),
            TweetMedia("video", "https://pbs.example/1.mp4", Path("1.mp4")),
        ]
    )

    outcome = await adapter.send_to_umo(
        object(),
        "official:GroupMessage:group-openid",
        "nasa",
        "https://nitter.example",
        [tweet],
        media_only=True,
    )

    assert outcome.success is True
    assert outcome.delivery_status == "partial_failed"
    assert outcome.delivery_error == "image failed"
    assert outcome.delivered_status_ids == (tweet.status_id,)


@pytest.mark.asyncio
async def test_qq_official_plain_delivery_keeps_partial_media_success():
    sender = _sender(images=True, videos=True)
    sender._send_context_message = AsyncMock(
        side_effect=[
            SendAttempt(success=True),
            SendAttempt(success=False, retryable=False, error="image failed"),
            SendAttempt(success=True),
        ]
    )
    adapter = _adapter(sender)
    tweet = _tweet(
        media=[
            TweetMedia("image", "https://pbs.example/1.jpg", Path("1.jpg")),
            TweetMedia("video", "https://pbs.example/1.mp4", Path("1.mp4")),
        ]
    )

    outcome = await adapter.send_to_umo(
        object(),
        "official:GroupMessage:group-openid",
        "nasa",
        "https://nitter.example",
        [tweet],
    )

    assert outcome.success is True
    assert outcome.delivery_status == "partial_failed"
    assert outcome.delivery_error == "image failed"


@pytest.mark.asyncio
async def test_qq_official_recovered_body_retry_clears_old_error():
    sender = _sender(images=True, videos=False)
    sender._send_context_message = AsyncMock(
        side_effect=[
            SendAttempt(success=False, retryable=True, error="text failed"),
            SendAttempt(success=True),
            SendAttempt(success=True),
        ]
    )
    adapter = _adapter(sender)
    tweet = _tweet(
        media=[TweetMedia("image", "https://pbs.example/1.jpg", Path("1.jpg"))]
    )

    outcome = await adapter.send_to_umo(
        object(),
        "official:GroupMessage:group-openid",
        "nasa",
        "https://nitter.example",
        [tweet],
    )

    assert outcome.success is True
    assert outcome.delivery_status == "success"
    assert outcome.error == ""
    assert outcome.delivery_error == ""
    assert sender._send_context_message.await_count == 3


def test_qq_official_markdown_keeps_sentence_punctuation_out_of_urls():
    escaped = TweetMessageRenderer.qq_official_markdown_text(
        "见 (https://example.com) 结束"
    )

    # The closing paren belongs to the sentence, not to the link.
    assert "https://example.com%29" not in escaped
    assert "https://example.com) 结束" in escaped

    # A paren that balances one inside the URL stays part of the link.
    balanced = TweetMessageRenderer.qq_official_markdown_text(
        "https://en.wikipedia.org/wiki/Foo_(bar)"
    )
    assert balanced == "https://en.wikipedia.org/wiki/Foo_%28bar%29"

    # Other sentence punctuation is split off the URL too; it escapes to the
    # same characters, so assert on the split itself.
    split = TweetMessageRenderer._split_url_trailing_punctuation
    assert split("https://example.com/a,") == ("https://example.com/a", ",")
    assert split("https://example.com/a。") == ("https://example.com/a", "。")
    assert split("https://example.com/a") == ("https://example.com/a", "")


def test_qq_official_markdown_escapes_syntax_but_leaves_html_literal():
    escaped = TweetMessageRenderer.qq_official_markdown_text(
        "<b>bold</b> ![img](http://evil.example/x.png)"
    )

    # HTML is not rendered by QQ's Markdown subset, so it stays literal.
    assert "<b>bold</b>" in escaped
    # Brackets and parens stay bare: a backslash in front of either builds one
    # of QQ's LaTeX delimiters, which swallows the text between the markers.
    assert "\\[" not in escaped
    assert "\\(" not in escaped
    # The link is defused by severing the "](" seam with a zero-width space,
    # which renders as nothing but stops the syntax from being recognised.
    assert "](http" not in escaped
    assert "![img]" + "\u200b" + "(http://evil.example/x.png)" in escaped

    strike = TweetMessageRenderer.qq_official_markdown_text("~~strike~~")
    assert strike == "\\~\\~strike\\~\\~"


def test_qq_official_markdown_link_label_cannot_break_out():
    """A label holding "](" must not close the link and open an attacker's."""

    link = TweetMessageRenderer.qq_official_markdown_link(
        "a](https://evil.example) b", "https://ok.example"
    )

    # Exactly one link is formed, and it points where we put it.
    assert link.count("](") == 1
    assert link.endswith("](https://ok.example)")
    assert "](https://evil.example)" not in link


def test_qq_official_markdown_escapes_indented_block_markers():
    """QQ reads a four-space indent as list nesting, so indented markers escape."""

    escaped = TweetMessageRenderer.qq_official_markdown_text(
        "text\n    - item\n    > quote\n    # head\n    1. first"
    )

    # The marker is escaped but its indent survives, so layout is preserved.
    assert "\n    \\- item" in escaped
    assert "\n    \\> quote" in escaped
    assert "\n    \\# head" in escaped
    assert "\n    1\\. first" in escaped


def test_qq_official_markdown_leaves_non_marker_punctuation_alone():
    """The lookahead keeps ordinary text from being treated as a list marker."""

    assert TweetMessageRenderer.qq_official_markdown_text("-5°C") == "-5°C"
    assert TweetMessageRenderer.qq_official_markdown_text("  -5°C") == "  -5°C"
    assert TweetMessageRenderer.qq_official_markdown_text("1.5x") == "1.5x"
    assert TweetMessageRenderer.qq_official_markdown_text("a - b") == "a - b"


def test_qq_official_markdown_preserves_inline_text_after_urls():
    escape = TweetMessageRenderer.qq_official_markdown_text

    assert escape("a https://x.com - item") == "a https://x.com - item"
    assert escape("a https://x.com # title") == "a https://x.com # title"
    assert escape("a https://x.com 1. item") == "a https://x.com 1. item"
    assert escape("https://x.com\n- item") == "https://x.com\n\\- item"


@pytest.mark.asyncio
async def test_qq_official_force_media_splits_despite_disabled_media_flags():
    """force_media copies the sender, so both media checks see the same flags."""

    from delivery.sender import TweetSender

    sender = TweetSender(
        {"send_image_attachments": False, "send_video_attachments": False}
    )
    sender._send_event_chain = AsyncMock(return_value=SendAttempt(success=True))
    profile = SimpleNamespace(
        should_split_qq_direct_images=True,
        should_split_qq_direct_videos=True,
    )
    observed: list = []

    def adapter_for(bound_sender, _profile):
        observed.append(bound_sender)
        return QQOfficialDeliveryAdapter(bound_sender, profile)

    sender.delivery_registry = SimpleNamespace(adapter_for=adapter_for)
    sender.platform_resolver = SimpleNamespace(from_event=lambda event: profile)
    tweet = _tweet(
        media=[
            TweetMedia("image", "https://pbs.example/1.jpg", Path("1.jpg")),
            TweetMedia("image", "https://pbs.example/2.jpg", Path("2.jpg")),
        ]
    )

    accepted = await sender.send(
        object(),
        "nasa",
        "https://nitter.example",
        [tweet],
        force_media=True,
    )

    assert accepted is True
    # The adapter must be bound to the forced copy, not the shared sender.
    forced_sender = observed[0]
    assert forced_sender is not sender
    assert forced_sender.send_image_attachments is True
    assert QQOfficialDeliveryAdapter._has_attached_media(forced_sender, [tweet]) is True
    # The Markdown body is sent first, then each image is split off.
    assert sender._send_event_chain.await_count == 3
    first_components = _chain_components(
        sender._send_event_chain.await_args_list[0].args[1]
    )
    assert all(
        type(component).__name__.endswith("Plain") and hasattr(component, "text")
        for component in first_components
    )
    assert sender._send_event_chain.await_args_list[0].args[1].use_markdown_ is True
    assert (
        "image"
        in type(
            _chain_components(sender._send_event_chain.await_args_list[1].args[1])[0]
        ).__name__.lower()
    )
    # The shared sender keeps its original flags.
    assert sender.send_image_attachments is False


@pytest.mark.asyncio
async def test_qq_official_media_only_needs_all_images_when_no_video():
    sender = _sender(images=True, videos=False)
    sender._send_context_message = AsyncMock(
        side_effect=[
            SendAttempt(success=True),
            SendAttempt(success=True),
            SendAttempt(success=False, retryable=False, error="second image failed"),
        ]
    )
    adapter = _adapter(sender)
    tweet = _tweet(
        media=[
            TweetMedia("image", "https://pbs.example/1.jpg", Path("1.jpg")),
            TweetMedia("image", "https://pbs.example/2.jpg", Path("2.jpg")),
        ]
    )

    outcome = await adapter.send_to_umo(
        object(),
        "official:GroupMessage:group-openid",
        "nasa",
        "https://nitter.example",
        [tweet],
        media_only=True,
    )

    assert outcome.success is False
    assert outcome.delivery_status == "partial_failed"
    assert outcome.delivery_error == "second image failed"
    assert outcome.delivered_status_ids == ()
