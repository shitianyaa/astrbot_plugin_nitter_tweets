from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .base import DeliveryAdapter
from .default import DefaultDeliveryAdapter
from .lark import LarkDeliveryAdapter
from .onebot import OneBotDeliveryAdapter
from .telegram import TelegramDeliveryAdapter


ONEBOT_PLATFORM_TYPES = {
    "aiocqhttp",
    "onebot",
    "onebot_v11",
    "napcat",
}

QQ_DIRECT_VIDEO_SPLIT_TYPES = ONEBOT_PLATFORM_TYPES | {
    "qq",
    "qq_official",
    "qqofficial",
}

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
}

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
        return {
            normalized
            for value in (self.platform_id, *self.platform_types)
            if (normalized := normalize_platform(value))
        }

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
    def is_onebot(self) -> bool:
        if self.normalized_types & ONEBOT_PLATFORM_TYPES:
            return True
        return callable(self.call_action) and not self.is_known_non_onebot

    @property
    def should_split_qq_direct_videos(self) -> bool:
        return self.is_onebot or bool(self.normalized_types & QQ_DIRECT_VIDEO_SPLIT_TYPES)


class PlatformResolver:
    def from_umo(self, context: Any, umo: str) -> PlatformProfile:
        platform_id, message_type, session_id = parse_umo(umo)
        platform = self.platform_inst_from_context(context, platform_id)
        platform_types = self._platform_type_candidates(platform, platform_id)
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

        platform = getattr(event, "platform", None) or getattr(event, "platform_inst", None)
        platform_types = self._platform_type_candidates(platform, platform_id)
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
                pass

        manager = getattr(context, "platform_manager", None)
        candidates = []
        get_insts = getattr(manager, "get_insts", None)
        if callable(get_insts):
            try:
                raw = get_insts()
                if isinstance(raw, (list, tuple)):
                    candidates.extend(raw)
            except Exception:
                pass
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

    def _platform_type_candidates(
        self, platform: Any, platform_id: str = ""
    ) -> tuple[str, ...]:
        values: list[str] = []
        self._append_candidate(values, platform_id)

        meta = self.safe_platform_meta(platform)
        for attr in ("type", "name", "id"):
            self._append_candidate(values, getattr(meta, attr, None))
        if isinstance(meta, dict):
            for key in ("type", "name", "id"):
                self._append_candidate(values, meta.get(key))

        for attr in ("platform_type", "platform_name", "platform", "id", "name"):
            self._append_candidate(values, getattr(platform, attr, None))

        config = getattr(platform, "config", None)
        if isinstance(config, dict):
            for key in ("type", "name", "platform", "adapter"):
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
        if profile.is_onebot:
            return OneBotDeliveryAdapter(sender, profile)
        return DefaultDeliveryAdapter(sender, profile)
