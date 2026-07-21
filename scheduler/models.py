from __future__ import annotations

from dataclasses import dataclass, field

try:
    from ..shared.group_ids import DEFAULT_GROUP_NAME, GLOBAL_GROUP_ID
    from .formatting import _format_limited_values
except ImportError:
    from shared.group_ids import DEFAULT_GROUP_NAME, GLOBAL_GROUP_ID
    from scheduler.formatting import _format_limited_values


@dataclass(slots=True)
class ScheduledPushResult:
    username: str
    new_count: int
    success_targets: int
    total_targets: int
    batch_key: str = field(default="", repr=False, compare=False)


@dataclass(slots=True)
class PendingTweetBatch:
    username: str
    instance: str
    tweets: list
    fetched_ids: list[str]
    seen_ids: list[str]
    delivered_targets: set[str] = field(default_factory=set)
    account_index: int = 0
    account_total: int = 0
    tweet_index: int = 0
    tweet_total: int = 0


@dataclass(slots=True)
class BatchSummaryTracker:
    text: str = ""
    delivered_targets: set[str] = field(default_factory=set)

    def for_target(self, target: str) -> str:
        if not self.text or target in self.delivered_targets:
            return ""
        return self.text

    def mark_delivered(self, target: str) -> None:
        if self.text:
            self.delivered_targets.add(target)


