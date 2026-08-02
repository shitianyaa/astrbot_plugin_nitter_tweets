"""发送阶段：即时/合并推送、缓存清理、push history 与目标拆分。

`NitterTweetScheduler` 的 mixin：只通过 `self` 协作，不 import 宿主类。
seen 写入仍走 `runner.py` 的 seen 接口，这里不直接决定 seen 推进时机。
"""

from __future__ import annotations

import asyncio
import inspect

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
    from ..ai import format_ai_tweet_summary
    from ..config import configured_merge_tweet_threshold
    from ..rendering import TweetMessageRenderer
    from ..shared import format_subscription_source
    from ..shared.group_ids import DEFAULT_GROUP_NAME, is_default_group
    from .config import ScheduleGroup
    from .formatting import _format_limited_values as scheduler_format_limited_values
    from .models import (
        BatchSummaryTracker,
        PendingTweetBatch,
        ScheduledCheckResult,
        ScheduledPushResult,
    )
except ImportError:
    from ai import format_ai_tweet_summary
    from config import configured_merge_tweet_threshold
    from rendering import TweetMessageRenderer
    from scheduler.config import ScheduleGroup
    from scheduler.formatting import (
        _format_limited_values as scheduler_format_limited_values,
    )
    from scheduler.models import (
        BatchSummaryTracker,
        PendingTweetBatch,
        ScheduledCheckResult,
        ScheduledPushResult,
    )
    from shared import format_subscription_source
    from shared.group_ids import DEFAULT_GROUP_NAME, is_default_group


