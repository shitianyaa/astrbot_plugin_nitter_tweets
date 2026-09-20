from __future__ import annotations

import logging
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

from command_handlers.manual import ManualCommandMixin
from scheduler.runner_send import SchedulerSendMixin
from shared.observability import (
    format_elapsed,
    safe_log,
    safe_task_log,
    sanitize_diagnostic,
    sanitize_sensitive_text,
)


def test_format_elapsed_converts_ms_and_seconds():
    assert format_elapsed(350) == "350 毫秒"
    assert format_elapsed(1500) == "1.5 秒"
    assert format_elapsed(17426) == "17.4 秒"
    assert format_elapsed(0) == "0 毫秒"


def test_sanitize_sensitive_text_masks_credentials():
    assert "Bearer ***" in sanitize_sensitive_text(
        "Authorization: Bearer my_secret_token_123"
    )
    assert "***" in sanitize_sensitive_text("api_key: g2a_secret_abc123")
    assert "http://***@example.com" in sanitize_sensitive_text(
        "http://user:password@example.com"
    )
    assert "https://example.com/api?***" == sanitize_sensitive_text(
        "https://example.com/api?sig=secret123&token=abc"
    )


def test_sanitize_diagnostic_truncates_and_strips():
    assert sanitize_diagnostic("  hello \n world  ") == "hello world"
    long_str = "a" * 600
    sanitized = sanitize_diagnostic(long_str)
    assert len(sanitized) == 503
    assert sanitized.endswith("...")


def test_safe_task_log_formats_structured_multiline_chinese_block(monkeypatch):
    mock_logger = MagicMock()
    monkeypatch.setattr("shared.observability.logger", mock_logger)

    safe_task_log(
        logging.INFO,
        "推文检查任务完成",
        operation="list_check",
        group_name="我的关注",
        group_id="group_1",
        group_type="list",
        instance="nitter.tiekoetter.com",
        failover_trace="nitter.top[429] ➔ nitter.tiekoetter.com[成功]",
        tweet_count=1,
        sent_count=1,
        filtered_count=6,
        filtered_label="过滤转发",
        target_success_ratio="1/1",
        result_status="成功",
        elapsed_ms=17426,
    )

    assert mock_logger.log.called
    level, message = mock_logger.log.call_args[0]
    assert level == logging.INFO
    assert message.startswith("[NitterTweets] 推文检查任务完成")
    assert "  分组名称: 我的关注 (group_1)" in message
    assert "  订阅类型: Twitter List" in message
    assert "  生效实例: nitter.tiekoetter.com" in message
    assert "  轮换轨迹: nitter.top[429] ➔ nitter.tiekoetter.com[成功]" in message
    assert "  推文统计: 新推文 1 条; 实际发送 1 条; 过滤转发 6 条" in message
    assert "  推送结果: 成功推送 1/1 个目标" in message
    assert "  执行状态: 成功" in message
    assert "  任务耗时: 17.4 秒" in message


def test_safe_task_log_omits_empty_or_unlisted_fields(monkeypatch):
    mock_logger = MagicMock()
    monkeypatch.setattr("shared.observability.logger", mock_logger)

    safe_task_log(
        logging.INFO,
        "日常检查完成",
        group_name="我的关注",
        group_id="group_1",
        unknown_field="secret_val",
        instance="",
    )

    _level, message = mock_logger.log.call_args[0]
    assert "unknown_field" not in message
    assert "secret_val" not in message
    assert "生效实例" not in message


def test_manual_task_log_uses_actual_zero_sent_count(monkeypatch):
    mock_logger = MagicMock()
    monkeypatch.setattr("shared.observability.logger", mock_logger)

    ManualCommandMixin._log_manual_send_task(
        "推文查询完成",
        operation="user_timeline",
        source="@nasa",
        instance="https://nitter.example",
        tweet_count=2,
        sent_count=0,
        started=time.perf_counter(),
    )

    mock_logger.log.assert_called_once()
    level, message = mock_logger.log.call_args.args
    assert level == logging.WARNING
    assert "触发原因: 手动命令 (推文)" in message
    assert "！" not in message
    assert "推文统计: 新推文 2 条; 实际发送 0 条" in message
    assert "推送结果: 成功推送 0/1 个目标" in message
    assert "执行状态: 发送失败" in message


def test_safe_log_formats_single_line_diagnostic_event(monkeypatch):
    mock_logger = MagicMock()
    monkeypatch.setattr("shared.observability.logger", mock_logger)

    safe_log(
        logging.INFO,
        "host_failover",
        from_host="nitter.top",
        to_host="nitter.tiekoetter.com",
        reason="HTTP_429",
    )

    assert mock_logger.log.called
    level, message = mock_logger.log.call_args[0]
    assert level == logging.INFO
    assert (
        message
        == "[NitterTweets] event=host_failover | from_host=nitter.top | to_host=nitter.tiekoetter.com | reason=HTTP_429"
    )


# --- has_translation suppression tests (f19d28a regression) ---


def test_manual_log_ai_skipped_when_translation_disabled(monkeypatch):
    """Manual path: translator.enabled=False suppresses all per-tweet AI logs."""
    mock_logger = MagicMock()
    monkeypatch.setattr("command_handlers.manual.logger", mock_logger)

    host = ManualCommandMixin()
    host.translator = SimpleNamespace(enabled=False)

    host._log_ai_process_results("test", [MagicMock(), MagicMock()], None)
    mock_logger.info.assert_not_called()


