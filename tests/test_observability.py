from __future__ import annotations

import logging
import time
from unittest.mock import MagicMock

from command_handlers.manual import ManualCommandMixin
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
