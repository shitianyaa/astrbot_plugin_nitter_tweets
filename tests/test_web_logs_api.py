"""``web/logs`` 接口与 ``safe_log`` / ``safe_task_log`` 写入环缓冲的联动测试。

覆盖：接口返回结构、after_seq 增量、空缓冲、上限字段透传，以及安全日志
辅助函数确实把已脱敏文本写进缓冲（含密钥脱敏）。
"""

from __future__ import annotations

import asyncio
import logging

import pytest

from plugin_api.api_logs import WebAPILogsMixin
from shared import log_buffer
from shared.observability import safe_log, safe_task_log


class _LogsAPI(WebAPILogsMixin):
    """最小宿主替身：只提供 mixin 依赖的 _ok。"""

    @staticmethod
    def _ok(**payload):
        return {"success": True, "error": "", **payload}


@pytest.fixture(autouse=True)
def _reset_buffer():
    log_buffer.clear()
    yield
    log_buffer.clear()


def build_logs(after_seq: int = 0):
    return asyncio.run(_LogsAPI().build_logs(after_seq))


def test_build_logs_returns_empty_entries_when_buffer_is_empty():
    payload = build_logs()
    assert payload["success"] is True
    assert payload["entries"] == []
    assert payload["max_entries"] == log_buffer.MAX_ENTRIES


def test_build_logs_exposes_appended_entries():
    log_buffer.append(logging.INFO, ["任务开始"])
    log_buffer.append(logging.WARNING, ["实例超时"])

    payload = build_logs()
    assert [e["level"] for e in payload["entries"]] == ["info", "warning"]
    assert payload["entries"][0]["lines"] == ["任务开始"]
    assert [e["seq"] for e in payload["entries"]] == [1, 2]


def test_build_logs_after_seq_only_returns_new_entries():
    log_buffer.append(logging.INFO, ["one"])
    log_buffer.append(logging.INFO, ["two"])
    log_buffer.append(logging.INFO, ["three"])

    payload = build_logs(2)
    assert [e["lines"][0] for e in payload["entries"]] == ["three"]


def test_safe_log_writes_sanitized_single_line():
    safe_log(logging.INFO, "media_transport", status="ok", media_kind="image")

    entries = log_buffer.snapshot()
    assert len(entries) == 1
    assert entries[0]["level"] == "info"
    assert entries[0]["lines"][0].startswith("[NitterTweets] event=media_transport")
    assert "status=ok" in entries[0]["lines"][0]


def test_safe_log_drops_unregistered_fields():
    safe_log(logging.INFO, "media_transport", status="ok", unexpected_secret="hunter2")

    line = log_buffer.snapshot()[0]["lines"][0]
    assert "unexpected_secret" not in line
    assert "hunter2" not in line


def test_safe_task_log_writes_multiline_block():
    safe_task_log(
        logging.INFO,
        "定时检查",
        group_name="测试分组",
        group_id="g1",
        tweet_count=2,
        sent_count=2,
    )

    entry = log_buffer.snapshot()[0]
    assert entry["level"] == "info"
    assert entry["lines"][0] == "[NitterTweets] 定时检查"
    joined = "\n".join(entry["lines"])
    assert "分组名称: 测试分组 (g1)" in joined
    assert "推文统计" in joined


def test_safe_task_log_redacts_instance_path():
    safe_task_log(
        logging.WARNING,
        "定时检查",
        instance="http://nitter.internal:8080/secret-path",
    )

    joined = "\n".join(log_buffer.snapshot()[0]["lines"])
    assert "secret-path" not in joined
