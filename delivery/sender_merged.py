"""多账号合并转发：分块、去视频降级和 payload 拒绝后的递归二分。

`TweetSender` 的 mixin：只通过 `self` / `cls` 协作，不 import 宿主类。
判定 payload 是否被拒（`_is_forward_payload_rejected_error`）仍在
`delivery/sender.py`，这里通过 `self` 调用。
"""

from __future__ import annotations

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
    from ..rendering import TweetBatch
    from .outcomes import MergedSendOutcome, SendAttempt
except ImportError:
    from delivery import MergedSendOutcome, SendAttempt
    from rendering import TweetBatch


class SenderMergedForwardMixin:
    """跨账号合并转发路径。"""

    async def send_merged_to_umo(
        self,
        context,
        umo: str,
        batches: list[TweetBatch],
        group_label: str = "",
        batch_summary: str = "",
        media_only: bool = False,
        omit_status_url: bool = True,
        hide_original_when_translated: bool = False,
        link_style: str = "plain",
    ) -> MergedSendOutcome:
        adapter = self._delivery_adapter_for_umo(context, umo)
        if link_style == "plain":
            link_style = self.resolve_link_style(getattr(adapter, "name", ""))
        tweet_count = self._count_batch_tweets(batches)
        if not self._should_use_merge_for_count(tweet_count):
            return await self._send_merged_direct_to_umo(
                context,
                umo,
                batches,
                group_label,
                batch_summary,
                media_only=media_only,
                omit_status_url=omit_status_url,
                hide_original_when_translated=hide_original_when_translated,
                link_style=link_style,
            )

        if not adapter.supports_merged_forward:
            return await self._send_merged_direct_to_umo(
                context,
                umo,
                batches,
                group_label,
                batch_summary,
                media_only=media_only,
                omit_status_url=omit_status_url,
                hide_original_when_translated=hide_original_when_translated,
                link_style=link_style,
            )

        if self._should_chunk_forward_tweets(tweet_count):
            return await self._send_merged_forward_chunks_to_umo(
                context,
                umo,
                batches,
                group_label,
                batch_summary,
                media_only=media_only,
                omit_status_url=omit_status_url,
                hide_original_when_translated=hide_original_when_translated,
                link_style=link_style,
            )

        return await self._send_merged_forward_chunk_to_umo(
            context,
            umo,
            batches,
            group_label,
            batch_summary,
            media_only=media_only,
            omit_status_url=omit_status_url,
            hide_original_when_translated=hide_original_when_translated,
            link_style=link_style,
        )

    async def _send_merged_forward_chunks_to_umo(
        self,
        context,
        umo: str,
        batches: list[TweetBatch],
        group_label: str = "",
        batch_summary: str = "",
        media_only: bool = False,
        omit_status_url: bool = True,
        hide_original_when_translated: bool = False,
        link_style: str = "plain",
    ) -> MergedSendOutcome:
        omitted_videos = 0

        def track_omitted_videos(outcome: MergedSendOutcome) -> None:
            nonlocal omitted_videos
            omitted_videos += outcome.omitted_videos

        chunked_batches = []
        start_index = 1
        for chunk_index, chunk in enumerate(self._batch_chunks(batches)):
            chunked_batches.append((chunk_index, start_index, chunk))
            start_index += self._count_batch_tweets(chunk)
        errors: list[str] = []
        warnings: list[str] = []
        delivery_errors: list[str] = []
        delivered: list[str] = []
        partial_delivery = False
        for indexed_chunk in chunked_batches:
            outcome = await self._send_merged_forward_chunk_to_umo(
                context,
                umo,
                indexed_chunk[2],
                group_label if indexed_chunk[0] == 0 else "",
                batch_summary if indexed_chunk[0] == 0 else "",
                tweet_start_index=indexed_chunk[1],
                media_only=media_only,
                omit_status_url=omit_status_url,
                hide_original_when_translated=hide_original_when_translated,
                link_style=link_style,
            )
            track_omitted_videos(outcome)
            if outcome.error:
                errors.append(outcome.error)
            if outcome.warning:
                warnings.append(outcome.warning)
            status = self._normalized_delivery_status(outcome)
            if status in {"partial_failed", "failed"}:
                partial_delivery = True
            outcome_delivery_error = getattr(outcome, "delivery_error", "")
            if outcome_delivery_error:
                delivery_errors.append(outcome_delivery_error)
            if outcome.success:
                delivered.extend(
                    getattr(outcome, "delivered_status_ids", ())
                    or self._status_ids_from_batches(indexed_chunk[2])
                )
            else:
                delivered.extend(getattr(outcome, "delivered_status_ids", ()))
                delivery_error = "; ".join(delivery_errors) or "; ".join(errors)
                return MergedSendOutcome(
                    success=False,
                    mode=outcome.mode,
                    omitted_videos=omitted_videos,
                    error="; ".join(errors) or outcome.error,
                    warning="; ".join(warnings),
                    delivery_status=(
                        "partial_failed"
                        if delivered or status == "partial_failed"
                        else "failed"
                    ),
                    delivery_error=delivery_error or outcome.error,
                    delivered_status_ids=self._dedupe_status_ids(delivered),
                )
        final_delivery_error = "; ".join(delivery_errors)
        if partial_delivery and not final_delivery_error:
            final_delivery_error = "; ".join(errors)
        return MergedSendOutcome(
            success=True,
            mode="chunked_forward",
            omitted_videos=omitted_videos,
            error="; ".join(errors),
            warning="; ".join(warnings),
            delivery_status="partial_failed" if partial_delivery else "success",
            delivery_error=final_delivery_error,
            delivered_status_ids=self._dedupe_status_ids(delivered),
        )

    async def _send_merged_forward_chunk_to_umo(
        self,
        context,
        umo: str,
        batches: list[TweetBatch],
        group_label: str = "",
        batch_summary: str = "",
        tweet_start_index: int = 1,
        media_only: bool = False,
        omit_status_url: bool = True,
        hide_original_when_translated: bool = False,
        link_style: str = "plain",
    ) -> MergedSendOutcome:
        omitted_videos = self._count_attached_videos(batches)
        has_video = self._merged_forward_has_video(batches)
        raw_forward_available = (
            has_video and self._onebot_call_action_for_umo(context, umo) is not None
        )
        attempt = SendAttempt(
            success=False,
            retryable=True,
            error="video merged forward not attempted",
        )
        if raw_forward_available:
            raw_nodes = self.renderer.build_merged_onebot_nodes_for_uin(
                10000,
                batches,
                start_index=tweet_start_index,
                group_label=group_label,
                batch_summary=batch_summary,
                media_only=media_only,
                omit_status_url=omit_status_url,
                hide_original_when_translated=hide_original_when_translated,
                link_style=link_style,
            )
            attempt = await self._send_onebot_umo_forward(
                context, umo, raw_nodes, "merged scheduled tweets"
            )
            if attempt.success:
                return MergedSendOutcome(success=True, mode="raw_forward")
            if not attempt.retryable:
                return MergedSendOutcome(
                    success=attempt.uncertain,
                    mode="uncertain_delivery" if attempt.uncertain else "failed",
                    omitted_videos=omitted_videos,
                    error=attempt.error,
                    warning=attempt.warning,
                )

        if not raw_forward_available:
            nodes = self.renderer.build_merged_nodes_for_uin(
                10000,
                batches,
                start_index=tweet_start_index,
                group_label=group_label,
                batch_summary=batch_summary,
                media_only=media_only,
                omit_status_url=omit_status_url,
                hide_original_when_translated=hide_original_when_translated,
                link_style=link_style,
            )
            attempt = await self._send_context_message(
                context, umo, MessageChain([nodes]), "merged scheduled tweets"
            )
            if attempt.success:
                return MergedSendOutcome(success=True, mode="full_forward")
            if not attempt.retryable:
                return MergedSendOutcome(
                    success=attempt.uncertain,
                    mode="uncertain_delivery" if attempt.uncertain else "failed",
                    omitted_videos=omitted_videos,
                    error=attempt.error,
                    warning=attempt.warning,
                )

        if omitted_videos and not media_only:
            raw_nodes_nv = self.renderer.build_merged_onebot_nodes_for_uin(
                10000,
                batches,
                start_index=tweet_start_index,
                exclude_videos=True,
                group_label=group_label,
                batch_summary=batch_summary,
                media_only=media_only,
                omit_status_url=omit_status_url,
                hide_original_when_translated=hide_original_when_translated,
                link_style=link_style,
            )
            raw_retry_attempt = await self._send_onebot_umo_forward(
                context,
                umo,
                raw_nodes_nv,
                "merged tweets without videos",
            )
            if raw_retry_attempt.success:
                logger.warning(
                    f"[NitterTweets] 初次失败后已向 {umo} 发送去除 "
                    f"{omitted_videos} 个视频/GIF 附件的合并推文"
                )
                return MergedSendOutcome(
                    success=not media_only,
                    mode="raw_forward_without_videos",
                    omitted_videos=omitted_videos,
                    error=attempt.error,
                    delivery_status="partial_failed",
                    delivery_error=attempt.error,
                )
            if not raw_retry_attempt.retryable:
                retry_accepted = raw_retry_attempt.uncertain
                return MergedSendOutcome(
                    success=retry_accepted and not media_only,
                    mode=("uncertain_delivery" if retry_accepted else "failed"),
                    omitted_videos=omitted_videos,
                    error=raw_retry_attempt.error or attempt.error,
                    warning=raw_retry_attempt.warning,
                    delivery_status=("partial_failed" if retry_accepted else "failed"),
                    delivery_error=raw_retry_attempt.error or attempt.error,
                )
            nodes_nv = self.renderer.build_merged_nodes_for_uin(
                10000,
                batches,
                start_index=tweet_start_index,
                exclude_videos=True,
                group_label=group_label,
                batch_summary=batch_summary,
                media_only=media_only,
                omit_status_url=omit_status_url,
                hide_original_when_translated=hide_original_when_translated,
                link_style=link_style,
            )
            retry_attempt = await self._send_context_message(
                context,
                umo,
                MessageChain([nodes_nv]),
                "merged tweets without videos",
            )
            if retry_attempt.success:
                logger.warning(
                    f"[NitterTweets] 初次失败后已向 {umo} 发送去除 "
                    f"{omitted_videos} 个视频/GIF 附件的合并推文"
                )
                return MergedSendOutcome(
                    success=not media_only,
                    mode="forward_without_videos",
                    omitted_videos=omitted_videos,
                    error=attempt.error,
                    delivery_status="partial_failed",
                    delivery_error=attempt.error,
                )
            if not retry_attempt.retryable:
                retry_accepted = retry_attempt.uncertain
                return MergedSendOutcome(
                    success=retry_accepted and not media_only,
                    mode=("uncertain_delivery" if retry_accepted else "failed"),
                    omitted_videos=omitted_videos,
                    error=retry_attempt.error or attempt.error,
                    warning=retry_attempt.warning,
                    delivery_status=("partial_failed" if retry_accepted else "failed"),
                    delivery_error=retry_attempt.error or attempt.error,
                )
            attempt = retry_attempt

        reject = bool(attempt.error) and self._is_forward_payload_rejected_error(
            Exception(str(attempt.error))
        )
        remaining_batches = batches
        remaining_start_index = tweet_start_index
        remaining_group_label = group_label
        remaining_summary = batch_summary
        delivered: list[str] = []
        split_error = ""
        split_warning = ""
        split_omitted_videos = 0
        if reject:
            parts = self._split_batches_for_forward_retry(batches)
            if parts:
                logger.info(
                    f"[NitterTweets] 定时多批次合并转发失败，拆成 {len(parts)} 段重试 "
                    f"(tweets={self._count_batch_tweets(batches)}, target={umo})"
                )
                index = tweet_start_index
                for offset, part in enumerate(parts):
                    part_outcome = await self._send_merged_forward_chunk_to_umo(
                        context,
                        umo,
                        part,
                        group_label if offset == 0 else "",
                        batch_summary if offset == 0 else "",
                        tweet_start_index=index,
                        media_only=media_only,
                        omit_status_url=omit_status_url,
                        hide_original_when_translated=hide_original_when_translated,
                        link_style=link_style,
                    )
                    split_omitted_videos += part_outcome.omitted_videos
                    part_delivered = tuple(
                        getattr(part_outcome, "delivered_status_ids", ()) or ()
                    )
                    if part_outcome.success and not part_delivered:
                        part_delivered = self._status_ids_from_batches(part)
                    delivered.extend(part_delivered)
                    if not part_outcome.success:
                        split_error = (
                            getattr(part_outcome, "delivery_error", "")
                            or part_outcome.error
                        )
                        split_warning = part_outcome.warning
                        tail = []
                        for later in parts[offset:]:
                            tail.extend(later)
                        (
                            remaining_batches,
                            first_remaining_offset,
                        ) = self._batches_without_status_ids(tail, delivered)
                        remaining_start_index = index + first_remaining_offset
                        keep_leading_text = offset == 0 and not delivered
                        remaining_group_label = group_label if keep_leading_text else ""
                        remaining_summary = batch_summary if keep_leading_text else ""
                        break
                    index += self._count_batch_tweets(part)
                else:
                    return MergedSendOutcome(
                        success=True,
                        mode="split_forward",
                        omitted_videos=split_omitted_videos,
                        error=attempt.error,
                        delivery_status="partial_failed",
                        delivery_error=attempt.error,
                        delivered_status_ids=self._dedupe_status_ids(delivered),
                    )

        if not remaining_batches:
            error = (
                split_error or attempt.error or "forward split produced empty remainder"
            )
            return MergedSendOutcome(
                success=False,
                mode="failed",
                omitted_videos=split_omitted_videos or omitted_videos,
                error=error,
                warning=split_warning,
                delivery_status="partial_failed" if delivered else "failed",
                delivery_error=error,
                delivered_status_ids=self._dedupe_status_ids(delivered),
            )

        if media_only:
            error = split_error or attempt.error or "media-only delivery failed"
            return MergedSendOutcome(
                success=False,
                mode="failed",
                omitted_videos=split_omitted_videos or omitted_videos,
                error=error,
                warning=split_warning,
                delivery_status="partial_failed" if delivered else "failed",
                delivery_error=error,
                delivered_status_ids=self._dedupe_status_ids(delivered),
            )

        fallback = await self._send_context_message(
            context,
            umo,
            MessageChain(
                [
                    Plain(
                        self.renderer.format_merged_plain(
                            remaining_batches,
                            start_index=remaining_start_index,
                            group_label=remaining_group_label,
                            batch_summary=remaining_summary,
                            media_only=media_only,
                            omit_status_url=omit_status_url,
                            hide_original_when_translated=hide_original_when_translated,
                            link_style=link_style,
                        )
                    )
                ]
            ),
            "merged scheduled tweet fallback",
        )
        if fallback.success or fallback.uncertain:
            if media_only:
                error = (
                    split_error
                    or attempt.error
                    or fallback.error
                    or "media-only fallback omitted media"
                )
                return MergedSendOutcome(
                    success=False,
                    mode="plain_fallback",
                    omitted_videos=split_omitted_videos or omitted_videos,
                    error=error,
                    warning=fallback.warning or split_warning,
                    delivery_status="partial_failed" if delivered else "failed",
                    delivery_error=error,
                    delivered_status_ids=self._dedupe_status_ids(delivered),
                )
            if fallback.success:
                delivered.extend(self._status_ids_from_batches(remaining_batches))
            return MergedSendOutcome(
                success=True,
                mode="uncertain_delivery" if fallback.uncertain else "plain_fallback",
                omitted_videos=split_omitted_videos or omitted_videos,
                error=split_error or attempt.error,
                warning=fallback.warning or split_warning,
                delivery_status=(
                    "partial_failed"
                    if split_error or attempt.error or delivered
                    else "success"
                ),
                delivery_error=split_error or attempt.error,
                delivered_status_ids=self._dedupe_status_ids(delivered),
            )
        error = fallback.error or split_error or attempt.error
        return MergedSendOutcome(
            success=False,
            mode="failed",
            omitted_videos=split_omitted_videos or omitted_videos,
            error=error,
            warning=fallback.warning or split_warning,
            delivery_status="partial_failed" if delivered else "failed",
            delivery_error=error,
            delivered_status_ids=self._dedupe_status_ids(delivered),
        )
