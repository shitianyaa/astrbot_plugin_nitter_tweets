from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import MagicMock

from command_handlers.manual import ManualCommandMixin
from media_support.client import NitterClient
from scheduler.models import ScheduledCheckResult
from scheduler.runner_send import SchedulerSendMixin
from shared.observability import (
    format_elapsed,
    redact_instance_urls,
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
        "info",
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

    assert mock_logger.info.called
    (message,) = mock_logger.info.call_args.args
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
        "info",
        "日常检查完成",
        group_name="我的关注",
        group_id="group_1",
        unknown_field="secret_val",
        instance="",
    )

    (message,) = mock_logger.info.call_args.args
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

    mock_logger.warning.assert_called_once()
    (message,) = mock_logger.warning.call_args.args
    assert "触发原因: 手动命令 (推文)" in message
    assert "！" not in message
    assert "推文统计: 新推文 2 条; 实际发送 0 条" in message
    assert "推送结果: 成功推送 0/1 个目标" in message
    assert "执行状态: 发送失败" in message


def test_safe_log_formats_single_line_diagnostic_event(monkeypatch):
    mock_logger = MagicMock()
    monkeypatch.setattr("shared.observability.logger", mock_logger)

    safe_log(
        "info",
        "host_failover",
        from_host="nitter.top",
        to_host="nitter.tiekoetter.com",
        reason="HTTP_429",
    )

    assert mock_logger.info.called
    (message,) = mock_logger.info.call_args.args
    assert (
        message
        == "[NitterTweets] event=host_failover | from_host=nitter.top | to_host=nitter.tiekoetter.com | reason=HTTP_429"
    )


def test_emit_covers_all_level_names_and_unknown_falls_back_to_info(monkeypatch):
    mock_logger = MagicMock()
    monkeypatch.setattr("shared.observability.logger", mock_logger)

    for level in ("debug", "info", "warning", "error"):
        mock_logger.reset_mock()
        safe_log(level, "level_probe", status="ok")
        expected = getattr(mock_logger, level)
        assert expected.call_count == 1
        (message,) = expected.call_args.args
        assert message == "[NitterTweets] event=level_probe | status=ok"
        for other in ("debug", "info", "warning", "error"):
            if other != level:
                assert not getattr(mock_logger, other).called

    mock_logger.reset_mock()
    safe_log("critical", "level_probe", status="ok")
    # critical 必须同名派发到宿主：环缓冲按 "critical" 记录，宿主侧降级成
    # info 会出现两边级别不一致（审查修正项）
    assert mock_logger.critical.call_count == 1
    (message,) = mock_logger.critical.call_args.args
    assert message == "[NitterTweets] event=level_probe | status=ok"
    assert not mock_logger.debug.called
    assert not mock_logger.info.called
    assert not mock_logger.warning.called
    assert not mock_logger.error.called


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
    monkeypatch.setattr("shared.observability.logger", mock_logger)
    monkeypatch.setattr(
        "scheduler.runner_send.format_ai_tweet_summary",
        lambda *a, **kw: "dummy",
    )

    runner = SchedulerSendMixin()
    runner.translator = SimpleNamespace(enabled=False)
    runner._log_ai_process_results("test", [MagicMock(), MagicMock()], None)
    mock_logger.info.assert_not_called()
    mock_logger.debug.assert_not_called()


def test_scheduler_log_ai_debug_does_not_flush_main_ring(monkeypatch):
    from shared import log_buffer

    mock_logger = MagicMock()
    monkeypatch.setattr("shared.observability.logger", mock_logger)
    monkeypatch.setattr(
        "scheduler.runner_send.format_ai_tweet_summary", lambda *a, **kw: "done"
    )
    log_buffer.clear()
    log_buffer.append("warning", ["keep warning"])
    runner = SchedulerSendMixin()
    runner.translator = SimpleNamespace(enabled=True)
    runner._log_ai_process_results("test", [MagicMock()], None)
    mock_logger.info.assert_not_called()
    assert log_buffer.snapshot()[0]["lines"] == ["keep warning"]
    assert log_buffer.snapshot(ring="debug")[0]["lines"] == ["done"]
    log_buffer.clear()


def test_scheduler_log_ai_emits_debug_when_translation_enabled(monkeypatch):
    mock_logger = MagicMock()
    monkeypatch.setattr("shared.observability.logger", mock_logger)
    monkeypatch.setattr(
        "scheduler.runner_send.format_ai_tweet_summary",
        lambda *a, **kw: "dummy",
    )

    runner = SchedulerSendMixin()
    runner.translator = SimpleNamespace(enabled=True)
    runner._log_ai_process_results("test", [MagicMock(), MagicMock()], None)
    assert mock_logger.debug.call_count == 2
    mock_logger.info.assert_not_called()


