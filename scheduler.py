from __future__ import annotations

import asyncio
import datetime as dt
import time
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from astrbot.api import logger

try:
    from astrbot.api.all import MessageChain
except ImportError:
    from astrbot.api.event import MessageChain

try:
    from astrbot.api.message_components import Plain
except ImportError:
    from astrbot.core.message.components import Plain

try:
    from .scheduler_config import (
        PushTargetParseResult,
        ScheduleGroup,
        SchedulerConfigReader,
        WatchUsersInfo,
    )
    from .seen_store import GLOBAL_GROUP_ID
    from .storage_adapter import StorageAdapter
    from .utils import (
        TweetItem,
        configured_merge_tweet_threshold,
    )
except ImportError:
    from scheduler_config import (
        PushTargetParseResult,
        ScheduleGroup,
        SchedulerConfigReader,
        WatchUsersInfo,
    )
    from seen_store import GLOBAL_GROUP_ID
    from storage_adapter import StorageAdapter
    from utils import (
        TweetItem,
        configured_merge_tweet_threshold,
    )


try:
    CN_TZ = ZoneInfo("Asia/Shanghai")
except ZoneInfoNotFoundError:
    CN_TZ = dt.timezone(dt.timedelta(hours=8), name="Asia/Shanghai")


POLL_SECONDS = 30


def _format_limited_values(
    values: list[str],
    limit: int = 10,
    separator: str = ", ",
) -> str:
    shown = [str(item) for item in values[:limit]]
    if len(values) > limit:
        shown.append(f"... 还有 {len(values) - limit} 个")
    return separator.join(shown)


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
    pending_ids: list[int] = field(default_factory=list)


