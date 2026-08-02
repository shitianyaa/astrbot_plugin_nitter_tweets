from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

try:
    from ..shared import (
        TweetItem,
        format_subscription_count,
        format_subscription_source,
    )
    from ..shared.group_ids import DEFAULT_GROUP_NAME, GLOBAL_GROUP_ID
    from .formatting import _format_limited_values
except ImportError:
    from scheduler.formatting import _format_limited_values
    from shared import TweetItem, format_subscription_count, format_subscription_source
    from shared.group_ids import DEFAULT_GROUP_NAME, GLOBAL_GROUP_ID

if TYPE_CHECKING:
    # 只用于注解。运行时不导入，避免 scheduler.models 反向拉起 ai（ai → config，
    # 而 config 对 scheduler 已经只保留 TYPE_CHECKING 依赖）。
    try:
        from ..ai import TranslationReport
    except ImportError:
        from ai import TranslationReport


class SourceStatus:
    """Per-source check outcomes, shared by the fetch and scheduling layers.

    Attribute access rather than bare literals: a mistyped status would
    otherwise be counted under a name no formatter knows about and vanish from
    every summary, so the miscount is the only symptom.
    """

    # Fetch classification (`UserFetchResult.fetch_status`).
    SUCCESS = "success"
    EMPTY = "empty"
    FILTERED_EMPTY = "filtered_empty"
    INCOMPLETE = "incomplete"
    # Refined once the scheduler knows what happened to the fetched tweets.
    UPDATED = "updated"
    NO_NEW = "no_new"
    INITIALIZED = "initialized"
    BASELINE_REBUILT = "baseline_rebuilt"
    BASELINE_REBUILD_FAILED = "baseline_rebuild_failed"
    DELIVERY_FAILED = "delivery_failed"
    FAILED = "failed"


# Per-source check outcomes, ordered from "healthy" to "needs attention".
# Insertion order drives both the log summary and the user-facing message so
# the two never disagree; the values are the labels shown to users.
_SOURCE_STATUS_LABELS: dict[str, str] = {
    SourceStatus.UPDATED: "发现更新",
    # Provisional status written right after a successful fetch; normally
    # refined to updated / no_new / initialized before the check ends.  Kept
    # in the table so a leaked provisional value is still counted, not dropped.
    SourceStatus.SUCCESS: "抓取成功",
    SourceStatus.NO_NEW: "正常无更新",
    SourceStatus.INITIALIZED: "首次初始化",
    SourceStatus.EMPTY: "返回空结果",
    SourceStatus.FILTERED_EMPTY: "过滤后为空",
    SourceStatus.INCOMPLETE: "扫描未完整",
    SourceStatus.BASELINE_REBUILT: "已重建基准",
    SourceStatus.BASELINE_REBUILD_FAILED: "基准未重建",
    SourceStatus.DELIVERY_FAILED: "发送未完成",
    SourceStatus.FAILED: "抓取失败",
}


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
    media_only: bool = False
    omit_status_url: bool = True
    hide_original_when_translated: bool = False
    media_status: str = "ready"
    media_cleaned: bool = field(default=False, repr=False, compare=False)


