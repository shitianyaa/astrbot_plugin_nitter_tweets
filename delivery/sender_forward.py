"""单账号合并转发：事件路径与 UMO 路径的分块、去视频降级与递归二分。

`TweetSender` 的 mixin：只通过 `self` / `cls` 协作，不 import 宿主类。
判定 payload 是否被拒和不确定送达（`_is_forward_payload_rejected_error` /
`_is_uncertain_delivery_error`）仍在 `delivery/sender.py`，这里通过 `self` 调用。
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
    from ..shared import TweetItem
    from .outcomes import SendOutcome
except ImportError:
    from shared import TweetItem
    from delivery import SendOutcome


class SenderForwardMixin:
    """单账号合并转发路径。"""

    async def _send_event_forward_chunks(
        self,
        event,
        username: str,
        instance: str,
        tweets: list[TweetItem],
        notices: list[str] | None = None,
        tweet_start_index: int = 1,
        media_only: bool = False,
        omit_status_url: bool = True,
        hide_original_when_translated: bool = False,
        link_style: str = "plain",
        on_delivered=None,
    ) -> bool:
        chunks = self._tweet_chunks(tweets)
        indexed_chunks = []
        index = tweet_start_index
        for chunk in chunks:
            indexed_chunks.append((index, chunk))
            index += len(chunk)
        return await self._send_chunked_bool(
            indexed_chunks,
            lambda item: self._send_event_forward_chunk(
                event,
                username,
                instance,
                item[1],
                notices=notices,
                tweet_start_index=item[0],
                media_only=media_only,
                omit_status_url=omit_status_url,
                hide_original_when_translated=hide_original_when_translated,
                link_style=link_style,
                on_delivered=on_delivered,
            ),
        )

    async def _send_event_forward_chunk(
        self,
        event,
        username: str,
        instance: str,
        tweets: list[TweetItem],
        notices: list[str] | None = None,
        tweet_start_index: int = 1,
        media_only: bool = False,
        omit_status_url: bool = True,
        hide_original_when_translated: bool = False,
        link_style: str = "plain",
        on_delivered=None,
    ) -> bool:
        nodes = self.renderer.build_nodes(
            event, username, instance, tweets, notices=notices,
            start_index=tweet_start_index,
            media_only=media_only,
            omit_status_url=omit_status_url,
            hide_original_when_translated=hide_original_when_translated,
            link_style=link_style,
        )
        raw_nodes = self.renderer.build_onebot_nodes(
            event, username, instance, tweets, notices=notices,
            start_index=tweet_start_index,
            media_only=media_only,
            omit_status_url=omit_status_url,
            hide_original_when_translated=hide_original_when_translated,
            link_style=link_style,
        )
        try:
            await event.send(event.chain_result([nodes]))
            self._notify_delivered(on_delivered, len(tweets))
            return True
        except Exception as exc:
            if self._is_uncertain_delivery_error(exc):
                self._log_uncertain_delivery(
                    "manual forwarded tweets", self._event_target(event), exc
                )
                self._notify_delivered(on_delivered, len(tweets))
                return True
            logger.warning(f"[NitterTweets] 发送合并转发节点失败: {exc}")

        # 去掉视频后重试
        if not media_only and any(
            m.is_video for t in tweets for m in t.media if m.path
        ):
            try:
                nodes_nv = self.renderer.build_nodes(
                    event, username, instance, tweets,
                    exclude_videos=True, notices=notices,
                    start_index=tweet_start_index,
                    media_only=media_only,
                    omit_status_url=omit_status_url,
                    hide_original_when_translated=hide_original_when_translated,
                    link_style=link_style,
                )
                await event.send(event.chain_result([nodes_nv]))
                logger.info("[NitterTweets] 初次失败后已发送去除视频的合并转发")
                self._notify_delivered(on_delivered, len(tweets))
                return True
            except Exception as exc:
                if self._is_uncertain_delivery_error(exc):
                    self._log_uncertain_delivery(
                        "manual tweets without videos", self._event_target(event), exc
                    )
                    self._notify_delivered(on_delivered, len(tweets))
                    return True
                logger.warning(
                    f"[NitterTweets] 发送去除视频的合并转发节点失败: {exc}"
                )

        last_exc: Exception | None = None
        try:
            if await self._send_onebot_forward(event, raw_nodes):
                self._notify_delivered(on_delivered, len(tweets))
                return True
            logger.warning(
                f"[NitterTweets] 发送 OneBot 合并转发消息失败: action returned false "
                f"(tweets={len(tweets)}, target={self._event_target(event)})"
            )
        except Exception as exc:
            last_exc = exc
            if self._is_uncertain_delivery_error(exc):
                self._log_uncertain_delivery(
                    "manual OneBot forward fallback", self._event_target(event), exc
                )
                self._notify_delivered(on_delivered, len(tweets))
                return True
            logger.warning(f"[NitterTweets] 发送 OneBot 合并转发消息失败: {exc}")

        # retcode 1200 / res_id fail / explicit false: split smaller merges then retry.
        # false return (no exception) is treated as payload reject so we can split.
        should_split = last_exc is None or self._is_forward_payload_rejected_error(
            last_exc
        )
        remaining = tweets
        remaining_index = tweet_start_index
        remaining_notices = notices
        if should_split:
            parts = self._split_tweets_for_forward_retry(tweets)
            if parts:
                logger.info(
                    f"[NitterTweets] 合并转发失败，拆成 {len(parts)} 段重试 "
                    f"(tweets={len(tweets)}, target={self._event_target(event)})"
                )
                index = tweet_start_index
                for offset, part in enumerate(parts):
                    part_delivered = 0

                    def record_part_delivered(count: int) -> None:
                        nonlocal part_delivered
                        try:
                            delivered = max(0, int(count))
                        except (TypeError, ValueError, OverflowError):
                            return
                        delivered = min(len(part) - part_delivered, delivered)
                        if delivered <= 0:
                            return
                        part_delivered += delivered
                        self._notify_delivered(on_delivered, delivered)

                    part_ok = await self._send_event_forward_chunk(
                        event,
                        username,
                        instance,
                        part,
                        notices=notices if offset == 0 else None,
                        tweet_start_index=index,
                        media_only=media_only,
                        omit_status_url=omit_status_url,
                        hide_original_when_translated=hide_original_when_translated,
                        link_style=link_style,
                        on_delivered=record_part_delivered,
                    )
                    if part_ok and part_delivered < len(part):
                        record_part_delivered(len(part) - part_delivered)
                    if not part_ok:
                        # Never re-send already-delivered parts as a full-batch fallback.
                        remaining = list(part[part_delivered:])
                        for later in parts[offset + 1 :]:
                            remaining.extend(later)
                        remaining_index = index + part_delivered
                        remaining_notices = (
                            notices if offset == 0 and part_delivered == 0 else None
                        )
                        break
                    index += len(part)
                else:
                    return True

        if not remaining:
            return True

        # Final fallback: direct send only the undelivered remainder.
        logger.info(
            f"[NitterTweets] 合并转发仍失败，降级直发 "
            f"(tweets={len(remaining)}/{len(tweets)}, "
            f"target={self._event_target(event)})"
        )
        try:
            accepted = await self._delivery_adapter_for_event(event).send_event(
                event,
                username,
                instance,
                remaining,
                notices=remaining_notices,
                tweet_start_index=remaining_index,
                media_only=media_only,
                omit_status_url=omit_status_url,
                hide_original_when_translated=hide_original_when_translated,
                link_style=link_style,
            )
            if accepted:
                self._notify_delivered(on_delivered, len(remaining))
            return accepted
        except Exception as exc:
            if self._is_uncertain_delivery_error(exc):
                self._log_uncertain_delivery(
                    "manual direct after forward fail", self._event_target(event), exc
                )
                self._notify_delivered(on_delivered, len(remaining))
                return True
            logger.warning(f"[NitterTweets] 合并转发降级直发仍失败: {exc}")
            return False

    async def _send_forward_chunks_to_umo(
        self,
        context,
        umo: str,
        username: str,
        instance: str,
        tweets: list[TweetItem],
        group_label: str = "",
        header_text: str = "",
        batch_summary: str = "",
        tweet_start_index: int = 1,
        media_only: bool = False,
        omit_status_url: bool = True,
        hide_original_when_translated: bool = False,
        link_style: str = "plain",
    ) -> SendOutcome:
        chunks = self._tweet_chunks(tweets)
        indexed_chunks = []
        index = tweet_start_index
        for chunk in chunks:
            indexed_chunks.append((len(indexed_chunks), index, chunk))
            index += len(chunk)
        errors: list[str] = []
        warnings: list[str] = []
        delivery_errors: list[str] = []
        delivered: list[str] = []
        partial_delivery = False
        for item in indexed_chunks:
            outcome = await self._send_forward_chunk_to_umo(
                context,
                umo,
                username,
                instance,
                item[2],
                group_label=group_label if item[0] == 0 else "",
                header_text=header_text if item[0] == 0 else "",
                batch_summary=batch_summary if item[0] == 0 else "",
                tweet_start_index=item[1],
                media_only=media_only,
                omit_status_url=omit_status_url,
                hide_original_when_translated=hide_original_when_translated,
                link_style=link_style,
            )
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
            delivered.extend(
                getattr(outcome, "delivered_status_ids", ())
                or self._status_ids_from_tweets(item[2])
                if outcome.success
                else getattr(outcome, "delivered_status_ids", ())
            )
            if not outcome.success:
                delivery_error = "; ".join(delivery_errors) or "; ".join(errors)
                return SendOutcome(
                    success=False,
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
        return SendOutcome(
            success=True,
            error="; ".join(errors),
            warning="; ".join(warnings),
            delivery_status="partial_failed" if partial_delivery else "success",
            delivery_error=final_delivery_error,
            delivered_status_ids=self._dedupe_status_ids(delivered),
        )

    async def _send_forward_chunk_to_umo(
        self,
        context,
        umo: str,
        username: str,
        instance: str,
        tweets: list[TweetItem],
        group_label: str = "",
        header_text: str = "",
        batch_summary: str = "",
        tweet_start_index: int = 1,
        media_only: bool = False,
        omit_status_url: bool = True,
        hide_original_when_translated: bool = False,
        link_style: str = "plain",
    ) -> SendOutcome:
        nodes = self.renderer.build_nodes_for_uin(
            10000,
            username,
            instance,
            tweets,
            start_index=tweet_start_index,
            group_label=group_label,
            header_text=header_text,
            batch_summary=batch_summary,
            media_only=media_only,
            omit_status_url=omit_status_url,
            hide_original_when_translated=hide_original_when_translated,
            link_style=link_style,
        )
        attempt = await self._send_context_message(
            context, umo, MessageChain([nodes]), "scheduled forwarded tweets"
        )
        if attempt.success:
            return SendOutcome(
                success=True,
                delivered_status_ids=self._status_ids_from_tweets(tweets),
            )
        if not attempt.retryable:
            return SendOutcome(
                success=attempt.uncertain,
                error=attempt.error,
                warning=attempt.warning,
            )

        # 去掉视频后重试
        if not media_only and any(
            m.is_video for t in tweets for m in t.media if m.path
        ):
            nodes_nv = self.renderer.build_nodes_for_uin(
                10000,
                username,
                instance,
                tweets,
                start_index=tweet_start_index,
                exclude_videos=True,
                group_label=group_label,
                header_text=header_text,
                batch_summary=batch_summary,
                media_only=media_only,
                omit_status_url=omit_status_url,
                hide_original_when_translated=hide_original_when_translated,
                link_style=link_style,
            )
            attempt_nv = await self._send_context_message(
                context,
                umo,
                MessageChain([nodes_nv]),
                "scheduled tweets without videos",
            )
            if attempt_nv.success:
                logger.info(
                    f"[NitterTweets] 初次失败后已向 {umo} 发送去除视频的定时推文"
                )
                return SendOutcome(
                    success=not media_only,
                    error=attempt.error,
                    delivery_status="partial_failed",
                    delivery_error=attempt.error,
                    delivered_status_ids=(
                        () if media_only else self._status_ids_from_tweets(tweets)
                    ),
                )
            if not attempt_nv.retryable:
                retry_accepted = attempt_nv.uncertain
                return SendOutcome(
                    success=retry_accepted and not media_only,
                    error=attempt_nv.error or attempt.error,
                    warning=attempt_nv.warning,
                    delivery_status=(
                        "partial_failed" if retry_accepted else "failed"
                    ),
                    delivery_error=attempt_nv.error or attempt.error,
                    delivered_status_ids=(
                        self._status_ids_from_tweets(tweets)
                        if retry_accepted and not media_only
                        else ()
                    ),
                )
            attempt = attempt_nv

        # Only split on explicit payload reject (retcode 1200 / res_id).
        # Other retryable errors (timeout/network) fall through to plain text.
        reject = bool(attempt.error) and self._is_forward_payload_rejected_error(
            Exception(str(attempt.error))
        )
        remaining = tweets
        remaining_index = tweet_start_index
        remaining_header = header_text
        remaining_summary = batch_summary
        any_part_sent = False
        delivered: list[str] = []
        split_error = ""
        split_warning = ""
        if reject:
            parts = self._split_tweets_for_forward_retry(tweets)
            if parts:
                logger.info(
                    f"[NitterTweets] 定时合并转发失败，拆成 {len(parts)} 段重试 "
                    f"(tweets={len(tweets)}, target={umo})"
                )
                index = tweet_start_index
                for offset, part in enumerate(parts):
                    part_outcome = await self._send_forward_chunk_to_umo(
                        context,
                        umo,
                        username,
                        instance,
                        part,
                        group_label=group_label if offset == 0 else "",
                        header_text=header_text if offset == 0 else "",
                        batch_summary=batch_summary if offset == 0 else "",
                        tweet_start_index=index,
                        media_only=media_only,
                        omit_status_url=omit_status_url,
                        hide_original_when_translated=hide_original_when_translated,
                        link_style=link_style,
                    )
                    part_delivered = tuple(
                        getattr(part_outcome, "delivered_status_ids", ()) or ()
                    )
                    if part_outcome.success and not part_delivered:
                        part_delivered = self._status_ids_from_tweets(part)
                    delivered.extend(part_delivered)
                    if part_delivered:
                        any_part_sent = True
                    if not part_outcome.success:
                        split_error = (
                            getattr(part_outcome, "delivery_error", "")
                            or part_outcome.error
                        )
                        split_warning = part_outcome.warning
                        tail = []
                        for later in parts[offset:]:
                            tail.extend(later)
                        delivered_set = set(self._dedupe_status_ids(delivered))
                        remaining_with_offsets = [
                            (tail_offset, tweet)
                            for tail_offset, tweet in enumerate(tail)
                            if not tweet.status_id
                            or str(tweet.status_id) not in delivered_set
                        ]
                        remaining = [tweet for _, tweet in remaining_with_offsets]
                        if remaining_with_offsets:
                            remaining_index = index + remaining_with_offsets[0][0]
                        keep_leading_text = offset == 0 and not any_part_sent
                        remaining_header = header_text if keep_leading_text else ""
                        remaining_summary = batch_summary if keep_leading_text else ""
                        break
                    any_part_sent = True
                    index += len(part)
                else:
                    return SendOutcome(
                        success=True,
                        error=attempt.error,
                        delivery_status=(
                            "partial_failed" if attempt.error else "success"
                        ),
                        delivery_error=attempt.error,
                        delivered_status_ids=self._dedupe_status_ids(delivered),
                    )

        if not remaining:
            error = split_error or attempt.error or "forward split produced empty remainder"
            return SendOutcome(
                success=False,
                error=error,
                warning=split_warning,
                delivery_status=(
                    "partial_failed" if any_part_sent or delivered else "failed"
                ),
                delivery_error=error,
                delivered_status_ids=self._dedupe_status_ids(delivered),
            )

        # Prefer media-capable direct send for undelivered remainder only.
        # If any split part already delivered, never re-send the full batch.
        logger.info(
            f"[NitterTweets] 定时合并转发仍失败，降级直发 "
            f"(tweets={len(remaining)}/{len(tweets)}, target={umo})"
        )
        fallback = await self._send_direct_to_umo(
            context,
            umo,
            username,
            instance,
            remaining,
            group_label=group_label,
            header_text=remaining_header,
            batch_summary=remaining_summary,
            tweet_start_index=remaining_index,
            media_only=media_only,
            omit_status_url=omit_status_url,
            hide_original_when_translated=hide_original_when_translated,
            link_style=link_style,
        )
        fallback_delivered = tuple(
            getattr(fallback, "delivered_status_ids", ()) or ()
        )
        if fallback.success:
            delivered.extend(
                fallback_delivered or self._status_ids_from_tweets(remaining)
            )
            return SendOutcome(
                success=True,
                error=attempt.error or fallback.error or split_error,
                warning=fallback.warning or split_warning,
                delivery_status=(
                    "partial_failed"
                    if attempt.error or fallback.error or split_error or any_part_sent
                    else "success"
                ),
                delivery_error=attempt.error or fallback.error or split_error or "",
                delivered_status_ids=self._dedupe_status_ids(delivered),
            )
        if fallback_delivered:
            delivered.extend(fallback_delivered)
            delivered_set = set(self._dedupe_status_ids(delivered))
            remaining_with_offsets = [
                (offset, tweet)
                for offset, tweet in enumerate(remaining)
                if not tweet.status_id
                or str(tweet.status_id) not in delivered_set
            ]
            remaining = [tweet for _, tweet in remaining_with_offsets]
            if remaining_with_offsets:
                remaining_index += remaining_with_offsets[0][0]
            remaining_header = ""
            remaining_summary = ""
            any_part_sent = True
            if not remaining:
                error = (
                    getattr(fallback, "delivery_error", "")
                    or fallback.error
                    or split_error
                )
                return SendOutcome(
                    success=False,
                    error=error,
                    warning=fallback.warning or split_warning,
                    delivery_status="partial_failed",
                    delivery_error=error,
                    delivered_status_ids=self._dedupe_status_ids(delivered),
                )

        if media_only:
            error = (
                getattr(fallback, "delivery_error", "")
                or fallback.error
                or split_error
                or attempt.error
                or "media-only delivery failed"
            )
            return SendOutcome(
                success=False,
                error=error,
                warning=fallback.warning or split_warning,
                delivery_status="partial_failed" if delivered else "failed",
                delivery_error=error,
                delivered_status_ids=self._dedupe_status_ids(delivered),
            )

        # Second-level: plain text (lighter payload) for remainder only.
        plain = await self._send_context_message(
            context,
            umo,
            MessageChain(
                [
                    Plain(
                        self.renderer.format_plain(
                            username,
                            instance,
                            remaining,
                            start_index=remaining_index,
                            group_label=group_label,
                            header_text=remaining_header,
                            batch_summary=remaining_summary,
                            media_only=media_only,
                            omit_status_url=omit_status_url,
                            hide_original_when_translated=hide_original_when_translated,
                            link_style=link_style,
                        )
                    )
                ]
            ),
            "scheduled tweet plain fallback",
        )
        plain_ok = plain.success or plain.uncertain
        if plain.success and not media_only:
            delivered.extend(self._status_ids_from_tweets(remaining))
        # Do not mark whole-batch success when only some split parts arrived:
        # scheduler would advance seen and permanently drop the remainder.
        # Prefer possible re-push of the first part over silent loss.
        if plain_ok and media_only:
            error = (
                plain.error
                or fallback.error
                or split_error
                or attempt.error
                or "media-only fallback omitted media"
            )
            return SendOutcome(
                success=False,
                error=error,
                warning=plain.warning or fallback.warning or split_warning,
                delivery_status="partial_failed" if delivered else "failed",
                delivery_error=error,
                delivered_status_ids=self._dedupe_status_ids(delivered),
            )
        if plain_ok:
            return SendOutcome(
                success=True,
                error=attempt.error or plain.error or fallback.error or split_error,
                warning=plain.warning or fallback.warning or split_warning,
                delivery_status=(
                    "partial_failed"
                    if attempt.error
                    or plain.error
                    or fallback.error
                    or split_error
                    or any_part_sent
                    else "success"
                ),
                delivery_error=(
                    attempt.error
                    or plain.error
                    or fallback.error
                    or split_error
                    or ""
                ),
                delivered_status_ids=self._dedupe_status_ids(delivered),
            )
        error = plain.error or fallback.error or split_error or attempt.error
        return SendOutcome(
            success=False,
            error=error,
            warning=plain.warning or fallback.warning or split_warning,
            delivery_status=(
                "partial_failed" if any_part_sent or delivered else "failed"
            ),
            delivery_error=error or "",
            delivered_status_ids=self._dedupe_status_ids(delivered),
        )
