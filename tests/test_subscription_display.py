from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from plugin_api.api import NitterWebAPI
from rendering.tweets import TweetMessageRenderer
from scheduler.config import SchedulerConfigReader
from scheduler.models import ScheduledCheckResult, ScheduledPushResult, SourceStatus
from scheduler.runner import NitterTweetScheduler
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
    assert "订阅源返回空结果" in message
    assert "RSS 无有效推文 ID" not in combined
    assert "已记录索引" not in combined
    assert "@q:" not in combined
    assert "@list:" not in combined


def test_empty_html_result_is_not_reported_as_no_new_tweets():
    source = "q:#AI"
    result = ScheduledCheckResult(
        reason="interval:20m",
        group_id="g1",
        group_name="测试组",
        group_type="tag",
        users=[source],
        targets=["telegram:FriendMessage:1"],
        empty_users=[source],
        source_statuses={source: "empty"},
        source_attempts={
            source: [
                "nitter.top=登录/维护/错误页",
                "nitter.poast.org=HTTP 403",
            ]
        },
    )

    message = result.format_message()
    brief = "\n".join(result.format_brief_log_lines())

    assert "抓取状态: 返回空结果 1 个" in message
    assert "水位状态: 未更新 1 个" in message
    assert "订阅源返回空结果" in message
    assert "实例结果" in message
    assert "本次没有发现需要推送的新推文。" not in message
    assert "status=empty:1" in brief


def test_structured_log_shows_effective_instance_from_single_success_attempt():
    result = ScheduledCheckResult(
        reason="interval:20m",
        group_id="g1",
        group_name="测试组",
        group_type="blogger",
        users=["nasa"],
        source_attempts={"nasa": ["nitter.example=成功"]},
    )

    structured = result.format_structured_task_log()

    assert "生效实例: nitter.example" in structured


def test_structured_log_keeps_all_operational_warnings_and_accurate_labels():
    source = "list:2081623084780671084"
    failed_source = "list:2081623084780671085"
    result = ScheduledCheckResult(
        reason="interval:20m",
        group_id="g1",
        group_name="测试组",
        group_type="list",
        users=[source, failed_source],
        targets=["telegram:FriendMessage:1", "telegram:FriendMessage:2"],
        invalid_targets=["bad-target"],
        source_statuses={
            source: SourceStatus.BASELINE_REBUILT,
            failed_source: SourceStatus.BASELINE_REBUILD_FAILED,
        },
        source_attempts={source: ["nitter.top=HTTP 403", "nitter.example=成功"]},
        baseline_rebuilt_users={source: 20},
        baseline_rebuild_failed_users={failed_source: "write token=secret failed"},
        pushes=[
            ScheduledPushResult(
                username=source,
                new_count=2,
                success_targets=1,
                total_targets=2,
            )
        ],
        delivery_warnings=["媒体部分失败", "媒体部分失败"],
        plain_text_filtered=3,
        target_blocked_filtered=1,
        media_only_skipped=2,
        media_only_retrying=1,
        max_tweets_per_check=5,
    )

    structured = result.format_structured_task_log(duration_ms=1250)
    detailed = "\n".join(result.format_brief_log_lines())

    assert "生效实例: nitter.example" in structured
    assert "轮换轨迹: List 2081623084780671084" in structured
    assert "抓取状态: 已重建基准 1 个、基准未重建 1 个" in structured
    assert "水位状态: 已重建 1 个、未更新 1 个" in structured
    assert "过滤纯文本 3 条" in structured
    assert "过滤转发" not in structured
    assert "成功推送 1/2 个目标" in structured
    assert "目标黑名单过滤 1 条" in structured
    assert "仅媒体策略跳过 2 条" in structured
    assert "媒体待重试 1 条" in structured
    assert "基准重建:" in structured
    assert "基准重建失败:" in structured
    assert "token=***" in structured
    assert "无效推送目标: bad-target" in structured
    assert structured.count("媒体部分失败") == 1
    assert "任务耗时: 1.2 秒" in structured
    assert "token=***" in detailed
    assert "token=secret" not in detailed
    assert result.needs_attention is True


def test_brief_scheduler_log_uses_warning_for_partial_delivery(monkeypatch):
    scheduler = object.__new__(NitterTweetScheduler)
    scheduler.config = {"brief_log_enabled": True}
    result = ScheduledCheckResult(
        reason="interval:20m",
        pushes=[
            ScheduledPushResult(
                username="nasa",
                new_count=1,
                success_targets=0,
                total_targets=1,
            )
        ],
    )
    mock_logger = MagicMock()
    monkeypatch.setattr("scheduler.runner.logger", mock_logger)

    scheduler._log_check_result(result, duration_ms=20)

    mock_logger.warning.assert_called_once()
    assert "成功推送 0/1 个目标" in mock_logger.warning.call_args.args[0]
    mock_logger.info.assert_not_called()


def test_structured_log_all_success_needs_no_attention_and_logs_info_only(monkeypatch):
    scheduler = object.__new__(NitterTweetScheduler)
    scheduler.config = {"brief_log_enabled": True}
    source = "list:2081623084780671084"
    result = ScheduledCheckResult(
        reason="interval:20m",
        group_id="g-success",
        group_name="全部成功组",
        group_type="list",
        users=[source],
        targets=["telegram:FriendMessage:1"],
        invalid_targets=[],
        pushes=[
            ScheduledPushResult(
                username=source,
                new_count=1,
                success_targets=1,
                total_targets=1,
            )
        ],
    )

    assert result.needs_attention is False

    mock_logger = MagicMock()
    monkeypatch.setattr("scheduler.runner.logger", mock_logger)

    scheduler._log_check_result(result, duration_ms=100)

    mock_logger.info.assert_called_once()
    mock_logger.warning.assert_not_called()
    assert "成功推送 1/1 个目标" in mock_logger.info.call_args.args[0]


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