@dataclass(slots=True)
class PendingBaselineRebuild:
    """A Tag/List source whose scan never reached the old watermark.

    `max_tweets_per_check > 0` still delivers up to that many tweets, so the
    rebuild has to wait until sending finishes: `selected_ids` collects what
    was queued, and the baseline is only rewritten once every one of those IDs
    made it into seen (i.e. all targets accepted the batch).
    """

    baseline_ids: list[str]
    selected_ids: set[str] = field(default_factory=set)


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
    group_type: str = "blogger"
    users: list[str] = field(default_factory=list)
    targets: list[str] = field(default_factory=list)
    invalid_targets: list[str] = field(default_factory=list)
    available_groups: list[str] = field(default_factory=list)
    # Fixed RSS first-page size used by the background scanner.
    fetch_limit: int = 0
    max_tweets_per_check: int = 0
    skipped_reason: str = ""
    initialized_users: dict[str, int] = field(default_factory=dict)
    no_new_users: list[str] = field(default_factory=list)
    empty_users: list[str] = field(default_factory=list)
    filtered_empty_users: list[str] = field(default_factory=list)
    failed_users: dict[str, str] = field(default_factory=dict)
    source_statuses: dict[str, str] = field(default_factory=dict)
    source_attempts: dict[str, list[str]] = field(default_factory=dict)
    baseline_rebuilt_users: dict[str, int] = field(default_factory=dict)
    baseline_rebuild_failed_users: dict[str, str] = field(default_factory=dict)
    pushes: list[ScheduledPushResult] = field(default_factory=list)
    push_mode: str = "per_user"
    merge_tweet_threshold: int = 0
    merged_push_success_targets: int = 0
    merged_push_total_targets: int = 0
    delivery_warnings: list[str] = field(default_factory=list)
    plain_text_filtered: int = 0
    target_blocked_filtered: int = 0
    media_only_skipped: int = 0
    media_only_retrying: int = 0

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
            + len(self.filtered_empty_users)
            + len(self.failed_users)
            + len(self.baseline_rebuilt_users)
            + len(self.baseline_rebuild_failed_users)
            + len(self.pushes)
        )

    def has_visible_no_update(self) -> bool:
        return (
            not self.skipped_reason
            and self.targets
            and self.new_tweet_count == 0
            and not self.baseline_rebuilt_users
            and not self.baseline_rebuild_failed_users
            and (
                bool(self.initialized_users)
                or bool(self.no_new_users)
                or bool(self.empty_users)
                or bool(self.filtered_empty_users)
                or bool(self.failed_users)
            )
        )

    def _source_status_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for username in self.users:
            status = self.source_statuses.get(username)
            if status:
                counts[status] = counts.get(status, 0) + 1
        return counts

    def _source_status_summary(self) -> str:
        counts = self._source_status_counts()
        return (
            ",".join(
                f"{status}:{counts[status]}"
                for status in _SOURCE_STATUS_LABELS
                if counts.get(status)
            )
            or "unknown"
        )

    def _source_status_message(self) -> str:
        counts = self._source_status_counts()
        return (
            "、".join(
                f"{label} {counts[status]} 个"
                for status, label in _SOURCE_STATUS_LABELS.items()
                if counts.get(status)
            )
            or "暂无结果"
        )

    def _watermark_counts(self) -> dict[str, int]:
        counts = {"advanced": 0, "rebuilt": 0, "initialized": 0, "unchanged": 0}
        for username in self.users:
            if username in self.baseline_rebuilt_users:
                counts["rebuilt"] += 1
            elif username in self.initialized_users:
                counts["initialized"] += 1
            elif self.source_statuses.get(username) in {
                SourceStatus.UPDATED,
                SourceStatus.NO_NEW,
            }:
                counts["advanced"] += 1
            else:
                counts["unchanged"] += 1
        return counts

    def _watermark_summary(self) -> str:
        counts = self._watermark_counts()
        return ",".join(f"{name}:{count}" for name, count in counts.items() if count)

    def _watermark_message(self) -> str:
        labels = {
            "advanced": "已推进",
            "rebuilt": "已重建",
            "initialized": "已初始化",
            "unchanged": "未更新",
        }
        counts = self._watermark_counts()
        return (
            "、".join(
                f"{labels[name]} {count} 个" for name, count in counts.items() if count
            )
            or "暂无结果"
        )

    def format_log_summary(self) -> str:
        if self.skipped_reason:
            return (
                "[NitterTweets] 定时检查已跳过: "
                f"group={self.group_id}, type={self.group_type}, "
                f"reason={self.skipped_reason}, sources={len(self.users)}, "
                f"targets={len(self.targets)}, invalid_targets={len(self.invalid_targets)}"
            )

        warning_part = (
            f", warnings={len(self.delivery_warnings)}"
            if self.delivery_warnings
            else ""
        )
        filtered_part = (
            f", filtered={self.plain_text_filtered}" if self.plain_text_filtered else ""
        )
        target_blocked_part = (
            f", target_blocked={self.target_blocked_filtered}"
            if self.target_blocked_filtered
            else ""
        )
        media_part = (
            f", media_skipped={self.media_only_skipped}, "
            f"media_retrying={self.media_only_retrying}"
            if self.media_only_skipped or self.media_only_retrying
            else ""
        )
        return (
            "[NitterTweets] 定时检查完成: "
            f"group={self.group_id}, type={self.group_type}, reason={self.reason}, "
            f"sources={len(self.users)}, targets={len(self.targets)}, "
            f"checked={self.checked_user_count}, initialized={len(self.initialized_users)}, "
            f"new_tweets={self.new_tweet_count}, no_new={len(self.no_new_users)}, "
            f"empty={len(self.empty_users)}, "
            f"filtered_empty={len(self.filtered_empty_users)}, "
            f"failed={len(self.failed_users)}, "
            f"status={self._source_status_summary()}, "
            f"watermark={self._watermark_summary()}, "
            f"baseline_rebuilt={len(self.baseline_rebuilt_users)}, "
            f"baseline_rebuild_failed={len(self.baseline_rebuild_failed_users)}, "
            f"push_mode={self.push_mode}, "
            f"qq_merge_threshold={self.merge_tweet_threshold}, "
            f"push_success={self.pushed_target_successes}/{self.pushed_target_attempts}, "
            f"invalid_targets={len(self.invalid_targets)}{warning_part}"
            f"{filtered_part}{target_blocked_part}{media_part}"
        )

    def format_brief_log_lines(self) -> list[str]:
        if self.skipped_reason:
            return [self.format_log_summary()]

        lines = [
            (
                "[NitterTweets] 推送结果: "
                f"group={self.group_name}({self.group_id}), "
                f"type={self.group_type}, "
                f"reason={self.reason}, "
                f"mode={self.push_mode}, "
                f"checked={self.checked_user_count}, "
                f"new={self.new_tweet_count}, "
                f"status={self._source_status_summary()}, "
                f"watermark={self._watermark_summary()}, "
                f"push_success={self.pushed_target_successes}/"
                f"{self.pushed_target_attempts}, "
                f"failed={len(self.failed_users)}, "
                f"invalid_targets={len(self.invalid_targets)}, "
                f"warnings={len(self.delivery_warnings)}"
            )
        ]
        if self.plain_text_filtered:
            lines[0] += f", filtered={self.plain_text_filtered}"
        if self.target_blocked_filtered:
            lines[0] += f", target_blocked={self.target_blocked_filtered}"
        if self.media_only_skipped or self.media_only_retrying:
            lines[0] += (
                f", media_skipped={self.media_only_skipped},"
                f" media_retrying={self.media_only_retrying}"
            )
        if self.failed_users:
            failed_items = [
                f"{self._failure_label(user)}: {error}"
                for user, error in self.failed_users.items()
            ]
            lines.append(
                "[NitterTweets] 失败详情: "
                + _format_limited_values(failed_items, limit=5, separator="; ")
            )
        if self.baseline_rebuilt_users:
            rebuilt_items = [
                f"{self._subscription_label(user)}({count} 个第一页基线 ID)"
                for user, count in self.baseline_rebuilt_users.items()
            ]
            lines.append(
                "[NitterTweets] 扫描未完整，自动重建基准: "
                + _format_limited_values(rebuilt_items, limit=5, separator="; ")
                + self._baseline_rebuild_notice()
            )
        if self.baseline_rebuild_failed_users:
            rebuild_items = [
                f"{self._subscription_label(user)}: {error}"
                for user, error in self.baseline_rebuild_failed_users.items()
            ]
            lines.append(
                "[NitterTweets] 扫描未完整，自动重建基准未完成: "
                + _format_limited_values(rebuild_items, limit=5, separator="; ")
            )
        if self.empty_users:
            lines.append(
                "[NitterTweets] 空结果详情: "
                + _format_limited_values(
                    [self._subscription_label(user) for user in self.empty_users],
                    limit=5,
                    separator="; ",
                )
            )
        if self.filtered_empty_users:
            lines.append(
                "[NitterTweets] 过滤后为空: "
                + _format_limited_values(
                    [
                        self._subscription_label(user)
                        for user in self.filtered_empty_users
                    ],
                    limit=5,
                    separator="; ",
                )
            )
        if self.source_attempts:
            attempts = [
                f"{self._subscription_label(user)}: {'；'.join(details)}"
                for user, details in self.source_attempts.items()
                if details
            ]
            if attempts:
                lines.append(
                    "[NitterTweets] 实例结果: "
                    + _format_limited_values(attempts, limit=5, separator="; ")
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

    def _failure_label(self, user: str) -> str:
        source = str(user or "").strip()
        status_suffix = ""
        known_sources = {str(item or "").strip() for item in self.users}
        if source not in known_sources and ":" in source:
            candidate_source, candidate_suffix = source.rsplit(":", 1)
            if candidate_source in known_sources and (
                candidate_suffix.isdigit() or candidate_suffix.startswith("index-")
            ):
                source = candidate_source
                status_suffix = f"（推文 {candidate_suffix}）"
        return format_subscription_source(source, self.group_type) + status_suffix

    def _subscription_label(self, user: str) -> str:
        user = str(user or "").strip()
        if user.startswith("list:"):
            return f"List {user[5:]}"
        return self._failure_label(user)

    def _baseline_rebuild_notice(self) -> str:
        if self.max_tweets_per_check <= 0:
            return "；未配置单轮推送上限，本轮未推送并自动重建基准，旧积压可能被跳过"
        return (
            f"；已按单轮推送上限 {self.max_tweets_per_check} 条处理并自动重建基准，"
            "旧积压可能被跳过"
        )

    def format_message(self, title: str = "Nitter 定时检查结果") -> str:
        lines = [
            title,
            f"分组: {self.group_name} ({self.group_id})",
            f"触发原因: {self.reason}",
            f"订阅数量: {format_subscription_count(len(self.users), self.group_type)}",
            f"推送目标: {len(self.targets)} 个",
        ]
        if self.fetch_limit:
            lines.append(f"后台首屏扫描: {self.fetch_limit} 条")
        if self.target_blocked_filtered:
            lines.append(f"目标黑名单过滤: {self.target_blocked_filtered} 条")
        if self.merge_tweet_threshold > 0:
            lines.append(f"QQ 合并阈值: {self.merge_tweet_threshold} 条及以上")
        else:
            lines.append("QQ 合并阈值: 已关闭")

        if self.source_statuses:
            lines.append(f"抓取状态: {self._source_status_message()}")
            lines.append(f"水位状态: {self._watermark_message()}")

        if self.skipped_reason:
            reason_text = {
                "no_watch_users": "未配置 watch_users",
                "no_watch_queries": "未配置 watch_queries",
                "no_watch_lists": "未配置 watch_lists",
                "no_push_targets": "未配置有效 push_targets",
                "check_already_running": "已有一次检查正在运行",
                "storage_not_ready": "调度存储尚未就绪",
                "unknown_group": "未找到指定分组",
            }.get(self.skipped_reason, self.skipped_reason)
            lines.append(f"检查跳过: {reason_text}")
            if self.available_groups:
                lines.append(
                    "可用分组: " + _format_limited_values(self.available_groups)
                )

        if self.initialized_users:
            items = [
                f"{format_subscription_source(username, self.group_type)}({count} 条)"
                for username, count in self.initialized_users.items()
            ]
            lines.append("首次记录: " + _format_limited_values(items))

        if self.baseline_rebuilt_users:
            items = [
                f"{self._subscription_label(user)} {count} 个第一页基线 ID"
                for user, count in self.baseline_rebuilt_users.items()
            ]
            lines.append(
                "扫描未完整，自动重建基准: "
                + _format_limited_values(items, separator="; ")
                + self._baseline_rebuild_notice()
            )

        if self.baseline_rebuild_failed_users:
            items = [
                f"{self._subscription_label(user)}: {error}"
                for user, error in self.baseline_rebuild_failed_users.items()
            ]
            lines.append(
                "扫描未完整，自动重建基准未完成: "
                + _format_limited_values(items, separator="; ")
            )

        if self.pushes and self.push_mode == "merged":
            items = [
                f"{format_subscription_source(item.username, self.group_type)} "
                f"{item.new_count} 条"
                for item in self.pushes
            ]
            lines.append("新推文: " + _format_limited_values(items, separator="; "))
        elif self.pushes:
            items = [
                f"{format_subscription_source(item.username, self.group_type)} "
                f"{item.new_count} 条，推送 {item.success_targets}/{item.total_targets}"
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
                    [
                        format_subscription_source(user, self.group_type)
                        for user in self.no_new_users
                    ]
                )
            )

        if self.empty_users:
            lines.append(
                "订阅源返回空结果: "
                + _format_limited_values(
                    [
                        format_subscription_source(user, self.group_type)
                        for user in self.empty_users
                    ]
                )
            )

        if self.filtered_empty_users:
            lines.append(
                "订阅源结果全部被过滤: "
                + _format_limited_values(
                    [
                        format_subscription_source(user, self.group_type)
                        for user in self.filtered_empty_users
                    ]
                )
            )

        if self.source_attempts:
            attempts = [
                f"{self._subscription_label(user)}: {'；'.join(details)}"
                for user, details in self.source_attempts.items()
                if details
            ]
            if attempts:
                lines.append(
                    "实例结果: "
                    + _format_limited_values(attempts, limit=5, separator="; ")
                )

        if self.failed_users:
            items = [
                f"{self._failure_label(user)}: {error}"
                for user, error in self.failed_users.items()
            ]
            lines.append("失败: " + _format_limited_values(items, separator="; "))

        if self.invalid_targets:
            lines.append(
                "无效推送目标: " + _format_limited_values(self.invalid_targets)
            )

        if (
            not self.skipped_reason
            and self.new_tweet_count == 0
            and self.no_new_users
            and len(self.no_new_users) == len(self.users)
            and not self.initialized_users
            and not self.empty_users
            and not self.filtered_empty_users
            and not self.failed_users
            and not self.baseline_rebuilt_users
            and not self.baseline_rebuild_failed_users
        ):
            lines.append("本次没有发现需要推送的新推文。")

        return "\n".join(lines)


@dataclass(slots=True)
class SchedulerTaskError:
    message: str
    kind: str = ""

    @classmethod
    def from_exception(cls, exc: Exception) -> SchedulerTaskError:
        return cls(message=str(exc), kind=type(exc).__name__)


@dataclass(slots=True)
class UserFetchResult:
    index: int
    username: str
    instance: str = ""
    tweets: list[TweetItem] = field(default_factory=list)
    scanned_status_ids: list[str] = field(default_factory=list)
    anchor_status_ids: list[str] = field(default_factory=list)
    latest_status_id: str = ""
    scan_complete: bool = True
    plain_text_filtered: int = 0
    error: SchedulerTaskError | None = None
    # HTML search keeps these internal counters so a tag's first RT-only
    # response can be distinguished from a genuinely empty page.
    retweet_filtered: int = 0
    html_raw_item_count: int = 0
    fetch_status: str = ""
    host_attempts: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PreparedBatchResult:
    batch: PendingTweetBatch
    translation_report: TranslationReport | None = None
    error: SchedulerTaskError | None = None
    media_status: str = "ready"
    media_error: str = ""
