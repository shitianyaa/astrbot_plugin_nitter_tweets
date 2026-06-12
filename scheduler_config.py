from __future__ import annotations


try:
    from .group_config import (
        GroupConfig,
        PushTargetParseResult,
        WatchUsersInfo,
        build_all_groups,
        build_default_group,
        normalize_group_id,
    )
except ImportError:
    from group_config import (
        GroupConfig,
        PushTargetParseResult,
        WatchUsersInfo,
        build_all_groups,
        build_default_group,
        normalize_group_id,
    )


class SchedulerConfigReader:
    def __init__(self, config, context):
        self.config = config
        self.context = context

    def default_group(self, log_invalid_targets: bool = True) -> GroupConfig:
        return build_default_group(
            self.config,
            context=self.context,
            log_invalid_targets=log_invalid_targets,
        )

    def schedule_groups(self, log_invalid_targets: bool = True) -> list[GroupConfig]:
        return build_all_groups(
            self.config,
            context=self.context,
            log_invalid_targets=log_invalid_targets,
        )

    def schedule_group(
        self, group_name: str = "", log_invalid_targets: bool = True
    ) -> GroupConfig | None:
        normalized = normalize_group_id(group_name)
        for group in self.schedule_groups(log_invalid_targets=log_invalid_targets):
            identifiers = {
                normalize_group_id(group.group_id),
                normalize_group_id(group.name),
                *(normalize_group_id(alias) for alias in group.aliases),
            }
            if normalized in identifiers:
                return group
        return None

    def watch_users(self) -> list[str]:
        return self.default_group().users

    def watch_users_info(self) -> WatchUsersInfo:
        return self.default_group().watch_users_info

    def push_targets(self) -> list[str]:
        return self.default_group().targets

    def platform(self) -> str:
        from .group_config import _detect_platform
        return _detect_platform(self.context)

    def parse_push_targets(self, log_invalid: bool = True) -> PushTargetParseResult:
        dg = self.default_group(log_invalid_targets=log_invalid)
        return dg.push_targets_info

    def parse_daily_times(self) -> list[tuple[int, int]]:
        return self.default_group().daily_check_times
