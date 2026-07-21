from __future__ import annotations

import asyncio
import datetime as dt
import inspect
import time
from collections.abc import Awaitable, Callable
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
    from ..config import (
        config_get,
        config_set,
        configured_merge_tweet_threshold,
        migrate_default_group_config,
    )
    from ..ai import (
        TranslationReport,
        format_ai_tweet_summary,
    )
    from ..shared.group_ids import (
        DEFAULT_GROUP_NAME,
        GLOBAL_GROUP_ID,
        is_default_group,
        normalize_group_id,
    )
    from .formatting import (
        _format_limited_values as scheduler_format_limited_values,
        format_daily_times as scheduler_format_daily_times,
        format_group_schedule as scheduler_format_group_schedule,
        format_merge_threshold as scheduler_format_merge_threshold,
        format_next_daily_time as scheduler_format_next_daily_time,
        format_timestamp as scheduler_format_timestamp,
    )
    from .models import (
        BatchSummaryTracker,
        PendingTweetBatch,
        ScheduledCheckResult,
        ScheduledPushResult,
    )
    from .config import (
        PushTargetParseResult,
        ScheduleGroup,
        SchedulerConfigReader,
        WatchUsersInfo,
    )
    from ..storage import StorageAdapter
    from ..rendering import TweetMessageRenderer
    from ..shared import TweetItem
except ImportError:
    from config import (
        config_get,
        config_set,
        configured_merge_tweet_threshold,
        migrate_default_group_config,
    )
    from ai import (
        TranslationReport,
        format_ai_tweet_summary,
    )
    from shared.group_ids import (
        DEFAULT_GROUP_NAME,
        GLOBAL_GROUP_ID,
        is_default_group,
        normalize_group_id,
    )
    from scheduler.formatting import (
        _format_limited_values as scheduler_format_limited_values,
        format_daily_times as scheduler_format_daily_times,
        format_group_schedule as scheduler_format_group_schedule,
        format_merge_threshold as scheduler_format_merge_threshold,
        format_next_daily_time as scheduler_format_next_daily_time,
        format_timestamp as scheduler_format_timestamp,
    )
    from scheduler.models import (
        BatchSummaryTracker,
        PendingTweetBatch,
        ScheduledCheckResult,
        ScheduledPushResult,
    )
    from scheduler.config import (
        PushTargetParseResult,
        ScheduleGroup,
        SchedulerConfigReader,
        WatchUsersInfo,
    )
    from storage import StorageAdapter
    from rendering import TweetMessageRenderer
    from shared import TweetItem


try:
    CN_TZ = ZoneInfo("Asia/Shanghai")
except ZoneInfoNotFoundError:
    CN_TZ = dt.timezone(dt.timedelta(hours=8), name="Asia/Shanghai")


POLL_SECONDS = 30


@dataclass(slots=True)
class SchedulerTaskError:
    message: str
    kind: str = ""

    @classmethod
    def from_exception(cls, exc: Exception) -> "SchedulerTaskError":
        return cls(message=str(exc), kind=type(exc).__name__)


@dataclass(slots=True)
class UserFetchResult:
    index: int
    username: str
    instance: str = ""
    tweets: list[TweetItem] = field(default_factory=list)
    plain_text_filtered: int = 0
    error: SchedulerTaskError | None = None


@dataclass(slots=True)
class PreparedBatchResult:
    batch: PendingTweetBatch
    translation_report: TranslationReport | None = None
    error: SchedulerTaskError | None = None


