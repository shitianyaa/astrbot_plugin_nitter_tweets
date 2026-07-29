from __future__ import annotations

from types import SimpleNamespace

import pytest

from ai.enrichment import TweetTranslator
from shared.utils import TweetItem, TweetMedia


class _Context:
    def __init__(self):
        self.provider_calls = 0
        self.llm_calls = 0

    async def get_current_chat_provider_id(self, *, umo):
        del umo
        self.provider_calls += 1
        return "provider"

    async def llm_generate(self, **kwargs):
        del kwargs
        self.llm_calls += 1
        return SimpleNamespace(completion_text="translated")


def _translator(context: _Context) -> TweetTranslator:
    return TweetTranslator(
        context,
        {
            "translate_enabled": True,
            "translate_min_chars": 0,
            "translate_chinese_ratio_threshold": 1.0,
        },
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["", "(无正文)", "（无正文）"])
async def test_empty_tweet_body_skips_provider_and_llm(text):
    context = _Context()
    translator = _translator(context)
    tweet = TweetItem(
        text=text,
        link="https://x.com/yureiyks/status/2082364407330341030",
        published="2026-07-29 15:15:37",
        media=[TweetMedia("video", "https://video.twimg.com/video.mp4")],
    )

    report = await translator.attach_translations([tweet], "telegram:GroupMessage:1")

    assert context.provider_calls == 0
    assert context.llm_calls == 0
    assert report.translated == 0
    assert report.skipped == 1
    assert report.tweet_results[0].status == "skipped"
    assert report.tweet_results[0].reason == "empty_body"


@pytest.mark.asyncio
async def test_non_empty_tweet_body_still_calls_llm():
    context = _Context()
    translator = _translator(context)
    tweet = TweetItem(
        text="hello world",
        link="https://x.com/user/status/1",
        published="2026-07-29 15:15:37",
    )

    report = await translator.attach_translations([tweet], "telegram:GroupMessage:1")

    assert context.provider_calls == 1
    assert context.llm_calls == 1
    assert tweet.translation == "translated"
    assert report.translated == 1