def test_safe_block_log_redacts_secrets_sessions_and_preserves_lines(monkeypatch):
    from shared import log_buffer
    from shared.observability import safe_block_log

    mock_logger = MagicMock()
    monkeypatch.setattr("shared.observability.logger", mock_logger)
    log_buffer.clear()
    safe_block_log(
        "error",
        "summary\n  token=hidden https://internal.example/private\nCookie: secret_cookie\ntarget=telegram:FriendMessage:secret_session",
        exc_info=True,
    )
    entry = log_buffer.snapshot()[0]
    text = "\n".join(entry["lines"])
    assert entry["lines"][0] == "summary"
    assert entry["lines"][1].startswith("  token=***")
    for secret in ("hidden", "internal.example", "secret_cookie", "secret_session"):
        assert secret not in text
    mock_logger.error.assert_called_once_with(text, exc_info=True)
    log_buffer.clear()


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
            "info",
            "测试任务",
            operation=op,
            trigger="manual_command",
        )
        (msg,) = mock_logger.info.call_args.args
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
        "warning",
        "任务失败",
        operation="fetch",
        instance="https://my-internal.nitter.corp:8443",
        failover_trace="https://h1.lan[429] ➔ https://h2.lan[500]",
        error_detail="Timeout connecting to https://secret.backend:8080/api?token=abc",
    )

    assert mock_logger.warning.called
    (message,) = mock_logger.warning.call_args.args
    assert "https://my-internal.nitter.corp:8443" not in message
    assert "https://h1.lan" not in message
    assert "https://h2.lan" not in message
    assert "https://secret.backend:8080" not in message
    assert "token=abc" not in message
    assert "生效实例: 实例地址" in message
    assert "轮换轨迹: 实例地址 ➔ 实例地址" in message
    assert "失败详情: Timeout connecting to 实例地址" in message


def test_redact_instance_urls_replaces_bare_urls():
    text = "http://64.112.40.168:8080: timed out (轮次 1/2); https://nitter.example: timed out"
    redacted = redact_instance_urls(text)
    assert "http://" not in redacted
    assert "https://" not in redacted
    assert "64.112.40.168" not in redacted
    assert "实例地址 timed out" in redacted


def test_redact_instance_urls_keeps_plain_text():
    assert (
        redact_instance_urls("#1: timed out (轮次 1/2)") == "#1: timed out (轮次 1/2)"
    )
    assert redact_instance_urls("") == ""
    assert redact_instance_urls(None) == ""


def test_fetch_error_summary_redacts_leftover_urls():
    client = NitterClient({"instances": ["https://a.example", "https://b.example"]})
    message = client._format_fetch_errors(
        ["http://64.112.40.168:8080: timed out (轮次 1/2)"], total_count=1
    )
    assert "http://" not in message
    assert "64.112.40.168" not in message
    assert "实例地址" in message


def test_fetch_error_summary_multi_round_copy():
    client = NitterClient({"instances": ["https://a.example", "https://b.example"]})
    message = client._format_fetch_errors(
        ["#1: timed out (轮次 1/2)", "#1: timed out (轮次 2/2)"], total_count=1
    )
    assert "已尝试 1 个 Nitter 实例共 2 次请求（含重试）" in message
    assert "2/1" not in message


def test_fetch_error_summary_single_round_copy():
    client = NitterClient({"instances": ["https://a.example", "https://b.example"]})
    message = client._format_fetch_errors(["#1: timed out (轮次 1/2)"], total_count=2)
    assert "已尝试 1/2 个 Nitter 实例" in message


def test_summary_failure_line_redacts_instance_urls():
    result = ScheduledCheckResult(
        reason="manual_command",
        group_name="qqcoser",
        group_id="group_1",
        failed_users={
            "@KOKOMO5512": "已尝试 2/1 个 Nitter 实例，未获得可用 RSS；错误: http://64.112.40.168:8080: timed out (轮次 1/2)"
        },
    )
    message = result.format_message()
    assert "http://" not in message
    assert "64.112.40.168" not in message
    assert "失败: @KOKOMO5512" in message


def test_summary_baseline_rebuild_failed_line_redacts_urls():
    result = ScheduledCheckResult(
        reason="manual_command",
        baseline_rebuild_failed_users={"@nasa": "http://64.112.40.168:8080: timed out"},
    )
    message = result.format_message()
    assert "http://" not in message
    assert "64.112.40.168" not in message