class SchedulerSendMixin:
    """定时推送的发送路径。"""

    def _tweets_for_target(
        self,
        batch: PendingTweetBatch,
        target_umo: str,
        result: ScheduledCheckResult | None = None,
    ) -> tuple[list, int]:
        reader = getattr(self, "config_reader", None)
        blocked_users_cache = getattr(self, "_target_blocked_users_cache", None)
        if blocked_users_cache is None:
            blocked_users_cache = (
                reader.target_blocked_users() if reader is not None else {}
            )
            self._target_blocked_users_cache = blocked_users_cache
        blocked_users = {
            str(username).casefold()
            for username in blocked_users_cache.get(target_umo, [])
        }
        if not blocked_users:
            return batch.tweets, 0

        allowed_tweets = [
            tweet
            for tweet in batch.tweets
            if str(getattr(tweet, "username", "") or "").casefold() not in blocked_users
        ]
        filtered_count = len(batch.tweets) - len(allowed_tweets)
        if filtered_count and result is not None:
            result.target_blocked_filtered += filtered_count
            self._log_verbose_info(
                "[NitterTweets] 按推送目标过滤作者: "
                f"target={target_umo}, source={batch.username}, "
                f"filtered={filtered_count}"
            )
        return allowed_tweets, filtered_count

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
                    await self._send_per_user_updates(
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
                    immediate_batches_sent += 1
                pending_batches.append(batch)
            except BaseException:
                await self._cleanup_batch_media(batch)
                raise
            return pending_batches, immediate_batches_sent

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
                    group_label=group_label,
                    batch_summary_tracker=immediate_batch_summary_tracker,
                    batch_progress=batch_progress,
                    history_group_id=group.group_id,
                    history_source="scheduled",
                )
                if (
                    self._all_targets_delivered(immediate_targets, batch)
                    and batch.tweets[0].status_id
                ):
                    await self._store_incremental_seen_ids(
                        group.group_id,
                        batch.username,
                        [batch.tweets[0].status_id],
                        seen_map,
                    )
                immediate_batches_sent += 1
        finally:
            await self._cleanup_batch_media(batch)
        return pending_batches, immediate_batches_sent

    async def _cleanup_batch_media(self, batch: PendingTweetBatch) -> None:
        """Clean one prepared batch at most once, including cancellation paths."""
        if batch.media_cleaned:
            return
        batch.media_cleaned = True
        try:
            await asyncio.to_thread(self.media.cleanup_after_send, batch.tweets)
        except BaseException:
            batch.media_cleaned = False
            raise

    async def _cleanup_batch_media_many(self, batches: list[PendingTweetBatch]) -> None:
        for batch in batches:
            try:
                await self._cleanup_batch_media(batch)
            except Exception as exc:
                logger.warning(
                    "[NitterTweets] 批量媒体清理失败，继续清理其余批次: "
                    f"source={format_subscription_source(batch.username)}, error={exc}"
                )

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
                target_tweets, target_filtered_count = self._tweets_for_target(
                    batch, umo, result
                )
                if not target_tweets:
                    await self._mark_batch_target_delivered(
                        batch, umo, on_target_delivered
                    )
                    continue
                attempted += 1
                try:
                    header_text = self._scheduled_update_header(batch, batch_progress)
                    target_batch_summary = (
                        batch_summary_tracker.for_target(umo)
                        if batch_summary_tracker is not None
                        else ""
                    )
                    if target_filtered_count:
                        target_batch_summary = ""
                    if target_batch_summary:
                        summary_outcome = await self.sender.send_summary_to_umo(
                            self.context,
                            umo,
                            target_batch_summary,
                        )
                        if not summary_outcome.success:
                            logger.warning(
                                "[NitterTweets] 定时推送概括发送失败: "
                                f"target={umo}, error={summary_outcome.error}"
                            )
                        if summary_outcome.warning:
                            result.delivery_warnings.append(summary_outcome.warning)
                        if batch_summary_tracker is not None:
                            # A target receives at most one standalone summary;
                            # a failed attempt must not be repeated before each tweet.
                            batch_summary_tracker.mark_delivered(umo)
                    tweet_start_index = self._scheduled_tweet_start_index(
                        batch,
                        batch_progress,
                    )
                    send_kwargs = {
                        # omit_status_url/link_style filled below
                        "group_label": group_label,
                        "header_text": header_text,
                        "batch_summary": "",
                        "tweet_start_index": tweet_start_index,
                    }
                    if batch.media_only:
                        send_kwargs["media_only"] = True
                    send_kwargs["omit_status_url"] = bool(
                        getattr(batch, "omit_status_url", True)
                    )
                    send_kwargs["hide_original_when_translated"] = bool(
                        getattr(batch, "hide_original_when_translated", False)
                    )
                    outcome = await self.sender.send_to_umo_with_outcome(
                        self.context,
                        umo,
                        batch.username,
                        batch.instance,
                        target_tweets,
                        **send_kwargs,
                    )
                    delivery_complete = self._delivery_is_complete(outcome)
                    if delivery_complete:
                        await self._mark_batch_target_delivered(
                            batch, umo, on_target_delivered
                        )
                    history_status_ids = self._delivery_history_status_ids(
                        outcome, target_tweets
                    )
                    if history_status_ids:
                        await self._record_batch_push_history(
                            history_group_id,
                            batch,
                            umo,
                            history_source,
                            delivery_status=getattr(
                                outcome, "delivery_status", "success"
                            ),
                            delivery_error=getattr(outcome, "delivery_error", ""),
                            status_ids=history_status_ids,
                        )
                    if delivery_complete:
                        success += 1
                    if outcome.warning:
                        result.delivery_warnings.append(outcome.warning)
                except Exception as exc:
                    logger.warning(
                        "[NitterTweets] 定时推送失败: "
                        f"source={format_subscription_source(batch.username, result.group_type)}, "
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
                f"source={format_subscription_source(batch.username, result.group_type)}, "
                f"tweets={len(batch.tweets)}, "
                f"targets={success}/{len(targets)}"
            )
            if batch_index < len(batches) - 1 and user_interval > 0:
                await asyncio.sleep(user_interval)
        return total_success

    @staticmethod
    def _scheduled_update_header(
        batch: PendingTweetBatch, batch_progress: tuple[int, int] | None = None
    ) -> str:
        del batch, batch_progress
        return ""

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
        status_ids: tuple[str, ...] | None = None,
    ) -> None:
        if not group_id:
            return
        selected_status_ids = None if status_ids is None else set(status_ids)
        for tweet in batch.tweets:
            if not getattr(tweet, "status_id", ""):
                continue
            if (
                selected_status_ids is not None
                and str(tweet.status_id) not in selected_status_ids
            ):
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
                    f"group={group_id}, source={format_subscription_source(batch.username)}, "
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
            target_batches: list[tuple[PendingTweetBatch, list]] = []
            target_filtered_count = 0
            for batch in batches:
                if umo in batch.delivered_targets:
                    continue
                target_tweets, filtered_count = self._tweets_for_target(
                    batch, umo, result
                )
                target_filtered_count += filtered_count
                if not target_tweets:
                    await self._mark_batch_target_delivered(
                        batch, umo, on_target_delivered
                    )
                    continue
                target_batches.append((batch, target_tweets))
            if not target_batches:
                continue
            attempts += 1
            try:
                target_batch_objects = [item[0] for item in target_batches]
                merge_kwargs = {
                    "omit_status_url": all(
                        bool(getattr(batch, "omit_status_url", True))
                        for batch in target_batch_objects
                    ),
                    "hide_original_when_translated": all(
                        bool(getattr(batch, "hide_original_when_translated", False))
                        for batch in target_batch_objects
                    ),
                }
                if any(batch.media_only for batch in target_batch_objects):
                    merge_kwargs["media_only"] = True
                outcome = await self.sender.send_merged_to_umo(
                    self.context,
                    umo,
                    [
                        (batch.username, batch.instance, target_tweets)
                        for batch, target_tweets in target_batches
                    ],
                    group_label=group_label,
                    batch_summary=("" if target_filtered_count else batch_summary),
                    **merge_kwargs,
                )
                delivery_complete = self._delivery_is_complete(outcome)
                if delivery_complete:
                    for batch, _ in target_batches:
                        await self._mark_batch_target_delivered(
                            batch, umo, on_target_delivered
                        )
                history_status_ids = self._delivery_history_status_ids(
                    outcome,
                    [
                        tweet
                        for _, target_tweets in target_batches
                        for tweet in target_tweets
                    ],
                )
                if history_status_ids:
                    selected_status_ids = set(history_status_ids)
                    for batch, target_tweets in target_batches:
                        batch_status_ids = tuple(
                            str(tweet.status_id)
                            for tweet in target_tweets
                            if tweet.status_id
                            and str(tweet.status_id) in selected_status_ids
                        )
                        if not batch_status_ids:
                            continue
                        await self._record_batch_push_history(
                            history_group_id,
                            batch,
                            umo,
                            history_source,
                            delivery_status=getattr(
                                outcome, "delivery_status", "success"
                            ),
                            delivery_error=getattr(outcome, "delivery_error", ""),
                            status_ids=batch_status_ids,
                        )
                if delivery_complete:
                    success += 1
                if outcome.success:
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
            result.push_mode = (
                "mixed" if ordinary_targets or result.pushes else "merged"
            )
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

    @classmethod
    def _delivery_history_status_ids(cls, outcome, tweets) -> tuple[str, ...]:
        """Return only tweet IDs confirmed delivered by this outcome."""
        available = tuple(
            str(getattr(tweet, "status_id", "") or "")
            for tweet in tweets
            if str(getattr(tweet, "status_id", "") or "")
        )
        if cls._delivery_is_complete(outcome):
            return available
        status = str(getattr(outcome, "delivery_status", "") or "").strip().lower()
        if status != "partial_failed":
            return ()
        delivered = {
            str(status_id or "")
            for status_id in getattr(outcome, "delivered_status_ids", ()) or ()
            if str(status_id or "")
        }
        return tuple(status_id for status_id in available if status_id in delivered)

    @staticmethod
    def _delivery_is_complete(outcome) -> bool:
        """Return whether an outcome is safe to advance the shared seen key."""
        return (
            bool(getattr(outcome, "success", False))
            and str(getattr(outcome, "delivery_status", "success") or "success")
            .strip()
            .lower()
            != "failed"
        )

    @staticmethod
    def _all_targets_delivered(targets: list[str], batch: PendingTweetBatch) -> bool:
        """Reject vacuous success when a delivery path has no targets."""
        return bool(targets) and set(targets).issubset(batch.delivered_targets)

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

    @staticmethod
    def _dedupe_targets(targets: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for target in targets:
            if not target or target in seen:
                continue
            seen.add(target)
            result.append(target)
        return result

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
        group_type: str = "blogger",
    ) -> str:
        if not batches:
            return ""
        return TweetMessageRenderer.format_batch_summary(
            SchedulerSendMixin._tweet_batches(batches),
            group_label=group_label,
            action_text=action_text,
            group_type=group_type,
        )

    @staticmethod
    def _append_fetch_failure_summary(
        summary: str,
        failed_users: dict[str, str],
        group_type: str = "blogger",
    ) -> str:
        if not failed_users:
            return summary
        failed_items = []
        for user, error in failed_users.items():
            label = format_subscription_source(user, group_type)
            failed_items.append(f"{label}: {error}")
        failure_summary = "抓取失败：" + scheduler_format_limited_values(
            failed_items,
            limit=5,
            separator="；",
        )
        if summary.strip():
            return f"{summary.rstrip()}\n{failure_summary}"
        return failure_summary

    @staticmethod
    def _push_group_label(group: ScheduleGroup) -> str:
        if is_default_group(group.group_id):
            return DEFAULT_GROUP_NAME
        return str(group.name or group.group_id).strip() or group.group_id
