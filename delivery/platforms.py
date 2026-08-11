from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from astrbot.api import logger

from .base import DeliveryAdapter
from .default import DefaultDeliveryAdapter
from .lark import LarkDeliveryAdapter
from .onebot import OneBotDeliveryAdapter
from .qq_official import QQOfficialDeliveryAdapter
from .telegram import TelegramDeliveryAdapter

PRIVATE_QQ_PLATFORM_TYPES = {
    "aiocqhttp",
    "onebot",
    "onebot_v11",
    "napcat",
}

# AstrBot registers the WebSocket and webhook adapters under separate names, but
# ``QQOfficialWebhookMessageEvent`` subclasses ``QQOfficialMessageEvent`` without
# overriding delivery, so both share one adapter here.  Unrecognised webhook
# instances would fall back to the default adapter, which never sets
# ``use_markdown_`` and therefore lets AstrBot send unescaped bodies as native
# Markdown.
QQ_OFFICIAL_PLATFORM_TYPES = {
    "qq_official",
    "qq_official_webhook",
    "qqofficial",
    "qqofficial_webhook",
}

# Historical generic QQ instance IDs still need direct media splitting, but
# they are not sufficient evidence that the adapter is QQ Official.
LEGACY_QQ_MEDIA_PLATFORM_TYPES = {"qq"}

ONEBOT_PLATFORM_TYPES = PRIVATE_QQ_PLATFORM_TYPES
QQ_DIRECT_MEDIA_SPLIT_TYPES = (
    PRIVATE_QQ_PLATFORM_TYPES
    | QQ_OFFICIAL_PLATFORM_TYPES
    | LEGACY_QQ_MEDIA_PLATFORM_TYPES
)
# Keep the old internal name for third-party imports while using the precise name
# in this module and documentation.
QQ_DIRECT_VIDEO_SPLIT_TYPES = QQ_DIRECT_MEDIA_SPLIT_TYPES

NON_ONEBOT_PLATFORM_TYPES = {
    "discord",
    "discord_bot",
    "feishu",
    "lark",
    "slack",
    "telegram",
    "webchat",
    "wechat",
    "weixin",
    "weixin_oc",
} | QQ_OFFICIAL_PLATFORM_TYPES

LARK_PLATFORM_TYPES = {"lark", "feishu"}
TELEGRAM_PLATFORM_TYPES = {"telegram"}