@dataclass(slots=True)
class ScheduledCheckResult:
    reason: str
    group_id: str = GLOBAL_GROUP_ID
    group_name: str = DEFAULT_GROUP_NAME
    users: list[str] = field(default_factory=list)
    targets: list[str] = field(default_factory=list)
    invalid_targets: list[str] = field(default_factory=list)
    available_groups: list[str] = field(default_factory=list)
    seen_users: int = 0
    fetch_limit: int = 0
    skipped_reason: str = ""
    initialized_users: dict[str, int] = field(default_factory=dict)
    no_new_users: list[str] = field(default_factory=list)
    empty_users: list[str] = field(default_factory=list)
    failed_users: dict[str, str] = field(default_factory=dict)
    pushes: list[ScheduledPushResult] = field(default_factory=list)
    push_mode: str = "per_user"
    merge_tweet_threshold: int = 0
    merged_push_success_targets: int = 0
    merged_push_total_targets: int = 0
    delivery_warnings: list[str] = field(default_factory=list)
    plain_text_filtered: int = 0

    @property
    def new_tweet_count(self) -> int:
        return sum(push.new_count for push in self.pushes)

    @property
    def pushed_target_successes(self) -> int:
        per_user_successes = sum(push.success_targets for push in self.pushes)
        if self.push_mode == "merged":
            return self.merged_push_success_targets
        if self.push_mode == "mixed":
            return per_user_successes + self.merged_push_success_targets
        return per_user_successes

    @property
    def pushed_target_attempts(self) -> int:
        per_user_attempts = sum(push.total_targets for push in self.pushes)
        if self.push_mode == "merged":
            return self.merged_push_total_targets
        if self.push_mode == "mixed":
            return per_user_attempts + self.merged_push_total_targets
        return per_user_attempts

    @property
    def checked_user_count(self) -> int:
        return (
            len(self.initialized_users)
            + len(self.no_new_users)
            + len(self.empty_users)
            + len(self.failed_users)
            + len(self.pushes)
        )

    def has_visible_no_update(self) -> bool:
        return (
            not self.skipped_reason
            and self.targets
            and self.new_tweet_count == 0
            and (
                bool(self.initialized_users)
                or bool(self.no_new_users)
                or bool(self.empty_users)
                or bool(self.failed_users)
            )
        )

    def format_log_summary(self) -> str:
        if self.skipped_reason:
            return (
                "[NitterTweets] 定时检查已跳过: "
                f"group={self.group_id}, reason={self.skipped_reason}, "
                f"users={len(self.users)}, "
                f"targets={len(self.targets)}, invalid_targets={len(self.invalid_targets)}"
            )

        warning_part = (
            f", warnings={len(self.delivery_warnings)}"
            if self.delivery_warnings else ""
        )
        filtered_part = (
            f", filtered={self.plain_text_filtered}"
            if self.plain_text_filtered else ""
        )
        return (
            "[NitterTweets] 定时检查完成: "
            f"group={self.group_id}, reason={self.reason}, "
            f"users={len(self.users)}, targets={len(self.targets)}, "
            f"checked={self.checked_user_count}, initialized={len(self.initialized_users)}, "
            f"new_tweets={self.new_tweet_count}, no_new={len(self.no_new_users)}, "
            f"empty={len(self.empty_users)}, failed={len(self.failed_users)}, "
            f"push_mode={self.push_mode}, "
            f"qq_merge_threshold={self.merge_tweet_threshold}, "
            f"push_success={self.pushed_target_successes}/{self.pushed_target_attempts}, "
            f"invalid_targets={len(self.invalid_targets)}{warning_part}{filtered_part}"
        )

    def format_brief_log_lines(self) -> list[str]:
        if self.skipped_reason:
            return [self.format_log_summary()]

        lines = [
            "[NitterTweets] 推送结果: "
            f"group={self.group_name}({self.group_id}), "
            f"reason={self.reason}, "
            f"mode={self.push_mode}, "
            f"checked={self.checked_user_count}, "
            f"new={self.new_tweet_count}, "
            f"push_success={self.pushed_target_successes}/"
            f"{self.pushed_target_attempts}, "
            f"failed={len(self.failed_users)}, "
            f"invalid_targets={len(self.invalid_targets)}, "
            f"warnings={len(self.delivery_warnings)}"
        ]
        if self.plain_text_filtered:
            lines[0] += f", filtered={self.plain_text_filtered}"
        if self.failed_users:
            failed_items = [
                f"{self._failure_label(user)}: {error}"
                for user, error in self.failed_users.items()
            ]
            lines.append(
                "[NitterTweets] 失败详情: "
                + _format_limited_values(failed_items, limit=5, separator="; ")
            )
        if self.invalid_targets:
            lines.append(
                "[NitterTweets] 无效推送目标: "
                + _format_limited_values(
                    list(dict.fromkeys(self.invalid_targets)),
                    limit=5,
                    separator="; ",
                )
            )
        if self.delivery_warnings:
            lines.append(
                "[NitterTweets] 发送状态提示: "
                + _format_limited_values(
                    list(dict.fromkeys(self.delivery_warnings)),
                    limit=5,
                    separator="; ",
                )
            )
        return lines

    @staticmethod
    def _failure_label(user: str) -> str:
        user = str(user or "").strip()
        if user == "publish":
            return user
        if user.startswith("@"):
            return user
        return f"@{user}"

    def format_message(self, title: str = "Nitter 定时检查结果") -> str:
        lines = [
            title,
            f"分组: {self.group_name} ({self.group_id})",
            f"触发原因: {self.reason}",
            f"关注账号: {len(self.users)} 个",
            f"推送目标: {len(self.targets)} 个",
            f"已记录账号索引: {self.seen_users} 个",
        ]
        if self.fetch_limit:
            lines.append(f"每账号拉取: {self.fetch_limit} 条")
        if self.merge_tweet_threshold > 0:
            lines.append(f"QQ 合并阈值: {self.merge_tweet_threshold} 条及以上")
        else:
            lines.append("QQ 合并阈值: 已关闭")

        if self.skipped_reason:
            reason_text = {
                "no_watch_users": "未配置 watch_users",
                "no_push_targets": "未配置有效 push_targets",
                "check_already_running": "已有一次检查正在运行",
                "unknown_group": "未找到指定分组",
            }.get(self.skipped_reason, self.skipped_reason)
            lines.append(f"检查跳过: {reason_text}")
            if self.available_groups:
                lines.append(
                    "可用分组: "
                    + _format_limited_values(self.available_groups)
                )

        if self.initialized_users:
            items = [
                f"@{username}({count} 条)"
                for username, count in self.initialized_users.items()
            ]
            lines.append("首次记录: " + _format_limited_values(items))

        if self.pushes and self.push_mode == "merged":
            items = [
                f"@{item.username} {item.new_count} 条"
                for item in self.pushes
            ]
            lines.append("新推文: " + _format_limited_values(items, separator="; "))
        elif self.pushes:
            items = [
                f"@{item.username} {item.new_count} 条，推送 {item.success_targets}/{item.total_targets}"
                for item in self.pushes
            ]
            lines.append("新推文: " + _format_limited_values(items, separator="; "))

        if self.merged_push_total_targets:
            lines.append(
                "QQ 合并推送: "
                f"{self.merged_push_success_targets}/{self.merged_push_total_targets}"
            )

        if self.no_new_users:
            lines.append(
                "无新推文: "
                + _format_limited_values(
                    [f"@{user}" for user in self.no_new_users]
                )
            )

        if self.empty_users:
            lines.append(
                "RSS 无有效推文 ID: "
                + _format_limited_values(
                    [f"@{user}" for user in self.empty_users]
                )
            )

        if self.failed_users:
            items = [f"@{user}: {error}" for user, error in self.failed_users.items()]
            lines.append("失败: " + _format_limited_values(items, separator="; "))

        if self.invalid_targets:
            lines.append(
                "无效推送目标: "
                + _format_limited_values(self.invalid_targets)
            )

        if not self.skipped_reason and self.new_tweet_count == 0:
            lines.append("本次没有发现需要推送的新推文。")

        return "\n".join(lines)
