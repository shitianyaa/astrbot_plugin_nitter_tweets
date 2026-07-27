"""调度状态汇总与日志/消息格式化。

`NitterTweetScheduler` 的 mixin：只通过 `self` 协作，不 import 宿主类。
"""

from __future__ import annotations

import asyncio

from astrbot.api import logger

try:
    from ..config import config_get, config_set
    from ..shared.group_ids import (
        GLOBAL_GROUP_ID,
        is_default_group,
        normalize_group_id,
    )
    from .config import ScheduleGroup, WatchUsersInfo
    from .formatting import (
        _format_limited_values as scheduler_format_limited_values,
        format_group_schedule as scheduler_format_group_schedule,
        format_merge_threshold as scheduler_format_merge_threshold,
    )
    from .models import ScheduledCheckResult
except ImportError:
    from config import config_get, config_set
    from shared.group_ids import GLOBAL_GROUP_ID, is_default_group, normalize_group_id
    from scheduler.config import ScheduleGroup, WatchUsersInfo
    from scheduler.formatting import (
        _format_limited_values as scheduler_format_limited_values,
        format_group_schedule as scheduler_format_group_schedule,
        format_merge_threshold as scheduler_format_merge_threshold,
    )
    from scheduler.models import ScheduledCheckResult


class SchedulerStatusMixin:
    """/推文状态 汇总与展示格式化。"""

    async def status_summary(self) -> str:
        groups = self._schedule_groups(log_invalid_targets=False)
        default_group = next(
            (item for item in groups if is_default_group(item.group_id)),
            None,
        )
        if not groups:
            return "Nitter 定时检查状态\n没有可用分组。"

        enabled_groups = [item for item in groups if item.enabled]
        total_users = sum(len(item.account_keys) for item in groups)
        total_raw_users = sum(
            (
                item.queries_info.raw_count
                if item.is_tag_group
                else item.users_info.raw_count
            )
            for item in groups
        )
        total_duplicates = sum(
            len(
                item.queries_info.duplicates
                if item.is_tag_group
                else item.users_info.duplicates
            )
            for item in groups
        )
        total_invalid_users = sum(
            len(
                item.queries_info.invalid_entries
                if item.is_tag_group
                else item.users_info.invalid_entries
            )
            for item in groups
        )
        total_targets = sum(len(item.targets) for item in groups)
        total_invalid_targets = sum(len(item.invalid_targets) for item in groups)
        seen_map_results = await asyncio.gather(
            *[self._get_seen_map(item.group_id) for item in groups]
        )
        group_seen_counts = {
            item.group_id: len(seen_map)
            for item, seen_map in zip(groups, seen_map_results)
        }
        total_seen_users = sum(group_seen_counts.values())

        lines = [
            "Nitter 定时检查状态",
            f"调度器: {'运行中' if self.is_running else '未运行'}",
            f"总开关: {'已启用' if self.schedule_enabled else '已关闭'}",
            "全局检查间隔: "
            f"{config_get(self.config, 'check_interval_minutes', 30)} 分钟",
            "启动立即检查: "
            f"{'已启用' if config_get(self.config, 'check_on_startup', False) else '已关闭'}",
            "无更新提示: "
            f"{'已启用' if config_get(self.config, 'notify_no_updates', False) else '已关闭'}",
            f"分组数量: {len(groups)} 个（启用 {len(enabled_groups)} 个）",
            f"QQ 合并阈值: {self._format_merge_threshold(self._merge_tweet_threshold())}",
            "全部分组订阅账号项: "
            f"{total_users} 个（配置 {total_raw_users} 项，"
            f"重复 {total_duplicates} 项，无效 {total_invalid_users} 项）",
            f"全部分组推送目标项: {total_targets} 个（无效 {total_invalid_targets} 个）",
            f"全部分组已记录索引: {total_seen_users} 个",
        ]
        if default_group is not None:
            lines.append("默认分组详情:")
            self._append_group_status(
                lines,
                default_group,
                seen_count=group_seen_counts.get(default_group.group_id, 0),
            )
        if len(groups) > (1 if default_group is not None else 0):
            lines.append("其他分组详情:")
            for item in groups:
                if (
                    default_group is not None
                    and item.group_id == default_group.group_id
                ):
                    continue
                self._append_group_status(
                    lines,
                    item,
                    seen_count=group_seen_counts.get(item.group_id, 0),
                )
        return "\n".join(lines)

    def deduplicate_watch_users(self) -> WatchUsersInfo:
        info = self._watch_users_info()
        if not info.changed:
            return info

        groups = config_get(self.config, "tweet_groups", []) or []
        if isinstance(groups, dict):
            groups = [groups]
        elif not isinstance(groups, list):
            groups = []
        for group in groups:
            if not isinstance(group, dict):
                continue
            if (
                normalize_group_id(group.get("group_id") or group.get("name") or "")
                == GLOBAL_GROUP_ID
            ):
                group["watch_users"] = info.users
                config_set(self.config, "tweet_groups", groups)
                break
        else:
            info.save_error = "未找到默认分组配置"
            return info

        save_config = getattr(self.config, "save_config", None)
        if not callable(save_config):
            info.save_error = "当前配置对象不支持 save_config()"
            return info

        try:
            save_config()
            info.saved = True
        except Exception as exc:
            info.save_error = str(exc)
            logger.warning(f"[NitterTweets] 保存去重后的关注账号失败: {exc}")
        return info

    def watch_users_info(self) -> WatchUsersInfo:
        return self._watch_users_info()

    def _should_notify_no_updates(
        self,
        result: ScheduledCheckResult,
        notify_no_updates: bool | None,
        group: ScheduleGroup,
    ) -> bool:
        if notify_no_updates is None:
            notify_no_updates = group.notify_no_updates
        return bool(notify_no_updates and result.has_visible_no_update())

    @staticmethod
    def _format_merge_threshold(threshold: int) -> str:
        return scheduler_format_merge_threshold(threshold)

    @staticmethod
    def _format_group_schedule(group: ScheduleGroup) -> str:
        return scheduler_format_group_schedule(group)

    def _append_group_status(
        self,
        lines: list[str],
        group: ScheduleGroup,
        seen_count: int | None = None,
    ) -> None:
        type_label = "标签" if group.is_tag_group else "博主"
        account_count = len(group.account_keys)
        lines.append(
            "- "
            f"{group.name} ({group.group_id}): "
            f"{'启用' if group.enabled else '关闭'}，"
            f"类型 {type_label}，"
            f"订阅 {account_count}，目标 {len(group.targets)}，"
            f"{self._format_group_schedule(group)}"
        )
        if group.aliases:
            lines.append("  别名: " + self._format_limited_values(group.aliases))
        if group.is_tag_group:
            lines.append(
                "  搜索订阅: "
                f"{len(group.queries)} 个（配置 {group.queries_info.raw_count} 项，"
                f"重复 {len(group.queries_info.duplicates)} 项，"
                f"无效 {len(group.queries_info.invalid_entries)} 项）"
            )
        else:
            lines.append(
                "  关注账号: "
                f"{len(group.users)} 个（配置 {group.users_info.raw_count} 项，"
                f"重复 {len(group.users_info.duplicates)} 项，"
                f"无效 {len(group.users_info.invalid_entries)} 项）"
            )
        lines.append(
            f"  推送目标: {len(group.targets)} 个"
            f"（无效 {len(group.invalid_targets)} 个）"
        )
        if seen_count is not None:
            lines.append(f"  已记录索引: {seen_count} 个")
        daily_times = group.daily_check_times
        if daily_times:
            formatted_times = ", ".join(
                f"{hour:02d}:{minute:02d}" for hour, minute in daily_times
            )
            lines.append(f"  每日时间: {formatted_times}")
        if group.is_tag_group and group.queries:
            labels = [f"{item.query} ({item.type})" for item in group.queries]
            lines.append("  订阅查询: " + self._format_limited_values(labels))
            if group.queries_info.duplicates:
                lines.append(
                    "  重复查询: "
                    + self._format_limited_values(group.queries_info.duplicates)
                )
            if group.queries_info.invalid_entries:
                lines.append(
                    "  无效查询: "
                    + self._format_limited_values(group.queries_info.invalid_entries)
                )
        elif group.users:
            usernames = [f"@{username}" for username in group.users]
            lines.append("  订阅账号: " + self._format_limited_values(usernames))
            if group.users_info.duplicates:
                lines.append(
                    "  重复订阅: "
                    + self._format_limited_values(group.users_info.duplicates)
                )
            if group.users_info.invalid_entries:
                lines.append(
                    "  无效订阅: "
                    + self._format_limited_values(group.users_info.invalid_entries)
                )
        if group.targets:
            lines.append("  推送目标:")
            for umo in group.targets[:8]:
                lines.append(f"  - {umo}")
            if len(group.targets) > 8:
                lines.append(f"  - ... 还有 {len(group.targets) - 8} 个")
        if group.invalid_targets:
            lines.append(
                "  无效目标: " + self._format_limited_values(group.invalid_targets)
            )

    @staticmethod
    def _format_limited_values(values: list[str], limit: int = 10) -> str:
        return scheduler_format_limited_values(values, limit=limit)