def normalize_platform(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_")


def parse_umo(umo: str) -> tuple[str, str, str]:
    parts = str(umo or "").split(":", 2)
    if len(parts) != 3:
        return "", "", ""
    return parts[0].strip(), parts[1].strip(), parts[2].strip()


@dataclass(slots=True)
class PlatformProfile:
    platform_id: str = ""
    message_type: str = ""
    session_id: str = ""
    platform: Any = None
    platform_types: tuple[str, ...] = ()
    call_action: Any = None
    source: str = ""

    @property
    def normalized_types(self) -> set[str]:
        resolved_types = {
            normalized
            for value in self.platform_types
            if (normalized := normalize_platform(value))
        }
        if resolved_types:
            return resolved_types
        fallback = normalize_platform(self.platform_id)
        return {fallback} if fallback else set()

    @property
    def is_lark(self) -> bool:
        return bool(self.normalized_types & LARK_PLATFORM_TYPES)

    @property
    def is_telegram(self) -> bool:
        return bool(self.normalized_types & TELEGRAM_PLATFORM_TYPES)

    @property
    def is_known_non_onebot(self) -> bool:
        return bool(self.normalized_types & NON_ONEBOT_PLATFORM_TYPES)

    @property
    def is_qq_official(self) -> bool:
        return bool(self.normalized_types & QQ_OFFICIAL_PLATFORM_TYPES)

    @property
    def is_onebot(self) -> bool:
        # QQ Official has a separate API and must not be routed through raw
        # OneBot actions even if a wrapper happens to expose call_action.
        if self.is_qq_official:
            return False
        if self.normalized_types & ONEBOT_PLATFORM_TYPES:
            return True
        return callable(self.call_action) and not self.is_known_non_onebot

    @property
    def should_split_qq_direct_videos(self) -> bool:
        return self.is_onebot or bool(
            self.normalized_types & QQ_DIRECT_MEDIA_SPLIT_TYPES
        )

    @property
    def should_split_qq_direct_images(self) -> bool:
        return self.is_onebot or bool(
            self.normalized_types & QQ_DIRECT_MEDIA_SPLIT_TYPES
        )


class PlatformResolver:
    def from_umo(self, context: Any, umo: str) -> PlatformProfile:
        platform_id, message_type, session_id = parse_umo(umo)
        platform = self.platform_inst_from_context(context, platform_id)
        platform_types = self._platform_type_candidates(platform)
        call_action = self.call_action_from_platform(platform)
        return PlatformProfile(
            platform_id=platform_id,
            message_type=message_type,
            session_id=session_id,
            platform=platform,
            platform_types=platform_types,
            call_action=call_action,
            source="umo",
        )

    def from_event(self, event: Any) -> PlatformProfile:
        platform_id = self._event_platform_id(event)
        message_type = ""
        session_id = ""
        if not platform_id:
            platform_id, message_type, session_id = parse_umo(
                str(getattr(event, "unified_msg_origin", "") or "")
            )

        platform = getattr(event, "platform", None) or getattr(
            event, "platform_inst", None
        )
        platform_types = self._event_platform_type_candidates(event, platform)
        bot = getattr(event, "bot", None)
        call_action = self.call_action_from_platform(
            platform
        ) or self.call_action_from_platform(bot)
        return PlatformProfile(
            platform_id=platform_id,
            message_type=message_type,
            session_id=session_id,
            platform=platform,
            platform_types=platform_types,
            call_action=call_action,
            source="event",
        )

    def platform_inst_from_context(self, context: Any, platform_id: str):
        if not platform_id:
            return None

        get_platform_inst = getattr(context, "get_platform_inst", None)
        if callable(get_platform_inst):
            try:
                platform = get_platform_inst(platform_id)
                if platform is not None:
                    return platform
            except Exception:
                logger.debug(
                    "[NitterTweets] get_platform_inst failed for id=%s",
                    platform_id,
                )

        manager = getattr(context, "platform_manager", None)
        candidates = []
        get_insts = getattr(manager, "get_insts", None)
        if callable(get_insts):
            try:
                raw = get_insts()
                if isinstance(raw, (list, tuple)):
                    candidates.extend(raw)
            except Exception:
                logger.debug("[NitterTweets] platform_manager.get_insts failed")
        candidates.extend(getattr(manager, "platform_insts", []) or [])

        for candidate in candidates:
            meta = self.safe_platform_meta(candidate)
            candidate_ids = [
                getattr(meta, "id", None),
                getattr(candidate, "platform_id", None),
                getattr(candidate, "id", None),
                getattr(candidate, "platform", None),
            ]
            if any(str(value or "") == platform_id for value in candidate_ids):
                return candidate

        return None

    def call_action_from_platform(self, platform: Any):
        for candidate in self._client_candidates(platform):
            api = getattr(candidate, "api", None)
            call_action = getattr(api, "call_action", None)
            if callable(call_action):
                return call_action
            call_action = getattr(candidate, "call_action", None)
            if callable(call_action):
                return call_action
        return None

    @staticmethod
    def safe_platform_meta(platform: Any):
        meta = getattr(platform, "meta", None)
        if not callable(meta):
            return None
        try:
            return meta()
        except Exception:
            return None

    def _event_platform_id(self, event: Any) -> str:
        for method_name in ("get_platform_id", "get_platform_name"):
            method = getattr(event, method_name, None)
            if callable(method):
                try:
                    value = method()
                except Exception:
                    value = ""
                if value:
                    return str(value)

        meta = getattr(event, "platform_meta", None)
        for attr in ("id", "type", "name"):
            value = getattr(meta, attr, None)
            if value:
                return str(value)

        return ""

    def _event_platform_type_candidates(
        self, event: Any, platform: Any
    ) -> tuple[str, ...]:
        values = list(self._platform_type_candidates(platform))
        if values:
            return tuple(dict.fromkeys(values))

        method = getattr(event, "get_platform_name", None)
        if callable(method):
            try:
                self._append_candidate(values, method())
            except Exception:
                pass
        if values:
            return tuple(dict.fromkeys(values))

        meta = getattr(event, "platform_meta", None)
        for attr in ("type", "name"):
            self._append_candidate(values, getattr(meta, attr, None))
        if isinstance(meta, dict):
            for key in ("type", "name"):
                self._append_candidate(values, meta.get(key))
        if values:
            return tuple(dict.fromkeys(values))

        for attr in ("platform_type", "platform_name"):
            self._append_candidate(values, getattr(event, attr, None))

        return tuple(dict.fromkeys(values))

    def _platform_type_candidates(self, platform: Any) -> tuple[str, ...]:
        values: list[str] = []

        meta = self.safe_platform_meta(platform)
        for attr in ("type", "name"):
            self._append_candidate(values, getattr(meta, attr, None))
        if isinstance(meta, dict):
            for key in ("type", "name"):
                self._append_candidate(values, meta.get(key))
        if values:
            return tuple(dict.fromkeys(values))

        for attr in ("platform_type", "platform_name"):
            self._append_candidate(values, getattr(platform, attr, None))
        if values:
            return tuple(dict.fromkeys(values))

        config = getattr(platform, "config", None)
        if isinstance(config, dict):
            for key in ("type", "platform", "adapter"):
                self._append_candidate(values, config.get(key))

        return tuple(dict.fromkeys(values))

    @staticmethod
    def _append_candidate(values: list[str], value: Any) -> None:
        if isinstance(value, str) and value.strip():
            values.append(value.strip())

    @staticmethod
    def _client_candidates(platform: Any) -> tuple[Any, ...]:
        if platform is None:
            return ()
        return (
            getattr(platform, "bot", None),
            getattr(platform, "client", None),
            getattr(platform, "adapter", None),
            platform,
        )


class PlatformDeliveryRegistry:
    def adapter_for(self, sender: Any, profile: PlatformProfile) -> DeliveryAdapter:
        if profile.is_lark:
            return LarkDeliveryAdapter(sender, profile)
        if profile.is_telegram:
            return TelegramDeliveryAdapter(sender, profile)
        if profile.is_qq_official:
            return QQOfficialDeliveryAdapter(sender, profile)
        if profile.is_onebot:
            return OneBotDeliveryAdapter(sender, profile)
        return DefaultDeliveryAdapter(sender, profile)
