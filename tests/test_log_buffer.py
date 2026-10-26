"""``shared.log_buffer`` 有界环缓冲测试。

覆盖：环形上限淘汰、seq 单调递增、级别映射、``snapshot(after_seq)`` 增量过滤、
空行与非法级别输入的降级行为。
"""

from __future__ import annotations

import pytest

from shared import log_buffer


@pytest.fixture(autouse=True)
def _reset_buffer():
    log_buffer.clear()
    yield
    log_buffer.clear()


def test_level_name_maps_standard_levels():
    assert log_buffer.level_name(10) == "debug"
    assert log_buffer.level_name(20) == "info"
    assert log_buffer.level_name(30) == "warning"
    assert log_buffer.level_name(40) == "error"
    assert log_buffer.level_name(50) == "critical"


def test_level_name_falls_back_to_info_for_unknown_input():
    assert log_buffer.level_name(0) == "info"
    assert log_buffer.level_name(None) == "info"
    assert log_buffer.level_name("not-a-level") == "info"


def test_append_records_sanitized_lines_with_monotonic_seq():
    log_buffer.append(20, ["first line", "second line"])
    log_buffer.append(40, ["boom"])

    entries = log_buffer.snapshot()
    assert [e["seq"] for e in entries] == [1, 2]
    assert entries[0]["level"] == "info"
    assert entries[0]["lines"] == ["first line", "second line"]
    assert entries[1]["level"] == "error"
    assert all(isinstance(e["ts"], float) for e in entries)


def test_append_skips_entries_without_content():
    log_buffer.append(20, [])
    log_buffer.append(20, ["   ", ""])
    assert log_buffer.snapshot() == []


def test_snapshot_after_seq_returns_only_newer_entries():
    for i in range(3):
        log_buffer.append(20, [f"line {i}"])

    assert [e["lines"][0] for e in log_buffer.snapshot(1)] == ["line 1", "line 2"]
    assert log_buffer.snapshot(3) == []


def test_ring_buffer_evicts_oldest_beyond_capacity():
    for i in range(log_buffer.MAX_ENTRIES + 5):
        log_buffer.append(20, [f"line {i}"])

    entries = log_buffer.snapshot()
    assert len(entries) == log_buffer.MAX_ENTRIES
    # 最早的 5 条被淘汰，窗口从第 6 条开始
    assert entries[0]["lines"] == ["line 5"]
    assert entries[-1]["lines"] == [f"line {log_buffer.MAX_ENTRIES + 4}"]


def test_snapshot_limit_keeps_newest():
    for i in range(10):
        log_buffer.append(20, [f"line {i}"])

    entries = log_buffer.snapshot(0, limit=3)
    assert [e["lines"][0] for e in entries] == ["line 7", "line 8", "line 9"]


def test_clear_resets_sequence():
    log_buffer.append(20, ["before"])
    log_buffer.clear()
    log_buffer.append(20, ["after"])

    entries = log_buffer.snapshot()
    assert len(entries) == 1
    assert entries[0]["seq"] == 1
    assert entries[0]["lines"] == ["after"]


def test_snapshot_returns_copies():
    log_buffer.append(20, ["original"])
    entries = log_buffer.snapshot()
    entries[0]["lines"].append("mutated")

    assert log_buffer.snapshot()[0]["lines"] == ["original"]
