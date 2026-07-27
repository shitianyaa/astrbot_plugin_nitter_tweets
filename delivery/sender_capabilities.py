"""平台能力判定与 OneBot 合并转发调用。

`TweetSender` 的 mixin：只通过 `self` / `cls` 协作，不 import 宿主类。
平台判定统一走 `PlatformResolver`，不要按 UMO 首段自行推断。
"""

from __future__ import annotations

try:
    from .outcomes import SendAttempt
    from .platforms import PlatformResolver
except ImportError:
    from delivery import PlatformResolver, SendAttempt


class SenderCapabilitiesMixin:
    """平台识别、适配器选择和 OneBot 合并转发动作。"""

    def supports_merged_forward_for_umo(self, context, umo: str) -> bool:
        return self._delivery_adapter_for_umo(context, umo).supports_merged_forward

    def _delivery_adapter_for_umo(self, context, umo: str):
        profile = self.platform_resolver.from_umo(context, umo)
        return self.delivery_registry.adapter_for(self, profile)

    def _delivery_adapter_for_event(self, event):
        profile = self.platform_resolver.from_event(event)
        return self.delivery_registry.adapter_for(self, profile)

    @classmethod
    def _should_split_direct_videos_for_umo(cls, context, umo: str) -> bool:
        profile = PlatformResolver().from_umo(context, umo)
        return profile.should_split_qq_direct_videos

    @classmethod
    def _should_split_direct_videos_for_event(cls, event) -> bool:
        profile = PlatformResolver().from_event(event)
        return profile.should_split_qq_direct_videos

    @classmethod
    def _platform_inst_from_context(cls, context, platform_id: str):
        return PlatformResolver().platform_inst_from_context(context, platform_id)

    @classmethod
    def _event_platform(cls, event) -> str:
        profile = PlatformResolver().from_event(event)
        return profile.platform_id or (
            profile.platform_types[0] if profile.platform_types else ""
        )

    async def _send_onebot_forward(self, event, raw_nodes: list[dict]) -> bool:
        send_forward = getattr(
            self._delivery_adapter_for_event(event), "send_event_forward", None
        )
        if not callable(send_forward):
            return False
        return await send_forward(event, raw_nodes)

    async def _send_onebot_umo_forward(
        self,
        context,
        umo: str,
        raw_nodes: list[dict],
        label: str,
    ) -> SendAttempt:
        send_forward = getattr(
            self._delivery_adapter_for_umo(context, umo), "send_umo_forward", None
        )
        if not callable(send_forward):
            return SendAttempt(
                success=False,
                retryable=True,
                error="OneBot call_action unavailable for proactive merged forward",
            )
        return await send_forward(context, umo, raw_nodes, label)

    @classmethod
    def _onebot_call_action_for_umo(cls, context, umo: str):
        return PlatformResolver().from_umo(context, umo).call_action
