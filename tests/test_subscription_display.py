from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from plugin_api.api import NitterWebAPI
from rendering.tweets import TweetMessageRenderer
from scheduler.config import SchedulerConfigReader
from scheduler.models import ScheduledCheckResult
from scheduler.runner_send import SchedulerSendMixin
from scheduler.runner_status import SchedulerStatusMixin
from shared import TweetItem, format_subscription_count, format_subscription_source


def _tweet(status_id: str = "1") -> TweetItem:
    return TweetItem(
        text=f"tweet {status_id}",
        link=f"https://x.com/nasa/status/{status_id}",
        published="",
    )


@pytest.mark.parametrize(
    ("group_type", "source", "count_label", "source_label"),
    [
        ("blogger", "nasa", "1 位博主", "@nasa"),
        ("tag", "q:#AI", "1 个搜索订阅", "搜索「#AI」"),
        ("list", "list:2081623084780671084", "1 个 List", "List 2081623084780671084"),
    ],
)
def test_type_aware_subscription_labels(
    group_type: str,
    source: str,
    count_label: str,
    source_label: str,
):
    assert format_subscription_count(1, group_type) == count_label
    assert format_subscription_source(source, group_type) == source_label
    summary = TweetMessageRenderer.format_batch_summary(
        [(source, "https://nitter.example", [_tweet()])],
        group_label="测试组",
        group_type=group_type,
    )
    assert count_label in summary


@pytest.mark.parametrize(
    ("group_type", "source", "source_label"),
    [
        ("tag", "q:#AI", "搜索「#AI」"),
        ("list", "list:2081623084780671084", "List 2081623084780671084"),
    ],
)
def test_check_messages_and_failure_summaries_hide_internal_prefixes(
    group_type: str,
    source: str,
    source_label: str,
):
    result = ScheduledCheckResult(
        reason="manual_command",
        group_id="g1",
        group_name="测试组",
        group_type=group_type,
        users=[source],
        targets=["telegram:FriendMessage:1"],
        initialized_users={source: 1},
        no_new_users=[source],
        empty_users=[source],
        failed_users={f"{source}:123": "boom"},
    )

    message = result.format_message()
    brief = "\n".join(result.format_brief_log_lines())
    failure_summary = SchedulerSendMixin._append_fetch_failure_summary(
        "",
        {source: "boom"},
        group_type=group_type,
    )
    combined = f"{message}\n{brief}\n{failure_summary}"

    assert source_label in combined
    assert "订阅源无有效推文 ID" in message
    assert "RSS 无有效推文 ID" not in combined
    assert "已记录索引" not in combined
    assert "@q:" not in combined
    assert "@list:" not in combined


def test_plain_list_fetch_failure_keeps_the_list_id_as_the_source():
    source = "list:2081623084780671084"
    result = ScheduledCheckResult(
        reason="manual_command",
        group_type="list",
        users=[source],
        failed_users={source: "boom"},
    )

    message = result.format_message()

    assert "List 2081623084780671084: boom" in message
    assert "推文 2081623084780671084" not in message


def test_tag_query_ending_in_numeric_segment_is_not_treated_as_tweet_suffix():
    source = "q:release:2026"
    result = ScheduledCheckResult(
        reason="manual_command",
        group_type="tag",
        users=[source],
        failed_users={source: "boom"},
    )

    assert "搜索「release:2026」: boom" in result.format_message()


def test_history_serialization_uses_list_subscription_source():
    record = SimpleNamespace(
        id=1,
        group_id="lists1",
        username="list:2081623084780671084",
        status_id="123",
        original_link="https://x.com/nasa/status/123",
        target_umo="telegram:FriendMessage:1",
        source="scheduled",
        instance="https://nitter.example",
        pushed_at=1,
        tweet=_tweet("123"),
        delivery_status="success",
        delivery_error="",
    )

    rows = NitterWebAPI._group_history_records(
        [record],
        {"lists1": "列表"},
        {
            "lists1": SimpleNamespace(
                group_type="list",
                targets=["telegram:FriendMessage:1"],
            )
        },
    )

    assert rows[0]["group_type"] == "list"
    assert rows[0]["subscription_source"] == "List 2081623084780671084"
    assert "@list:" not in rows[0]["subscription_source"]


def test_status_summary_does_not_read_or_display_seen_indexes():
    config = {
        "schedule_enabled": True,
        "tweet_groups": [
            {
                "name": "列表",
                "group_id": "lists1",
                "group_type": "list",
                "watch_lists": ["2081623084780671084"],
                "push_targets": ["telegram:FriendMessage:1"],
            }
        ],
    }
    groups = SchedulerConfigReader(config, context=None).schedule_groups()
    status = SchedulerStatusMixin.__new__(SchedulerStatusMixin)
    status.config = config
    status.is_running = True
    status.schedule_enabled = True
    status._schedule_groups = lambda **_kwargs: groups
    status._merge_tweet_threshold = lambda: 2
    status._get_seen_map = AsyncMock(side_effect=AssertionError("must not read seen"))

    summary = __import__("asyncio").run(status.status_summary())

    assert "1 个 List" in summary
    assert "已记录索引" not in summary
    status._get_seen_map.assert_not_awaited()
