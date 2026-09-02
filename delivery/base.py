from __future__ import annotations

from typing import TYPE_CHECKING, Any

try:
    from .media_transport import PATH_ONLY_LADDER
    from .sender_transport import AdapterTransportMixin
except ImportError:  # pragma: no cover - flat import fallback
    from delivery.media_transport import PATH_ONLY_LADDER
    from delivery.sender_transport import AdapterTransportMixin

if TYPE_CHECKING:
    from .platforms import PlatformProfile


class DeliveryAdapter(AdapterTransportMixin):
    name = "default"
    is_lark = False
    is_telegram = False

    def __init__(self, sender: Any, profile: PlatformProfile):
        self.sender = sender
        self.profile = profile

    @property
    def supports_merged_forward(self) -> bool:
        return False

    @property
    def should_split_direct_videos(self) -> bool:
        return bool(getattr(self.profile, "should_split_qq_direct_videos", False))

    @property
    def should_split_direct_images(self) -> bool:
        return bool(getattr(self.profile, "should_split_qq_direct_images", False))

    def media_transport_ladder(self, media, **kwargs) -> tuple[str, ...]:
        """Wire encodings to try for one media item, in order.

        Only adapters that hand a file path *across a process boundary* need more
        than one rung. Lark, Telegram, QQ Official and the default adapter upload
        from within the AstrBot process — Lark even resolves the component back to
        a local ``Path`` to read its bytes (``delivery/lark_support.py``), so a
        non-path encoding would break it.
        """
        return PATH_ONLY_LADDER

    async def send_event_media_segment(self, event, segment: dict, label: str):
        """Send one raw media segment to an event target.

        ``None`` means this adapter has no raw segment path, so the caller keeps
        using the normal component chain.
        """
        return None

    async def send_umo_media_segment(
        self, context, umo: str, segment: dict, label: str
    ):
        """Send one raw media segment to a UMO target. ``None`` = unsupported."""
        return None
