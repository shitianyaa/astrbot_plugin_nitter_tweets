# -*- coding: utf-8 -*-
"""每日/间隔检查槽位的触发与记账。

每日检查以 `_last_daily_check` 为基准判断“是否跨过了配置时刻”。启动时必须
先锚定基准，否则基准为 None 会让所有已配置时刻在第一轮全部命中，绕过
check_on_startup，并在启动后立刻触发一批检查。
"""
from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

from scheduler.runner import CN_TZ, NitterTweetScheduler


def _scheduler() -> NitterTweetScheduler:
    scheduler = NitterTweetScheduler.__new__(NitterTweetScheduler)
    scheduler._startup_schedule_seeded = set()
    scheduler._last_interval_slots = {}
    scheduler._daily_slots = {}
    scheduler._last_daily_check = {}
    scheduler._log_verbose_info = lambda *_args, **_kwargs: None
    return scheduler


def _group(
    *,
    check_on_startup: bool = False,
    interval: bool = False,
    daily_times: list[tuple[int, int]] | None = None,
) -> SimpleNamespace:
    times = daily_times if daily_times is not None else [(9, 0), (21, 0)]
    return SimpleNamespace(
        group_id="g1",
        check_on_startup=check_on_startup,
        interval_check_enabled=interval,
        check_interval_minutes=30,
        daily_check_enabled=bool(times),
        daily_check_times=times,
    )


def _at(hour: int, minute: int, second: int = 0) -> dt.datetime:
    return dt.datetime(2026, 7, 26, hour, minute, second, tzinfo=CN_TZ)


def test_daily_times_do_not_all_fire_after_startup():
    scheduler = _scheduler()
    group = _group()

    assert scheduler._scheduled_reasons(group, _at(14, 0)) == []
    # 第二轮不再走启动分支，若基准未锚定这里会补出全部每日时刻。
    assert scheduler._scheduled_reasons(group, _at(14, 0, 30)) == []
    assert scheduler._scheduled_reasons(group, _at(20, 59)) == []


def test_daily_times_do_not_fire_at_startup_with_check_on_startup():
    scheduler = _scheduler()
    group = _group(check_on_startup=True)

    assert scheduler._scheduled_reasons(group, _at(14, 0)) == []


def test_daily_fires_once_when_configured_time_passes():
    scheduler = _scheduler()
    group = _group(daily_times=[(21, 0)])

    assert scheduler._scheduled_reasons(group, _at(20, 59)) == []
    assert scheduler._scheduled_reasons(group, _at(21, 0)) == ["daily:21:00"]

    # 执行后记账（_consume_schedule_slots 的效果），不得重复触发。
    scheduler._last_daily_check[group.group_id] = _at(21, 0)
    assert scheduler._scheduled_reasons(group, _at(21, 0, 30)) == []
    assert scheduler._scheduled_reasons(group, _at(22, 0)) == []


def test_daily_catches_up_when_tick_is_late():
    scheduler = _scheduler()
    group = _group(daily_times=[(21, 0)])

    assert scheduler._scheduled_reasons(group, _at(20, 59)) == []
    # 轮询被拖过整点，仍应补触发一次而不是整天跳过。
    assert scheduler._scheduled_reasons(group, _at(21, 3)) == ["daily:21:00"]


def test_startup_seeding_suppresses_first_interval_round():
    scheduler = _scheduler()
    group = _group(interval=True, daily_times=[])

    assert scheduler._scheduled_reasons(group, _at(14, 0)) == []
    assert scheduler._scheduled_reasons(group, _at(14, 0, 30)) == []
    assert scheduler._scheduled_reasons(group, _at(14, 31)) == ["interval:30m"]


def test_interval_reason_repeats_until_consumed():
    scheduler = _scheduler()
    group = _group(interval=True, check_on_startup=True, daily_times=[])

    # check_on_startup 不 seed 间隔槽位，启动即触发一次。
    assert scheduler._scheduled_reasons(group, _at(14, 0)) == ["interval:30m"]
    # 未记账前保持待触发，避免检查被锁跳过后整轮丢失。
    assert scheduler._scheduled_reasons(group, _at(14, 1)) == ["interval:30m"]

    scheduler._consume_schedule_slots(group, "interval:30m")
    assert scheduler._last_interval_slots[group.group_id] is not None
