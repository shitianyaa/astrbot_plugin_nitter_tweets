from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .platforms import PlatformProfile


class DeliveryAdapter:
    name = "default"
    is_lark = False
    is_telegram = False

    def __init__(self, sender: Any, profile: "PlatformProfile"):
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
