"""准备阶段：翻译/媒体准备的串并调度与 media_only 判定。

`NitterTweetScheduler` 的 mixin：只通过 `self` 协作，不 import 宿主类。
准备完成后经 `self._send_or_buffer_immediate_batch` 交给发送路径（见 runner_send）。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from astrbot.api import logger

try:
    from ..config import media_only_unavailable_reason
    from ..shared import TweetItem
    from ..shared.media_status import (
        MEDIA_STATUS_NO_CANDIDATE,
        MEDIA_STATUS_POLICY_SKIPPED,
        MEDIA_STATUS_READY,
    )
    from .config import ScheduleGroup
    from .models import (
        BatchSummaryTracker,
        PendingTweetBatch,
        PreparedBatchResult,
        ScheduledCheckResult,
        SchedulerTaskError,
    )
except ImportError:
    from config import media_only_unavailable_reason
    from shared import TweetItem
    from shared.media_status import (
        MEDIA_STATUS_NO_CANDIDATE,
        MEDIA_STATUS_POLICY_SKIPPED,
        MEDIA_STATUS_READY,
    )
    from scheduler.config import ScheduleGroup
    from scheduler.models import (
        BatchSummaryTracker,
        PendingTweetBatch,
        PreparedBatchResult,
        ScheduledCheckResult,
        SchedulerTaskError,
    )


class SchedulerPrepareMixin:
    """准备批次与 media_only 策略。"""

    @staticmethod
    def _should_use_concurrent_prepare(group: ScheduleGroup) -> bool:
        return bool(group.concurrent_prepare_enabled) and group.prepare_concurrency > 1

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
        current_batch: PendingTweetBatch | None = None
        try:
            for discovered_batch in discovered_batches:
                username = discovered_batch.username
                new_tweets = discovered_batch.tweets
                prepared_count = 0
                for tweet_index, tweet in enumerate(new_tweets, 1):
                    current_batch = self._single_tweet_batch(
                        discovered_batch,
                        tweet,
                        tweet_index,
                        seen_map,
                    )
                    try:
                        prepared = await self._prepare_immediate_batch(
                            current_batch, target_umo
                        )
                    except Exception as exc:
                        await self._record_prepare_failure(result, current_batch, exc)
                        current_batch = None
                        continue

                    if prepared.media_status != MEDIA_STATUS_READY:
                        await self._handle_media_prepare_status(
                            result,
                            current_batch,
                            prepared.media_status,
                            prepared.media_error,
                            seen_map,
                            group.group_id,
                        )
                        current_batch = None
                        continue

                    await self._handle_immediate_prepare_success(
                        group, prepared, seen_map
                    )
                    prepared_count += 1
                    (
                        pending_batches,
                        immediate_batches_sent,
                    ) = await self._send_or_buffer_immediate_batch(
                        current_batch,
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
                    current_batch = None
                self._log_prepare_progress(username, prepared_count, len(new_tweets))
        except BaseException:
            batches_to_clean = list(pending_batches)
            if current_batch is not None:
                batches_to_clean.append(current_batch)
            await self._cleanup_batch_media_many(batches_to_clean)
            raise
        return pending_batches, immediate_batches_sent

    async def _prepare_batches_concurrently(
        self,
        batches: list[PendingTweetBatch],
        concurrency: int,
        prepare_one: Callable[[PendingTweetBatch], Awaitable[PreparedBatchResult]],
        on_result: Callable[[PreparedBatchResult], Awaitable[None]] | None = None,
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

        tasks = [asyncio.create_task(prepare(batch)) for batch in batches]
        results: list[PreparedBatchResult] = []
        try:
            for task in asyncio.as_completed(tasks):
                prepared = await task
                results.append(prepared)
                if on_result is not None:
                    await on_result(prepared)
        except BaseException:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        return results

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

        pending_batches: list[PendingTweetBatch] = []
        prepared_count_by_user: dict[str, int] = {}
        total_by_user: dict[str, int] = {}
        for batch in discovered_batches:
            total_by_user[batch.username] = total_by_user.get(batch.username, 0) + len(
                batch.tweets
            )

        async def consume(prepared: PreparedBatchResult) -> None:
            nonlocal pending_batches, immediate_batches_sent
            batch = prepared.batch
            tweet_index = batch.tweet_index
            if prepared.error:
                await self._record_prepare_failure(result, batch, prepared.error)
                return
            if prepared.media_status != MEDIA_STATUS_READY:
                await self._handle_media_prepare_status(
                    result,
                    batch,
                    prepared.media_status,
                    prepared.media_error,
                    seen_map,
                    group.group_id,
                )
                return

            await self._handle_immediate_prepare_success(group, prepared, seen_map)
            prepared_count_by_user[batch.username] = (
                prepared_count_by_user.get(batch.username, 0) + 1
            )
            (
                pending_batches,
                immediate_batches_sent,
            ) = await self._send_or_buffer_immediate_batch(
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

        try:
            await self._prepare_batches_concurrently(
                single_batches,
                group.prepare_concurrency,
                lambda batch: self._prepare_immediate_batch(batch, target_umo),
                on_result=consume,
            )
        except BaseException:
            await self._cleanup_batch_media_many([*single_batches, *pending_batches])
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
        translation_report = None
        if not batch.media_only:
            translation_report = await self.translator.attach_translations(
                batch.tweets, target_umo
            )

        media_status = MEDIA_STATUS_READY
        media_error = ""
        if batch.media_only:
            media_results_method = getattr(
                self.media, "attach_media_with_results", None
            )
            if callable(media_results_method):
                reports = await media_results_method(batch.tweets)
                report = reports[0] if reports else None
                media_status = str(getattr(report, "status", MEDIA_STATUS_NO_CANDIDATE))
                media_error = str(getattr(report, "error", "") or "")
            else:
                await self.media.attach_media(batch.tweets)
                media_status = (
                    MEDIA_STATUS_READY
                    if self._has_prepared_media(batch.tweets)
                    else MEDIA_STATUS_NO_CANDIDATE
                )
        else:
            await self.media.attach_media(batch.tweets)
        return PreparedBatchResult(
            batch=batch,
            translation_report=translation_report,
            media_status=media_status,
            media_error=media_error,
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
            media_only=discovered_batch.media_only,
            omit_status_url=bool(getattr(discovered_batch, 'omit_status_url', True)),
            hide_original_when_translated=bool(getattr(discovered_batch, "hide_original_when_translated", False)),
        )

    async def _record_prepare_failure(
        self,
        result: ScheduledCheckResult,
        batch: PendingTweetBatch,
        error: SchedulerTaskError | Exception,
    ) -> None:
        username = batch.username
        tweet = batch.tweets[0]
        tweet_index = batch.tweet_index
        status_id = tweet.status_id or f"index-{tweet_index}"
        if isinstance(error, SchedulerTaskError):
            error_message = error.message
        else:
            error_message = str(error)
        await self._cleanup_batch_media(batch)
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
        if batch.media_only:
            return
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

    def _media_only_effective(self, group: ScheduleGroup) -> bool:
        return bool(
            group.media_only_enabled and not self._media_only_unavailable_reason(group)
        )

    async def _handle_media_prepare_status(
        self,
        result: ScheduledCheckResult,
        batch: PendingTweetBatch,
        status: str,
        error: str,
        seen_map: dict[str, list[str]],
        group_id: str,
    ) -> None:
        batch.media_status = status
        await self._cleanup_batch_media(batch)
        status_id = str(batch.tweets[0].status_id or "") if batch.tweets else ""
        if status == MEDIA_STATUS_POLICY_SKIPPED:
            result.media_only_skipped += 1
            if status_id:
                await self._store_incremental_seen_ids(
                    group_id,
                    batch.username,
                    [status_id],
                    seen_map,
                )
            self._log_verbose_info(
                "[NitterTweets] 仅媒体推文按全局媒体策略跳过: "
                f"username={batch.username}, status={status_id}"
            )
            return

        result.media_only_retrying += 1
        logger.warning(
            "[NitterTweets] 仅媒体推文暂未准备好，下轮重试: "
            f"username={batch.username}, status={status_id}, "
            f"status={status}, error={error or 'no media'}"
        )

    @staticmethod
    def _has_prepared_media(tweets: list[TweetItem]) -> bool:
        return any(
            media.path and (media.is_image or media.is_video)
            for tweet in tweets
            for media in getattr(tweet, "media", [])
        )

    def _media_only_unavailable_reason(self, group: ScheduleGroup) -> str:
        return media_only_unavailable_reason(
            self.config,
            media_only_enabled=group.media_only_enabled,
        )
