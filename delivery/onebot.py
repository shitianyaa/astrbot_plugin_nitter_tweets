from __future__ import annotations

from astrbot.api import logger

from .default import DefaultDeliveryAdapter
from .outcomes import SendAttempt

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

    async def send_event_media_segment(self, event, segment: dict, label: str):
        """Send one media segment through a raw OneBot action.

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
        self, context, umo: str, segment: dict, label: str
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
        segment: dict,
        label: str,
        target: str,
    ) -> SendAttempt:
        try:
            await call_action(action, **payload, message=[segment])
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
