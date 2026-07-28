from __future__ import annotations

import asyncio
import copy
import datetime as dt
import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from astrbot.api import logger

try:
    from ..config import (
        config_get,
        migrate_default_group_config,
        parse_config_bool,
        resolve_hide_original_when_translated,
    )
    from ..shared import format_subscription_source
    from ..shared.group_ids import GLOBAL_GROUP_ID
    from ..storage import StorageAdapter
    from .config import (
        PushTargetParseResult,
        ScheduleGroup,
        SchedulerConfigReader,
        WatchUsersInfo,
    )
    from .models import (
        BatchSummaryTracker,
        PendingTweetBatch,
        PreparedBatchResult,
        ScheduledCheckResult,
        SchedulerTaskError,
        UserFetchResult,
    )
    from .runner_fetch import SchedulerFetchMixin
    from .runner_prepare import SchedulerPrepareMixin
    from .runner_seen import SchedulerSeenMixin
    from .runner_send import SchedulerSendMixin
    from .runner_status import SchedulerStatusMixin
except ImportError:
    from config import (
        config_get,
        migrate_default_group_config,
        parse_config_bool,
        resolve_hide_original_when_translated,
    )
    from scheduler.config import (
        PushTargetParseResult,
        ScheduleGroup,
        SchedulerConfigReader,
        WatchUsersInfo,
    )
    from scheduler.models import (
        BatchSummaryTracker,
        PendingTweetBatch,
        PreparedBatchResult,  # noqa: F401  拆分前定义于此，保留再导出
        ScheduledCheckResult,
        SchedulerTaskError,  # noqa: F401  拆分前定义于此，保留再导出
        UserFetchResult,  # noqa: F401  拆分前定义于此，保留再导出
    )
    from scheduler.runner_fetch import SchedulerFetchMixin
    from scheduler.runner_prepare import SchedulerPrepareMixin
    from scheduler.runner_seen import SchedulerSeenMixin
    from scheduler.runner_send import SchedulerSendMixin
    from scheduler.runner_status import SchedulerStatusMixin
    from shared import format_subscription_source
    from shared.group_ids import GLOBAL_GROUP_ID
    from storage import StorageAdapter


try:
    CN_TZ = ZoneInfo("Asia/Shanghai")
except ZoneInfoNotFoundError:
    CN_TZ = dt.timezone(dt.timedelta(hours=8), name="Asia/Shanghai")


POLL_SECONDS = 30


