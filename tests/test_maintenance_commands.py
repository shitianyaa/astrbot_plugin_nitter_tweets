from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from astrbot.core.star.filter.command import CommandFilter, GreedyStr

from main import NitterTweetsPlugin
from scheduler.config import SchedulerConfigReader
from shared import TweetItem
from storage import SQLiteStorage, StorageAdapter


class _Event:
    is_at_or_wake_command = True

    def __init__(self, message):
        self.message = message
        self.extras = {}
        self.sent = []
        self.stopped = False

    def get_message_str(self):
        return self.message

    def get_self_id(self):
        return ""

    def set_extra(self, key, value):
        self.extras[key] = value

    def stop_event(self):
        self.stopped = True

    def plain_result(self, text):
        return text

    async def send(self, message):
        self.sent.append(message)


@pytest.fixture
def plugin(tmp_path, monkeypatch):
    sqlite = SQLiteStorage(tmp_path / "maintenance.db")
    monkeypatch.setattr(StorageAdapter, "_init_sqlite", lambda self: sqlite)
    instance = NitterTweetsPlugin.__new__(NitterTweetsPlugin)
    config = {
        "tweet_groups": [
            {
                "group_id": group_id,
                "name": name,
                "group_type": "blogger",
                "watch_users": ["nasa"],
                "push_targets": ["telegram:FriendMessage:1"],
                "enabled": True,
            }
            for group_id, name in (("science", "科技"), ("other", "其他"))
        ]
    }
    instance.get_kv_data = AsyncMock(return_value={})
    instance.delete_kv_data = AsyncMock()
    reader = SchedulerConfigReader(config, None)
    storage = StorageAdapter(instance, config, None)
    instance.scheduler = SimpleNamespace(config_reader=reader, storage=storage)

    async def seed():
        await storage.migrate_and_sync(reader.schedule_groups(False))
        for group_id in ("science", "other"):
            await storage.add_seen_ids(group_id, "nasa", ["100"])
            await storage.set_scan_watermark(group_id, "nasa", ["100"])
            await storage.record_push_history(
                group_id,
                "nasa",
                TweetItem(
                    text="old", link="https://x.com/nasa/status/100", published=""
                ),
                "telegram:FriendMessage:1",
                "scheduled",
            )

    asyncio.run(seed())
    instance.delete_kv_data.reset_mock()
    yield instance
    storage.close()


async def _dispatch(plugin, arguments):
    event = _Event(f"推文记录清理 {arguments}".strip())
    command = CommandFilter(
        "推文记录清理",
        handler_md=SimpleNamespace(handler=NitterTweetsPlugin.cmd_tweets_clear_seen),
    )
    assert command.filter(event, {})
    await plugin.cmd_tweets_clear_seen(event, **event.extras["parsed_params"])
    return event


@pytest.mark.parametrize("arguments", ["", "all", "全部", "科技", "science"])
def test_clear_progress_without_confirmation_preserves_history(plugin, arguments):
    asyncio.run(_check_clear_progress(plugin, arguments))


async def _check_clear_progress(plugin, arguments):
    storage = plugin.scheduler.storage
    sqlite = storage.sqlite
    groups_before = sqlite.get_all_groups()
    users_before = sqlite.get_group_users("science")
    targets_before = sqlite.get_group_targets("science")
    event = await _dispatch(plugin, arguments)

    assert event.stopped
    assert await storage.get_seen_ids("science", "nasa") == []
    assert await storage.get_group_scan_watermarks("science") == {}
    clear_all = arguments in {"", "all", "全部"}
    assert await storage.get_seen_ids("other", "nasa") == ([] if clear_all else ["100"])
    assert await storage.get_group_scan_watermarks("other") == (
        {} if clear_all else {"nasa": ["100"]}
    )
    assert await storage.count_push_history() == 2
    assert sqlite.get_all_groups() == groups_before
    assert sqlite.get_group_users("science") == users_before
    assert sqlite.get_group_targets("science") == targets_before
    assert plugin.delete_kv_data.await_count == 2
    assert "下次检查只记录当前推文，不发送" in event.sent[-1]
    assert "面板推送历史、订阅和媒体文件保留" in event.sent[-1]


@pytest.mark.parametrize("arguments", ["不存在", "科技 确认", "确认"])
def test_unknown_clear_group_does_not_reset_progress(plugin, arguments):
    asyncio.run(_check_unknown_group(plugin, arguments))


async def _check_unknown_group(plugin, arguments):
    event = await _dispatch(plugin, arguments)
    for group_id in ("science", "other"):
        assert await plugin.scheduler.storage.get_seen_ids(group_id, "nasa") == ["100"]
        assert await plugin.scheduler.storage.get_group_scan_watermarks(group_id) == {
            "nasa": ["100"]
        }
    assert "未找到分组" in event.sent[-1]
    assert "/推文记录清理 [分组名]" in event.sent[-1]
    plugin.delete_kv_data.assert_not_awaited()


def test_clear_handler_default_marker_is_treated_as_empty(plugin):
    asyncio.run(_check_default_marker(plugin))


async def _check_default_marker(plugin):
    event = _Event("推文记录清理")
    await plugin._cmd_tweets_clear_seen_impl(event, GreedyStr)
    assert await plugin.scheduler.storage.get_seen_ids("science", "nasa") == []
    assert await plugin.scheduler.storage.get_seen_ids("other", "nasa") == []