@dataclass(slots=True)
class ScheduledCheckResult:
    reason: str
    group_id: str = GLOBAL_GROUP_ID
    group_name: str = "全局分组"
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
    queued_tweets: dict[str, int] = field(default_factory=dict)

    @property
    def new_tweet_count(self) -> int:
        if self.push_mode == "deferred":
            return self.queued_tweet_count
        return sum(push.new_count for push in self.pushes)

    @property
    def queued_tweet_count(self) -> int:
        return sum(self.queued_tweets.values())

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
            + len(self.queued_tweets)
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
                "[NitterTweets] scheduled check skipped: "
                f"group={self.group_id}, reason={self.skipped_reason}, "
                f"users={len(self.users)}, "
                f"targets={len(self.targets)}, invalid_targets={len(self.invalid_targets)}"
            )

        warning_part = (
            f", warnings={len(self.delivery_warnings)}"
            if self.delivery_warnings else ""
        )
        return (
            "[NitterTweets] scheduled check finished: "
            f"group={self.group_id}, reason={self.reason}, "
            f"users={len(self.users)}, targets={len(self.targets)}, "
            f"checked={self.checked_user_count}, initialized={len(self.initialized_users)}, "
            f"new_tweets={self.new_tweet_count}, no_new={len(self.no_new_users)}, "
            f"empty={len(self.empty_users)}, failed={len(self.failed_users)}, "
            f"push_mode={self.push_mode}, "
            f"qq_merge_threshold={self.merge_tweet_threshold}, "
            f"push_success={self.pushed_target_successes}/{self.pushed_target_attempts}, "
            f"invalid_targets={len(self.invalid_targets)}{warning_part}"
        )

    def format_message(self, title: str = "Nitter 定时检查结果") -> str:
        lines = [
            title,
            f"分组: {self.group_name} ({self.group_id})",
            f"触发原因: {self.reason}",
            f"关注账号: {len(self.users)} 个",
            f"推送目标: {len(self.targets)} 个",
            f"已记录账号: {self.seen_users} 个",
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
                "no_pending_tweets": "没有待发布推文",
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

        if self.queued_tweets:
            items = [
                f"@{username} {count} 条"
                for username, count in self.queued_tweets.items()
            ]
            lines.append("已暂存: " + _format_limited_values(items, separator="; "))

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


class NitterTweetScheduler:
    def __init__(
        self, owner, context, config, nitter, media, sender, translator, enricher=None
    ):
        self.owner = owner
        self.context = context
        self.config = config
        self.nitter = nitter
        self.media = media
        self.sender = sender
        self.translator = translator
        self.enricher = enricher
        self.config_reader = SchedulerConfigReader(config, context)
        self.storage = StorageAdapter(owner, config, context)
        self._task: asyncio.Task | None = None
        self._last_interval_slots: dict[str, int] = {}
        self._daily_slots: dict[str, set[str]] = {}
        self._deferred_publish_slots: dict[str, set[str]] = {}
        self._startup_schedule_seeded: set[str] = set()
        self._last_enabled_state: bool | None = None
        self._check_lock = asyncio.Lock()
        self._migration_done = False

    def start(self, reason: str = "") -> None:
        if self._task is not None and not self._task.done():
            logger.info(
                "[NitterTweets] scheduler already running "
                f"({reason}); enabled={self.schedule_enabled}"
            )
            return
        try:
            loop = asyncio.get_running_loop()
            self._task = loop.create_task(self._loop())
            groups = self._schedule_groups(log_invalid_targets=False)
            logger.info(
                "[NitterTweets] scheduler started "
                f"({reason}); enabled={self.schedule_enabled}, "
                f"groups={len(groups)}, "
                f"enabled_groups={sum(1 for group in groups if group.enabled)}, "
                f"watch_users={sum(len(group.users) for group in groups)}, "
                f"push_targets={sum(len(group.targets) for group in groups)}"
            )
        except RuntimeError:
            logger.info(
                f"[NitterTweets] no running event loop during {reason}; "
                "scheduler will wait for the next startup hook"
            )

    async def stop(self) -> None:
        if self._task is None or self._task.done():
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self.storage.close()
        logger.info("[NitterTweets] scheduler stopped")

    async def _loop(self) -> None:
        logger.info("[NitterTweets] scheduler loop entered")
        await asyncio.sleep(2)

        # 执行一次性迁移和配置同步
        if not self._migration_done:
            try:
                schedule_groups = self._schedule_groups(log_invalid_targets=False)
                await self.storage.migrate_and_sync(schedule_groups)
                self._migration_done = True
                logger.info("[NitterTweets] Migration and sync completed successfully")
            except Exception as exc:
                logger.error(f"[NitterTweets] migration/sync failed: {exc}", exc_info=True)
                logger.error("[NitterTweets] Scheduler will retry migration in 5 minutes")
                await asyncio.sleep(300)
                return  # Exit loop, will retry on next start() call

        while True:
            try:
                if self.schedule_enabled:
                    self._log_enabled_state(True)
                    await self._tick()
                else:
                    self._log_enabled_state(False)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"[NitterTweets] scheduler error: {exc}", exc_info=True)
                await asyncio.sleep(60)
                continue
            await asyncio.sleep(POLL_SECONDS)

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def schedule_enabled(self) -> bool:
        config_enabled = bool(self.config.get("schedule_enabled", False))
        return config_enabled and any(
            group.enabled
            for group in self._schedule_groups(log_invalid_targets=False)
        )

    def _log_enabled_state(self, enabled: bool) -> None:
        if self._last_enabled_state is enabled:
            return
        self._last_enabled_state = enabled
        if enabled:
            logger.info("[NitterTweets] scheduler active: schedule_enabled=true")
        else:
            logger.info("[NitterTweets] scheduler idle: schedule_enabled=false")

    async def _tick(self) -> None:
        now = dt.datetime.now(CN_TZ)
        for group in self._schedule_groups(log_invalid_targets=False):
            if not group.enabled:
                continue
            reasons = self._scheduled_reasons(group, now)
            if reasons:
                logger.info(
                    "[NitterTweets] scheduled check triggered: "
                    f"group={group.group_id}, reasons={', '.join(reasons)}"
                )
                await self.run_check(
                    reason=", ".join(reasons),
                    group_name=group.group_id,
                )
            publish_reasons = self._deferred_publish_reasons(group, now)
            if publish_reasons:
                logger.info(
                    "[NitterTweets] deferred publish triggered: "
                    f"group={group.group_id}, reasons={', '.join(publish_reasons)}"
                )
                await self.publish_pending(
                    group_name=group.group_id,
                    reason=", ".join(publish_reasons),
                )

    def _scheduled_reasons(
        self, group: ScheduleGroup, now: dt.datetime
    ) -> list[str]:
        reasons: list[str] = []
        group_id = group.group_id

        if group_id not in self._startup_schedule_seeded:
            self._startup_schedule_seeded.add(group_id)
            if not group.check_on_startup:
                self._seed_schedule_slots(group, now)
                logger.info(
                    "[NitterTweets] startup scheduled check skipped: "
                    f"group={group_id}, check_on_startup=false"
                )
                return reasons

        if group.interval_check_enabled:
            interval_minutes = group.check_interval_minutes
            slot = int(now.timestamp() // (interval_minutes * 60))
            if slot != self._last_interval_slots.get(group_id):
                self._last_interval_slots[group_id] = slot
                reasons.append(f"interval:{interval_minutes}m")

        if group.daily_check_enabled:
            daily_slots = self._daily_slots.setdefault(group_id, set())
            for hour, minute in group.daily_check_times:
                if now.hour == hour and now.minute == minute:
                    slot_key = f"{now.date().isoformat()}:{hour:02d}:{minute:02d}"
                    if slot_key not in daily_slots:
                        daily_slots.add(slot_key)
                        reasons.append(f"daily:{hour:02d}:{minute:02d}")

            if len(daily_slots) > 256:
                today = now.date().isoformat()
                self._daily_slots[group_id] = {
                    slot for slot in daily_slots if slot.startswith(today)
                }

        return reasons

    def _deferred_publish_reasons(
        self, group: ScheduleGroup, now: dt.datetime
    ) -> list[str]:
        if not group.deferred_publish_enabled:
            return []

        publish_slots = self._deferred_publish_slots.setdefault(group.group_id, set())
        reasons: list[str] = []
        for hour, minute in group.deferred_publish_times:
            if now.hour == hour and now.minute == minute:
                slot_key = f"{now.date().isoformat()}:{hour:02d}:{minute:02d}"
                if slot_key not in publish_slots:
                    publish_slots.add(slot_key)
                    reasons.append(f"deferred:{hour:02d}:{minute:02d}")

        if len(publish_slots) > 256:
            today = now.date().isoformat()
            self._deferred_publish_slots[group.group_id] = {
                slot for slot in publish_slots if slot.startswith(today)
            }
        return reasons

    def _seed_schedule_slots(self, group: ScheduleGroup, now: dt.datetime) -> None:
        group_id = group.group_id
        if group.interval_check_enabled:
            interval_minutes = group.check_interval_minutes
            self._last_interval_slots[group_id] = int(
                now.timestamp() // (interval_minutes * 60)
            )

        if group.daily_check_enabled:
            daily_slots = self._daily_slots.setdefault(group_id, set())
            for hour, minute in group.daily_check_times:
                if now.hour == hour and now.minute == minute:
                    daily_slots.add(f"{now.date().isoformat()}:{hour:02d}:{minute:02d}")

    async def run_check(
        self,
        reason: str = "manual",
        notify_no_updates: bool | None = None,
        group_name: str = GLOBAL_GROUP_ID,
        target_override: list[str] | None = None,
        force_immediate: bool = False,
    ) -> ScheduledCheckResult:
        group = self._schedule_group(group_name)
        if group is None:
            result = self._unknown_group_result(reason, group_name)
            logger.warning(result.format_log_summary())
            return result

        if self._check_lock.locked():
            result = self._new_check_result(reason, group, target_override)
            result.skipped_reason = "check_already_running"
            logger.warning(result.format_log_summary())
            return result

        async with self._check_lock:
            return await self._run_check_unlocked(
                group,
                reason,
                notify_no_updates,
                target_override,
                force_immediate,
            )

    def _new_check_result(
        self,
        reason: str,
        group: ScheduleGroup,
        target_override: list[str] | None = None,
    ) -> ScheduledCheckResult:
        targets = list(target_override) if target_override is not None else group.targets
        invalid_targets = [] if target_override is not None else group.invalid_targets
        return ScheduledCheckResult(
            reason=reason,
            group_id=group.group_id,
            group_name=group.name,
            users=group.users,
            targets=targets,
            invalid_targets=invalid_targets,
        )

    async def _run_check_unlocked(
        self,
        group: ScheduleGroup,
        reason: str,
        notify_no_updates: bool | None,
        target_override: list[str] | None = None,
        force_immediate: bool = False,
    ) -> ScheduledCheckResult:
        result = self._new_check_result(reason, group, target_override)
        users = result.users
        targets = result.targets
        merge_threshold = self._merge_tweet_threshold()
        result.merge_tweet_threshold = merge_threshold
        deferred_enabled = group.deferred_publish_enabled and not force_immediate
        if deferred_enabled:
            result.push_mode = "deferred"
        pending_batches = []
        immediate_targets, buffered_targets = self._split_immediate_targets(
            targets, merge_threshold
        )
        immediate_batches_sent = 0
        if not users:
            result.skipped_reason = "no_watch_users"
            logger.info(result.format_log_summary())
            return result
        if not targets:
            result.skipped_reason = "no_push_targets"
            logger.info(result.format_log_summary())
            return result

        seen_map = await self._get_seen_map(group.group_id)
        result.seen_users = len(seen_map)
        fetch_limit = group.scheduled_fetch_limit
        result.fetch_limit = fetch_limit
        target_interval = group.send_target_interval
        user_interval = group.send_user_interval
        logger.info(
            "[NitterTweets] scheduled check started: "
            f"group={group.group_id}, reason={reason}, "
            f"users={len(users)}, targets={len(targets)}, "
            f"invalid_targets={len(result.invalid_targets)}, "
            f"fetch_limit={fetch_limit}, qq_merge_threshold={merge_threshold}"
        )

        for username in users:
            try:
                instance, tweets = await self.nitter.fetch_tweets(username, fetch_limit)
            except Exception as exc:
                result.failed_users[username] = str(exc)
                logger.warning(f"[NitterTweets] scheduled fetch @{username} failed: {exc}")
                continue

            tweets = [tweet for tweet in tweets if tweet.status_id]
            if not tweets:
                result.empty_users.append(username)
                logger.info(
                    f"[NitterTweets] scheduled check @{username}: no valid status ids"
                )
                continue

            fetched_ids = [tweet.status_id for tweet in tweets]
            seen_ids = seen_map.get(username)

            if not isinstance(seen_ids, list):
                seen_map[username] = self.storage.initial_seen_ids(fetched_ids)
                await self._put_seen_map(group.group_id, seen_map)
                result.initialized_users[username] = len(fetched_ids)
                logger.info(
                    "[NitterTweets] initialized "
                    f"group={group.group_id} @{username} with "
                    f"{len(fetched_ids)} seen tweets"
                )
                continue

            seen_set = set(str(item) for item in seen_ids)
            new_tweets = [
                tweet for tweet in tweets if tweet.status_id not in seen_set
            ]

            if new_tweets:
                new_tweets.reverse()
                try:
                    await self.translator.attach_translations(new_tweets, targets[0])
                    if deferred_enabled:
                        if group.deferred_prefetch_media:
                            await self._attach_deferred_media(group, username, new_tweets)
                    else:
                        await self.media.attach_media(new_tweets)
                    if self.enricher is not None:
                        await self.enricher.attach_enrichments(new_tweets, targets[0])
                except Exception as exc:
                    await asyncio.to_thread(
                        self.media.cleanup_after_send, new_tweets
                    )
                    result.failed_users[username] = f"prepare failed: {exc}"
                    logger.warning(
                        f"[NitterTweets] scheduled prepare @{username} failed: {exc}"
                    )
                    continue

                batch = PendingTweetBatch(
                    username=username,
                    instance=instance,
                    tweets=new_tweets,
                    fetched_ids=fetched_ids,
                    seen_ids=seen_ids,
                )
                if deferred_enabled:
                    pending_batches.append(batch)
                else:
                    await self._store_pending_seen_ids(
                        group.group_id, [batch], seen_map
                    )
                    if buffered_targets:
                        try:
                            if immediate_targets:
                                if immediate_batches_sent > 0 and user_interval > 0:
                                    await asyncio.sleep(user_interval)
                                await self._send_per_user_updates(
                                    [batch],
                                    result,
                                    immediate_targets,
                                    target_interval,
                                    0.0,
                                )
                                immediate_batches_sent += 1
                            pending_batches.append(batch)
                        except BaseException:
                            await asyncio.to_thread(
                                self.media.cleanup_after_send, batch.tweets
                            )
                            raise
                    else:
                        try:
                            if immediate_targets:
                                if immediate_batches_sent > 0 and user_interval > 0:
                                    await asyncio.sleep(user_interval)
                                await self._send_per_user_updates(
                                    [batch],
                                    result,
                                    immediate_targets,
                                    target_interval,
                                    0.0,
                                )
                                immediate_batches_sent += 1
                        finally:
                            await asyncio.to_thread(
                                self.media.cleanup_after_send, batch.tweets
                            )
                logger.info(
                    f"[NitterTweets] prepared @{username} {len(new_tweets)} "
                    "new tweets for scheduled push"
                )
            else:
                result.no_new_users.append(username)
                logger.info(
                    f"[NitterTweets] scheduled check group={group.group_id} "
                    f"@{username}: no new tweets"
                )
                seen_map[username] = self._merge_seen_ids(fetched_ids, seen_ids)
                await self._put_seen_map(group.group_id, seen_map)

        if pending_batches and deferred_enabled:
            await self._enqueue_pending_batches(group, pending_batches, result)
            await self._store_pending_seen_ids(group.group_id, pending_batches, seen_map)

        if deferred_enabled:
            for batch in pending_batches:
                await asyncio.to_thread(self.media.cleanup_after_send, batch.tweets)
            logger.info(result.format_log_summary())
            if self._should_notify_no_updates(result, notify_no_updates, group):
                await self._send_no_update_notice(result, target_interval)
            return result

        if pending_batches:
            try:
                await self._send_prepared_batches(
                    pending_batches,
                    result,
                    buffered_targets,
                    target_interval,
                    user_interval,
                    record_merge_placeholders=not bool(immediate_targets),
                    merge_existing_stats=bool(immediate_targets),
                )
            finally:
                for batch in pending_batches:
                    await asyncio.to_thread(self.media.cleanup_after_send, batch.tweets)

        logger.info(result.format_log_summary())
        if result.delivery_warnings:
            unique_warning_count = len(dict.fromkeys(result.delivery_warnings))
            logger.warning(
                f"[NitterTweets] 发送状态提示：{unique_warning_count} 条"
            )
        if self._should_notify_no_updates(result, notify_no_updates, group):
            await self._send_no_update_notice(result, target_interval)
        return result

    async def status_summary(self) -> str:
        groups = self._schedule_groups(log_invalid_targets=False)
        default_group = next(
            (item for item in groups if item.group_id == GLOBAL_GROUP_ID),
            groups[0] if groups else None,
        )
        if default_group is None:
            return "Nitter 定时检查状态\n没有可用分组。"

        enabled_groups = [item for item in groups if item.enabled]
        total_users = sum(len(item.users) for item in groups)
        total_raw_users = sum(item.users_info.raw_count for item in groups)
        total_duplicates = sum(len(item.users_info.duplicates) for item in groups)
        total_invalid_users = sum(
            len(item.users_info.invalid_entries) for item in groups
        )
        total_targets = sum(len(item.targets) for item in groups)
        total_invalid_targets = sum(len(item.invalid_targets) for item in groups)
        queue_summary_results = await asyncio.gather(
            *[
                self.storage.get_pending_queue_summary(item.group_id)
                for item in groups
            ]
        )
        queue_summaries = {
            item.group_id: summary
            for item, summary in zip(groups, queue_summary_results)
        }
        total_pending = sum(item.pending_count for item in queue_summaries.values())
        total_pending_media = sum(item.media_count for item in queue_summaries.values())
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
            f"分组数量: {len(groups)} 个（启用 {len(enabled_groups)} 个）",
            f"QQ 合并阈值: {self._format_merge_threshold(self._merge_tweet_threshold())}",
            "全部分组订阅账号项: "
            f"{total_users} 个（配置 {total_raw_users} 项，"
            f"重复 {total_duplicates} 项，无效 {total_invalid_users} 项）",
            f"全部分组推送目标项: {total_targets} 个（无效 {total_invalid_targets} 个）",
            f"全部分组已记录账号项: {total_seen_users} 个",
            f"全部分组待发布: {total_pending} 条（媒体 {total_pending_media} 个）",
        ]
        lines.append("默认分组详情:")
        self._append_group_status(
            lines,
            default_group,
            seen_count=group_seen_counts.get(default_group.group_id, 0),
        )
        if len(groups) > 1:
            lines.append("其他分组详情:")
            for item in groups:
                if item.group_id == default_group.group_id:
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

        self.config["watch_users"] = info.users
        save_config = getattr(self.config, "save_config", None)
        if not callable(save_config):
            info.save_error = "当前配置对象不支持 save_config()"
            return info

        try:
            save_config()
            info.saved = True
        except Exception as exc:
            info.save_error = str(exc)
            logger.warning(f"[NitterTweets] failed to save deduplicated watch_users: {exc}")
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

    async def _send_no_update_notice(
        self, result: ScheduledCheckResult, target_interval: float
    ) -> None:
        text = result.format_message("Nitter 定时检查无更新")
        success = 0
        for target_index, umo in enumerate(result.targets):
            try:
                sent = await self.context.send_message(umo, MessageChain([Plain(text)]))
                if sent is not False:
                    success += 1
                else:
                    logger.warning(
                        "[NitterTweets] no-update notice to "
                        f"{umo} failed: target platform not found or proactive send "
                        "is unsupported"
                    )
            except Exception as exc:
                logger.warning(
                    f"[NitterTweets] no-update notice to {umo} failed: {exc}"
                )
            if target_index < len(result.targets) - 1 and target_interval > 0:
                await asyncio.sleep(target_interval)
        logger.info(
            f"[NitterTweets] no-update notice sent to {success}/{len(result.targets)} targets"
        )

    async def _send_per_user_updates(
        self,
        batches,
        result: ScheduledCheckResult,
        targets: list[str],
        target_interval: float,
        user_interval: float,
        merge_existing_stats: bool = False,
    ) -> None:
        for batch_index, batch in enumerate(batches):
            success = 0
            for target_index, umo in enumerate(targets):
                try:
                    outcome = await self.sender.send_to_umo_with_outcome(
                        self.context,
                        umo,
                        batch.username,
                        batch.instance,
                        batch.tweets,
                    )
                    if outcome.success:
                        success += 1
                    if outcome.warning:
                        result.delivery_warnings.append(outcome.warning)
                except Exception as exc:
                    logger.warning(
                        f"[NitterTweets] scheduled push @{batch.username} to {umo} failed: {exc}"
                    )
                if target_index < len(targets) - 1 and target_interval > 0:
                    await asyncio.sleep(target_interval)
            self._record_scheduled_push(
                result,
                batch,
                success,
                len(targets),
                merge_existing_stats=merge_existing_stats,
            )
            logger.info(
                f"[NitterTweets] pushed @{batch.username} {len(batch.tweets)} new tweets "
                f"to {success}/{len(targets)} targets"
            )
            if batch_index < len(batches) - 1 and user_interval > 0:
                await asyncio.sleep(user_interval)

    def _record_scheduled_push(
        self,
        result: ScheduledCheckResult,
        batch: PendingTweetBatch,
        success_targets: int,
        total_targets: int,
        *,
        merge_existing_stats: bool = False,
    ) -> None:
        batch_key = self._scheduled_batch_key(batch)
        if merge_existing_stats:
            for push in result.pushes:
                if push.batch_key == batch_key:
                    push.success_targets += success_targets
                    push.total_targets += total_targets
                    return
        result.pushes.append(
            ScheduledPushResult(
                username=batch.username,
                new_count=len(batch.tweets),
                success_targets=success_targets,
                total_targets=total_targets,
                batch_key=batch_key,
            )
        )

    @staticmethod
    def _scheduled_batch_key(batch: PendingTweetBatch) -> str:
        status_ids = tuple(
            str(getattr(tweet, "status_id", "")) for tweet in batch.tweets
        )
        pending_ids = tuple(str(item) for item in batch.pending_ids)
        return repr((batch.username, batch.instance, status_ids, pending_ids))

    async def _send_merged_updates(
        self,
        batches,
        result: ScheduledCheckResult,
        targets: list[str],
        target_interval: float,
    ) -> None:
        success = 0
        for target_index, umo in enumerate(targets):
            try:
                outcome = await self.sender.send_merged_to_umo(
                    self.context, umo, batches
                )
                if outcome.success:
                    success += 1
                    if outcome.warning:
                        result.delivery_warnings.append(outcome.warning)
                    if outcome.mode not in {
                        "full_forward",
                        "forward_without_videos",
                        "uncertain_delivery",
                    }:
                        logger.info(
                            f"[NitterTweets] QQ 合并推送使用普通发送路径：mode={outcome.mode}"
                        )
                else:
                    logger.warning(
                        f"[NitterTweets] merged scheduled push to {umo} failed: "
                        f"{outcome.error}"
                    )
            except Exception as exc:
                logger.warning(
                    f"[NitterTweets] merged scheduled push to {umo} failed: {exc}"
                )
            if target_index < len(targets) - 1 and target_interval > 0:
                await asyncio.sleep(target_interval)

        result.merged_push_success_targets = success
        result.merged_push_total_targets = len(targets)
        logger.info(
            f"[NitterTweets] pushed {result.new_tweet_count} merged new tweets "
            f"from {len(batches)} users to {success}/{len(targets)} QQ targets"
        )

    async def _enqueue_pending_batches(
        self,
        group: ScheduleGroup,
        batches: list[PendingTweetBatch],
        result: ScheduledCheckResult,
    ) -> None:
        for batch in batches:
            queued = await self.storage.enqueue_pending_tweets(
                group.group_id,
                batch.username,
                batch.instance,
                batch.tweets,
            )
            if queued:
                result.queued_tweets[batch.username] = queued
            logger.info(
                "[NitterTweets] queued deferred tweets: "
                f"group={group.group_id}, user=@{batch.username}, "
                f"queued={queued}, prepared={len(batch.tweets)}"
            )

    async def _attach_deferred_media(
        self,
        group: ScheduleGroup,
        username: str,
        tweets: list[TweetItem],
    ) -> None:
        for index, tweet in enumerate(tweets):
            await self.media.attach_media([tweet])
            await self.media.move_tweets_media_to_staged(
                group.group_id,
                username,
                [tweet],
                0.0,
            )
            if (
                index < len(tweets) - 1
                and group.deferred_media_download_interval_seconds > 0
            ):
                await asyncio.sleep(group.deferred_media_download_interval_seconds)

    async def publish_pending(
        self,
        group_name: str = GLOBAL_GROUP_ID,
        reason: str = "manual_publish",
    ) -> ScheduledCheckResult:
        group = self._schedule_group(group_name)
        if group is None:
            result = self._unknown_group_result(reason, group_name)
            logger.warning(result.format_log_summary())
            return result

        if self._check_lock.locked():
            result = self._new_check_result(reason, group)
            result.skipped_reason = "check_already_running"
            logger.warning(result.format_log_summary())
            return result

        async with self._check_lock:
            return await self._publish_pending_unlocked(group, reason)

    async def _publish_pending_unlocked(
        self, group: ScheduleGroup, reason: str
    ) -> ScheduledCheckResult:
        result = self._new_check_result(reason, group)
        result.merge_tweet_threshold = self._merge_tweet_threshold()
        result.fetch_limit = group.deferred_publish_batch_limit
        if not group.targets:
            result.skipped_reason = "no_push_targets"
            logger.info(result.format_log_summary())
            return result

        records = await self.storage.get_pending_tweets(
            group.group_id,
            group.deferred_publish_batch_limit,
        )
        if not records:
            result.skipped_reason = "no_pending_tweets"
            logger.info(result.format_log_summary())
            return result

        batches = self._pending_records_to_batches(records)
        pending_ids = [record.id for record in records]
        target_interval = group.send_target_interval
        user_interval = group.send_user_interval
        cleanup_retention_hours = group.deferred_media_retention_hours
        try:
            protected_media_paths = await self.storage.get_pending_media_paths()
            await asyncio.to_thread(
                self.media.cleanup_expired_staged_media,
                cleanup_retention_hours,
                protected_media_paths,
            )
            await self._send_prepared_batches(
                batches,
                result,
                group.targets,
                target_interval,
                user_interval,
            )
            if (
                result.pushed_target_attempts
                and result.pushed_target_successes < result.pushed_target_attempts
            ):
                raise RuntimeError(
                    "deferred publish reached only "
                    f"{result.pushed_target_successes}/"
                    f"{result.pushed_target_attempts} configured targets"
            )
            await self.storage.mark_pending_tweets_published(pending_ids)
            for batch in batches:
                try:
                    await asyncio.to_thread(
                        self.media.cleanup_staged_media_for_tweets, batch.tweets
                    )
                except Exception as cleanup_exc:
                    logger.warning(
                        "[NitterTweets] deferred staged media cleanup failed: "
                        f"group={group.group_id}, error={cleanup_exc}"
                    )
            await self.storage.cleanup_sent_pending_tweets(int(time.time()))
        except Exception as exc:
            await self.storage.mark_pending_tweets_failed(pending_ids, str(exc))
            result.failed_users["publish"] = str(exc)
            logger.warning(
                f"[NitterTweets] deferred publish failed: "
                f"group={group.group_id}, error={exc}"
            )

        logger.info(result.format_log_summary())
        if result.delivery_warnings:
            unique_warning_count = len(dict.fromkeys(result.delivery_warnings))
            logger.warning(
                f"[NitterTweets] 发送状态提示：{unique_warning_count} 条"
            )
        return result

    def _pending_records_to_batches(self, records) -> list[PendingTweetBatch]:
        batches: list[PendingTweetBatch] = []
        batch_by_key: dict[tuple[str, str], PendingTweetBatch] = {}
        for record in records:
            key = (record.username, record.instance)
            batch = batch_by_key.get(key)
            if batch is None:
                batch = PendingTweetBatch(
                    username=record.username,
                    instance=record.instance,
                    tweets=[],
                    fetched_ids=[],
                    seen_ids=[],
                    pending_ids=[],
                )
                batch_by_key[key] = batch
                batches.append(batch)
            batch.tweets.append(record.tweet)
            batch.pending_ids.append(record.id)
        return batches

    async def _send_prepared_batches(
        self,
        batches: list[PendingTweetBatch],
        result: ScheduledCheckResult,
        targets: list[str],
        target_interval: float,
        user_interval: float,
        record_merge_placeholders: bool = True,
        merge_existing_stats: bool = False,
    ) -> None:
        if self._should_merge_batches(batches, result.merge_tweet_threshold):
            merge_targets, ordinary_targets = self._split_merge_targets(targets)
        else:
            merge_targets, ordinary_targets = [], targets

        if merge_targets:
            result.push_mode = "mixed" if ordinary_targets or result.pushes else "merged"
            if ordinary_targets:
                await self._send_per_user_updates(
                    batches,
                    result,
                    ordinary_targets,
                    target_interval,
                    user_interval,
                    merge_existing_stats=merge_existing_stats,
                )
                if target_interval > 0:
                    await asyncio.sleep(target_interval)
            elif record_merge_placeholders:
                for batch in batches:
                    result.pushes.append(
                        ScheduledPushResult(
                            username=batch.username,
                            new_count=len(batch.tweets),
                            success_targets=0,
                            total_targets=0,
                            batch_key=self._scheduled_batch_key(batch),
                        )
                    )
            await self._send_merged_updates(
                self._tweet_batches(batches),
                result,
                merge_targets,
                target_interval,
            )
            return

        result.push_mode = "per_user"
        await self._send_per_user_updates(
            batches,
            result,
            ordinary_targets,
            target_interval,
            user_interval,
            merge_existing_stats=merge_existing_stats,
        )

    def _merge_tweet_threshold(self) -> int:
        return configured_merge_tweet_threshold(self.config)

    @staticmethod
    def _should_merge_batches(batches: list[PendingTweetBatch], threshold: int) -> bool:
        if threshold <= 0:
            return False
        return sum(len(batch.tweets) for batch in batches) >= threshold

    def _split_immediate_targets(
        self, targets: list[str], merge_threshold: int
    ) -> tuple[list[str], list[str]]:
        if merge_threshold <= 0:
            return targets, []
        merge_targets, ordinary_targets = self._split_merge_targets(targets)
        if not merge_targets:
            return targets, []
        return ordinary_targets, merge_targets

    def _split_merge_targets(self, targets: list[str]) -> tuple[list[str], list[str]]:
        merge_targets = []
        ordinary_targets = []
        for umo in targets:
            if self.sender.supports_merged_forward_for_umo(self.context, umo):
                merge_targets.append(umo)
            else:
                ordinary_targets.append(umo)
        return merge_targets, ordinary_targets

    @staticmethod
    def _tweet_batches(batches: list[PendingTweetBatch]) -> list[tuple[str, str, list]]:
        return [(batch.username, batch.instance, batch.tweets) for batch in batches]

    async def _store_pending_seen_ids(
        self,
        group_id: str,
        batches: list[PendingTweetBatch],
        seen_map: dict[str, list[str]],
    ) -> None:
        for batch in batches:
            seen_map[batch.username] = self._merge_seen_ids(
                batch.fetched_ids, batch.seen_ids
            )
        await self._put_seen_map(group_id, seen_map)

    @staticmethod
    def _format_merge_threshold(threshold: int) -> str:
        if threshold <= 0:
            return "已关闭"
        return f"{threshold} 条及以上"

    @staticmethod
    def _format_group_schedule(group: ScheduleGroup) -> str:
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

    def _append_group_status(
        self,
        lines: list[str],
        group: ScheduleGroup,
        seen_count: int | None = None,
    ) -> None:
        lines.append(
            "- "
            f"{group.name} ({group.group_id}): "
            f"{'启用' if group.enabled else '关闭'}，"
            f"账号 {len(group.users)}，目标 {len(group.targets)}，"
            f"{self._format_group_schedule(group)}"
        )
        if group.aliases:
            lines.append("  别名: " + self._format_limited_values(group.aliases))
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
            lines.append(f"  已记录账号: {seen_count} 个")
        if group.deferred_publish_enabled:
            lines.append(
                "  暂存发布: 已启用，"
                f"发布时间 {self._format_daily_times(group.deferred_publish_times)}，"
                f"每次最多 {group.deferred_publish_batch_limit} 条"
            )
        else:
            lines.append("  暂存发布: 已关闭")
        daily_times = group.daily_check_times
        if daily_times:
            formatted_times = ", ".join(
                f"{hour:02d}:{minute:02d}" for hour, minute in daily_times
            )
            lines.append(f"  每日时间: {formatted_times}")
        lines.append(
            "  启动立即检查: "
            f"{'已启用' if group.check_on_startup else '已关闭'}"
        )
        lines.append(
            "  无更新提示: "
            f"{'已启用' if group.notify_no_updates else '已关闭'}"
        )
        if group.users:
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
        return _format_limited_values(values, limit=limit)

    async def pending_queue_summary(self, group_name: str = "") -> str:
        group = self._schedule_group(group_name or GLOBAL_GROUP_ID)
        if group is None:
            requested = str(group_name or "").strip() or GLOBAL_GROUP_ID
            available = _format_limited_values(
                [
                    f"{item.name} ({item.group_id})"
                    for item in self._schedule_groups(log_invalid_targets=False)
                ]
            )
            return f"Nitter 暂存队列\n未找到分组: {requested}\n可用分组: {available}"

        summary = await self.storage.get_pending_queue_summary(group.group_id)
        lines = [
            "Nitter 暂存队列",
            f"分组: {group.name} ({group.group_id})",
            f"暂存发布: {'已启用' if group.deferred_publish_enabled else '已关闭'}",
            f"待发布: {summary.pending_count} 条",
            f"失败待重试: {summary.failed_count} 条",
            f"暂存媒体: {summary.media_count} 个",
            f"发布时间: {self._format_daily_times(group.deferred_publish_times)}",
            f"每次发布上限: {group.deferred_publish_batch_limit} 条",
        ]
        if summary.user_counts:
            lines.append(
                "暂存博主: "
                + self._format_pending_user_counts(summary.user_counts)
            )
        if summary.oldest_created_at:
            lines.append(
                "最早暂存: "
                + self._format_timestamp(summary.oldest_created_at)
            )
        if summary.newest_created_at:
            lines.append(
                "最新暂存: "
                + self._format_timestamp(summary.newest_created_at)
            )
        return "\n".join(lines)

    async def check_pending_brief(self, group: ScheduleGroup) -> str:
        if not group.deferred_publish_enabled:
            return "当前分组暂存: 已关闭"

        summary = await self.storage.get_pending_queue_summary(group.group_id)
        suffix = self._group_command_suffix(group)
        lines = [
            "当前分组暂存:",
            f"待发布: {summary.pending_count} 条",
            f"失败待重试: {summary.failed_count} 条",
            "暂存博主: "
            + (
                self._format_pending_user_counts(summary.user_counts)
                if summary.user_counts
                else "无"
            ),
            "下次发布时间: "
            + self._format_next_daily_time(group.deferred_publish_times),
            "",
            "可用命令:",
            f" /推文队列{suffix}",
            f" /推文发布{suffix}",
        ]
        return "\n".join(lines)

    @staticmethod
    def _group_command_suffix(group: ScheduleGroup) -> str:
        if group.group_id == GLOBAL_GROUP_ID:
            return ""
        name = str(group.name or group.group_id).strip()
        return f" {name}" if name else ""

    @staticmethod
    def _format_pending_user_counts(user_counts: list[tuple[str, int]]) -> str:
        values = [
            f"@{username} {count} 条"
            for username, count in user_counts
        ]
        return _format_limited_values(values, separator="; ")

    @staticmethod
    def _format_daily_times(times: list[tuple[int, int]]) -> str:
        if not times:
            return "未配置"
        return ", ".join(f"{hour:02d}:{minute:02d}" for hour, minute in times)

    @staticmethod
    def _format_next_daily_time(times: list[tuple[int, int]]) -> str:
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

    @staticmethod
    def _format_timestamp(timestamp: int) -> str:
        return dt.datetime.fromtimestamp(timestamp, CN_TZ).strftime(
            "%Y-%m-%d %H:%M:%S"
        )

    async def _get_seen_map(
        self, group_id: str = GLOBAL_GROUP_ID
    ) -> dict[str, list[str]]:
        return await self.storage.get_group_seen_map(group_id)

    async def _put_seen_map(
        self, group_id: str, seen_map: dict[str, list[str]]
    ) -> None:
        await self.storage.put_group_seen_map(group_id, seen_map)

    def _merge_seen_ids(self, new_ids: list[str], old_ids: list[str]) -> list[str]:
        return self.storage.merge_seen_ids(new_ids, old_ids)

    def _watch_users(self) -> list[str]:
        return self.config_reader.watch_users()

    def _watch_users_info(self) -> WatchUsersInfo:
        return self.config_reader.watch_users_info()

    def _push_targets(self) -> list[str]:
        return self.config_reader.push_targets()

    def _parse_push_targets(self, log_invalid: bool = True) -> PushTargetParseResult:
        return self.config_reader.parse_push_targets(log_invalid=log_invalid)

    def _get_platform(self) -> str:
        return self.config_reader.platform()

    def _parse_daily_times(self) -> list[tuple[int, int]]:
        return self.config_reader.parse_daily_times()

    def _schedule_groups(
        self, log_invalid_targets: bool = True
    ) -> list[ScheduleGroup]:
        return self.config_reader.schedule_groups(
            log_invalid_targets=log_invalid_targets
        )

    def _schedule_group(
        self, group_name: str = GLOBAL_GROUP_ID, log_invalid_targets: bool = True
    ) -> ScheduleGroup | None:
        return self.config_reader.schedule_group(
            group_name, log_invalid_targets=log_invalid_targets
        )

    def _unknown_group_result(
        self, reason: str, group_name: str
    ) -> ScheduledCheckResult:
        requested = str(group_name or "").strip() or GLOBAL_GROUP_ID
        return ScheduledCheckResult(
            reason=reason,
            group_id=requested,
            group_name=requested,
            skipped_reason="unknown_group",
            available_groups=[
                f"{group.name} ({group.group_id})"
                for group in self._schedule_groups(log_invalid_targets=False)
            ],
            merge_tweet_threshold=self._merge_tweet_threshold(),
        )
