"""每日/间隔检查槽位的触发与记账。

每日检查以 `_last_daily_check` 为基准判断“是否跨过了配置时刻”。启动时必须
先锚定基准，否则基准为 None 会让所有已配置时刻在第一轮全部命中，绕过
check_on_startup，并在启动后立刻触发一批检查。
"""

from __future__ import annotations

import asyncio
import datetime as dt
from types import SimpleNamespace
from unittest.mock import AsyncMock

from scheduler.models import ScheduledCheckResult
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


def _startup_group(
    group_id: str,
    group_type: str,
    *,
    interval: bool = False,
    daily_times: list[tuple[int, int]] | None = None,
    sources: list[str] | None = None,
    targets: list[str] | None = None,
) -> SimpleNamespace:
    times = daily_times if daily_times is not None else []
    return SimpleNamespace(
        group_id=group_id,
        name=group_id,
        enabled=True,
        group_type=group_type,
        check_on_startup=True,
        interval_check_enabled=interval,
        check_interval_minutes=30,
        daily_check_enabled=bool(times),
        daily_check_times=times,
        account_keys=list([group_id] if sources is None else sources),
        targets=list(["telegram:FriendMessage:1"] if targets is None else targets),
    )


def _at(hour: int, minute: int, second: int = 0) -> dt.datetime:
    return dt.datetime(2026, 7, 26, hour, minute, second, tzinfo=CN_TZ)


def _storage_gate_scheduler():
    scheduler = NitterTweetScheduler.__new__(NitterTweetScheduler)
    group = _startup_group("g1", "blogger")
    scheduler._migration_done = False
    scheduler._storage_init_lock = asyncio.Lock()
    scheduler._storage_ready = asyncio.Event()
    scheduler._storage_init_error = ""
    scheduler._check_lock = asyncio.Lock()
    scheduler._schedule_groups = lambda **_kwargs: [group]
    scheduler._schedule_group = lambda _name: group
    scheduler.storage = SimpleNamespace(migrate_and_sync=AsyncMock())
    scheduler._new_check_result = lambda reason, selected, _target=None: (
        ScheduledCheckResult(
            reason=reason,
            group_id=selected.group_id,
            group_name=selected.name,
            group_type=selected.group_type,
            users=list(selected.account_keys),
            targets=list(selected.targets),
        )
    )
    scheduler._run_check_unlocked = AsyncMock(
        return_value=ScheduledCheckResult(
            reason="manual_command",
            group_id=group.group_id,
            group_name=group.name,
            group_type=group.group_type,
            users=list(group.account_keys),
            targets=list(group.targets),
        )
    )
    return scheduler, group


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

    # 首次槽位现在由独立 startup 检查负责，普通槽位初始化不立即触发。
    assert scheduler._scheduled_reasons(group, _at(14, 0)) == []
    assert scheduler._scheduled_reasons(group, _at(14, 1)) == []

    scheduler._consume_schedule_slots(group, "interval:30m")
    assert scheduler._last_interval_slots[group.group_id] is not None


def test_startup_checks_cover_daily_interval_and_unscheduled_groups_serially():
    scheduler = _scheduler()
    groups = [
        _startup_group("daily", "tag", daily_times=[(9, 0)]),
        _startup_group("interval", "blogger", interval=True),
        _startup_group("manual", "list"),
    ]
    scheduler._schedule_groups = lambda **_kwargs: groups
    calls = []

    async def fake_run_check(*, reason, group_name, **_kwargs):
        calls.append((reason, group_name))

    scheduler.run_check = fake_run_check
    asyncio.run(scheduler._run_startup_checks(_at(14, 0)))

    assert calls == [
        ("startup", "daily"),
        ("startup", "interval"),
        ("startup", "manual"),
    ]
    for group in groups:
        assert scheduler._scheduled_reasons(group, _at(14, 0)) == []


def test_startup_check_skips_incomplete_group_and_seeds_slots():
    scheduler = _scheduler()
    group = _startup_group(
        "incomplete",
        "list",
        interval=True,
        sources=[],
    )
    scheduler._schedule_groups = lambda **_kwargs: [group]
    calls = []

    async def fake_run_check(*, reason, group_name, **_kwargs):
        calls.append((reason, group_name))

    scheduler.run_check = fake_run_check
    asyncio.run(scheduler._run_startup_checks(_at(14, 0)))

    assert calls == []
    assert scheduler._scheduled_reasons(group, _at(14, 0)) == []


def test_startup_check_disabled_only_seeds_slots():
    scheduler = _scheduler()
    group = _startup_group("disabled", "blogger", interval=True)
    group.check_on_startup = False
    scheduler._schedule_groups = lambda **_kwargs: [group]
    scheduler.run_check = AsyncMock()

    asyncio.run(scheduler._run_startup_checks(_at(14, 0)))

    scheduler.run_check.assert_not_awaited()
    assert scheduler._scheduled_reasons(group, _at(14, 0)) == []


def test_storage_initialization_is_shared_by_concurrent_waiters():
    async def scenario():
        scheduler, _group = _storage_gate_scheduler()
        entered = asyncio.Event()
        release = asyncio.Event()

        async def migrate(_groups):
            entered.set()
            await release.wait()

        scheduler.storage.migrate_and_sync.side_effect = migrate
        first = asyncio.create_task(scheduler._ensure_storage_ready())
        await entered.wait()
        second = asyncio.create_task(scheduler._ensure_storage_ready())
        await asyncio.sleep(0)
        assert not second.done()
        release.set()

        assert await asyncio.gather(first, second) == [True, True]
        scheduler.storage.migrate_and_sync.assert_awaited_once()

    asyncio.run(scenario())


def test_manual_check_waits_for_shared_storage_initialization():
    async def scenario():
        scheduler, group = _storage_gate_scheduler()
        entered = asyncio.Event()
        release = asyncio.Event()

        async def migrate(_groups):
            entered.set()
            await release.wait()

        scheduler.storage.migrate_and_sync.side_effect = migrate
        initializer = asyncio.create_task(scheduler._ensure_storage_ready())
        await entered.wait()
        manual = asyncio.create_task(
            scheduler.run_check(reason="manual_command", group_name=group.group_id)
        )
        await asyncio.sleep(0)
        assert not manual.done()
        release.set()

        assert await initializer is True
        result = await manual
        assert result.skipped_reason == ""
        scheduler.storage.migrate_and_sync.assert_awaited_once()
        scheduler._run_check_unlocked.assert_awaited_once()

    asyncio.run(scenario())


def test_storage_initialization_failure_skips_fetch_and_send():
    async def scenario():
        scheduler, group = _storage_gate_scheduler()
        scheduler.storage.migrate_and_sync.side_effect = RuntimeError("db unavailable")

        result = await scheduler.run_check(
            reason="manual_command",
            group_name=group.group_id,
        )

        assert result.skipped_reason == "storage_not_ready"
        assert "存储" in result.format_message()
        scheduler._run_check_unlocked.assert_not_awaited()

    asyncio.run(scenario())


def test_startup_check_waits_for_existing_manual_check_lock():
    async def scenario():
        scheduler, group = _storage_gate_scheduler()
        scheduler._migration_done = True
        scheduler._storage_ready.set()
        await scheduler._check_lock.acquire()
        startup = asyncio.create_task(
            scheduler.run_check(reason="startup", group_name=group.group_id)
        )
        await asyncio.sleep(0)
        assert not startup.done()
        scheduler._check_lock.release()

        result = await startup
        assert result.skipped_reason == ""
        scheduler._run_check_unlocked.assert_awaited_once()

    asyncio.run(scenario())
