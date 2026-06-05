from __future__ import annotations

import asyncio
import datetime as dt
import re
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
    from .utils import clamp_float, clamp_int, normalize_username
except ImportError:
    from utils import clamp_float, clamp_int, normalize_username


try:
    CN_TZ = ZoneInfo("Asia/Shanghai")
except ZoneInfoNotFoundError:
    CN_TZ = dt.timezone(dt.timedelta(hours=8), name="Asia/Shanghai")


KV_KEY_SEEN = "nitter_seen_status_ids"
POLL_SECONDS = 30
SEEN_LIMIT_PER_USER = 100


@dataclass(slots=True)
class PushTargetParseResult:
    targets: list[str] = field(default_factory=list)
    invalid_targets: list[str] = field(default_factory=list)


@dataclass(slots=True)
class WatchUsersInfo:
    raw_count: int
    users: list[str] = field(default_factory=list)
    duplicates: list[str] = field(default_factory=list)
    invalid_entries: list[str] = field(default_factory=list)
    changed: bool = False
    saved: bool = False
    save_error: str = ""


@dataclass(slots=True)
class ScheduledPushResult:
    username: str
    new_count: int
    success_targets: int
    total_targets: int


@dataclass(slots=True)
class ScheduledCheckResult:
    reason: str
    users: list[str] = field(default_factory=list)
    targets: list[str] = field(default_factory=list)
    invalid_targets: list[str] = field(default_factory=list)
    seen_users: int = 0
    fetch_limit: int = 0
    skipped_reason: str = ""
    initialized_users: dict[str, int] = field(default_factory=dict)
    no_new_users: list[str] = field(default_factory=list)
    empty_users: list[str] = field(default_factory=list)
    failed_users: dict[str, str] = field(default_factory=dict)
    pushes: list[ScheduledPushResult] = field(default_factory=list)
    push_mode: str = "per_user"
    merged_push_success_targets: int = 0
    merged_push_total_targets: int = 0
    delivery_warnings: list[str] = field(default_factory=list)

    @property
    def new_tweet_count(self) -> int:
        return sum(push.new_count for push in self.pushes)

    @property
    def pushed_target_successes(self) -> int:
        if self.push_mode == "merged":
            return self.merged_push_success_targets
        return sum(push.success_targets for push in self.pushes)

    @property
    def pushed_target_attempts(self) -> int:
        if self.push_mode == "merged":
            return self.merged_push_total_targets
        return sum(push.total_targets for push in self.pushes)

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
                f"reason={self.skipped_reason}, users={len(self.users)}, "
                f"targets={len(self.targets)}, invalid_targets={len(self.invalid_targets)}"
            )

        warning_part = (
            f", warnings={len(self.delivery_warnings)}"
            if self.delivery_warnings else ""
        )
        return (
            "[NitterTweets] scheduled check finished: "
            f"reason={self.reason}, users={len(self.users)}, targets={len(self.targets)}, "
            f"checked={self.checked_user_count}, initialized={len(self.initialized_users)}, "
            f"new_tweets={self.new_tweet_count}, no_new={len(self.no_new_users)}, "
            f"empty={len(self.empty_users)}, failed={len(self.failed_users)}, "
            f"push_mode={self.push_mode}, "
            f"push_success={self.pushed_target_successes}/{self.pushed_target_attempts}, "
            f"invalid_targets={len(self.invalid_targets)}{warning_part}"
        )

    def format_message(self, title: str = "Nitter 定时检查结果") -> str:
        lines = [
            title,
            f"触发原因: {self.reason}",
            f"关注账号: {len(self.users)} 个",
            f"推送目标: {len(self.targets)} 个",
            f"已记录账号: {self.seen_users} 个",
        ]
        if self.fetch_limit:
            lines.append(f"每账号拉取: {self.fetch_limit} 条")

        if self.skipped_reason:
            reason_text = {
                "no_watch_users": "未配置 watch_users",
                "no_push_targets": "未配置有效 push_targets",
            }.get(self.skipped_reason, self.skipped_reason)
            lines.append(f"检查跳过: {reason_text}")

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
            lines.append(
                "合并推送: "
                f"{self.merged_push_success_targets}/{self.merged_push_total_targets}"
            )
        elif self.pushes:
            items = [
                f"@{item.username} {item.new_count} 条，推送 {item.success_targets}/{item.total_targets}"
                for item in self.pushes
            ]
            lines.append("新推文: " + "; ".join(items))

        if self.no_new_users:
            lines.append("无新推文: " + ", ".join(f"@{user}" for user in self.no_new_users))

        if self.empty_users:
            lines.append("RSS 无有效推文 ID: " + ", ".join(f"@{user}" for user in self.empty_users))

        if self.failed_users:
            items = [f"@{user}: {error}" for user, error in self.failed_users.items()]
            lines.append("失败: " + "; ".join(items))

        if self.delivery_warnings:
            lines.append("发送提示:")
            lines.extend(f"- {warning}" for warning in self.delivery_warnings)

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
        self._task: asyncio.Task | None = None
        self._last_interval_slot: int | None = None
        self._daily_slots: set[str] = set()
        self._startup_schedule_seeded = False
        self._last_enabled_state: bool | None = None

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
            logger.info(
                "[NitterTweets] scheduler started "
                f"({reason}); enabled={self.schedule_enabled}, "
                f"watch_users={len(self._watch_users())}, "
                f"push_targets={len(self._parse_push_targets(log_invalid=False).targets)}"
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
        return bool(self.config.get("schedule_enabled", False))

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
        reasons: list[str] = []

        if not self._startup_schedule_seeded:
            self._startup_schedule_seeded = True
            if not self.config.get("check_on_startup", False):
                self._seed_schedule_slots(now)
                logger.info(
                    "[NitterTweets] startup scheduled check skipped: "
                    "check_on_startup=false"
                )
                return

        if self.config.get("interval_check_enabled", True):
            interval_minutes = clamp_int(
                self.config.get("check_interval_minutes", 30), 1, 1440
            )
            slot = int(now.timestamp() // (interval_minutes * 60))
            if slot != self._last_interval_slot:
                self._last_interval_slot = slot
                reasons.append(f"interval:{interval_minutes}m")

        if self.config.get("daily_check_enabled", False):
            for hhmm in self._parse_daily_times():
                hour, minute = hhmm
                if now.hour == hour and now.minute == minute:
                    slot_key = f"{now.date().isoformat()}:{hour:02d}:{minute:02d}"
                    if slot_key not in self._daily_slots:
                        self._daily_slots.add(slot_key)
                        reasons.append(f"daily:{hour:02d}:{minute:02d}")

            if len(self._daily_slots) > 256:
                today = now.date().isoformat()
                self._daily_slots = {
                    slot for slot in self._daily_slots if slot.startswith(today)
                }

        if reasons:
            logger.info(f"[NitterTweets] scheduled check triggered: {', '.join(reasons)}")
            await self.run_check(reason=", ".join(reasons))

    def _seed_schedule_slots(self, now: dt.datetime) -> None:
        if self.config.get("interval_check_enabled", True):
            interval_minutes = clamp_int(
                self.config.get("check_interval_minutes", 30), 1, 1440
            )
            self._last_interval_slot = int(now.timestamp() // (interval_minutes * 60))

        if self.config.get("daily_check_enabled", False):
            for hour, minute in self._parse_daily_times():
                if now.hour == hour and now.minute == minute:
                    self._daily_slots.add(
                        f"{now.date().isoformat()}:{hour:02d}:{minute:02d}"
                    )

    async def run_check(
        self,
        reason: str = "manual",
        notify_no_updates: bool | None = None,
    ) -> ScheduledCheckResult:
        users = self._watch_users()
        target_info = self._parse_push_targets()
        targets = target_info.targets
        result = ScheduledCheckResult(
            reason=reason,
            users=users,
            targets=targets,
            invalid_targets=target_info.invalid_targets,
        )
        merge_updates = bool(self.config.get("merge_scheduled_updates", False))
        result.push_mode = "merged" if merge_updates else "per_user"
        merged_batches = []
        if not users:
            result.skipped_reason = "no_watch_users"
            logger.info(result.format_log_summary())
            return result
        if not targets:
            result.skipped_reason = "no_push_targets"
            logger.info(result.format_log_summary())
            return result

        seen_map = await self._get_seen_map()
        result.seen_users = len(seen_map)
        fetch_limit = clamp_int(self.config.get("scheduled_fetch_limit", 5), 1, 20)
        result.fetch_limit = fetch_limit
        target_interval = clamp_float(
            self.config.get("send_target_interval", 1.5), 0.0, 60.0
        )
        user_interval = clamp_float(
            self.config.get("send_user_interval", 2.0), 0.0, 60.0
        )
        logger.info(
            "[NitterTweets] scheduled check started: "
            f"reason={reason}, users={len(users)}, targets={len(targets)}, "
            f"invalid_targets={len(target_info.invalid_targets)}, "
            f"fetch_limit={fetch_limit}, push_mode={result.push_mode}"
        )

        for user_index, username in enumerate(users):
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
                seen_map[username] = fetched_ids[:SEEN_LIMIT_PER_USER]
                await self._put_seen_map(seen_map)
                result.initialized_users[username] = len(fetched_ids)
                logger.info(
                    f"[NitterTweets] initialized @{username} with {len(fetched_ids)} seen tweets"
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

                if merge_updates:
                    merged_batches.append((username, instance, new_tweets))
                    result.pushes.append(
                        ScheduledPushResult(
                            username=username,
                            new_count=len(new_tweets),
                            success_targets=0,
                            total_targets=0,
                        )
                    )
                    logger.info(
                        f"[NitterTweets] queued @{username} {len(new_tweets)} "
                        "new tweets for merged push"
                    )
                else:
                    success = 0
                    for target_index, umo in enumerate(targets):
                        try:
                            if await self.sender.send_to_umo(
                                self.context, umo, username, instance, new_tweets
                            ):
                                success += 1
                        except Exception as exc:
                            logger.warning(
                                f"[NitterTweets] scheduled push @{username} to {umo} failed: {exc}"
                            )
                        if target_index < len(targets) - 1 and target_interval > 0:
                            await asyncio.sleep(target_interval)
                    result.pushes.append(
                        ScheduledPushResult(
                            username=username,
                            new_count=len(new_tweets),
                            success_targets=success,
                            total_targets=len(targets),
                        )
                    )
                    logger.info(
                        f"[NitterTweets] pushed @{username} {len(new_tweets)} new tweets "
                        f"to {success}/{len(targets)} targets"
                    )
            else:
                result.no_new_users.append(username)
                logger.info(f"[NitterTweets] scheduled check @{username}: no new tweets")

            seen_map[username] = self._merge_seen_ids(fetched_ids, seen_ids)
            await self._put_seen_map(seen_map)

            if user_index < len(users) - 1 and user_interval > 0:
                await asyncio.sleep(user_interval)

        if merge_updates and merged_batches:
            await self._send_merged_updates(merged_batches, result, target_interval)

        logger.info(result.format_log_summary())
        if self._should_notify_no_updates(result, notify_no_updates):
            await self._send_no_update_notice(result, target_interval)
        return result

    async def status_summary(self) -> str:
        watch_info = self._watch_users_info()
        users = watch_info.users
        target_info = self._parse_push_targets(log_invalid=False)
        seen_map = await self._get_seen_map()
        interval_minutes = clamp_int(
            self.config.get("check_interval_minutes", 30), 1, 1440
        )
        daily_times = self._parse_daily_times()

        lines = [
            "Nitter 定时检查状态",
            f"调度器: {'运行中' if self.is_running else '未运行'}",
            f"总开关: {'已启用' if self.schedule_enabled else '已关闭'}",
            f"启动立即检查: {'已启用' if self.config.get('check_on_startup', False) else '已关闭'}",
            f"间隔检查: {'已启用' if self.config.get('interval_check_enabled', True) else '已关闭'} / {interval_minutes} 分钟",
            f"每日定点: {'已启用' if self.config.get('daily_check_enabled', False) else '已关闭'}",
            f"无更新提示: {'已启用' if self.config.get('notify_no_updates', False) else '已关闭'}",
            f"合并本轮更新: {'已启用' if self.config.get('merge_scheduled_updates', False) else '已关闭'}",
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
    ) -> bool:
        if notify_no_updates is None:
            notify_no_updates = bool(self.config.get("notify_no_updates", False))
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

    async def _send_merged_updates(
        self,
        batches,
        result: ScheduledCheckResult,
        target_interval: float,
    ) -> None:
        success = 0
        for target_index, umo in enumerate(result.targets):
            try:
                outcome = await self.sender.send_merged_to_umo(
                    self.context, umo, batches
                )
                if outcome.success:
                    success += 1
                    if outcome.mode not in {"full_forward", "direct_message"}:
                        if outcome.omitted_videos:
                            warning = (
                                f"{umo} 合并推送已降级：mode={outcome.mode}，"
                                f"{outcome.omitted_videos} 个视频/GIF 未作为附件发送，"
                                "消息中已包含原文链接。"
                            )
                        else:
                            warning = (
                                f"{umo} 合并推送已降级：mode={outcome.mode}，"
                                "已改用普通文本发送。"
                            )
                        result.delivery_warnings.append(warning)
                        logger.warning(f"[NitterTweets] {warning}")
                else:
                    logger.warning(
                        f"[NitterTweets] merged scheduled push to {umo} failed: "
                        f"{outcome.error}"
                    )
            except Exception as exc:
                logger.warning(
                    f"[NitterTweets] merged scheduled push to {umo} failed: {exc}"
                )
            if target_index < len(result.targets) - 1 and target_interval > 0:
                await asyncio.sleep(target_interval)

        result.merged_push_success_targets = success
        result.merged_push_total_targets = len(result.targets)
        logger.info(
            f"[NitterTweets] pushed {result.new_tweet_count} merged new tweets "
            f"from {len(batches)} users to {success}/{len(result.targets)} targets"
        )

    async def _get_seen_map(self) -> dict[str, list[str]]:
        value = await self.owner.get_kv_data(KV_KEY_SEEN, {})
        if not isinstance(value, dict):
            return {}
        result: dict[str, list[str]] = {}
        for key, ids in value.items():
            username = normalize_username(str(key))
            if not username or not isinstance(ids, list):
                continue
            result[username] = [str(item) for item in ids if item]
        return result

    async def _put_seen_map(self, seen_map: dict[str, list[str]]) -> None:
        await self.owner.put_kv_data(KV_KEY_SEEN, seen_map)

    @staticmethod
    def _merge_seen_ids(new_ids: list[str], old_ids: list[str]) -> list[str]:
        merged: list[str] = []
        seen: set[str] = set()
        for status_id in [*new_ids, *[str(item) for item in old_ids]]:
            if not status_id or status_id in seen:
                continue
            seen.add(status_id)
            merged.append(status_id)
            if len(merged) >= SEEN_LIMIT_PER_USER:
                break
        return merged

    def _watch_users(self) -> list[str]:
        return self._watch_users_info().users

    def _watch_users_info(self) -> WatchUsersInfo:
        raw_users = self.config.get("watch_users", []) or []
        if isinstance(raw_users, str):
            raw_users = re.split(r"[\n,，]+", raw_users)
        elif not isinstance(raw_users, list):
            raw_users = [raw_users]
        raw_entries = [str(raw).strip() for raw in raw_users if str(raw).strip()]
        users: list[str] = []
        seen: set[str] = set()
        duplicates: list[str] = []
        invalid_entries: list[str] = []
        for raw in raw_entries:
            username = normalize_username(raw)
            if not username:
                invalid_entries.append(raw)
                continue
            username_key = username.lower()
            if username_key in seen:
                duplicates.append(raw)
                continue
            seen.add(username_key)
            users.append(username)
        return WatchUsersInfo(
            raw_count=len(raw_entries),
            users=users,
            duplicates=duplicates,
            invalid_entries=invalid_entries,
            changed=raw_entries != users,
        )

    def _push_targets(self) -> list[str]:
        return self._parse_push_targets().targets

    def _parse_push_targets(self, log_invalid: bool = True) -> PushTargetParseResult:
        default_platform = self._get_platform()
        raw_targets = self.config.get("push_targets", []) or []
        result = PushTargetParseResult()
        seen: set[str] = set()
        for raw in raw_targets:
            if not isinstance(raw, str):
                invalid = repr(raw)
                result.invalid_targets.append(invalid)
                if log_invalid:
                    logger.warning(f"[NitterTweets] invalid push target: {invalid}")
                continue
            target = raw.strip().replace("：", ":")
            if not target:
                continue
            umo = self._parse_target_to_umo(target, default_platform)
            if umo is None:
                result.invalid_targets.append(raw)
                if log_invalid:
                    logger.warning(f"[NitterTweets] invalid push target: {raw!r}")
                continue
            if umo not in seen:
                seen.add(umo)
                result.targets.append(umo)
        return result

    def _get_platform(self) -> str:
        configured = (self.config.get("platform_id", "") or "").strip()
        if configured:
            return configured

        platform_id = self._detect_context_platform_id()
        if platform_id:
            return platform_id

        return "aiocqhttp"

    def _detect_context_platform_id(self) -> str:
        try:
            get_all_platforms = getattr(self.context, "get_all_platforms", None)
            if callable(get_all_platforms):
                platform_id = self._first_platform_id(get_all_platforms())
                if platform_id:
                    return platform_id
        except Exception as exc:
            logger.debug(f"[NitterTweets] platform auto-detect failed: {exc}")

        try:
            manager = getattr(self.context, "platform_manager", None)
            platform_id = self._first_platform_id(
                getattr(manager, "platform_insts", []) or []
            )
            if platform_id:
                return platform_id
        except Exception as exc:
            logger.debug(f"[NitterTweets] platform manager lookup failed: {exc}")

        return ""

    @classmethod
    def _first_platform_id(cls, platforms) -> str:
        if not platforms:
            return ""

        if isinstance(platforms, dict):
            for key in platforms:
                platform_id = str(key).strip()
                if platform_id and platform_id != "webchat":
                    return platform_id
            return ""

        for platform in platforms:
            platform_id = cls._platform_id(platform)
            if platform_id and platform_id != "webchat":
                return platform_id
        return ""

    @staticmethod
    def _platform_id(platform) -> str:
        for attr in ("platform_id", "platform_name", "id", "name"):
            value = getattr(platform, attr, None)
            if isinstance(value, str) and value.strip():
                return value.strip()

        meta = getattr(platform, "meta", None)
        if callable(meta):
            try:
                metadata = meta()
            except Exception:
                metadata = None
            for attr in ("id", "name"):
                value = getattr(metadata, attr, None)
                if isinstance(value, str) and value.strip():
                    return value.strip()

        config = getattr(platform, "config", None)
        if isinstance(config, dict):
            value = config.get("id") or config.get("type")
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    @staticmethod
    def _parse_target_to_umo(target: str, default_platform: str) -> str | None:
        if ":GroupMessage:" in target or ":FriendMessage:" in target:
            return target

        parts = target.split(":")
        if len(parts) == 2:
            kind, ident = parts[0].strip().lower(), parts[1].strip()
            if not ident:
                return None
            if kind == "group":
                return f"{default_platform}:GroupMessage:{ident}"
            if kind == "private":
                return f"{default_platform}:FriendMessage:{ident}"
            return None

        if len(parts) == 3:
            platform, kind, ident = (
                parts[0].strip(),
                parts[1].strip().lower(),
                parts[2].strip(),
            )
            if not platform or not ident:
                return None
            if kind == "group":
                return f"{platform}:GroupMessage:{ident}"
            if kind == "private":
                return f"{platform}:FriendMessage:{ident}"
            return None

        if len(parts) == 1 and target.isdigit():
            return f"{default_platform}:GroupMessage:{target}"
        return None

    def _parse_daily_times(self) -> list[tuple[int, int]]:
        raw_times = self.config.get("daily_check_times", []) or []
        if isinstance(raw_times, str):
            raw_times = re.split(r"[\n,，]+", raw_times)

        times: list[tuple[int, int]] = []
        for raw in raw_times:
            value = str(raw).strip().replace("：", ":")
            if not value:
                continue
            try:
                hour_s, minute_s = value.split(":", 1)
                hour, minute = int(hour_s), int(minute_s)
            except (TypeError, ValueError):
                logger.warning(f"[NitterTweets] invalid daily_check_times entry: {raw!r}")
                continue
            if 0 <= hour < 24 and 0 <= minute < 60:
                times.append((hour, minute))
            else:
                logger.warning(f"[NitterTweets] daily_check_times out of range: {raw!r}")
        return times
