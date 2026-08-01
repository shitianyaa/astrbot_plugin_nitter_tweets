"""概览面板与分组序列化。

`NitterWebAPI` 的 mixin：只通过 `self` 协作，不 import 宿主类。
"""

from __future__ import annotations

from typing import Any

try:
    from ..config import (
        config_get,
        media_only_unavailable_reason,
        parse_config_bool,
        resolve_send_image_attachments,
        resolve_send_video_attachments,
    )
    from ..scheduler import ScheduleGroup
    from ..shared import format_subscription_count
except ImportError:
    from config import (
        config_get,
        media_only_unavailable_reason,
        parse_config_bool,
        resolve_send_image_attachments,
        resolve_send_video_attachments,
    )
    from scheduler import ScheduleGroup
    from shared import format_subscription_count


class WebAPIOverviewMixin:
    """overview / groups 数据组装。"""

    async def build_overview(self) -> dict[str, Any]:
        groups = self._schedule_groups()

        blogger_groups = [group for group in groups if group.is_blogger_group]
        tag_groups = [group for group in groups if group.is_tag_group]
        list_groups = [group for group in groups if group.is_list_group]
        total_raw_users = sum(group.users_info.raw_count for group in blogger_groups)
        total_duplicate_users = sum(
            len(group.users_info.duplicates) for group in blogger_groups
        )
        total_invalid_users = sum(
            len(group.users_info.invalid_entries) for group in blogger_groups
        )
        total_raw_queries = sum(group.queries_info.raw_count for group in tag_groups)
        total_duplicate_queries = sum(
            len(group.queries_info.duplicates) for group in tag_groups
        )
        total_invalid_queries = sum(
            len(group.queries_info.invalid_entries) for group in tag_groups
        )
        total_raw_lists = sum(group.lists_info.raw_count for group in list_groups)
        total_duplicate_lists = sum(
            len(group.lists_info.duplicates) for group in list_groups
        )
        total_invalid_lists = sum(
            len(group.lists_info.invalid_entries) for group in list_groups
        )
        total_raw_lists = sum(group.lists_info.raw_count for group in groups)
        total_duplicate_lists = sum(
            len(group.lists_info.duplicates) for group in groups
        )
        total_invalid_lists = sum(
            len(group.lists_info.invalid_entries) for group in groups
        )
        counts = {
            "groups": len(groups),
            "enabled_groups": sum(1 for group in groups if group.enabled),
            "watch_users": sum(len(group.users) for group in blogger_groups),
            "raw_watch_users": total_raw_users,
            "duplicate_watch_users": total_duplicate_users,
            "invalid_watch_users": total_invalid_users,
            "watch_queries": sum(len(group.queries) for group in tag_groups),
            "raw_watch_queries": total_raw_queries,
            "duplicate_watch_queries": total_duplicate_queries,
            "invalid_watch_queries": total_invalid_queries,
            "watch_lists": sum(len(group.list_ids) for group in list_groups),
            "raw_watch_lists": total_raw_lists,
            "duplicate_watch_lists": total_duplicate_lists,
            "invalid_watch_lists": total_invalid_lists,
            "push_targets": sum(len(group.targets) for group in groups),
            "invalid_push_targets": sum(len(group.invalid_targets) for group in groups),
        }
        scheduler_state = {
            "running": bool(getattr(self.scheduler, "is_running", False)),
            "schedule_enabled": bool(
                getattr(self.scheduler, "schedule_enabled", False)
            ),
        }
        features = {
            "images": resolve_send_image_attachments(self.config),
            "videos": resolve_send_video_attachments(self.config),
            "translation": parse_config_bool(
                config_get(self.config, "translate_enabled", False), False
            ),
        }
        instance_lists = self._configured_instance_lists()
        instances = list(instance_lists["rss"])
        return self._ok(
            scheduler=scheduler_state,
            counts=counts,
            features=features,
            config_summary=self._config_summary(instances, groups, instance_lists),
            instances=instances,
            instance_lists=instance_lists,
            attention_items=self._overview_attention_items(
                counts, scheduler_state, instances, groups
            ),
            terminology=self._terminology(),
        )

    async def build_groups(self) -> dict[str, Any]:
        groups = self._schedule_groups()
        return self._ok(
            groups=[self._serialize_group(group) for group in groups],
            terminology=self._terminology(),
        )

    @staticmethod
    def _overview_attention_items(
        counts: dict[str, int],
        scheduler_state: dict[str, bool],
        instances: list[str],
        groups: list[ScheduleGroup] | None = None,
    ) -> list[dict[str, str]]:
        items: list[dict[str, str]] = []
        if not scheduler_state.get("running", False):
            items.append(
                {
                    "key": "scheduler_not_running",
                    "level": "warning",
                    "title": "调度器未运行",
                    "detail": "后台检查不会自动执行。",
                }
            )
        if not scheduler_state.get("schedule_enabled", False):
            items.append(
                {
                    "key": "schedule_disabled",
                    "level": "warning",
                    "title": "后台检查总开关关闭",
                    "detail": "定时检查不会自动触发。",
                }
            )
        if not instances:
            items.append(
                {
                    "key": "no_instances",
                    "level": "warning",
                    "title": "未配置 Nitter 实例",
                    "detail": "手动查询、镜像测试和后台检查都需要可用实例。",
                }
            )
        if int(counts.get("groups", 0)) <= 0:
            items.append(
                {
                    "key": "no_groups",
                    "level": "info",
                    "title": "没有推送分组",
                    "detail": "订阅源和推送目标需要先在 AstrBot 设置页或插件面板配置。",
                }
            )
        elif int(counts.get("enabled_groups", 0)) <= 0:
            items.append(
                {
                    "key": "no_enabled_groups",
                    "level": "warning",
                    "title": "没有启用的推送分组",
                    "detail": "后台检查不会处理已停用分组。",
                }
            )
        if int(counts.get("invalid_push_targets", 0)) > 0:
            items.append(
                {
                    "key": "invalid_push_targets",
                    "level": "warning",
                    "title": "存在无效推送目标",
                    "detail": f"{counts['invalid_push_targets']} 个推送目标未通过 UMO 校验。",
                }
            )
        if int(counts.get("invalid_watch_users", 0)) > 0:
            items.append(
                {
                    "key": "invalid_watch_users",
                    "level": "warning",
                    "title": "存在无效关注账号",
                    "detail": f"{counts['invalid_watch_users']} 个关注账号格式无效。",
                }
            )
        if int(counts.get("invalid_watch_queries", 0)) > 0:
            items.append(
                {
                    "key": "invalid_watch_queries",
                    "level": "warning",
                    "title": "存在无效搜索订阅",
                    "detail": f"{counts['invalid_watch_queries']} 个搜索订阅格式无效。",
                }
            )
        if int(counts.get("invalid_watch_lists", 0)) > 0:
            items.append(
                {
                    "key": "invalid_watch_lists",
                    "level": "warning",
                    "title": "存在无效 List ID",
                    "detail": f"{counts['invalid_watch_lists']} 个 List ID 格式无效。",
                }
            )
        if groups:
            items.extend(WebAPIOverviewMixin._overview_group_diagnostics(groups))

        if not items:
            items.append(
                {
                    "key": "ok",
                    "level": "ok",
                    "title": "当前没有需要处理的提示",
                    "detail": "关键状态未发现异常。",
                }
            )
        return items

    @staticmethod
    def _overview_group_diagnostics(
        groups: list[ScheduleGroup],
    ) -> list[dict[str, str]]:
        enabled_groups = [group for group in groups if group.enabled]
        if not enabled_groups:
            return []

        items: list[dict[str, str]] = []
        no_watch_users = [
            group
            for group in enabled_groups
            if group.is_blogger_group and not group.users
        ]
        no_watch_queries = [
            group
            for group in enabled_groups
            if group.is_tag_group and not group.queries
        ]
        no_watch_lists = [
            group
            for group in enabled_groups
            if group.is_list_group and not group.list_ids
        ]
        no_push_targets = [group for group in enabled_groups if not group.targets]
        no_check_triggers = [
            group
            for group in enabled_groups
            if not group.interval_check_enabled and not group.daily_check_enabled
        ]

        if no_watch_users:
            items.append(
                {
                    "key": "groups_without_watch_users",
                    "level": "warning",
                    "title": "启用博主分组没有关注账号",
                    "detail": (
                        "这些分组不会检查任何账号："
                        + WebAPIOverviewMixin._format_group_names(no_watch_users)
                    ),
                }
            )
        if no_watch_queries:
            items.append(
                {
                    "key": "groups_without_watch_queries",
                    "level": "warning",
                    "title": "启用标签分组没有搜索订阅",
                    "detail": (
                        "这些分组不会检查任何查询："
                        + WebAPIOverviewMixin._format_group_names(no_watch_queries)
                    ),
                }
            )
        if no_watch_lists:
            items.append(
                {
                    "key": "groups_without_watch_lists",
                    "level": "warning",
                    "title": "启用 List 分组没有 List ID",
                    "detail": (
                        "这些分组不会检查任何 List："
                        + WebAPIOverviewMixin._format_group_names(no_watch_lists)
                    ),
                }
            )
        invalid_queries = [
            group
            for group in enabled_groups
            if group.is_tag_group and group.queries_info.invalid_entries
        ]
        invalid_lists = [
            group
            for group in enabled_groups
            if group.is_list_group and group.lists_info.invalid_entries
        ]
        if invalid_queries:
            items.append(
                {
                    "key": "groups_with_invalid_watch_queries",
                    "level": "warning",
                    "title": "启用搜索分组存在无效订阅",
                    "detail": "这些分组包含无效搜索订阅："
                    + WebAPIOverviewMixin._format_group_names(invalid_queries),
                }
            )
        if invalid_lists:
            items.append(
                {
                    "key": "groups_with_invalid_watch_lists",
                    "level": "warning",
                    "title": "启用 List 分组存在无效 ID",
                    "detail": "这些分组包含无效 List ID："
                    + WebAPIOverviewMixin._format_group_names(invalid_lists),
                }
            )
        if no_push_targets:
            items.append(
                {
                    "key": "groups_without_push_targets",
                    "level": "warning",
                    "title": "启用分组没有推送目标",
                    "detail": (
                        "新推文无法送达这些分组："
                        + WebAPIOverviewMixin._format_group_names(no_push_targets)
                    ),
                }
            )
        if no_check_triggers:
            items.append(
                {
                    "key": "groups_without_check_triggers",
                    "level": "warning",
                    "title": "启用分组没有周期检查",
                    "detail": (
                        "这些分组既没有间隔检查也没有每日检查；"
                        "开启启动首检时只会在启动后检查一次："
                        + WebAPIOverviewMixin._format_group_names(no_check_triggers)
                    ),
                }
            )
        return items

    @staticmethod
    def _format_group_names(groups: list[ScheduleGroup], limit: int = 4) -> str:
        names = [str(group.name or group.group_id) for group in groups]
        visible = names[:limit]
        suffix = f" 等 {len(names)} 个" if len(names) > limit else ""
        return "、".join(visible) + suffix

    def _serialize_group(
        self,
        group: ScheduleGroup,
    ) -> dict[str, Any]:
        global_filter_reposts_enabled = parse_config_bool(
            config_get(self.config, "filter_reposts_enabled", True),
            True,
        )
        group_filter_reposts_enabled = bool(
            getattr(group, "filter_reposts_enabled", True)
        )
        return {
            "group_id": group.group_id,
            "name": group.name,
            "enabled": group.enabled,
            "group_type": group.group_type,
            "aliases": list(group.aliases),
            "watch_users": list(group.users),
            "watch_user_count": len(group.users),
            "raw_watch_user_count": group.users_info.raw_count,
            "duplicate_watch_users": list(group.users_info.duplicates),
            "invalid_watch_users": list(group.users_info.invalid_entries),
            "watch_queries": [
                {"query": item.query, "type": item.type} for item in group.queries
            ],
            "watch_query_count": len(group.queries),
            "raw_watch_query_count": group.queries_info.raw_count,
            "duplicate_watch_queries": list(group.queries_info.duplicates),
            "invalid_watch_queries": list(group.queries_info.invalid_entries),
            "watch_lists": list(group.list_ids),
            "watch_list_count": len(group.list_ids),
            "raw_watch_list_count": group.lists_info.raw_count,
            "duplicate_watch_lists": list(group.lists_info.duplicates),
            "invalid_watch_lists": list(group.lists_info.invalid_entries),
            "subscription_label": self._subscription_label(group),
            "push_targets": list(group.targets),
            "push_target_count": len(group.targets),
            "invalid_push_targets": list(group.invalid_targets),
            "invalid_push_target_count": len(group.invalid_targets),
            "interval_check_enabled": group.interval_check_enabled,
            "check_interval_minutes": group.check_interval_minutes,
            "daily_check_enabled": group.daily_check_enabled,
            "daily_check_times": self._format_times(group.daily_check_times),
            "filter_reposts_enabled": group_filter_reposts_enabled,
            "global_filter_reposts_enabled": global_filter_reposts_enabled,
            "effective_filter_reposts_enabled": (
                global_filter_reposts_enabled and group_filter_reposts_enabled
            ),
            "filter_plain_text_enabled": group.filter_plain_text_enabled,
            "media_only_enabled": group.media_only_enabled,
            "omit_status_url": bool(getattr(group, "omit_status_url", True)),
            "hide_original_when_translated": bool(
                getattr(group, "hide_original_when_translated", False)
            ),
            "media_only_effective": self._media_only_effective(group),
            # Global media availability only; independent of saved group toggle
            # so the dashboard draft can warn before save.
            "media_only_unavailable_reason": media_only_unavailable_reason(self.config),
            "attention_items": self._group_attention_items(group),
        }

    def _media_only_effective(self, group: ScheduleGroup) -> bool:
        return bool(
            group.media_only_enabled and not media_only_unavailable_reason(self.config)
        )

    @staticmethod
    def _group_attention_items(
        group: ScheduleGroup,
    ) -> list[dict[str, str]]:
        items: list[dict[str, str]] = []
        if not group.enabled:
            items.append(
                {
                    "key": "group_disabled",
                    "level": "info",
                    "title": "分组停用",
                    "detail": "停用分组不会参与后台检查。",
                }
            )
        if group.is_tag_group:
            if not group.queries:
                items.append(
                    {
                        "key": "no_watch_queries",
                        "level": "warning",
                        "title": "无搜索订阅",
                        "detail": "该标签分组没有可检查的搜索订阅。",
                    }
                )
        elif group.is_list_group:
            if not group.list_ids:
                items.append(
                    {
                        "key": "no_watch_lists",
                        "level": "warning",
                        "title": "无 List 订阅",
                        "detail": "该 List 分组没有可检查的 List ID。",
                    }
                )
        elif not group.users:
            items.append(
                {
                    "key": "no_watch_users",
                    "level": "warning",
                    "title": "无关注账号",
                    "detail": "该分组没有可检查的关注账号。",
                }
            )
        if not group.targets:
            items.append(
                {
                    "key": "no_push_targets",
                    "level": "warning",
                    "title": "无推送目标",
                    "detail": "新推文没有可发送的推送目标。",
                }
            )
        if group.is_tag_group and group.queries_info.invalid_entries:
            items.append(
                {
                    "key": "invalid_watch_queries",
                    "level": "warning",
                    "title": "搜索订阅无效",
                    "detail": f"{len(group.queries_info.invalid_entries)} 个搜索订阅格式无效。",
                }
            )
        elif group.is_list_group and group.lists_info.invalid_entries:
            items.append(
                {
                    "key": "invalid_watch_lists",
                    "level": "warning",
                    "title": "List ID 无效",
                    "detail": f"{len(group.lists_info.invalid_entries)} 个 List ID 格式无效。",
                }
            )
        elif group.users_info.invalid_entries:
            items.append(
                {
                    "key": "invalid_watch_users",
                    "level": "warning",
                    "title": "关注账号无效",
                    "detail": f"{len(group.users_info.invalid_entries)} 个关注账号格式无效。",
                }
            )
        if group.invalid_targets:
            items.append(
                {
                    "key": "invalid_push_targets",
                    "level": "warning",
                    "title": "推送目标无效",
                    "detail": f"{len(group.invalid_targets)} 个推送目标未通过 UMO 校验。",
                }
            )
        return items

    @staticmethod
    def _subscription_label(group: ScheduleGroup) -> str:
        return format_subscription_count(len(group.account_keys), group.group_type)