class NitterTweetScheduler:
    def __init__(
        self, owner, context, config, nitter, media, sender, translator
    ):
        self.owner = owner
        self.context = context
        self.config = config
        self.nitter = nitter
        self.media = media
        self.sender = sender
        self.translator = translator
        migrate_default_group_config(config)
        self.config_reader = SchedulerConfigReader(config, context)
        self.storage = StorageAdapter(owner, config, context)
        self._task: asyncio.Task | None = None
        self._last_interval_slots: dict[str, int] = {}
        self._daily_slots: dict[str, set[str]] = {}
        self._startup_schedule_seeded: set[str] = set()
        self._last_enabled_state: bool | None = None
        self._check_lock = asyncio.Lock()
        self._migration_done = False

    def start(self, reason: str = "") -> None:
        if self._task is not None and not self._task.done():
            logger.info(
                "[NitterTweets] 调度器已在运行 "
                f"({reason}); enabled={self.schedule_enabled}"
            )
            return
        try:
            loop = asyncio.get_running_loop()
            self._task = loop.create_task(self._loop())
            groups = self._schedule_groups(log_invalid_targets=False)
            logger.info(
                "[NitterTweets] 调度器已启动 "
                f"({reason}); enabled={self.schedule_enabled}, "
                f"groups={len(groups)}, "
                f"enabled_groups={sum(1 for group in groups if group.enabled)}, "
                f"watch_users={sum(len(group.users) for group in groups)}, "
                f"push_targets={sum(len(group.targets) for group in groups)}"
            )
        except RuntimeError:
            logger.info(
                f"[NitterTweets] 当前无运行中的事件循环: reason={reason}; "
                "调度器将等待下一次启动钩子"
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
        logger.info("[NitterTweets] 调度器已停止")

    async def _loop(self) -> None:
        logger.info("[NitterTweets] 调度器循环已进入")
        await asyncio.sleep(2)

        # 执行一次性迁移和配置同步
        if not self._migration_done:
            try:
                schedule_groups = self._schedule_groups(log_invalid_targets=False)
                await self.storage.migrate_and_sync(schedule_groups)
                self._migration_done = True
                logger.info("[NitterTweets] 数据迁移与配置同步完成")
            except Exception as exc:
                logger.error(f"[NitterTweets] 数据迁移或同步失败: {exc}", exc_info=True)
                logger.error("[NitterTweets] 调度器将在 5 分钟后重试迁移")
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
                logger.error(f"[NitterTweets] 调度器异常: {exc}", exc_info=True)
                await asyncio.sleep(60)
                continue
            await asyncio.sleep(POLL_SECONDS)

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def schedule_enabled(self) -> bool:
        config_enabled = bool(config_get(self.config, "schedule_enabled", False))
        return config_enabled and any(
            group.enabled
            for group in self._schedule_groups(log_invalid_targets=False)
        )

    @property
    def brief_log_enabled(self) -> bool:
        return bool(config_get(self.config, "brief_log_enabled", True))

    def _log_verbose_info(self, message: str) -> None:
        if not self.brief_log_enabled:
            logger.info(message)

    def _log_check_result(self, result: ScheduledCheckResult) -> None:
        if self.brief_log_enabled and not result.skipped_reason:
            lines = result.format_brief_log_lines()
            if not lines:
                return
            logger.info(lines[0])
            for line in lines[1:]:
                logger.warning(line)
            return

        logger.info(result.format_log_summary())
        self._log_delivery_warning_count(result)

    @staticmethod
    def _log_delivery_warning_count(result: ScheduledCheckResult) -> None:
        if result.delivery_warnings:
            unique_warning_count = len(dict.fromkeys(result.delivery_warnings))
            logger.warning(
                f"[NitterTweets] 发送状态提示：{unique_warning_count} 条"
            )

    def _log_enabled_state(self, enabled: bool) -> None:
        if self._last_enabled_state is enabled:
            return
        self._last_enabled_state = enabled
        if enabled:
            self._log_verbose_info("[NitterTweets] 调度器已启用: schedule_enabled=true")
        else:
            self._log_verbose_info("[NitterTweets] 调度器已闲置: schedule_enabled=false")

    async def _tick(self) -> None:
        now = dt.datetime.now(CN_TZ)
        for group in self._schedule_groups(log_invalid_targets=False):
            if not group.enabled:
                continue
            reasons = self._scheduled_reasons(group, now)
            if reasons:
                self._log_verbose_info(
                    "[NitterTweets] 定时检查已触发: "
                    f"group={group.group_id}, reasons={', '.join(reasons)}"
                )
                await self.run_check(
                    reason=", ".join(reasons),
                    group_name=group.group_id,
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
                self._log_verbose_info(
                    "[NitterTweets] 启动时跳过定时检查: "
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
            )

    def _new_check_result(
        self,
        reason: str,
        group: ScheduleGroup,
        target_override: list[str] | None = None,
    ) -> ScheduledCheckResult:
        targets = list(target_override) if target_override is not None else group.targets
        targets = self._order_targets_for_push(targets)
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
    ) -> ScheduledCheckResult:
        result = self._new_check_result(reason, group, target_override)
        users = result.users
        targets = result.targets
        merge_threshold = self._merge_tweet_threshold()
        result.merge_tweet_threshold = merge_threshold
        pending_batches = []
        immediate_targets, buffered_targets = self._split_immediate_targets(
            targets, merge_threshold
        )
        immediate_batches_sent = 0
        if not users:
            result.skipped_reason = "no_watch_users"
            self._log_check_result(result)
            return result
        if not targets:
            result.skipped_reason = "no_push_targets"
            self._log_check_result(result)
            return result

        seen_map = await self._get_seen_map(group.group_id)
        result.seen_users = len(seen_map)
        fetch_limit = group.scheduled_fetch_limit
        result.fetch_limit = fetch_limit
        target_interval = group.send_target_interval
        user_interval = group.send_user_interval
        group_label = self._push_group_label(group)
        skip_plain_text = bool(group.filter_plain_text_enabled)
        use_fetch_parallel = self._should_use_concurrent_fetch(group)
        use_prepare_parallel = self._should_use_concurrent_prepare(group)
        self._log_verbose_info(
            "[NitterTweets] 定时检查开始: "
            f"group={group.group_id}, reason={reason}, "
            f"users={len(users)}, targets={len(targets)}, "
            f"invalid_targets={len(result.invalid_targets)}, "
            f"fetch_limit={fetch_limit}, qq_merge_threshold={merge_threshold}, "
            f"skip_plain_text={skip_plain_text}, "
            f"拉取并发={'开' if use_fetch_parallel else '关'}, "
            f"拉取数={group.fetch_concurrency}, "
            f"专用镜像={len(group.concurrent_fetch_instances)}, "
            f"准备并发={'开' if use_prepare_parallel else '关'}, "
            f"准备数={group.prepare_concurrency}"
        )
        discovered_batches: list[PendingTweetBatch] = []
        group_plain_text_filtered_total = 0
        fetch_results = await self._fetch_group_users(group, fetch_limit, skip_plain_text)
        for fetch_result in fetch_results:
            username = fetch_result.username
            if fetch_result.error:
                result.failed_users[username] = fetch_result.error.message
                logger.warning(
                    f"[NitterTweets] 定时抓取 @{username} 失败: "
                    f"{fetch_result.error.message}"
                )
                continue

            instance = fetch_result.instance
            tweets = fetch_result.tweets
            plain_text_filtered = fetch_result.plain_text_filtered
            if skip_plain_text and plain_text_filtered > 0:
                group_plain_text_filtered_total += plain_text_filtered
                self._log_verbose_info(
                    f"[NitterTweets] 定时检查 @{username}: "
                    f"已过滤 {plain_text_filtered} 条纯文本推文（无作者上传媒体）"
                )

            tweets = [tweet for tweet in tweets if tweet.status_id]
            if not tweets:
                result.empty_users.append(username)
                self._log_verbose_info(
                    f"[NitterTweets] 定时检查 @{username}: 没有有效推文 ID"
                )
                continue

            fetched_ids = [tweet.status_id for tweet in tweets]
            seen_ids = seen_map.get(username)

            if not isinstance(seen_ids, list):
                seen_map[username] = self.storage.initial_seen_ids(fetched_ids)
                await self._put_seen_map(group.group_id, seen_map)
                result.initialized_users[username] = len(fetched_ids)
                self._log_verbose_info(
                    "[NitterTweets] 首次记录已初始化: "
                    f"group={group.group_id}, username={username}, "
                    f"seen={len(fetched_ids)}"
                )
                continue

            new_tweets, historical_unseen_ids = (
                self._select_new_tweets_after_seen_watermark(tweets, seen_ids)
            )
            if historical_unseen_ids:
                seen_ids = self._merge_seen_ids(historical_unseen_ids, seen_ids)
                seen_map[username] = seen_ids
                await self._put_seen_map(group.group_id, seen_map)
                self._log_verbose_info(
                    "[NitterTweets] 定时检查忽略基准前历史推文: "
                    f"group={group.group_id}, username={username}, "
                    f"ignored={len(historical_unseen_ids)}"
                )

            if new_tweets:
                new_tweets.reverse()
                discovered_batches.append(
                    PendingTweetBatch(
                        username=username,
                        instance=instance,
                        tweets=new_tweets,
                        fetched_ids=fetched_ids,
                        seen_ids=seen_ids,
                        tweet_index=len(new_tweets),
                        tweet_total=len(new_tweets),
                    )
                )
            else:
                result.no_new_users.append(username)
                self._log_verbose_info(
                    f"[NitterTweets] 定时检查无新推文: group={group.group_id}, "
                    f"username={username}"
                )
                seen_map[username] = self._merge_seen_ids(fetched_ids, seen_ids)
                await self._put_seen_map(group.group_id, seen_map)

        if skip_plain_text and group_plain_text_filtered_total > 0:
            result.plain_text_filtered = group_plain_text_filtered_total
            self._log_verbose_info(
                "[NitterTweets] 定时检查已过滤纯文本推文: "
                f"group={group.group_id}, "
                f"filtered={group_plain_text_filtered_total}"
            )

        fetch_failures = dict(result.failed_users)
        check_batch_summary = self._format_push_batch_summary(
            discovered_batches,
            group_label,
            action_text="本次检查发现",
        )
        check_batch_summary = self._append_fetch_failure_summary(
            check_batch_summary,
            fetch_failures,
        )
        immediate_batch_summary_tracker = BatchSummaryTracker(check_batch_summary)
        self._set_discovered_batch_progress(discovered_batches)
        if self._should_use_concurrent_prepare(group):
            pending_batches, immediate_batches_sent = (
                await self._prepare_immediate_batches_concurrently(
                    group,
                    discovered_batches,
                    result,
                    targets[0],
                    seen_map,
                    immediate_targets,
                    buffered_targets,
                    target_interval,
                    user_interval,
                    group_label,
                    immediate_batch_summary_tracker,
                    immediate_batches_sent,
                )
            )
        else:
            pending_batches, immediate_batches_sent = (
                await self._prepare_discovered_batches_serial(
                    group,
                    discovered_batches,
                    result,
                    targets[0],
                    seen_map,
                    immediate_targets,
                    buffered_targets,
                    target_interval,
                    user_interval,
                    group_label,
                    immediate_batch_summary_tracker,
                    immediate_batches_sent,
                )
            )

        result.seen_users = len(seen_map)
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
                    group_label=group_label,
                    batch_summary=check_batch_summary,
                    history_group_id=group.group_id,
                    history_source="scheduled",
                )
                # Buffered/merge targets are not marked as seen during prepare.
                # Write seen only after at least one target accepted the batch.
                for batch in pending_batches:
                    if not batch.delivered_targets:
                        continue
                    status_ids = [
                        tweet.status_id for tweet in batch.tweets if tweet.status_id
                    ]
                    if status_ids:
                        await self._store_incremental_seen_ids(
                            group.group_id,
                            batch.username,
                            status_ids,
                            seen_map,
                        )
            finally:
                for batch in pending_batches:
                    await asyncio.to_thread(self.media.cleanup_after_send, batch.tweets)

        self._log_check_result(result)
        if self._should_notify_no_updates(result, notify_no_updates, group):
            await self._send_no_update_notice(result, target_interval)
        return result

    async def status_summary(self) -> str:
        groups = self._schedule_groups(log_invalid_targets=False)
        default_group = next(
            (item for item in groups if is_default_group(item.group_id)),
            None,
        )
        if not groups:
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
            f"全部分组已记录账号索引: {total_seen_users} 个",
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
                if default_group is not None and item.group_id == default_group.group_id:
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
            if normalize_group_id(group.get("group_id") or group.get("name") or "") == GLOBAL_GROUP_ID:
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

    async def _fetch_group_users(
        self,
        group: ScheduleGroup,
        fetch_limit: int,
        skip_plain_text: bool,
    ) -> list[UserFetchResult]:
        if not self._should_use_concurrent_fetch(group):
            results = []
            for index, username in enumerate(group.users):
                results.append(
                    await self._fetch_group_user(
                        group,
                        index,
                        username,
                        fetch_limit,
                        skip_plain_text,
                        concurrent=False,
                    )
                )
            return results

        semaphore = asyncio.Semaphore(group.fetch_concurrency)

        async def fetch_with_limit(index: int, username: str) -> UserFetchResult:
            async with semaphore:
                return await self._fetch_group_user(
                    group,
                    index,
                    username,
                    fetch_limit,
                    skip_plain_text,
                    concurrent=True,
                )

        tasks = [
            fetch_with_limit(index, username)
            for index, username in enumerate(group.users)
        ]
        return list(await asyncio.gather(*tasks))

    async def _fetch_group_user(
        self,
        group: ScheduleGroup,
        index: int,
        username: str,
        fetch_limit: int,
        skip_plain_text: bool,
        *,
        concurrent: bool,
    ) -> UserFetchResult:
        try:
            if concurrent:
                instance, tweets, plain_text_filtered = (
                    await self.nitter.fetch_tweets_with_stats_from_instances(
                        username,
                        fetch_limit,
                        group.concurrent_fetch_instances,
                        start_index=index,
                        skip_plain_text=skip_plain_text,
                        retry_attempts=3,
                    )
                )
            else:
                instance, tweets, plain_text_filtered = (
                    await self.nitter.fetch_tweets_with_stats(
                        username, fetch_limit, skip_plain_text=skip_plain_text
                    )
                )
        except Exception as exc:
            return UserFetchResult(
                index=index,
                username=username,
                error=SchedulerTaskError.from_exception(exc),
            )
        return UserFetchResult(
            index=index,
            username=username,
            instance=instance,
            tweets=tweets,
            plain_text_filtered=plain_text_filtered,
        )

    @staticmethod
    def _should_use_concurrent_fetch(group: ScheduleGroup) -> bool:
        return (
            bool(group.concurrent_fetch_enabled)
            and bool(group.concurrent_fetch_instances)
            and group.fetch_concurrency > 1
        )

    @staticmethod
    def _should_use_concurrent_prepare(group: ScheduleGroup) -> bool:
        return bool(group.concurrent_prepare_enabled) and group.prepare_concurrency > 1

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
                        "[NitterTweets] 发送无更新提示失败: "
                        f"target={umo}, error=未找到目标平台或平台不支持主动发送"
                    )
            except Exception as exc:
                logger.warning(
                    f"[NitterTweets] 发送无更新提示失败: target={umo}, error={exc}"
                )
            if target_index < len(result.targets) - 1 and target_interval > 0:
                await asyncio.sleep(target_interval)
        self._log_verbose_info(
            f"[NitterTweets] 无更新提示发送完成: success={success}/{len(result.targets)}"
        )

    @staticmethod
    def _set_discovered_batch_progress(
        discovered_batches: list[PendingTweetBatch],
    ) -> None:
        account_total = len(discovered_batches)
        for account_index, discovered_batch in enumerate(discovered_batches, 1):
            discovered_batch.account_index = account_index
            discovered_batch.account_total = account_total

    async def _prepare_discovered_batches_serial(
        self,
        group: ScheduleGroup,
        discovered_batches: list[PendingTweetBatch],
        result: ScheduledCheckResult,
        target_umo: str,
        seen_map: dict[str, list[str]],
        immediate_targets: list[str],
        buffered_targets: list[str],
        target_interval: float,
        user_interval: float,
        group_label: str,
        immediate_batch_summary_tracker: BatchSummaryTracker,
        immediate_batches_sent: int,
    ) -> tuple[list[PendingTweetBatch], int]:
        pending_batches: list[PendingTweetBatch] = []
        for discovered_batch in discovered_batches:
            username = discovered_batch.username
            new_tweets = discovered_batch.tweets
            prepared_count = 0
            for tweet_index, tweet in enumerate(new_tweets, 1):
                batch = self._single_tweet_batch(
                    discovered_batch,
                    tweet,
                    tweet_index,
                    seen_map,
                )
                try:
                    prepared = await self._prepare_immediate_batch(
                        batch, target_umo
                    )
                except Exception as exc:
                    await self._record_prepare_failure(
                        result, username, tweet, tweet_index, [tweet], exc
                    )
                    continue

                await self._handle_immediate_prepare_success(
                    group, prepared, seen_map
                )
                prepared_count += 1
                pending_batches, immediate_batches_sent = (
                    await self._send_or_buffer_immediate_batch(
                        batch,
                        group,
                        pending_batches,
                        result,
                        immediate_targets,
                        buffered_targets,
                        target_interval,
                        user_interval,
                        group_label,
                        immediate_batch_summary_tracker,
                        immediate_batches_sent,
                        seen_map,
                        batch_progress=(tweet_index, len(new_tweets)),
                    )
                )
            self._log_prepare_progress(username, prepared_count, len(new_tweets))
        return pending_batches, immediate_batches_sent

    async def _prepare_batches_concurrently(
        self,
        batches: list[PendingTweetBatch],
        concurrency: int,
        prepare_one: Callable[[PendingTweetBatch], Awaitable[PreparedBatchResult]],
    ) -> list[PreparedBatchResult]:
        semaphore = asyncio.Semaphore(concurrency)

        async def prepare(batch: PendingTweetBatch) -> PreparedBatchResult:
            async with semaphore:
                try:
                    return await prepare_one(batch)
                except Exception as exc:
                    return PreparedBatchResult(
                        batch=batch,
                        error=SchedulerTaskError.from_exception(exc),
                    )

        return list(await asyncio.gather(*[prepare(batch) for batch in batches]))


    async def _prepare_immediate_batches_concurrently(
        self,
        group: ScheduleGroup,
        discovered_batches: list[PendingTweetBatch],
        result: ScheduledCheckResult,
        target_umo: str,
        seen_map: dict[str, list[str]],
        immediate_targets: list[str],
        buffered_targets: list[str],
        target_interval: float,
        user_interval: float,
        group_label: str,
        immediate_batch_summary_tracker: BatchSummaryTracker,
        immediate_batches_sent: int,
    ) -> tuple[list[PendingTweetBatch], int]:
        single_batches: list[PendingTweetBatch] = []
        for discovered_batch in discovered_batches:
            for tweet_index, tweet in enumerate(discovered_batch.tweets, 1):
                single_batches.append(
                    self._single_tweet_batch(
                        discovered_batch,
                        tweet,
                        tweet_index,
                        seen_map,
                    )
                )

        prepared_results = await self._prepare_batches_concurrently(
            single_batches,
            group.prepare_concurrency,
            lambda batch: self._prepare_immediate_batch(batch, target_umo),
        )
        pending_batches: list[PendingTweetBatch] = []
        prepared_count_by_user: dict[str, int] = {}
        total_by_user: dict[str, int] = {}
        for batch in discovered_batches:
            total_by_user[batch.username] = (
                total_by_user.get(batch.username, 0) + len(batch.tweets)
            )
        consumed_count = 0
        try:
            for prepared in prepared_results:
                batch = prepared.batch
                tweet = batch.tweets[0]
                tweet_index = batch.tweet_index
                consumed_count += 1
                if prepared.error:
                    await self._record_prepare_failure(
                        result,
                        batch.username,
                        tweet,
                        tweet_index,
                        batch.tweets,
                        prepared.error,
                    )
                    continue

                await self._handle_immediate_prepare_success(
                    group, prepared, seen_map
                )
                prepared_count_by_user[batch.username] = (
                    prepared_count_by_user.get(batch.username, 0) + 1
                )
                pending_batches, immediate_batches_sent = (
                    await self._send_or_buffer_immediate_batch(
                        batch,
                        group,
                        pending_batches,
                        result,
                        immediate_targets,
                        buffered_targets,
                        target_interval,
                        user_interval,
                        group_label,
                        immediate_batch_summary_tracker,
                        immediate_batches_sent,
                        seen_map,
                        batch_progress=(tweet_index, batch.tweet_total),
                    )
                )
        except BaseException:
            for remaining in prepared_results[consumed_count:]:
                await asyncio.to_thread(
                    self.media.cleanup_after_send, remaining.batch.tweets
                )
            raise

        for discovered_batch in discovered_batches:
            prepared_count = prepared_count_by_user.get(discovered_batch.username, 0)
            self._log_prepare_progress(
                discovered_batch.username,
                prepared_count,
                total_by_user.get(discovered_batch.username, 0),
            )
        return pending_batches, immediate_batches_sent


    async def _prepare_immediate_batch(
        self,
        batch: PendingTweetBatch,
        target_umo: str,
    ) -> PreparedBatchResult:
        translation_report = await self.translator.attach_translations(
            batch.tweets, target_umo
        )
        await self.media.attach_media(batch.tweets)
        return PreparedBatchResult(
            batch=batch,
            translation_report=translation_report,
        )

    @staticmethod
    def _single_tweet_batch(
        discovered_batch: PendingTweetBatch,
        tweet: TweetItem,
        tweet_index: int,
        seen_map: dict[str, list[str]],
    ) -> PendingTweetBatch:
        return PendingTweetBatch(
            username=discovered_batch.username,
            instance=discovered_batch.instance,
            tweets=[tweet],
            fetched_ids=[tweet.status_id] if tweet.status_id else [],
            seen_ids=seen_map.get(discovered_batch.username, []),
            account_index=discovered_batch.account_index,
            account_total=discovered_batch.account_total,
            tweet_index=tweet_index,
            tweet_total=len(discovered_batch.tweets),
        )

    async def _record_prepare_failure(
        self,
        result: ScheduledCheckResult,
        username: str,
        tweet: TweetItem,
        tweet_index: int,
        tweets: list[TweetItem],
        error: SchedulerTaskError | Exception,
    ) -> None:
        status_id = tweet.status_id or f"index-{tweet_index}"
        if isinstance(error, SchedulerTaskError):
            error_message = error.message
        else:
            error_message = str(error)
        await asyncio.to_thread(self.media.cleanup_after_send, tweets)
        result.failed_users[f"{username}:{status_id}"] = (
            f"推文准备失败: {error_message}"
        )
        logger.warning(
            "[NitterTweets] 定时推送准备失败: "
            f"username={username}, status={status_id}, error={error_message}"
        )



    async def _handle_immediate_prepare_success(
        self,
        group: ScheduleGroup,
        prepared: PreparedBatchResult,
        seen_map: dict[str, list[str]],
    ) -> None:
        batch = prepared.batch
        self._log_ai_process_results(
            batch.username,
            batch.tweets,
            prepared.translation_report,
            progress_index=batch.tweet_index,
            progress_total=batch.tweet_total,
        )

    def _log_prepare_progress(
        self,
        username: str,
        prepared_count: int,
        total_count: int,
    ) -> None:
        self._log_verbose_info(
            f"[NitterTweets] prepared @{username} {prepared_count}/"
            f"{total_count} new tweets for scheduled push"
        )

    async def _send_or_buffer_immediate_batch(
        self,
        batch: PendingTweetBatch,
        group: ScheduleGroup,
        pending_batches: list[PendingTweetBatch],
        result: ScheduledCheckResult,
        immediate_targets: list[str],
        buffered_targets: list[str],
        target_interval: float,
        user_interval: float,
        group_label: str,
        immediate_batch_summary_tracker: BatchSummaryTracker,
        immediate_batches_sent: int,
        seen_map: dict[str, list[str]],
        *,
        batch_progress: tuple[int, int],
    ) -> tuple[list[PendingTweetBatch], int]:
        if buffered_targets:
            try:
                if immediate_targets:
                    if immediate_batches_sent > 0 and user_interval > 0:
                        await asyncio.sleep(user_interval)
                    success_count = await self._send_per_user_updates(
                        [batch],
                        result,
                        immediate_targets,
                        target_interval,
                        0.0,
                        group_label=group_label,
                        batch_summary_tracker=immediate_batch_summary_tracker,
                        batch_progress=batch_progress,
                        history_group_id=group.group_id,
                        history_source="scheduled",
                    )
                    if success_count and batch.tweets[0].status_id:
                        await self._store_incremental_seen_ids(
                            group.group_id,
                            batch.username,
                            [batch.tweets[0].status_id],
                            seen_map,
                        )
                    immediate_batches_sent += 1
                pending_batches.append(batch)
            except BaseException:
                await asyncio.to_thread(self.media.cleanup_after_send, batch.tweets)
                raise
            return pending_batches, immediate_batches_sent

        try:
            if immediate_targets:
                if immediate_batches_sent > 0 and user_interval > 0:
                    await asyncio.sleep(user_interval)
                success_count = await self._send_per_user_updates(
                    [batch],
                    result,
                    immediate_targets,
                    target_interval,
                    0.0,
                    group_label=group_label,
                    batch_summary_tracker=immediate_batch_summary_tracker,
                    batch_progress=batch_progress,
                    history_group_id=group.group_id,
                    history_source="scheduled",
                )
                if success_count and batch.tweets[0].status_id:
                    await self._store_incremental_seen_ids(
                        group.group_id,
                        batch.username,
                        [batch.tweets[0].status_id],
                        seen_map,
                    )
                immediate_batches_sent += 1
        finally:
            await asyncio.to_thread(self.media.cleanup_after_send, batch.tweets)
        return pending_batches, immediate_batches_sent

    async def _send_per_user_updates(
        self,
        batches,
        result: ScheduledCheckResult,
        targets: list[str],
        target_interval: float,
        user_interval: float,
        merge_existing_stats: bool = False,
        group_label: str = "",
        batch_summary: str = "",
        batch_summary_tracker: BatchSummaryTracker | None = None,
        batch_progress: tuple[int, int] | None = None,
        on_target_delivered=None,
        history_group_id: str = "",
        history_source: str = "scheduled",
    ) -> int:
        if batch_summary and batch_summary_tracker is None:
            batch_summary_tracker = BatchSummaryTracker(batch_summary)

        total_success = 0
        for batch_index, batch in enumerate(batches):
            success = 0
            attempted = 0
            for target_index, umo in enumerate(targets):
                if umo in batch.delivered_targets:
                    continue
                attempted += 1
                try:
                    header_text = self._scheduled_update_header(batch, batch_progress)
                    target_batch_summary = (
                        batch_summary_tracker.for_target(umo)
                        if batch_summary_tracker is not None
                        else ""
                    )
                    if target_batch_summary:
                        summary_outcome = await self.sender.send_summary_to_umo(
                            self.context,
                            umo,
                            target_batch_summary,
                        )
                        if summary_outcome.success:
                            if batch_summary_tracker is not None:
                                batch_summary_tracker.mark_delivered(umo)
                        else:
                            logger.warning(
                                "[NitterTweets] 定时推送概括发送失败: "
                                f"target={umo}, error={summary_outcome.error}"
                            )
                        if summary_outcome.warning:
                            result.delivery_warnings.append(summary_outcome.warning)
                    tweet_start_index = self._scheduled_tweet_start_index(
                        batch,
                        batch_progress,
                    )
                    outcome = await self.sender.send_to_umo_with_outcome(
                        self.context,
                        umo,
                        batch.username,
                        batch.instance,
                        batch.tweets,
                        group_label=group_label,
                        header_text=header_text,
                        batch_summary="",
                        tweet_start_index=tweet_start_index,
                    )
                    if outcome.success:
                        await self._mark_batch_target_delivered(
                            batch, umo, on_target_delivered
                        )
                        await self._record_batch_push_history(
                            history_group_id,
                            batch,
                            umo,
                            history_source,
                            delivery_status=getattr(
                                outcome, "delivery_status", "success"
                            ),
                            delivery_error=getattr(outcome, "delivery_error", ""),
                        )
                        success += 1
                    if outcome.warning:
                        result.delivery_warnings.append(outcome.warning)
                except Exception as exc:
                    logger.warning(
                        f"[NitterTweets] 定时推送失败: username={batch.username}, "
                        f"target={umo}, error={exc}"
                    )
                if target_index < len(targets) - 1 and target_interval > 0:
                    await asyncio.sleep(target_interval)
            self._record_scheduled_push(
                result,
                batch,
                success,
                attempted,
                merge_existing_stats=merge_existing_stats,
            )
            total_success += success
            if batch_progress:
                progress_text = f" progress={batch_progress[0]}/{batch_progress[1]}"
            elif len(batches) > 1:
                progress_text = f" progress={batch_index + 1}/{len(batches)}"
            else:
                progress_text = ""
            self._log_verbose_info(
                f"[NitterTweets] 推送完成{progress_text}: "
                f"username={batch.username}, tweets={len(batch.tweets)}, "
                f"targets={success}/{len(targets)}"
            )
            if batch_index < len(batches) - 1 and user_interval > 0:
                await asyncio.sleep(user_interval)
        return total_success

    @staticmethod
    def _scheduled_update_header(
        batch: PendingTweetBatch, batch_progress: tuple[int, int] | None = None
    ) -> str:
        if batch_progress:
            tweet_index, tweet_total = batch_progress
        else:
            tweet_index = batch.tweet_index
            tweet_total = batch.tweet_total
        if tweet_total <= 0:
            tweet_total = max(len(batch.tweets), 1)
        if tweet_index <= 0:
            tweet_index = min(len(batch.tweets), tweet_total) or 1

        lines = [f"@{batch.username} 新推文"]
        if batch.account_index > 0 and batch.account_total > 0:
            lines.append(f"所有账号：{batch.account_index}/{batch.account_total}")
        lines.append(f"该账号推文：{tweet_index}/{tweet_total}")
        return "\n".join(lines)

    @staticmethod
    def _scheduled_tweet_start_index(
        batch: PendingTweetBatch,
        batch_progress: tuple[int, int] | None = None,
    ) -> int:
        if batch_progress and batch_progress[0] > 0:
            return batch_progress[0]
        if batch.tweet_index > 0:
            return max(batch.tweet_index - len(batch.tweets) + 1, 1)
        return 1

    def _log_ai_process_results(
        self,
        username: str,
        tweets,
        translation_report=None,
        progress_index: int = 0,
        progress_total: int = 0,
    ) -> None:
        total = progress_total or len(tweets)
        start = progress_index or 1
        if self.brief_log_enabled:
            return
        for offset, tweet in enumerate(tweets):
            logger.info(
                format_ai_tweet_summary(
                    username,
                    tweet,
                    translation_report,
                    start + offset,
                    total,
                )
            )

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
        return repr((batch.username, batch.instance, status_ids))

    async def _record_batch_push_history(
        self,
        group_id: str,
        batch: PendingTweetBatch,
        target_umo: str,
        source: str,
        delivery_status: str = "success",
        delivery_error: str = "",
    ) -> None:
        if not group_id:
            return
        for tweet in batch.tweets:
            if not getattr(tweet, "status_id", ""):
                continue
            try:
                await self.storage.record_push_history(
                    group_id,
                    batch.username,
                    tweet,
                    target_umo,
                    source,
                    batch.instance,
                    delivery_status,
                    delivery_error,
                )
            except Exception as exc:
                logger.warning(
                    "[NitterTweets] 记录推送历史失败: "
                    f"group={group_id}, username={batch.username}, "
                    f"status={tweet.status_id}, target={target_umo}, error={exc}"
                )

    async def _send_merged_updates(
        self,
        batches: list[PendingTweetBatch],
        result: ScheduledCheckResult,
        targets: list[str],
        target_interval: float,
        group_label: str = "",
        batch_summary: str = "",
        on_target_delivered=None,
        history_group_id: str = "",
        history_source: str = "scheduled",
    ) -> None:
        success = 0
        attempts = 0
        for target_index, umo in enumerate(targets):
            target_batches = [
                batch for batch in batches if umo not in batch.delivered_targets
            ]
            if not target_batches:
                continue
            attempts += 1
            try:
                outcome = await self.sender.send_merged_to_umo(
                    self.context,
                    umo,
                    self._tweet_batches(target_batches),
                    group_label=group_label,
                    batch_summary=batch_summary,
                )
                if outcome.success:
                    for batch in target_batches:
                        await self._mark_batch_target_delivered(
                            batch, umo, on_target_delivered
                        )
                        await self._record_batch_push_history(
                            history_group_id,
                            batch,
                            umo,
                            history_source,
                            delivery_status=getattr(
                                outcome, "delivery_status", "success"
                            ),
                            delivery_error=getattr(outcome, "delivery_error", ""),
                        )
                    success += 1
                    if outcome.warning:
                        result.delivery_warnings.append(outcome.warning)
                    if outcome.mode not in {
                        "full_forward",
                        "raw_forward",
                        "forward_without_videos",
                        "raw_forward_without_videos",
                        "uncertain_delivery",
                    }:
                        self._log_verbose_info(
                            f"[NitterTweets] QQ 合并推送使用普通发送路径：mode={outcome.mode}"
                        )
                else:
                    logger.warning(
                        f"[NitterTweets] 定时合并推送失败: target={umo}, "
                        f"error={outcome.error}"
                    )
            except Exception as exc:
                logger.warning(
                    f"[NitterTweets] 定时合并推送失败: target={umo}, error={exc}"
                )
            if target_index < len(targets) - 1 and target_interval > 0:
                await asyncio.sleep(target_interval)

        result.merged_push_success_targets = success
        result.merged_push_total_targets = attempts
        self._log_verbose_info(
            f"[NitterTweets] 合并推送完成: tweets={result.new_tweet_count}, "
            f"users={len(batches)}, qq_targets={success}/{attempts}"
        )




    async def _send_prepared_batches(
        self,
        batches: list[PendingTweetBatch],
        result: ScheduledCheckResult,
        targets: list[str],
        target_interval: float,
        user_interval: float,
        record_merge_placeholders: bool = True,
        merge_existing_stats: bool = False,
        group_label: str = "",
        batch_summary: str = "",
        on_target_delivered=None,
        history_group_id: str = "",
        history_source: str = "scheduled",
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
                    group_label=group_label,
                    batch_summary=batch_summary,
                    on_target_delivered=on_target_delivered,
                    history_group_id=history_group_id,
                    history_source=history_source,
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
                batches,
                result,
                merge_targets,
                target_interval,
                group_label=group_label,
                batch_summary=batch_summary,
                on_target_delivered=on_target_delivered,
                history_group_id=history_group_id,
                history_source=history_source,
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
            group_label=group_label,
            batch_summary=batch_summary,
            on_target_delivered=on_target_delivered,
            history_group_id=history_group_id,
            history_source=history_source,
        )

    @staticmethod
    async def _mark_batch_target_delivered(
        batch: PendingTweetBatch,
        target: str,
        on_target_delivered=None,
    ) -> None:
        if on_target_delivered is None:
            batch.delivered_targets.add(target)
            return
        result = on_target_delivered(batch, target)
        if inspect.isawaitable(result):
            await result
        batch.delivered_targets.add(target)

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

    def _order_targets_for_push(self, targets: list[str]) -> list[str]:
        ordinary_targets = []
        merge_targets = []
        for umo in targets:
            if self.sender.supports_merged_forward_for_umo(self.context, umo):
                merge_targets.append(umo)
            else:
                ordinary_targets.append(umo)
        return ordinary_targets + merge_targets

    @staticmethod
    def _tweet_batches(batches: list[PendingTweetBatch]) -> list[tuple[str, str, list]]:
        return [(batch.username, batch.instance, batch.tweets) for batch in batches]

    @staticmethod
    def _format_push_batch_summary(
        batches: list[PendingTweetBatch],
        group_label: str,
        action_text: str,
    ) -> str:
        if not batches:
            return ""
        return TweetMessageRenderer.format_batch_summary(
            NitterTweetScheduler._tweet_batches(batches),
            group_label=group_label,
            action_text=action_text,
        )

    @staticmethod
    def _append_fetch_failure_summary(
        summary: str,
        failed_users: dict[str, str],
    ) -> str:
        if not failed_users:
            return summary
        failed_items = [
            f"@{user}: {error}"
            for user, error in failed_users.items()
        ]
        failure_summary = (
            "抓取失败："
            + scheduler_format_limited_values(
                failed_items,
                limit=5,
                separator="；",
            )
        )
        if summary.strip():
            return f"{summary.rstrip()}\n{failure_summary}"
        return failure_summary

    @staticmethod
    def _push_group_label(group: ScheduleGroup) -> str:
        if is_default_group(group.group_id):
            return DEFAULT_GROUP_NAME
        return str(group.name or group.group_id).strip() or group.group_id


    async def _store_incremental_seen_ids(
        self,
        group_id: str,
        username: str,
        status_ids: list[str],
        seen_map: dict[str, list[str]],
    ) -> None:
        ids = [str(item) for item in status_ids if item]
        if not ids:
            return
        current = seen_map.get(username, [])
        if not isinstance(current, list):
            current = []
        seen_map[username] = self._merge_seen_ids(ids, current)
        await self.storage.add_seen_ids(group_id, username, ids)

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
            lines.append(f"  已记录账号索引: {seen_count} 个")
        daily_times = group.daily_check_times
        if daily_times:
            formatted_times = ", ".join(
                f"{hour:02d}:{minute:02d}" for hour, minute in daily_times
            )
            lines.append(f"  每日时间: {formatted_times}")
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
        return scheduler_format_limited_values(values, limit=limit)

    @staticmethod
    def _format_daily_times(times: list[tuple[int, int]]) -> str:
        return scheduler_format_daily_times(times)
    @staticmethod
    def _format_next_daily_time(times: list[tuple[int, int]]) -> str:
        return scheduler_format_next_daily_time(times)
    @staticmethod
    def _format_timestamp(timestamp: int) -> str:
        return scheduler_format_timestamp(timestamp)
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

    @classmethod
    def _select_new_tweets_after_seen_watermark(
        cls,
        tweets: list[TweetItem],
        seen_ids: list[str],
    ) -> tuple[list[TweetItem], list[str]]:
        seen_set = set(str(item) for item in seen_ids)
        watermark = cls._max_numeric_status_id(seen_ids)
        new_tweets: list[TweetItem] = []
        historical_unseen_ids: list[str] = []

        for tweet in tweets:
            status_id = str(tweet.status_id or "")
            if not status_id or status_id in seen_set:
                continue

            status_number = cls._parse_numeric_status_id(status_id)
            if (
                watermark is not None
                and status_number is not None
                and status_number <= watermark
            ):
                historical_unseen_ids.append(status_id)
                continue

            new_tweets.append(tweet)

        return new_tweets, historical_unseen_ids

    @classmethod
    def _max_numeric_status_id(cls, seen_ids: list[str]) -> int | None:
        numeric_ids = [
            status_number
            for status_id in seen_ids
            if (status_number := cls._parse_numeric_status_id(str(status_id)))
            is not None
        ]
        if not numeric_ids:
            return None
        return max(numeric_ids)

    @staticmethod
    def _parse_numeric_status_id(status_id: str) -> int | None:
        value = str(status_id or "").strip()
        if not value or not value.isdigit():
            return None
        return int(value)

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
