from __future__ import annotations

from dataclasses import replace

from astrbot.api import logger

from .default import DefaultDeliveryAdapter
from .media_transport import apply_memo
from .outcomes import SendAttempt, SendOutcome
from .sender_transport import _build_media_segment

try:
    from ..shared import safe_call
except ImportError:
    from shared import safe_call


class OneBotDeliveryAdapter(DefaultDeliveryAdapter):
    name = "onebot"

    @property
    def supports_merged_forward(self) -> bool:
        return True

    @property
    def should_split_direct_videos(self) -> bool:
        return True

    @property
    def should_split_direct_images(self) -> bool:
        return True

    def media_transport_ladder(self, media, **kwargs) -> tuple[str, ...]:
        """OneBot is the one adapter that hands a path to a separate process.

        NapCat / LLOneBot / Lagrange may run in another container or on another
        host, where ``file:///`` is unreadable. Fall back to other wire encodings
        before the lossy content degradation gets a chance to drop the media.
        """
        policy = getattr(self.sender, "transport_policy", None)
        if policy is None:
            return super().media_transport_ladder(media, **kwargs)
        return policy.ladder_for(media, **kwargs)

    def _event_call_action(self, event):
        client = getattr(event, "bot", None)
        if hasattr(client, "api") and hasattr(client.api, "call_action"):
            return client.api.call_action
        if hasattr(client, "call_action"):
            return client.call_action
        return self.profile.call_action

    async def send_event_forward(self, event, raw_nodes: list[dict]) -> bool:
        call_action = self._event_call_action(event)
        if call_action is None:
            return False

        group_id = safe_call(event, "get_group_id")
        if group_id:
            await self.call_forward_action(
                call_action,
                "send_group_forward_msg",
                {"group_id": int(group_id)},
                raw_nodes,
            )
            return True

        user_id = safe_call(event, "get_sender_id")
        if user_id:
            await self.call_forward_action(
                call_action,
                "send_private_forward_msg",
                {"user_id": int(user_id)},
                raw_nodes,
            )
            return True

        return False

    async def send_event_media_segment(
        self, event, segment: dict | list[dict], label: str
    ):
        """Send media segments, optionally with text, through a raw OneBot action.

        Going around AstrBot's component chain is what gives the transport layer
        control over the ``file`` value. Without ``call_action`` we return ``None``
        so the caller falls back to the unchanged component path.
        """
        call_action = self._event_call_action(event)
        if call_action is None:
            return None

        group_id = safe_call(event, "get_group_id")
        if group_id:
            action = "send_group_msg"
            payload = {"group_id": int(group_id)}
            target = str(group_id)
        else:
            user_id = safe_call(event, "get_sender_id")
            if not user_id:
                return None
            action = "send_private_msg"
            payload = {"user_id": int(user_id)}
            target = str(user_id)

        return await self._call_message_action(
            call_action, action, payload, segment, label, target
        )

    async def send_umo_media_segment(
        self, context, umo: str, segment: dict | list[dict], label: str
    ):
        call_action = self.sender._onebot_call_action_for_umo(context, umo)
        if call_action is None:
            return None

        message_type, session_id = self.onebot_target_from_umo(umo)
        if not session_id:
            return None

        action = "send_group_msg"
        payload = {"group_id": session_id}
        if message_type in {"private", "friend", "friendmessage", "privatemessage"}:
            action = "send_private_msg"
            payload = {"user_id": session_id}

        return await self._call_message_action(
            call_action, action, payload, segment, label, umo
        )

    async def _call_message_action(
        self,
        call_action,
        action: str,
        payload: dict,
        segment: dict | list[dict],
        label: str,
        target: str,
    ) -> SendAttempt:
        try:
            await call_action(
                action,
                **payload,
                message=segment if isinstance(segment, list) else [segment],
            )
        except Exception as exc:
            return self.sender._send_exception_attempt(exc, label, target)
        return SendAttempt(success=True)

    async def send_umo_forward(
        self,
        context,
        umo: str,
        raw_nodes: list[dict],
        label: str,
    ) -> SendAttempt:
        call_action = self.sender._onebot_call_action_for_umo(context, umo)
        if call_action is None:
            return SendAttempt(
                success=False,
                retryable=True,
                error="OneBot call_action unavailable for proactive merged forward",
            )

        message_type, session_id = self.onebot_target_from_umo(umo)
        if not session_id:
            return SendAttempt(
                success=False,
                retryable=True,
                error=f"invalid OneBot target UMO: {umo}",
            )

        action = "send_group_forward_msg"
        base_payload = {"group_id": session_id}
        if message_type in {"private", "friend", "friendmessage", "privatemessage"}:
            action = "send_private_forward_msg"
            base_payload = {"user_id": session_id}

        try:
            await self.call_forward_action(
                call_action,
                action,
                base_payload,
                raw_nodes,
            )
        except Exception as exc:
            error = str(exc)
            if self.sender._is_uncertain_delivery_error(exc):
                warning = self.sender.UNCERTAIN_DELIVERY_WARNING
                self.sender._log_uncertain_delivery(label, umo, exc)
                return SendAttempt(
                    success=False,
                    retryable=False,
                    uncertain=True,
                    error=error,
                    warning=warning,
                )
            logger.warning(
                f"[NitterTweets] 通过 OneBot action 发送失败: "
                f"label={label}, target={umo}, error={error}"
            )
            return SendAttempt(success=False, retryable=True, error=error)

        return SendAttempt(success=True)

    @staticmethod
    def onebot_target_from_umo(umo: str) -> tuple[str, int | str]:
        parts = str(umo or "").split(":", 2)
        message_type = parts[1].strip().lower() if len(parts) >= 2 else ""
        raw_session_id = parts[2].strip() if len(parts) >= 3 else ""
        try:
            session_id: int | str = int(raw_session_id)
        except (TypeError, ValueError):
            session_id = raw_session_id
        return message_type, session_id

    @staticmethod
    async def call_forward_action(
        call_action,
        action: str,
        base_payload: dict,
        raw_nodes: list[dict],
    ) -> None:
        try:
            await call_action(action, **base_payload, messages=raw_nodes)
        except TypeError:
            await call_action(action, **base_payload, message=raw_nodes)

    async def _send_split_direct_videos_event(
        self, event, username, instance, tweets, **options
    ) -> bool:
        async def send_chain(components, label):
            return await self.sender._send_event_chain(
                event, self._message_chain(components), label
            )

        async def send_segments(segments, label):
            return await self.send_event_media_segment(event, segments, label)

        async def send_video(media, component, label):
            return await self._send_event_media_item(
                event,
                media,
                component_send=self._event_component_sender(
                    self.sender, event, component, label
                ),
                label=label,
            )

        async def fallback(tweet, kwargs):
            accepted = await super(
                OneBotDeliveryAdapter, self
            )._send_split_direct_videos_event(
                event, username, instance, [tweet], **kwargs
            )
            return SendOutcome(success=accepted)

        outcome = await self._send_direct_tweets(
            username,
            instance,
            tweets,
            options,
            send_chain,
            send_segments,
            send_video,
            fallback,
            event_mode=True,
        )
        return outcome.success

    async def _send_split_direct_videos_to_umo(
        self, context, umo, username, instance, tweets, **options
    ) -> SendOutcome:
        async def send_chain(components, label):
            return await self.sender._send_context_message(
                context, umo, self._message_chain(components), label
            )

        async def send_segments(segments, label):
            return await self.send_umo_media_segment(context, umo, segments, label)

        async def send_video(media, component, label):
            return await self._send_umo_media_item(
                context,
                umo,
                media,
                component_send=self._umo_component_sender(
                    self.sender, context, umo, component, label
                ),
                label=label,
            )

        async def fallback(tweet, kwargs):
            return await super(
                OneBotDeliveryAdapter, self
            )._send_split_direct_videos_to_umo(
                context, umo, username, instance, [tweet], **kwargs
            )

        return await self._send_direct_tweets(
            username,
            instance,
            tweets,
            options,
            send_chain,
            send_segments,
            send_video,
            fallback,
        )

    async def _send_direct_image_body(
        self, components, image_items, send_chain, send_segments
    ) -> SendAttempt:
        if not image_items:
            return (
                await send_chain(components, "OneBot direct tweet text")
                if components
                else SendAttempt(success=True)
            )

        # Each image keeps its own size/URL policy and encoding memo. Rebuild the
        # whole message on retry so text and all images stay together.
        memo = getattr(self.sender, "transport_memo", None)
        platform_id = self.profile.platform_id
        ladders = []
        for media, _component in image_items:
            ladder = self.media_transport_ladder(media, allow_skip=False)
            if memo is not None:
                ladder = apply_memo(ladder, memo.preferred(platform_id, "image"))
            ladders.append(ladder)
        last = SendAttempt(
            success=False, retryable=True, error="no usable image encoding"
        )
        mixed_components = components + [component for _media, component in image_items]
        for step in range(max(map(len, ladders))):
            encodings = [ladder[min(step, len(ladder) - 1)] for ladder in ladders]
            segments = [self.sender.renderer.raw_text(c.text) for c in components]
            for (media, _component), encoding in zip(image_items, encodings):
                segment = await _build_media_segment(media, encoding)
                if segment is None:
                    break
                segments.append(segment)
            else:
                attempt = await send_segments(
                    segments, "OneBot direct tweet with images"
                )
                if attempt is None:
                    # No raw action: AstrBot supports a mixed Plain/Image chain.
                    return await send_chain(
                        mixed_components, "OneBot direct tweet with images"
                    )
                if attempt.success:
                    if memo is not None and len(set(encodings)) == 1:
                        memo.record_success(platform_id, "image", encodings[0])
                    return attempt
                if memo is not None:
                    memo.forget(platform_id, "image")
                if attempt.uncertain or attempt.rejected or not attempt.retryable:
                    return attempt
                last = attempt
        return last

    async def _send_direct_tweets(
        self,
        username,
        instance,
        tweets,
        options,
        send_chain,
        send_segments,
        send_video,
        fallback,
        *,
        event_mode=False,
    ) -> SendOutcome:
        renderer = self.sender.renderer
        result = SendOutcome(success=True)
        delivered_ids: list[str] = []
        media_only = options.get("media_only", False)
        for offset, tweet in enumerate(tweets):
            kwargs = dict(options)
            kwargs["tweet_start_index"] = options.get("tweet_start_index", 1) + offset
            if offset:
                for key in ("notices", "header_text", "group_label", "batch_summary"):
                    kwargs.pop(key, None)
            render_options = dict(kwargs)
            render_options["start_index"] = render_options.pop("tweet_start_index")
            components = renderer.build_direct_components(
                username,
                instance,
                [tweet],
                include_images=False,
                include_videos=False,
                **render_options,
            )
            image_items = renderer.build_direct_image_items([tweet])
            body = await self._send_direct_image_body(
                components, image_items, send_chain, send_segments
            )
            if not (body.success or body.uncertain):
                if body.rejected and image_items:
                    # A content rejection must not resend the same image bytes.
                    if media_only:
                        outcome = SendOutcome(success=False)
                    else:
                        text_tweet = replace(
                            tweet, media=[m for m in tweet.media if not m.is_image]
                        )
                        outcome = await fallback(text_tweet, kwargs)
                        notice = renderer.build_image_send_failed_notice_components(
                            [tweet],
                            rejected=True,
                            omit_status_url=options.get("omit_status_url", True),
                        )
                        if notice:
                            await send_chain(
                                notice, "OneBot direct image rejected notice"
                            )
                    fallback_error = outcome.delivery_error or outcome.error
                    outcome.error = outcome.delivery_error = (
                        f"{fallback_error}; image rejected: {body.error}"
                        if not outcome.success and fallback_error
                        else body.error
                    )
                    outcome.delivery_status = (
                        "partial_failed" if outcome.success else "failed"
                    )
                elif body.retryable:
                    # Different payload: split text/images only after transport
                    # retries have finished, never after uncertain delivery.
                    outcome = await fallback(tweet, kwargs)
                else:
                    outcome = SendOutcome(
                        success=False,
                        error=body.error,
                        delivery_status="failed",
                        delivery_error=body.error,
                    )
            else:
                outcome = SendOutcome(success=True, warning=body.warning)
                videos = renderer.build_direct_video_items([tweet])
                if media_only and not (image_items or videos):
                    outcome.success = False
                    outcome.delivery_status = "failed"
                for media, component in videos:
                    video = (
                        await send_video(media, component, "OneBot direct video")
                    ).attempt
                    if video.success or video.uncertain:
                        outcome.warning = outcome.warning or video.warning
                        continue
                    outcome.success = not media_only and (
                        not event_mode or video.retryable
                    )
                    outcome.error = outcome.delivery_error = video.error
                    outcome.delivery_status = "partial_failed"
                    if not media_only and outcome.success:
                        notice = renderer.build_video_omitted_notice_components([tweet])
                        if notice:
                            notice_attempt = await send_chain(
                                notice, "OneBot direct video omitted notice"
                            )
                            outcome.warning = outcome.warning or notice_attempt.warning
                            if event_mode:
                                outcome.success = (
                                    notice_attempt.success or notice_attempt.uncertain
                                )
                    break
            result.error = result.error or outcome.error
            result.warning = result.warning or outcome.warning
            result.delivery_error = result.delivery_error or outcome.delivery_error
            if outcome.delivery_status != "success":
                result.delivery_status = outcome.delivery_status
            if not outcome.success:
                result.error = outcome.error or result.error
                result.delivery_error = outcome.delivery_error or result.delivery_error
                if delivered_ids:
                    result.delivery_status = "partial_failed"
                    result.delivered_status_ids = tuple(dict.fromkeys(delivered_ids))
                result.success = False
                return result
            status_id = str(getattr(tweet, "status_id", "") or "")
            if status_id:
                delivered_ids.append(status_id)
        return result
