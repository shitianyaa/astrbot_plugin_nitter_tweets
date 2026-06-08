from __future__ import annotations

import asyncio
import datetime as dt
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
    from .seen_store import GLOBAL_GROUP_ID, SeenStore
    from .utils import (
        configured_merge_tweet_threshold,
    )
except ImportError:
    from scheduler_config import (
        PushTargetParseResult,
        ScheduleGroup,
        SchedulerConfigReader,
        WatchUsersInfo,
    )
    from seen_store import GLOBAL_GROUP_ID, SeenStore
    from utils import (
        configured_merge_tweet_threshold,
    )


try:
    CN_TZ = ZoneInfo("Asia/Shanghai")
except ZoneInfoNotFoundError:
    CN_TZ = dt.timezone(dt.timedelta(hours=8), name="Asia/Shanghai")


POLL_SECONDS = 30


@dataclass(slots=True)
class ScheduledPushResult:
    username: str
    new_count: int
    success_targets: int
    total_targets: int


@dataclass(slots=True)
class PendingTweetBatch:
    username: str
    instance: str
    tweets: list
    fetched_ids: list[str]
    seen_ids: list[str]


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
            }.get(self.skipped_reason, self.skipped_reason)
            lines.append(f"检查跳过: {reason_text}")
            if self.available_groups:
                lines.append("可用分组: " + ", ".join(self.available_groups))

        if self.initialized_users:
            items = [
                f"@{username}({count} 条)"
                for username, count in self.initialized_users.items()
            ]
            lines.append("首次记录: " + ", ".join(items))

        if self.pushes and self.push_mode == "merged":
            items = [
                f"@{item.username} {item.new_count} 条"
                for item in self.pushes
            ]
            lines.append("新推文: " + "; ".join(items))
        elif self.pushes:
            items = [
                f"@{item.username} {item.new_count} 条，推送 {item.success_targets}/{item.total_targets}"
                for item in self.pushes
            ]
            lines.append("新推文: " + "; ".join(items))

        if self.merged_push_total_targets:
            lines.append(
                "QQ 合并推送: "
                f"{self.merged_push_success_targets}/{self.merged_push_total_targets}"
            )

        if self.no_new_users:
            lines.append("无新推文: " + ", ".join(f"@{user}" for user in self.no_new_users))

        if self.empty_users:
            lines.append("RSS 无有效推文 ID: " + ", ".join(f"@{user}" for user in self.empty_users))

        if self.failed_users:
            items = [f"@{user}: {error}" for user, error in self.failed_users.items()]
            lines.append("失败: " + "; ".join(items))

        if self.invalid_targets:
            lines.append("无效推送目标: " + ", ".join(self.invalid_targets))

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
        self.seen_store = SeenStore(owner)
        self._task: asyncio.Task | None = None
        self._last_interval_slots: dict[str, int] = {}
        self._daily_slots: dict[str, set[str]] = {}
        self._startup_schedule_seeded: set[str] = set()
        self._last_enabled_state: bool | None = None
        self._check_lock = asyncio.Lock()

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
        logger.info("[NitterTweets] scheduler stopped")

    async def _loop(self) -> None:
        logger.info("[NitterTweets] scheduler loop entered")
        await asyncio.sleep(2)
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
        return any(
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
            if not reasons:
                continue
            logger.info(
                "[NitterTweets] scheduled check triggered: "
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
            return await self._run_check_unlocked(group, reason, notify_no_updates)

    def _new_check_result(
        self, reason: str, group: ScheduleGroup
    ) -> ScheduledCheckResult:
        return ScheduledCheckResult(
            reason=reason,
            group_id=group.group_id,
            group_name=group.name,
            users=group.users,
            targets=group.targets,
            invalid_targets=group.invalid_targets,
        )

    async def _run_check_unlocked(
        self,
        group: ScheduleGroup,
        reason: str,
        notify_no_updates: bool | None,
    ) -> ScheduledCheckResult:
        result = self._new_check_result(reason, group)
        users = result.users
        targets = result.targets
        merge_threshold = self._merge_tweet_threshold()
        result.merge_tweet_threshold = merge_threshold
        pending_batches = []
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
                seen_map[username] = self.seen_store.initial_seen_ids(fetched_ids)
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
                    await self.media.attach_media(new_tweets)
                    if self.enricher is not None:
                        await self.enricher.attach_enrichments(new_tweets, targets[0])
                except Exception as exc:
                    result.failed_users[username] = f"prepare failed: {exc}"
                    logger.warning(
                        f"[NitterTweets] scheduled prepare @{username} failed: {exc}"
                    )
                    continue

                pending_batches.append(
                    PendingTweetBatch(
                        username=username,
                        instance=instance,
                        tweets=new_tweets,
                        fetched_ids=fetched_ids,
                        seen_ids=seen_ids,
                    )
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

        if pending_batches:
            await self._store_pending_seen_ids(group.group_id, pending_batches, seen_map)

        if self._should_merge_batches(pending_batches, merge_threshold):
            merge_targets, ordinary_targets = self._split_merge_targets(targets)
        else:
            merge_targets, ordinary_targets = [], targets

        if merge_targets:
            result.push_mode = "mixed" if ordinary_targets else "merged"
            if ordinary_targets:
                await self._send_per_user_updates(
                    pending_batches,
                    result,
                    ordinary_targets,
                    target_interval,
                    user_interval,
                )
                if target_interval > 0:
                    await asyncio.sleep(target_interval)
            else:
                for batch in pending_batches:
                    result.pushes.append(
                        ScheduledPushResult(
                            username=batch.username,
                            new_count=len(batch.tweets),
                            success_targets=0,
                            total_targets=0,
                        )
                    )
            await self._send_merged_updates(
                self._tweet_batches(pending_batches),
                result,
                merge_targets,
                target_interval,
            )
        else:
            result.push_mode = "per_user"
            await self._send_per_user_updates(
                pending_batches, result, ordinary_targets, target_interval, user_interval
            )

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
        group = next(
            (item for item in groups if item.group_id == GLOBAL_GROUP_ID),
            groups[0] if groups else None,
        )
        if group is None:
            return "Nitter 定时检查状态\n没有可用分组。"

        watch_info = group.users_info
        users = group.users
        target_info = group.target_info
        seen_map = await self._get_seen_map(group.group_id)
        daily_times = group.daily_check_times
        enabled_groups = [item for item in groups if item.enabled]

        lines = [
            "Nitter 定时检查状态",
            f"调度器: {'运行中' if self.is_running else '未运行'}",
            f"总开关: {'已启用' if self.schedule_enabled else '已关闭'}",
            f"分组数量: {len(groups)} 个（启用 {len(enabled_groups)} 个）",
            f"分组: {group.name} ({group.group_id})",
            f"启动立即检查: {'已启用' if group.check_on_startup else '已关闭'}",
            f"间隔检查: {'已启用' if group.interval_check_enabled else '已关闭'} / {group.check_interval_minutes} 分钟",
            f"每日定点: {'已启用' if group.daily_check_enabled else '已关闭'}",
            f"无更新提示: {'已启用' if group.notify_no_updates else '已关闭'}",
            f"QQ 合并阈值: {self._format_merge_threshold(self._merge_tweet_threshold())}",
            f"关注账号: {len(users)} 个（配置 {watch_info.raw_count} 项，重复 {len(watch_info.duplicates)} 项，无效 {len(watch_info.invalid_entries)} 项）",
            f"推送目标: {len(target_info.targets)} 个",
            f"无效目标: {len(target_info.invalid_targets)} 个",
            f"已记录账号: {len(seen_map)} 个",
        ]
        if daily_times:
            formatted_times = ", ".join(f"{hour:02d}:{minute:02d}" for hour, minute in daily_times)
            lines.append(f"每日时间: {formatted_times}")
        if users:
            lines.append("账号列表: " + ", ".join(f"@{user}" for user in users))
        if watch_info.duplicates:
            lines.append("重复订阅: " + ", ".join(watch_info.duplicates[:8]))
        if watch_info.invalid_entries:
            lines.append("无效订阅: " + ", ".join(watch_info.invalid_entries[:8]))
        if target_info.targets:
            lines.append("解析目标:")
            for umo in target_info.targets[:8]:
                lines.append(f"- {umo}")
            if len(target_info.targets) > 8:
                lines.append(f"- ... 还有 {len(target_info.targets) - 8} 个")
        if target_info.invalid_targets:
            lines.append("无效目标: " + ", ".join(target_info.invalid_targets))
        if len(groups) > 1:
            lines.append("分组列表:")
            for item in groups:
                self._append_group_status(lines, item)
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
            result.pushes.append(
                ScheduledPushResult(
                    username=batch.username,
                    new_count=len(batch.tweets),
                    success_targets=success,
                    total_targets=len(targets),
                )
            )
            logger.info(
                f"[NitterTweets] pushed @{batch.username} {len(batch.tweets)} new tweets "
                f"to {success}/{len(targets)} targets"
            )
            if batch_index < len(batches) - 1 and user_interval > 0:
                await asyncio.sleep(user_interval)

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

    def _merge_tweet_threshold(self) -> int:
        return configured_merge_tweet_threshold(self.config)

    @staticmethod
    def _should_merge_batches(batches: list[PendingTweetBatch], threshold: int) -> bool:
        if threshold <= 0:
            return False
        return sum(len(batch.tweets) for batch in batches) >= threshold

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

    def _append_group_status(self, lines: list[str], group: ScheduleGroup) -> None:
        lines.append(
            "- "
            f"{group.name} ({group.group_id}): "
            f"{'启用' if group.enabled else '关闭'}，"
            f"账号 {len(group.users)}，目标 {len(group.targets)}，"
            f"{self._format_group_schedule(group)}"
        )
        if group.aliases:
            lines.append("  别名: " + self._format_limited_values(group.aliases))
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
    def _format_limited_values(values: list[str], limit: int = 8) -> str:
        shown = [str(item) for item in values[:limit]]
        if len(values) > limit:
            shown.append(f"... 还有 {len(values) - limit} 个")
        return ", ".join(shown)

    async def _get_seen_map(
        self, group_id: str = GLOBAL_GROUP_ID
    ) -> dict[str, list[str]]:
        return await self.seen_store.get_group_seen_map(group_id)

    async def _put_seen_map(
        self, group_id: str, seen_map: dict[str, list[str]]
    ) -> None:
        await self.seen_store.put_group_seen_map(group_id, seen_map)

    def _merge_seen_ids(self, new_ids: list[str], old_ids: list[str]) -> list[str]:
        return self.seen_store.merge_seen_ids(new_ids, old_ids)

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
