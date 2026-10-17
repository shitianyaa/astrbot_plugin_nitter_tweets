"""P-03 end-to-end LLM FunctionTools on real AstrBot dataclass contracts."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.agent.tool import FunctionTool

from command_handlers.llm_tools import build_llm_tools
from query.budget import QueryBudget
from query.llm_controller import LLMQueryController
from shared.utils import TweetItem, TweetMedia


class Event:
    def __init__(self, *, sender="alice", umo="telegram:GroupMessage:1"):
        self.unified_msg_origin = umo
        self.sender = sender
        self.extras = {}
        self.send = AsyncMock()
        self.plain_result = lambda v: v
        self._admin = False
        self._private = False

    def get_sender_id(self):
        return self.sender

    def get_extra(self, key, default=None):
        return self.extras.get(key, default)

    def set_extra(self, key, value):
        self.extras[key] = value

    def is_admin(self):
        return self._admin

    def is_private_chat(self):
        return self._private


def tweet(i=1, *, video=False) -> TweetItem:
    return TweetItem(
        text=f"Post {i}: normal English tweet",
        link=f"https://x.com/nasa/status/{i}",
        published="2026-10-17",
        media=[TweetMedia(kind="video", url="https://video.twimg.com/x.mp4")]
        if video
        else [],
    )


def plugin():
    p = SimpleNamespace()
    p.config = {"llm_tools_enabled": True, "fetch_backend": "mix"}
    p.fetch_backend = "mix"
    p.filter_reposts_enabled = True
    p.nitter = MagicMock()
    p.nitter.instances = ["http://private-nitter:8080"]
    p.nitter.fetch_user = AsyncMock(return_value=("private-host", [tweet(1)]))
    p.fxtwitter = MagicMock()
    p.fxtwitter.fetch_user_timeline.return_value = (
        [tweet(i) for i in range(1, 16)],
        None,
    )
    p.fxtwitter.search_tweets.return_value = ([tweet(i) for i in range(1, 16)], None)
    p.fxtwitter.fetch_trends.return_value = [{"name": "Topic", "rank": 1}]
    p.media = MagicMock()
    p.media.enabled = False
    p.media.cleanup_after_send = MagicMock()
    p.sender = MagicMock()
    p.sender.send = AsyncMock(return_value=True)
    p.sender.send_video_attachments = False
    p.sender.send_image_attachments = False
    p.translator = MagicMock()
    p._cooldown_left = MagicMock(return_value=0.0)
    p._mark_cooldown = MagicMock()
    p.context = MagicMock()
    p._llm_query_controller = LLMQueryController(p)
    return p


def wrapped(event):
    return ContextWrapper(context=SimpleNamespace(event=event))


def get_tools(p):
    names = build_llm_tools(p)
    assert len(names) == 4
    assert all(isinstance(t, FunctionTool) for t in names)
    return {t.name: t for t in names}


@pytest.mark.asyncio
async def test_real_function_tool_returns_tweets_to_model_without_chat_or_translation():
    p, event = plugin(), Event()
    tools = get_tools(p)
    output = json.loads(
        await tools["nitter_fetch_user_tweets"].call(
            wrapped(event), username="@nasa", limit=5
        )
    )
    assert output["status"] == "success"
    assert output["returned_count"] == 5
    assert output["items"][0]["text"] == "Post 1: normal English tweet"
    assert output["items"][0]["x_url"] == "https://x.com/nasa/status/1"
    assert "private-nitter" not in json.dumps(output)
    assert output["delivery"]["requested"] is False
    event.send.assert_not_awaited()
    p.translator.attach_translations.assert_not_called()
    p.media.attach_media_with_results.assert_not_called()
    p.sender.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_search_cache_more_and_refresh_query_with_budget():
    p = plugin()
    tools = get_tools(p)
    ev1 = Event()
    first = json.loads(
        await tools["nitter_search_tweets"].call(
            wrapped(ev1), query="cats", limit=5, sort="latest"
        )
    )
    assert first["from_cache"] is False
    assert first["has_more"] is True
    assert first["returned_count"] == 5
    assert p.fxtwitter.search_tweets.call_count == 1

    ev2 = Event()
    more = json.loads(
        await tools["nitter_search_tweets"].call(wrapped(ev2), query="cats", limit=5)
    )
    assert more["from_cache"] is True
    assert [i["x_url"] for i in more["items"]] != [i["x_url"] for i in first["items"]]
    assert p.fxtwitter.search_tweets.call_count == 1
    assert QueryBudget.for_event(ev2).network_used == 0

    refreshed = json.loads(
        await tools["nitter_search_tweets"].call(
            wrapped(Event()), query="cats", limit=5, page_mode="refresh"
        )
    )
    assert refreshed["from_cache"] is False
    assert refreshed["items"][0] == first["items"][0]
    assert p.fxtwitter.search_tweets.call_count == 2


@pytest.mark.asyncio
async def test_same_event_multiple_network_calls_bypass_own_cooldown_but_not_another_event():
    p, event = plugin(), Event()
    tools = get_tools(p)
    first = json.loads(
        await tools["nitter_search_tweets"].call(wrapped(event), query="cats")
    )
    assert first["status"] == "success"
    p._cooldown_left.return_value = 30
    second = json.loads(
        await tools["nitter_search_tweets"].call(wrapped(event), query="dogs")
    )
    assert second["status"] == "success"
    assert QueryBudget.for_event(event).network_used == 2
    p._mark_cooldown.assert_called_once()
    other = json.loads(
        await tools["nitter_search_tweets"].call(
            wrapped(Event(sender="bob")), query="birds"
        )
    )
    assert other["status"] == "cooldown"
    assert p.fxtwitter.search_tweets.call_count == 2


@pytest.mark.asyncio
async def test_validation_happens_before_touching_network_or_cooldown():
    p = plugin()
    tools = get_tools(p)
    event = Event()
    for bad in (True, "5", 11, 0, 1.5, -1):
        output = json.loads(
            await tools["nitter_fetch_user_tweets"].call(
                wrapped(event), username="nasa", limit=bad
            )
        )
        assert output["status"] == "invalid"
    invalid = json.loads(
        await tools["nitter_search_tweets"].call(
            wrapped(event), query="cats", sort="bogus"
        )
    )
    assert invalid["status"] == "invalid"
    p.fxtwitter.fetch_user_timeline.assert_not_called()
    p.fxtwitter.search_tweets.assert_not_called()
    assert QueryBudget.for_event(event).network_used == 0


@pytest.mark.asyncio
async def test_network_limit_across_three_different_queries():
    p, event = plugin(), Event()
    tools = get_tools(p)
    p.fxtwitter.search_tweets.return_value = ([tweet(1)], None)
    for q in ["cats", "dogs", "birds"]:
        out = json.loads(
            await tools["nitter_search_tweets"].call(wrapped(event), query=q)
        )
        assert out["status"] == "success"
    fourth = json.loads(await tools["nitter_get_twitter_trends"].call(wrapped(event)))
    assert fourth["status"] == "budget_exceeded"
    assert fourth["resource"] == "network"
    assert p.fxtwitter.fetch_trends.call_count == 0


@pytest.mark.asyncio
async def test_tweet_cap_is_shared_and_fewer_rows_only_charge_real_count():
    p, event = plugin(), Event()
    tools = get_tools(p)
    for q in ["cats", "dogs"]:
        result = json.loads(
            await tools["nitter_search_tweets"].call(wrapped(event), query=q, limit=10)
        )
        assert result["returned_count"] == 10
    third = json.loads(
        await tools["nitter_search_tweets"].call(wrapped(event), query="birds", limit=1)
    )
    assert third["status"] == "budget_exceeded"
    assert third["resource"] == "data"
    assert p.fxtwitter.search_tweets.call_count == 2


@pytest.mark.asyncio
async def test_media_delivery_obeys_policy_and_five_attempt_round_cap():
    p, event = plugin(), Event()
    tools = get_tools(p)
    output = json.loads(
        await tools["nitter_fetch_user_tweets"].call(
            wrapped(event), username="nasa", limit=8, delivery="media"
        )
    )
    assert output["returned_count"] == 8
    assert output["delivery"]["confirmed_sent"] == 5
    assert output["delivery"]["attempted"] == 5
    assert p.sender.send.await_count == 5
    assert event.send.await_count == 1
    p.media.attach_media_with_results.assert_not_called()
    assert all(
        call.kwargs["force_media"] is False for call in p.sender.send.await_args_list
    )
    assert QueryBudget.for_event(event).remaining()["send"] == 0


@pytest.mark.asyncio
async def test_media_send_partial_failure_never_retries_unknown_suffix():
    p, event = plugin(), Event()
    calls = 0

    async def sometimes_fail(*args, **kwargs):
        nonlocal calls
        calls += 1
        return calls <= 3

    p.sender.send.side_effect = sometimes_fail
    output = json.loads(
        await get_tools(p)["nitter_fetch_user_tweets"].call(
            wrapped(event), username="nasa", limit=5, delivery="media"
        )
    )
    assert output["status"] == "partial"
    assert output["delivery"]["confirmed_sent"] == 3
    assert output["delivery"]["failed"] == 1
    assert output["delivery"]["attempted"] == 4
    assert calls == 4
    assert "已发送" not in json.dumps(output["items"])


@pytest.mark.asyncio
async def test_media_video_disabled_only_sends_allowed_text_links():
    p, event = plugin(), Event()
    p.fxtwitter.fetch_user_timeline.return_value = ([tweet(1, video=True)], None)
    output = json.loads(
        await get_tools(p)["nitter_fetch_user_tweets"].call(
            wrapped(event), username="nasa", media_type="video", delivery="media"
        )
    )
    assert output["returned_count"] == 1
    assert output["items"][0]["media_types"] == ["video"]
    p.media.attach_media_with_results.assert_not_called()
    assert p.sender.send.await_args.kwargs["force_media"] is False


@pytest.mark.asyncio
async def test_error_from_provider_is_never_reported_as_empty():
    p, event = plugin(), Event()
    p.fetch_backend = "fx"
    p.fxtwitter.search_tweets.side_effect = TimeoutError(
        "https://private.internal/?token=secret"
    )
    output = json.loads(
        await get_tools(p)["nitter_search_tweets"].call(wrapped(event), query="nasa")
    )
    assert output["status"] == "error"
    assert output["error_kind"] == "TimeoutError"
    assert "private.internal" not in json.dumps(output)


@pytest.mark.asyncio
async def test_trends_returns_items_and_does_not_send():
    p, event = plugin(), Event()
    result = json.loads(
        await get_tools(p)["nitter_get_twitter_trends"].call(wrapped(event))
    )
    assert result["status"] == "success"
    assert result["items"][0]["name"] == "Topic"
    event.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_config_flag_disables_even_stale_tool_object():
    p, event = plugin(), Event()
    tool = get_tools(p)["nitter_search_tweets"]
    p.config["llm_tools_enabled"] = False
    output = json.loads(await tool.call(wrapped(event), query="cats"))
    assert output["status"] == "disabled"
    p.fxtwitter.search_tweets.assert_not_called()


@pytest.mark.asyncio
async def test_partial_media_delivery_status():
    p, event = plugin(), Event()
    p.sender.send.side_effect = [True, True, True, False]
    out = json.loads(
        await get_tools(p)["nitter_fetch_user_tweets"].call(
            wrapped(event), username="nasa", limit=5, delivery="media"
        )
    )
    assert out["status"] == "partial"
    assert (out["delivery"]["confirmed_sent"], out["delivery"]["failed"]) == (3, 1)


@pytest.mark.asyncio
async def test_media_preparation_timeout_is_not_platform_uncertain():
    p, event = plugin(), Event()
    p.media.enabled = True
    p.media.attach_media_with_results.side_effect = TimeoutError("preparing")
    out = json.loads(
        await get_tools(p)["nitter_fetch_user_tweets"].call(
            wrapped(event), username="nasa", limit=2, delivery="media"
        )
    )
    assert out["status"] == "partial"
    assert out["delivery"]["attempted"] == 0
    assert out["delivery"]["uncertain"] == 0
    assert out["delivery"]["preparation_failed"] == 1
    p.sender.send.assert_not_awaited()
    assert QueryBudget.for_event(event).sends_used == 0


@pytest.mark.asyncio
async def test_text_budget_reserved_before_any_media_delivery():
    p, event = plugin(), Event()
    QueryBudget.for_event(event).reserve_text(23_950).commit()
    out = json.loads(
        await get_tools(p)["nitter_fetch_user_tweets"].call(
            wrapped(event), username="nasa", limit=5, delivery="media"
        )
    )
    assert out["status"] == "budget_exceeded"
    assert out["resource"] == "text"
    p.sender.send.assert_not_awaited()
    event.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_unexpected_value_error_cannot_expose_provider_message():
    p, event = plugin(), Event()
    p._llm_query_controller.timeline = AsyncMock(
        side_effect=ValueError("https://private.invalid/?token=fiction")
    )
    out = await get_tools(p)["nitter_fetch_user_tweets"].call(
        wrapped(event), username="nasa"
    )
    assert "private.invalid" not in out and "fiction" not in out
    assert json.loads(out)["status"] == "error"


@pytest.mark.asyncio
async def test_search_uses_next_backend_cursor_after_buffer_drained():
    p = plugin()

    def pages(_query, **kwargs):
        if kwargs.get("cursor") == "next-page":
            return ([tweet(i) for i in range(16, 31)], None)
        return ([tweet(i) for i in range(1, 16)], "next-page")

    p.fxtwitter.search_tweets.side_effect = pages
    tool = get_tools(p)["nitter_search_tweets"]
    results = [
        json.loads(await tool.call(wrapped(Event()), query="cats", limit=5))
        for _ in range(4)
    ]
    assert all(x["returned_count"] == 5 for x in results)
    assert results[3]["items"][0]["x_url"] == "https://x.com/nasa/status/16"
    assert p.fxtwitter.search_tweets.call_count == 2
    assert p.fxtwitter.search_tweets.call_args.kwargs["cursor"] == "next-page"


@pytest.mark.asyncio
async def test_exhausted_search_does_not_repeat_first_page_fetch():
    p = plugin()
    tool = get_tools(p)["nitter_search_tweets"]
    rows = [
        json.loads(await tool.call(wrapped(Event()), query="cats", limit=5))
        for _ in range(4)
    ]
    assert rows[3]["status"] == "empty"
    assert rows[3]["returned_count"] == 0
    assert p.fxtwitter.search_tweets.call_count == 1


@pytest.mark.asyncio
async def test_truncation_does_not_mark_omitted_rows_read(monkeypatch):
    import query.formatting as formatting

    monkeypatch.setattr(formatting, "MAX_TOOL_TEXT", 1_500)
    p, event = plugin(), Event()
    p.fxtwitter.search_tweets.return_value = (
        [
            TweetItem(
                text="x" * 900, link=f"https://x.com/nasa/status/{i}", published=""
            )
            for i in range(1, 16)
        ],
        None,
    )
    tool = get_tools(p)["nitter_search_tweets"]
    first = json.loads(await tool.call(wrapped(event), query="cats", limit=10))
    assert first["truncated"] is True
    assert 0 < first["returned_count"] < 10
    assert QueryBudget.for_event(event).data_used == first["returned_count"]
    second = json.loads(await tool.call(wrapped(Event()), query="cats", limit=5))
    assert second["items"][0]["x_url"] == (
        f"https://x.com/nasa/status/{first['returned_count'] + 1}"
    )


@pytest.mark.asyncio
async def test_real_astrbot_tool_executor_receives_json_without_side_effects():
    from astrbot.core.astr_agent_tool_exec import FunctionToolExecutor

    p, event = plugin(), Event()
    tool = get_tools(p)["nitter_fetch_user_tweets"]
    returned = [
        result
        async for result in FunctionToolExecutor.execute(
            tool, wrapped(event), username="nasa", limit=2
        )
    ]
    assert len(returned) == 1
    output = json.loads(returned[0].content[0].text)
    assert output["status"] == "success"
    assert output["returned_count"] == 2
    event.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancellation_during_media_preparation_restores_unsent_window():
    import asyncio

    p, event = plugin(), Event()
    p.media.enabled = True
    p.media.attach_media_with_results.side_effect = asyncio.CancelledError()
    tool = get_tools(p)["nitter_fetch_user_tweets"]
    with pytest.raises(asyncio.CancelledError):
        await tool.call(wrapped(event), username="nasa", limit=5, delivery="media")
    p.sender.send.assert_not_awaited()
    assert QueryBudget.for_event(event).sends_used == 0
    p.media.enabled = False
    later = json.loads(await tool.call(wrapped(Event()), username="nasa", limit=2))
    assert later["from_cache"] is True
    assert later["items"][0]["x_url"] == "https://x.com/nasa/status/1"


@pytest.mark.asyncio
async def test_cancellation_during_platform_send_never_replays_uncertain_item():
    import asyncio

    p, event = plugin(), Event()
    p.sender.send.side_effect = asyncio.CancelledError()
    tool = get_tools(p)["nitter_fetch_user_tweets"]
    with pytest.raises(asyncio.CancelledError):
        await tool.call(wrapped(event), username="nasa", limit=5, delivery="media")
    assert QueryBudget.for_event(event).sends_used == 1
    p.sender.send.side_effect = None
    later = json.loads(await tool.call(wrapped(Event()), username="nasa", limit=2))
    assert later["from_cache"] is True
    assert later["items"][0]["x_url"] == "https://x.com/nasa/status/2"
