"""Administrator-only state view: real scheduler parsing and exact UMO scopes."""

from __future__ import annotations

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from astrbot.core.agent.run_context import ContextWrapper

from command_handlers.llm_tools import build_llm_tools
from query.llm_controller import LLMQueryController


class Event:
    def __init__(
        self, *, admin=False, private=False, umo="telegram:GroupMessage:1", sender="1"
    ):
        self._admin = admin
        self._private = private
        self.unified_msg_origin = umo
        self.sender = sender
        self.extra = {}

    def is_admin(self):
        return self._admin

    def is_private_chat(self):
        return self._private

    def get_sender_id(self):
        return self.sender

    def get_extra(self, key, default=None):
        return self.extra.get(key, default)

    def set_extra(self, key, value):
        self.extra[key] = value


def plugin():
    p = SimpleNamespace()
    p.config = {
        "llm_tools_enabled": True,
        "tweet_groups": [
            {
                "group_id": "g1",
                "name": "Alpha",
                "group_type": "blogger",
                "watch_users": ["nasa", "SpaceX"],
                "push_targets": ["telegram:GroupMessage:1"],
            },
            {
                "group_id": "g2",
                "name": "Other private group",
                "group_type": "tag",
                "watch_queries": ["#classified"],
                "push_targets": ["telegram:GroupMessage:2"],
            },
            {
                "group_id": "g3",
                "name": "Public List",
                "group_type": "list",
                "watch_lists": ["1553232306718257152"],
                "push_targets": ["telegram:GroupMessage:1"],
            },
        ],
    }
    p.context = None
    p.nitter = SimpleNamespace(instances=["https://private.invalid/?token=fiction"])
    p._llm_query_controller = LLMQueryController(p)
    return p


async def state(p, event, **kwargs):
    tool = {x.name: x for x in build_llm_tools(p)}["nitter_list_plugin_state"]
    value = await tool.call(
        ContextWrapper(context=SimpleNamespace(event=event)), **kwargs
    )
    return json.loads(value), value


@pytest.mark.asyncio
async def test_regular_member_cannot_obtain_group_or_instance_details():
    p = plugin()
    result, raw = await state(p, Event(), scope="all")
    assert result["status"] == "forbidden"
    assert "Alpha" not in raw and "private.invalid" not in raw
    assert "instances" not in result


@pytest.mark.asyncio
async def test_admin_group_scope_exactly_matches_umo_and_excludes_other_groups():
    p = plugin()
    result, raw = await state(p, Event(admin=True), scope="all")
    assert result["status"] == "success"
    assert {entry["group"] for entry in result["entries"]} == {"Alpha", "Public List"}
    assert any("@nasa" in entry["sources"] for entry in result["entries"])
    assert any(
        "list:1553232306718257152" in entry["sources"] for entry in result["entries"]
    )
    assert "Other private group" not in raw
    assert "#classified" not in raw
    assert "telegram:GroupMessage:1" not in raw
    assert "private.invalid" not in raw


@pytest.mark.asyncio
async def test_admin_private_can_paginate_every_group_without_writing_config():
    p = plugin()
    p.config["tweet_groups"][0]["watch_users"] = [f"user{i}" for i in range(65)]
    before = deepcopy(p.config)
    event = Event(admin=True, private=True, umo="telegram:FriendMessage:1")
    first, _ = await state(p, event, scope="subscriptions")
    assert first["status"] == "success"
    assert first["has_more"] is True
    assert first["total_entries"] == 9  # 7 chunks + tag + list
    second, _ = await state(p, event, scope="subscriptions", page=2)
    assert second["page"] == 2 and second["has_more"] is False
    assert second["total_entries"] == 9
    assert {entry["group"] for entry in second["entries"]} == {
        "Alpha",
        "Other private group",
        "Public List",
    }
    assert p.config == before


@pytest.mark.asyncio
async def test_unknown_session_or_cross_platform_group_does_not_disclose():
    p = plugin()
    for umo, sender in [
        ("", "1"),
        ("telegram:GroupMessage:1", ""),
        ("qq:GroupMessage:1", "1"),
        ("telegram:GroupMessage:100", "1"),
    ]:
        result, raw = await state(p, Event(admin=True, umo=umo, sender=sender))
        assert result["status"] in ("forbidden", "empty")
        assert "Alpha" not in raw
        assert "Other private group" not in raw


@pytest.mark.asyncio
async def test_bad_scope_and_page_are_rejected_without_exposing_config():
    p = plugin()
    admin = Event(admin=True, private=True, umo="tg:FriendMessage:1")
    for kw in [{"scope": "raw"}, {"page": True}, {"page": 0}, {"page": -1}]:
        result, raw = await state(p, admin, **kw)
        assert result["status"] == "invalid"
        assert "Alpha" not in raw


@pytest.mark.asyncio
async def test_group_name_private_umo_and_url_are_redacted():
    p = plugin()
    p.config["tweet_groups"][0]["name"] = (
        "Alpha telegram:GroupMessage:999 https://private.invalid/?token=fiction"
    )
    result, raw = await state(p, Event(admin=True))
    assert result["status"] == "success"
    assert "telegram:GroupMessage:999" not in raw
    assert "private.invalid" not in raw
    assert "fiction" not in raw