class NitterTweetScheduler(
    SchedulerFetchMixin,
    SchedulerPrepareMixin,
    SchedulerSendMixin,
    SchedulerSeenMixin,
    SchedulerStatusMixin,
):
    def __init__(
        self,
        owner,
        context,
        config,
        nitter,
        media,
        sender,
        translator,
        html_backend=None,
    ):
        self.owner = owner
        self.context = context
        self.config = config
        self.nitter = nitter
        self.media = media
        self.sender = sender
        self.translator = translator
        self.html_backend = html_backend
        migrate_default_group_config(config)
        self.config_reader = SchedulerConfigReader(config, context)
        self.storage = StorageAdapter(owner, config, context)
        self._task: asyncio.Task | None = None
        self._last_interval_slots: dict[str, int] = {}
        self._daily_slots: dict[str, set[str]] = {}
        self._last_daily_check: dict[str, dt.datetime] = {}
        self._startup_schedule_seeded: set[str] = set()
        self._last_enabled_state: bool | None = None
        self._check_lock = asyncio.Lock()
        self._storage_init_lock = asyncio.Lock()
        self._storage_ready = asyncio.Event()
        self._storage_init_error = ""
        self._migration_done = False
        self._startup_checks_done = False

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
                f"accounts={sum(len(group.account_keys) for group in groups)}, "
                f"push_targets={sum(len(group.targets) for group in groups)}"
            )
        except RuntimeError:
            logger.info(
                f"[NitterTweets] 当前无运行中的事件循环: reason={reason}; "
                "调度器将等待下一次启动钩子"
            )

    async def stop(self) -> None:
        task = self._task
        try:
            if task is not None:
                if not task.done():
                    task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        except Exception as exc:
            # A task may have failed before unload (for example during a
            # migration retry).  Still close storage and let unload finish.
            logger.warning(f"[NitterTweets] 调度器停止时任务异常: {exc}")
        finally:
            self.storage.close()
            self._task = None
            logger.info("[NitterTweets] 调度器已停止")

    async def _loop(self) -> None:
        logger.info("[NitterTweets] 调度器循环已进入")

        # 存储迁移由后台循环和手动检查共享。失败时保留当前 task，并允许
        # 手动检查成功完成同一初始化后唤醒这里，避免固定等待或并行迁移。
        while not await self._ensure_storage_ready():
            logger.error("[NitterTweets] 调度器将在 5 分钟后重试存储初始化")
            try:
                await asyncio.wait_for(self._storage_ready.wait(), timeout=300)
            except asyncio.TimeoutError:
                continue

        while True:
            try:
                if self.schedule_enabled:
                    if not self._startup_checks_done:
                        await self._run_startup_checks()
                        self._startup_checks_done = True
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
        config_enabled = parse_config_bool(
            config_get(self.config, "schedule_enabled", False), False
        )
        return config_enabled and any(
            group.enabled for group in self._schedule_groups(log_invalid_targets=False)
        )

    @property
    def brief_log_enabled(self) -> bool:
        return parse_config_bool(
            config_get(self.config, "brief_log_enabled", True), True
        )

    def _log_verbose_info(self, message: str) -> None:
        if not self.brief_log_enabled:
            logger.info(message)

    async def _ensure_storage_ready(self) -> bool:
        """Serialize storage migration for the scheduler and manual checks."""
        if self._migration_done:
            return True

        async with self._storage_init_lock:
            if self._migration_done:
                return True
            started = time.perf_counter()
            logger.info("[NitterTweets] 调度存储初始化开始")
            try:
                schedule_groups = self._schedule_groups(log_invalid_targets=False)
                await self.storage.migrate_and_sync(schedule_groups)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                duration_ms = (time.perf_counter() - started) * 1000
                self._storage_init_error = str(exc)
                logger.error(
                    "[NitterTweets] 调度存储初始化失败: "
                    f"duration_ms={duration_ms:.1f}, error={exc}",
                    exc_info=True,
                )
                return False

            self._migration_done = True
            self._storage_init_error = ""
            self._storage_ready.set()
            duration_ms = (time.perf_counter() - started) * 1000
            logger.info(
                "[NitterTweets] 调度存储初始化完成: "
                f"groups={len(schedule_groups)}, duration_ms={duration_ms:.1f}"
            )
            return True

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
            logger.warning(f"[NitterTweets] 发送状态提示：{unique_warning_count} 条")

    def _log_enabled_state(self, enabled: bool) -> None:
        if self._last_enabled_state is enabled:
            return
        self._last_enabled_state = enabled
        if enabled:
            self._log_verbose_info("[NitterTweets] 调度器已启用: schedule_enabled=true")
        else:
            self._log_verbose_info(
                "[NitterTweets] 调度器已闲置: schedule_enabled=false"
            )

    async def _tick(self) -> None:
        for group in self._schedule_groups(log_invalid_targets=False):
            if not group.enabled:
                continue
            now = dt.datetime.now(CN_TZ)
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

    async def _run_startup_checks(self, now: dt.datetime | None = None) -> None:
        """Run one serialized startup check for each eligible enabled group."""
        groups = self._schedule_groups(log_invalid_targets=False)
        anchor_now = now if now is not None else dt.datetime.now(CN_TZ)
        for group in groups:
            if not group.enabled:
                continue

            group_now = anchor_now
            self._startup_schedule_seeded.add(group.group_id)
            if not group.check_on_startup:
                self._seed_schedule_slots(group, group_now)
                continue

            source_count = len(group.account_keys)
            target_count = len(group.targets)
            if not source_count or not target_count:
                missing = "订阅源" if not source_count else "有效推送目标"
                logger.info(
                    "[NitterTweets] 启动首检跳过: "
                    f"group_id={group.group_id}, group_type={group.group_type}, "
                    f"sources={source_count}, targets={target_count}, "
                    f"reason=startup, missing={missing}"
                )
                self._seed_schedule_slots(group, group_now)
                continue

            try:
                await self.run_check(reason="startup", group_name=group.group_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error(
                    "[NitterTweets] 启动首检异常: "
                    f"group_id={group.group_id}, group_type={group.group_type}, "
                    f"sources={source_count}, targets={target_count}, "
                    f"reason=startup, error={exc}",
                    exc_info=True,
                )
            finally:
                # Anchor after the check so a long startup fetch cannot cause the
                # same interval/daily slot to fire again on the first tick.
                self._seed_schedule_slots(
                    group,
                    anchor_now if now is not None else dt.datetime.now(CN_TZ),
                )

    def _scheduled_reasons(self, group: ScheduleGroup, now: dt.datetime) -> list[str]:
        reasons: list[str] = []
        group_id = group.group_id

        if group_id not in self._startup_schedule_seeded:
            self._startup_schedule_seeded.add(group_id)
            self._seed_schedule_slots(group, now)
            return reasons

        if group.interval_check_enabled:
            interval_minutes = group.check_interval_minutes
            slot = int(now.timestamp() // (interval_minutes * 60))
            if slot != self._last_interval_slots.get(group_id):
                reasons.append(f"interval:{interval_minutes}m")

        if group.daily_check_enabled:
            daily_slots = self._daily_slots.setdefault(group_id, set())
            last_check = self._last_daily_check.get(group_id)
            for hour, minute in group.daily_check_times:
                target_time = now.replace(
                    hour=hour, minute=minute, second=0, microsecond=0
                )
                if last_check is None or now >= target_time > last_check:
                    slot_key = f"{now.date().isoformat()}:{hour:02d}:{minute:02d}"
                    if slot_key not in daily_slots:
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
            self._last_daily_check[group_id] = now
            daily_slots = self._daily_slots.setdefault(group_id, set())
            for hour, minute in group.daily_check_times:
                if now.hour == hour and now.minute == minute:
                    daily_slots.add(f"{now.date().isoformat()}:{hour:02d}:{minute:02d}")

    def _consume_schedule_slots(self, group: ScheduleGroup, reason: str) -> None:
        group_id = group.group_id
        now = dt.datetime.now(CN_TZ)

        if group.interval_check_enabled and "interval:" in reason:
            interval_minutes = group.check_interval_minutes
            slot = int(now.timestamp() // (interval_minutes * 60))
            self._last_interval_slots[group_id] = slot

        if group.daily_check_enabled and "daily:" in reason:
            daily_slots = self._daily_slots.setdefault(group_id, set())
            for hour, minute in group.daily_check_times:
                if now.hour == hour and now.minute == minute:
                    slot_key = f"{now.date().isoformat()}:{hour:02d}:{minute:02d}"
                    daily_slots.add(slot_key)
            self._last_daily_check[group_id] = now

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

        observable = self._is_observable_check_reason(reason)
        effective_targets = (
            list(target_override) if target_override is not None else group.targets
        )
        started = time.perf_counter() if observable else 0.0
        if observable:
            logger.info(
                "[NitterTweets] 检查开始: "
                f"group_id={group.group_id}, group_type={group.group_type}, "
                f"sources={len(group.account_keys)}, targets={len(effective_targets)}, "
                f"reason={reason}"
            )

        try:
            if not await self._ensure_storage_ready():
                result = self._new_check_result(reason, group, target_override)
                result.skipped_reason = "storage_not_ready"
                logger.warning(
                    "[NitterTweets] 检查因存储未就绪跳过: "
                    f"group_id={group.group_id}, group_type={group.group_type}, "
                    f"reason={reason}, error={self._storage_init_error or 'unknown'}"
                )
            elif not observable and self._check_lock.locked():
                result = self._new_check_result(reason, group, target_override)
                result.skipped_reason = "check_already_running"
                logger.warning(result.format_log_summary())
            else:
                async with self._check_lock:
                    result = await self._run_check_unlocked(
                        group,
                        reason,
                        notify_no_updates,
                        target_override,
                    )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if observable:
                duration_ms = (time.perf_counter() - started) * 1000
                logger.error(
                    "[NitterTweets] 检查异常: "
                    f"group_id={group.group_id}, group_type={group.group_type}, "
                    f"sources={len(group.account_keys)}, targets={len(group.targets)}, "
                    f"reason={reason}, duration_ms={duration_ms:.1f}, error={exc}",
                    exc_info=True,
                )
            raise

        if observable:
            duration_ms = (time.perf_counter() - started) * 1000
            logger.info(
                "[NitterTweets] 检查结束: "
                f"group_id={result.group_id}, group_type={result.group_type}, "
                f"sources={len(result.users)}, targets={len(result.targets)}, "
                f"reason={result.reason}, duration_ms={duration_ms:.1f}, "
                f"new={result.new_tweet_count}, failed={len(result.failed_users)}, "
                f"skipped={result.skipped_reason or 'none'}, "
                f"push_success={result.pushed_target_successes}/"
                f"{result.pushed_target_attempts}"
            )
        return result

    @staticmethod
    def _is_observable_check_reason(reason: str) -> bool:
        normalized = str(reason or "").strip().lower()
        return (
            normalized == "startup"
            or normalized == "webui"
            or normalized.startswith("manual")
        )

    async def replay_push_history(
        self,
        record_id: int,
        target_umos: list[str] | None = None,
    ) -> dict[str, object]:
        """Replay one stored delivery to current targets in its group."""
        record = await self.storage.get_push_history_record(record_id)
        if record is None:
            return {"success": False, "error": "未找到推送记录"}

        group = self._schedule_group(record.group_id)
        if group is None:
            return {
                "success": False,
                "error": f"未找到分组：{record.group_id}",
            }
        if not group.enabled:
            return {
                "success": False,
                "error": f"分组已停用：{self._push_group_label(group)}",
            }
        if not group.targets:
            return {
                "success": False,
                "error": "当前分组没有有效推送目标，请先维护推送目标",
            }

        selected_targets = self._dedupe_targets(
            [str(target or "").strip() for target in (target_umos or [])]
        )
        if selected_targets:
            current_targets = set(group.targets)
            invalid_targets = [
                target for target in selected_targets if target not in current_targets
            ]
            if invalid_targets:
                return {
                    "success": False,
                    "error": "只能选择当前分组当前配置中的推送目标",
                    "invalid_targets": invalid_targets,
                }
            targets = selected_targets
        else:
            targets = list(group.targets)
        if not targets:
            return {
                "success": False,
                "error": "请选择要重新推送的推送目标",
            }

        replay_tweet = copy.deepcopy(record.tweet)
        translator_enabled = bool(getattr(self.translator, "enabled", False))
        if not translator_enabled:
            replay_tweet.translation = ""
            replay_tweet.ai_warnings = [
                warning
                for warning in replay_tweet.ai_warnings
                if "翻译" not in str(warning)
            ]

        batch = PendingTweetBatch(
            username=record.username,
            instance=record.instance,
            tweets=[replay_tweet],
            fetched_ids=[record.status_id] if record.status_id else [],
            seen_ids=[],
            account_index=1,
            account_total=1,
            tweet_index=1,
            tweet_total=1,
            # History replay is an explicit recovery action and always sends
            # the complete tweet, regardless of the current group mode.
            media_only=False,
            omit_status_url=bool(getattr(group, "omit_status_url", True)),
            hide_original_when_translated=resolve_hide_original_when_translated(
                self.config,
                group_hide=bool(getattr(group, "hide_original_when_translated", False)),
            ),
        )
        try:
            if translator_enabled:
                await self.translator.attach_translations(
                    batch.tweets, targets[0] if targets else None
                )
            await self.media.attach_media(batch.tweets)
        except Exception as exc:
            logger.warning(
                "[NitterTweets] 重新推送媒体准备失败，继续发送文本: "
                f"record={record_id}, error={exc}"
            )
        except BaseException:
            await self._cleanup_batch_media(batch)
            raise

        success_targets = 0
        failed_targets: dict[str, str] = {}
        group_label = self._push_group_label(group)
        try:
            for target_index, target in enumerate(targets):
                try:
                    outcome = await self.sender.send_to_umo_with_outcome(
                        self.context,
                        target,
                        record.username,
                        record.instance,
                        batch.tweets,
                        group_label=group_label,
                        batch_summary="",
                        tweet_start_index=1,
                        media_only=False,
                        omit_status_url=batch.omit_status_url,
                        hide_original_when_translated=(
                            batch.hide_original_when_translated
                        ),
                    )
                    delivery_complete = self._delivery_is_complete(outcome)
                    history_status_ids = self._delivery_history_status_ids(
                        outcome, batch.tweets
                    )
                    if history_status_ids:
                        await self._record_batch_push_history(
                            group.group_id,
                            batch,
                            target,
                            "replay",
                            delivery_status=getattr(
                                outcome, "delivery_status", "success"
                            ),
                            delivery_error=getattr(outcome, "delivery_error", ""),
                            status_ids=history_status_ids,
                        )
                    if delivery_complete:
                        success_targets += 1
                    else:
                        failed_targets[target] = (
                            getattr(outcome, "error", "")
                            or getattr(outcome, "delivery_error", "")
                            or "send failed"
                        )
                except Exception as exc:
                    failed_targets[target] = str(exc)
                    logger.warning(
                        "[NitterTweets] 重新推送失败: "
                        f"record={record_id}, target={target}, error={exc}"
                    )
                if target_index < len(targets) - 1 and group.send_target_interval > 0:
                    await asyncio.sleep(group.send_target_interval)
        finally:
            await self._cleanup_batch_media(batch)

        return {
            "success": success_targets > 0,
            "error": "" if success_targets > 0 else "重新推送失败",
            "record_id": record_id,
            "target_count": len(targets),
            "success_targets": success_targets,
            "total_targets": len(targets),
            "failed_targets": failed_targets,
        }

    def _new_check_result(
        self,
        reason: str,
        group: ScheduleGroup,
        target_override: list[str] | None = None,
    ) -> ScheduledCheckResult:
        targets = (
            list(target_override) if target_override is not None else group.targets
        )
        targets = self._order_targets_for_push(targets)
        invalid_targets = [] if target_override is not None else group.invalid_targets
        return ScheduledCheckResult(
            reason=reason,
            group_id=group.group_id,
            group_name=group.name,
            group_type=group.group_type,
            users=list(group.account_keys),
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
        self._consume_schedule_slots(group, reason)
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
            if group.is_tag_group:
                result.skipped_reason = "no_watch_queries"
            elif group.is_list_group:
                result.skipped_reason = "no_watch_lists"
            else:
                result.skipped_reason = "no_watch_users"
            self._log_check_result(result)
            return result
        if not targets:
            result.skipped_reason = "no_push_targets"
            self._log_check_result(result)
            return result

        # S2=A: RSS host skip only for this blogger check; end only if we began.
        run_host_skip_started = False
        if group.is_blogger_group and hasattr(self.nitter, "begin_run_host_skip"):
            self.nitter.begin_run_host_skip()
            run_host_skip_started = True
        try:
            seen_map = await self._get_seen_map(group.group_id)
            scan_watermarks = await self._get_scan_watermarks(group.group_id, seen_map)
            fetch_limit = 20
            result.fetch_limit = fetch_limit
            target_interval = group.send_target_interval
            user_interval = group.send_user_interval
            group_label = self._push_group_label(group)
            filter_plain_text_enabled = bool(group.filter_plain_text_enabled)
            media_only_effective = self._media_only_effective(group)
            if group.media_only_enabled and not media_only_effective:
                reason_text = self._media_only_unavailable_reason(group)
                logger.info(
                    "[NitterTweets] 分组仅媒体未生效，已回退完整内容: "
                    f"group={group.group_id}, reason={reason_text or 'unknown'}"
                )
            skip_plain_text = filter_plain_text_enabled or media_only_effective
            use_fetch_parallel = self._should_use_concurrent_fetch(group)
            use_prepare_parallel = self._should_use_concurrent_prepare(group)
            self._log_verbose_info(
                "[NitterTweets] 定时检查开始: "
                f"group={group.group_id}, reason={reason}, "
                f"users={len(users)}, targets={len(targets)}, "
                f"invalid_targets={len(result.invalid_targets)}, "
                f"首屏扫描={fetch_limit}, qq_merge_threshold={merge_threshold}, "
                f"skip_plain_text={skip_plain_text}, "
                f"拉取并发={'开' if use_fetch_parallel else '关'}, "
                f"拉取数={group.fetch_concurrency}, "
                f"专用镜像={len(group.concurrent_fetch_instances)}, "
                f"准备并发={'开' if use_prepare_parallel else '关'}, "
                f"准备数={group.prepare_concurrency}"
            )
            discovered_batches: list[PendingTweetBatch] = []
            group_plain_text_filtered_total = 0
            fetch_results = await self._fetch_group_users(
                group, fetch_limit, skip_plain_text, scan_watermarks
            )
            watermark_candidates: dict[str, tuple[list[str], set[str]]] = {}
            for fetch_result in fetch_results:
                username = fetch_result.username
                source_label = format_subscription_source(username, group.group_type)
                if fetch_result.error:
                    result.failed_users[username] = fetch_result.error.message
                    logger.warning(
                        f"[NitterTweets] 定时抓取 {source_label} 失败: "
                        f"{fetch_result.error.message}"
                    )
                    continue

                instance = fetch_result.instance
                tweets = fetch_result.tweets
                scanned_status_ids = list(
                    dict.fromkeys(
                        str(item)
                        for item in fetch_result.scanned_status_ids
                        if str(item)
                    )
                )
                full_scanned_status_ids = (
                    fetch_result.anchor_status_ids
                    if fetch_result.anchor_status_ids
                    else scanned_status_ids
                )
                watermark = scan_watermarks.get(username)
                if watermark and scanned_status_ids:
                    boundary_ids = set(watermark)
                    boundary_index = next(
                        (
                            index
                            for index, status_id in enumerate(scanned_status_ids)
                            if status_id in boundary_ids
                        ),
                        None,
                    )
                    if boundary_index is not None:
                        scanned_status_ids = scanned_status_ids[: boundary_index + 1]
                        allowed_status_ids = set(scanned_status_ids)
                        tweets = [
                            tweet
                            for tweet in tweets
                            if str(tweet.status_id or "") in allowed_status_ids
                        ]
                if not fetch_result.scan_complete:
                    result.failed_users[username] = "分页未完整扫描，已跳过本轮"
                    logger.warning(
                        f"[NitterTweets] 定时抓取 {source_label} 未完整扫描，跳过本轮"
                    )
                    continue
                plain_text_filtered = fetch_result.plain_text_filtered
                if skip_plain_text and plain_text_filtered > 0:
                    group_plain_text_filtered_total += plain_text_filtered
                    self._log_verbose_info(
                        f"[NitterTweets] 定时检查 {source_label}: "
                        f"已过滤 {plain_text_filtered} 条纯文本推文（无作者上传媒体）"
                    )

                tweets = [tweet for tweet in tweets if tweet.status_id]
                seen_ids = seen_map.get(username)

                if username not in scan_watermarks:
                    seed_ids = scanned_status_ids or [
                        tweet.status_id for tweet in tweets if tweet.status_id
                    ]
                    # Tag/search HTML is single-page.  A result that contained
                    # rows but had every row filtered (pure RT/text/media-only)
                    # must be marked initialized with an explicit empty
                    # watermark: leaving it uninitialized would make the next
                    # eligible tweet look like historical seed data and drop
                    # the notification.  A genuinely empty response remains
                    # uninitialized so a transient empty search does not seal
                    # a whole page as history.
                    if not seed_ids and (group.is_tag_group or group.is_list_group):
                        source_kind_label = (
                            "搜索订阅" if group.is_tag_group else "List 订阅"
                        )
                        if (
                            fetch_result.plain_text_filtered > 0
                            or fetch_result.retweet_filtered > 0
                            or fetch_result.html_raw_item_count > 0
                        ):
                            await self._set_scan_watermark(
                                group.group_id,
                                username,
                                [],
                            )
                            result.initialized_users[username] = 0
                            self._log_verbose_info(
                                f"[NitterTweets] {source_kind_label}首轮结果全部被过滤，"
                                "已记录空扫描水位: "
                                f"group={group.group_id}, source={source_label}"
                            )
                            continue
                        result.failed_users[username] = (
                            "首次抓取无有效推文 ID，未建立订阅源基线（下轮重试）"
                        )
                        logger.warning(
                            f"[NitterTweets] {source_kind_label}首次抓取为空，跳过初始化: "
                            f"group={group.group_id}, source={source_label}"
                        )
                        continue
                    seen_map[username] = self.storage.initial_seen_ids(seed_ids)
                    await self._put_seen_map(group.group_id, seen_map)
                    await self._set_scan_watermark(
                        group.group_id, username, full_scanned_status_ids
                    )
                    result.initialized_users[username] = len(seed_ids)
                    self._log_verbose_info(
                        "[NitterTweets] 首次订阅源已初始化: "
                        f"group={group.group_id}, source={source_label}, "
                        f"seen={len(seed_ids)}"
                    )
                    continue

                if not isinstance(seen_ids, list):
                    seen_ids = []
                new_tweets, historical_unseen_ids = (
                    self._select_new_tweets_after_scan_watermark(
                        tweets, seen_ids, watermark
                    )
                )
                if historical_unseen_ids:
                    seen_ids = self._merge_seen_ids(historical_unseen_ids, seen_ids)
                    seen_map[username] = seen_ids
                    await self._put_seen_map(group.group_id, seen_map)
                    self._log_verbose_info(
                        "[NitterTweets] 定时检查忽略基准前历史推文: "
                        f"group={group.group_id}, source={source_label}, "
                        f"ignored={len(historical_unseen_ids)}"
                    )

                if new_tweets:
                    # max_tweets_per_check: keep the newest N; the excess is
                    # marked seen (like pre-watermark history) so the advanced
                    # scan watermark cannot silently drop it next round.
                    max_tweets = group.max_tweets_per_check
                    if max_tweets > 0 and len(new_tweets) > max_tweets:
                        dropped_tweets = new_tweets[max_tweets:]
                        new_tweets = new_tweets[:max_tweets]
                        dropped_ids = [
                            tweet.status_id
                            for tweet in dropped_tweets
                            if tweet.status_id
                        ]
                        if dropped_ids:
                            seen_ids = self._merge_seen_ids(dropped_ids, seen_ids)
                            seen_map[username] = seen_ids
                            await self._put_seen_map(group.group_id, seen_map)
                        self._log_verbose_info(
                            "[NitterTweets] 定时检查超出单次推送上限，已跳过较旧推文: "
                            f"group={group.group_id}, source={source_label}, "
                            f"max={max_tweets}, skipped={len(dropped_tweets)}"
                        )

                    selected_ids = {
                        tweet.status_id for tweet in new_tweets if tweet.status_id
                    }
                    watermark_candidates[username] = (
                        full_scanned_status_ids,
                        selected_ids,
                    )
                    discovered_batches.append(
                        PendingTweetBatch(
                            username=username,
                            instance=instance,
                            tweets=new_tweets,
                            fetched_ids=scanned_status_ids,
                            seen_ids=seen_ids,
                            media_only=media_only_effective,
                            omit_status_url=bool(
                                getattr(group, "omit_status_url", True)
                            ),
                            hide_original_when_translated=resolve_hide_original_when_translated(
                                self.config,
                                group_hide=bool(
                                    getattr(
                                        group, "hide_original_when_translated", False
                                    )
                                ),
                            ),
                            tweet_index=len(new_tweets),
                            tweet_total=len(new_tweets),
                        )
                    )
                else:
                    result.no_new_users.append(username)
                    self._log_verbose_info(
                        f"[NitterTweets] 定时检查无新推文: group={group.group_id}, "
                        f"source={source_label}"
                    )
                    seen_map[username] = self._merge_seen_ids(
                        scanned_status_ids, seen_ids
                    )
                    await self._put_seen_map(group.group_id, seen_map)
                    if scanned_status_ids:
                        await self._set_scan_watermark(
                            group.group_id, username, full_scanned_status_ids
                        )

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
                group_type=group.group_type,
            )
            check_batch_summary = self._append_fetch_failure_summary(
                check_batch_summary,
                fetch_failures,
                group_type=group.group_type,
            )
            immediate_batch_summary_tracker = BatchSummaryTracker(check_batch_summary)
            self._set_discovered_batch_progress(discovered_batches)
            if self._should_use_concurrent_prepare(group):
                (
                    pending_batches,
                    immediate_batches_sent,
                ) = await self._prepare_immediate_batches_concurrently(
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
            else:
                (
                    pending_batches,
                    immediate_batches_sent,
                ) = await self._prepare_discovered_batches_serial(
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
                        # A group-level seen key is shared by all push
                        # targets.  Advance it only after every target for
                        # this batch accepted the delivery; recording after a
                        # partial success would permanently hide the tweet
                        # from a failed target on the next round.
                        if not self._all_targets_delivered(targets, batch):
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
                        await self._cleanup_batch_media(batch)

            for username, (
                anchor_status_ids,
                selected_ids,
            ) in watermark_candidates.items():
                current_seen = set(seen_map.get(username, []))
                if selected_ids and not selected_ids.issubset(current_seen):
                    continue
                await self._set_scan_watermark(
                    group.group_id, username, anchor_status_ids
                )

            self._log_check_result(result)
            if self._should_notify_no_updates(result, notify_no_updates, group):
                await self._send_no_update_notice(result, target_interval)
            return result
        finally:
            if run_host_skip_started and hasattr(self.nitter, "end_run_host_skip"):
                self.nitter.end_run_host_skip()

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

    def _schedule_groups(self, log_invalid_targets: bool = True) -> list[ScheduleGroup]:
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
            group_type="blogger",
            skipped_reason="unknown_group",
            available_groups=[
                f"{group.name} ({group.group_id})"
                for group in self._schedule_groups(log_invalid_targets=False)
            ],
            merge_tweet_threshold=self._merge_tweet_threshold(),
        )
