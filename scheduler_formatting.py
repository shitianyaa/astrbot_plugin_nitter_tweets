from __future__ import annotations

import datetime as dt
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:
    CN_TZ = ZoneInfo("Asia/Shanghai")
except ZoneInfoNotFoundError:
    CN_TZ = dt.timezone(dt.timedelta(hours=8), name="Asia/Shanghai")



def _format_limited_values(
    values: list[str],
    limit: int = 10,
    separator: str = ", ",
) -> str:
    shown = [str(item) for item in values[:limit]]
    if len(values) > limit:
        shown.append(f"... 还有 {len(values) - limit} 个")
    return separator.join(shown)


def format_merge_threshold(threshold: int) -> str:
    if threshold <= 0:
        return "已关闭"
    return f"{threshold} 条及以上"

def format_group_schedule(group: Any) -> str:
    parts = []
    if group.interval_check_enabled:
        parts.append(f"间隔 {group.check_interval_minutes} 分钟")
    if group.daily_check_enabled:
        if group.daily_check_times:
            times = ", ".join(
                f"{hour:02d}:{minute:02d}"
                for hour, minute in group.daily_check_times
            )
            parts.append(f"每日 {times}")
        else:
            parts.append("每日定点未配置时间")
    return " / ".join(parts) if parts else "未配置定时规则"

def format_pending_user_counts(user_counts: list[tuple[str, int]]) -> str:
    values = [
        f"@{username} {count} 条"
        for username, count in user_counts
    ]
    return _format_limited_values(values, separator="; ")

def format_daily_times(times: list[tuple[int, int]]) -> str:
    if not times:
        return "未配置"
    return ", ".join(f"{hour:02d}:{minute:02d}" for hour, minute in times)

def format_next_daily_time(times: list[tuple[int, int]]) -> str:
    if not times:
        return "未配置"
    now = dt.datetime.now(CN_TZ)
    candidates = []
    for hour, minute in times:
        candidate = now.replace(
            hour=hour,
            minute=minute,
            second=0,
            microsecond=0,
        )
        if candidate <= now:
            candidate += dt.timedelta(days=1)
        candidates.append(candidate)
    next_time = min(candidates)
    if next_time.date() == now.date():
        prefix = "今天"
    elif next_time.date() == (now + dt.timedelta(days=1)).date():
        prefix = "明天"
    else:
        prefix = next_time.strftime("%Y-%m-%d")
    return f"{prefix} {next_time:%H:%M}"

def format_timestamp(timestamp: int) -> str:
    return dt.datetime.fromtimestamp(timestamp, CN_TZ).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