def test_manual_log_ai_emits_when_translation_enabled(monkeypatch):
    """Manual path: translator.enabled=True still logs per-tweet AI summaries."""
    mock_logger = MagicMock()
    monkeypatch.setattr("command_handlers.manual.logger", mock_logger)
    monkeypatch.setattr(
        "command_handlers.manual.format_ai_tweet_summary",
        lambda *a, **kw: "dummy",
    )

    host = ManualCommandMixin()
    host.translator = SimpleNamespace(enabled=True)

    host._log_ai_process_results("test", [MagicMock()], None)
    assert mock_logger.info.call_count == 1


def test_scheduler_log_ai_skipped_when_translation_disabled(monkeypatch):
    """Scheduler path: translator.enabled=False suppresses per-tweet AI logs."""
    mock_logger = MagicMock()
    monkeypatch.setattr("scheduler.runner_send.logger", mock_logger)
    monkeypatch.setattr(
        "scheduler.runner_send.format_ai_tweet_summary",
        lambda *a, **kw: "dummy",
    )

    runner = SchedulerSendMixin()
    runner.translator = SimpleNamespace(enabled=False)
    runner.brief_log_enabled = False

    runner._log_ai_process_results("test", [MagicMock(), MagicMock()], None)
    mock_logger.info.assert_not_called()


def test_scheduler_log_ai_skipped_when_brief_log_enabled(monkeypatch):
    """Scheduler path: brief_log_enabled also suppresses per-tweet AI logs."""
    mock_logger = MagicMock()
    monkeypatch.setattr("scheduler.runner_send.logger", mock_logger)

    runner = SchedulerSendMixin()
    runner.translator = SimpleNamespace(enabled=True)
    runner.brief_log_enabled = True

    runner._log_ai_process_results("test", [MagicMock()], None)
    mock_logger.info.assert_not_called()


def test_scheduler_log_ai_emits_when_enabled_and_not_brief(monkeypatch):
    """Scheduler path: both translator.enabled and not brief → logs emitted."""
    mock_logger = MagicMock()
    monkeypatch.setattr("scheduler.runner_send.logger", mock_logger)
    monkeypatch.setattr(
        "scheduler.runner_send.format_ai_tweet_summary",
        lambda *a, **kw: "dummy",
    )

    runner = SchedulerSendMixin()
    runner.translator = SimpleNamespace(enabled=True)
    runner.brief_log_enabled = False

    runner._log_ai_process_results("test", [MagicMock(), MagicMock()], None)
    assert mock_logger.info.call_count == 2


def test_manual_task_log_dynamic_operation_labels(monkeypatch):
    mock_logger = MagicMock()
    monkeypatch.setattr("shared.observability.logger", mock_logger)

    ops_and_expected = [
        ("user_media", "手动命令 (推图)"),
        ("user_timeline", "手动命令 (推文)"),
        ("tweet_search", "手动命令 (推文搜索)"),
        ("tweet_pic_search", "手动命令 (推文搜图)"),
        ("trends", "手动命令 (推特热搜)"),
        ("mirror_test", "手动命令 (镜像测试)"),
        ("unknown_op", "手动命令"),
        ("", "手动命令"),
    ]

    for op, expected in ops_and_expected:
        mock_logger.reset_mock()
        safe_task_log(
            logging.INFO,
            "测试任务",
            operation=op,
            trigger="manual_command",
        )
        _lvl, msg = mock_logger.log.call_args[0]
        assert f"触发原因: {expected}" in msg
        assert "！" not in msg


def test_scheduled_check_result_reason_display_manual():
    from scheduler.models import ScheduledCheckResult

    result = ScheduledCheckResult(
        reason="manual:123",
        group_id="g1",
        group_name="测试组",
        group_type="blogger",
        users=["nasa"],
    )
    log = result.format_structured_task_log()
    assert "触发原因: 手动检查" in log
    assert "！" not in log
    assert "推文检查任务完成" in log

    summary = result.format_log_summary()
    assert "reason=手动检查" in summary


def test_safe_task_log_redacts_instance_urls_in_instance_trace_and_error(monkeypatch):
    """Verify safe_task_log redacts bare instance URLs in instance, failover_trace, and error_detail."""
    mock_logger = MagicMock()
    monkeypatch.setattr("shared.observability.logger", mock_logger)

    safe_task_log(
        logging.WARNING,
        "任务失败",
        operation="fetch",
        instance="https://my-internal.nitter.corp:8443",
        failover_trace="https://h1.lan[429] ➔ https://h2.lan[500]",
        error_detail="Timeout connecting to https://secret.backend:8080/api?token=abc",
    )

    assert mock_logger.log.called
    _lvl, message = mock_logger.log.call_args[0]
    assert "https://my-internal.nitter.corp:8443" not in message
    assert "https://h1.lan" not in message
    assert "https://h2.lan" not in message
    assert "https://secret.backend:8080" not in message
    assert "token=abc" not in message
    assert "生效实例: 实例地址" in message
    assert "轮换轨迹: 实例地址 ➔ 实例地址" in message
    assert "失败详情: Timeout connecting to 实例地址" in message
