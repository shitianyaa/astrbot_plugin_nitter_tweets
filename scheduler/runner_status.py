"""调度状态汇总与日志/消息格式化。

`NitterTweetScheduler` 的 mixin：只通过 `self` 协作，不 import 宿主类。
"""

from __future__ import annotations

from astrbot.api import logger

try:
    from ..config import config_get, config_set, parse_config_bool
    from ..shared import format_subscription_count, format_subscription_source
    from ..shared.group_ids import (
        GLOBAL_GROUP_ID,
        is_default_group,
        normalize_group_id,
    )
    from .config import ScheduleGroup, WatchUsersInfo
    from .formatting import (
        _format_limited_values as scheduler_format_limited_values,
    )
    from .formatting import (
        format_group_schedule as scheduler_format_group_schedule,
    )
    from .formatting import (
        format_merge_threshold as scheduler_format_merge_threshold,
    )
    from .models import ScheduledCheckResult
except ImportError:
    from config import config_get, config_set, parse_config_bool
    from scheduler.config import ScheduleGroup, WatchUsersInfo
    from scheduler.formatting import (
        _format_limited_values as scheduler_format_limited_values,
    )
    from scheduler.formatting import (
        format_group_schedule as scheduler_format_group_schedule,
    )
    from scheduler.formatting import (
        format_merge_threshold as scheduler_format_merge_threshold,
    )
    from scheduler.models import ScheduledCheckResult
    from shared import format_subscription_count, format_subscription_source
    from shared.group_ids import GLOBAL_GROUP_ID, is_default_group, normalize_group_id


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
            self._group_subscription_info(item).raw_count for item in groups
        )
        total_duplicates = sum(
            len(self._group_subscription_info(item).duplicates) for item in groups
        )
        total_invalid_users = sum(
            len(self._group_subscription_info(item).invalid_entries) for item in groups
        )
        total_targets = sum(len(item.targets) for item in groups)
        total_invalid_targets = sum(len(item.invalid_targets) for item in groups)
        config_reader = getattr(self, "config_reader", None)
        target_blacklist_info = (
            config_reader.parse_target_blocked_users()
            if config_reader is not None
            else None
        )
        target_blacklist_users = sum(
            len(users)
            for users in (
                target_blacklist_info.blocked_users.values()
                if target_blacklist_info
                else []
            )
        )
        global_filter_reposts_enabled = parse_config_bool(
            config_get(self.config, "filter_reposts_enabled", True),
            True,
        )
        lines = [
            "Nitter 定时检查状态",
            f"调度器: {'运行中' if self.is_running else '未运行'}",
            f"总开关: {'已启用' if self.schedule_enabled else '已关闭'}",
            (
                "全局检查间隔: "
                f"{config_get(self.config, 'check_interval_minutes', 30)} 分钟"
            ),
            (
                "启动立即检查: "
                f"{'已启用' if config_get(self.config, 'check_on_startup', False) else '已关闭'}"
            ),
            (
                "无更新提示: "
                f"{'已启用' if config_get(self.config, 'notify_no_updates', False) else '已关闭'}"
            ),
            (
                "转发过滤总开关: "
                f"{'已启用' if global_filter_reposts_enabled else '已关闭'}"
            ),
            f"分组数量: {len(groups)} 个（启用 {len(enabled_groups)} 个）",
            f"QQ 合并阈值: {self._format_merge_threshold(self._merge_tweet_threshold())}",
            (
                "全部分组订阅项: "
                f"{total_users} 个（配置 {total_raw_users} 项，"
                f"重复 {total_duplicates} 项，无效 {total_invalid_users} 项）"
            ),
            f"全部分组推送目标项: {total_targets} 个（无效 {total_invalid_targets} 个）",
            "目标作者黑名单: "
            f"{len(target_blacklist_info.blocked_users) if target_blacklist_info else 0} 个目标，"
            f"{target_blacklist_users} 个作者",
        ]
        if default_group is not None:
            lines.append("默认分组详情:")
            self._append_group_status(
                lines,
                default_group,
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

    @staticmethod
    def _group_subscription_info(group: ScheduleGroup):
        if group.is_tag_group:
            return group.queries_info
        if group.is_list_group:
            return group.lists_info
        return group.users_info

    def _append_group_status(
        self,
        lines: list[str],
        group: ScheduleGroup,
    ) -> None:
        type_label = (
            "标签" if group.is_tag_group else "列表" if group.is_list_group else "博主"
        )
        account_count = len(group.account_keys)
        lines.append(
            "- "
            f"{group.name} ({group.group_id}): "
            f"{'启用' if group.enabled else '关闭'}，"
            f"类型 {type_label}，"
            f"订阅 {format_subscription_count(account_count, group.group_type)}，"
            f"目标 {len(group.targets)}，"
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
        elif group.is_list_group:
            lines.append(
                "  List 订阅: "
                f"{len(group.list_ids)} 个（配置 {group.lists_info.raw_count} 项，"
                f"重复 {len(group.lists_info.duplicates)} 项，"
                f"无效 {len(group.lists_info.invalid_entries)} 项）"
            )
        else:
            lines.append(
                "  博主订阅: "
                f"{len(group.users)} 个（配置 {group.users_info.raw_count} 项，"
                f"重复 {len(group.users_info.duplicates)} 项，"
                f"无效 {len(group.users_info.invalid_entries)} 项）"
            )
        lines.append(
            f"  推送目标: {len(group.targets)} 个"
            f"（无效 {len(group.invalid_targets)} 个）"
        )
        global_filter_reposts_enabled = parse_config_bool(
            config_get(getattr(self, "config", {}), "filter_reposts_enabled", True),
            True,
        )
        group_filter_reposts_enabled = bool(
            getattr(group, "filter_reposts_enabled", True)
        )
        effective_filter_reposts_enabled = (
            global_filter_reposts_enabled and group_filter_reposts_enabled
        )
        lines.append(
            "  转发过滤: "
            f"{'开启' if effective_filter_reposts_enabled else '关闭'}"
            f"（全局 {'开' if global_filter_reposts_enabled else '关'}，"
            f"分组 {'开' if group_filter_reposts_enabled else '关'}）"
        )
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
        elif group.is_list_group and group.list_ids:
            lines.append("  List ID: " + self._format_limited_values(group.list_ids))
            if group.lists_info.duplicates:
                lines.append(
                    "  重复 List ID: "
                    + self._format_limited_values(group.lists_info.duplicates)
                )
            if group.lists_info.invalid_entries:
                lines.append(
                    "  无效 List ID: "
                    + self._format_limited_values(group.lists_info.invalid_entries)
                )
        elif group.users:
            usernames = [
                format_subscription_source(username, group.group_type)
                for username in group.users
            ]
            lines.append("  博主订阅源: " + self._format_limited_values(usernames))
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
