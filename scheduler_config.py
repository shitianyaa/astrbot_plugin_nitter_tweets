from __future__ import annotations

import re
from dataclasses import dataclass, field

from astrbot.api import logger

try:
    from .seen_store import GLOBAL_GROUP_ID, normalize_group_id
    from .utils import clamp_float, clamp_int, normalize_username
except ImportError:
    from seen_store import GLOBAL_GROUP_ID, normalize_group_id
    from utils import clamp_float, clamp_int, normalize_username


@dataclass(slots=True)
class PushTargetParseResult:
    targets: list[str] = field(default_factory=list)
    invalid_targets: list[str] = field(default_factory=list)


@dataclass(slots=True)
class WatchUsersInfo:
    raw_count: int
    users: list[str] = field(default_factory=list)
    duplicates: list[str] = field(default_factory=list)
    invalid_entries: list[str] = field(default_factory=list)
    changed: bool = False
    saved: bool = False
    save_error: str = ""


@dataclass(slots=True)
class ScheduleGroup:
    group_id: str
    name: str
    enabled: bool
    check_on_startup: bool
    interval_check_enabled: bool
    check_interval_minutes: int
    daily_check_enabled: bool
    daily_check_times: list[tuple[int, int]]
    scheduled_fetch_limit: int
    send_target_interval: float
    send_user_interval: float
    notify_no_updates: bool
    users_info: WatchUsersInfo
    target_info: PushTargetParseResult
    aliases: list[str] = field(default_factory=list)

    @property
    def users(self) -> list[str]:
        return self.users_info.users

    @property
    def targets(self) -> list[str]:
        return self.target_info.targets

    @property
    def invalid_targets(self) -> list[str]:
        return self.target_info.invalid_targets


class SchedulerConfigReader:
    def __init__(self, config, context):
        self.config = config
        self.context = context

    def global_group(self, log_invalid_targets: bool = True) -> ScheduleGroup:
        return ScheduleGroup(
            group_id=GLOBAL_GROUP_ID,
            name="全局分组",
            enabled=bool(self.config.get("schedule_enabled", False)),
            check_on_startup=bool(self.config.get("check_on_startup", False)),
            interval_check_enabled=bool(
                self.config.get("interval_check_enabled", True)
            ),
            check_interval_minutes=clamp_int(
                self.config.get("check_interval_minutes", 30), 1, 1440
            ),
            daily_check_enabled=bool(self.config.get("daily_check_enabled", False)),
            daily_check_times=self.parse_daily_times(),
            scheduled_fetch_limit=clamp_int(
                self.config.get("scheduled_fetch_limit", 5), 1, 20
            ),
            send_target_interval=clamp_float(
                self.config.get("send_target_interval", 1.5), 0.0, 60.0
            ),
            send_user_interval=clamp_float(
                self.config.get("send_user_interval", 2.0), 0.0, 60.0
            ),
            notify_no_updates=bool(self.config.get("notify_no_updates", False)),
            users_info=self.watch_users_info(),
            target_info=self.parse_push_targets(log_invalid=log_invalid_targets),
            aliases=["全局", "默认", "default"],
        )

    def schedule_groups(self, log_invalid_targets: bool = True) -> list[ScheduleGroup]:
        return [self.global_group(log_invalid_targets=log_invalid_targets)]

    def schedule_group(
        self, group_name: str = "", log_invalid_targets: bool = True
    ) -> ScheduleGroup | None:
        normalized = normalize_group_id(group_name)
        for group in self.schedule_groups(log_invalid_targets=log_invalid_targets):
            identifiers = {
                normalize_group_id(group.group_id),
                normalize_group_id(group.name),
                *(normalize_group_id(alias) for alias in group.aliases),
            }
            if normalized in identifiers:
                return group
        return None

    def watch_users(self) -> list[str]:
        return self.watch_users_info().users

    def watch_users_info(self) -> WatchUsersInfo:
        raw_users = self.config.get("watch_users", []) or []
        if isinstance(raw_users, str):
            raw_users = re.split(r"[\n,，]+", raw_users)
        elif not isinstance(raw_users, list):
            raw_users = [raw_users]

        raw_entries = [str(raw).strip() for raw in raw_users if str(raw).strip()]
        users: list[str] = []
        seen: set[str] = set()
        duplicates: list[str] = []
        invalid_entries: list[str] = []
        for raw in raw_entries:
            username = normalize_username(raw)
            if not username:
                invalid_entries.append(raw)
                continue
            username_key = username.lower()
            if username_key in seen:
                duplicates.append(raw)
                continue
            seen.add(username_key)
            users.append(username)

        return WatchUsersInfo(
            raw_count=len(raw_entries),
            users=users,
            duplicates=duplicates,
            invalid_entries=invalid_entries,
            changed=raw_entries != users,
        )

    def push_targets(self) -> list[str]:
        return self.parse_push_targets().targets

    def parse_push_targets(self, log_invalid: bool = True) -> PushTargetParseResult:
        default_platform = self.platform()
        raw_targets = self.config.get("push_targets", []) or []
        result = PushTargetParseResult()
        seen: set[str] = set()
        for raw in raw_targets:
            if not isinstance(raw, str):
                invalid = repr(raw)
                result.invalid_targets.append(invalid)
                if log_invalid:
                    logger.warning(f"[NitterTweets] invalid push target: {invalid}")
                continue

            target = raw.strip().replace("：", ":")
            if not target:
                continue
            umo = self.parse_target_to_umo(target, default_platform)
            if umo is None:
                result.invalid_targets.append(raw)
                if log_invalid:
                    logger.warning(f"[NitterTweets] invalid push target: {raw!r}")
                continue
            if umo not in seen:
                seen.add(umo)
                result.targets.append(umo)
        return result

    def platform(self) -> str:
        configured = (self.config.get("platform_id", "") or "").strip()
        if configured:
            return configured

        platform_id = self.detect_context_platform_id()
        if platform_id:
            return platform_id

        return "aiocqhttp"

    def detect_context_platform_id(self) -> str:
        try:
            get_all_platforms = getattr(self.context, "get_all_platforms", None)
            if callable(get_all_platforms):
                platform_id = self.first_platform_id(get_all_platforms())
                if platform_id:
                    return platform_id
        except Exception as exc:
            logger.debug(f"[NitterTweets] platform auto-detect failed: {exc}")

        try:
            manager = getattr(self.context, "platform_manager", None)
            platform_id = self.first_platform_id(
                getattr(manager, "platform_insts", []) or []
            )
            if platform_id:
                return platform_id
        except Exception as exc:
            logger.debug(f"[NitterTweets] platform manager lookup failed: {exc}")

        return ""

    @classmethod
    def first_platform_id(cls, platforms) -> str:
        if not platforms:
            return ""

        if isinstance(platforms, dict):
            for key in platforms:
                platform_id = str(key).strip()
                if platform_id and platform_id != "webchat":
                    return platform_id
            return ""

        for platform in platforms:
            platform_id = cls.platform_id(platform)
            if platform_id and platform_id != "webchat":
                return platform_id
        return ""

    @staticmethod
    def platform_id(platform) -> str:
        for attr in ("platform_id", "platform_name", "id", "name"):
            value = getattr(platform, attr, None)
            if isinstance(value, str) and value.strip():
                return value.strip()

        meta = getattr(platform, "meta", None)
        if callable(meta):
            try:
                metadata = meta()
            except Exception:
                metadata = None
            for attr in ("id", "name"):
                value = getattr(metadata, attr, None)
                if isinstance(value, str) and value.strip():
                    return value.strip()

        config = getattr(platform, "config", None)
        if isinstance(config, dict):
            value = config.get("id") or config.get("type")
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    @staticmethod
    def parse_target_to_umo(target: str, default_platform: str) -> str | None:
        if ":GroupMessage:" in target or ":FriendMessage:" in target:
            return target

        parts = target.split(":")
        if len(parts) == 2:
            kind, ident = parts[0].strip().lower(), parts[1].strip()
            if not ident:
                return None
            if kind == "group":
                return f"{default_platform}:GroupMessage:{ident}"
            if kind == "private":
                return f"{default_platform}:FriendMessage:{ident}"
            return None

        if len(parts) == 3:
            platform, kind, ident = (
                parts[0].strip(),
                parts[1].strip().lower(),
                parts[2].strip(),
            )
            if not platform or not ident:
                return None
            if kind == "group":
                return f"{platform}:GroupMessage:{ident}"
            if kind == "private":
                return f"{platform}:FriendMessage:{ident}"
            return None

        if len(parts) == 1 and target.isdigit():
            return f"{default_platform}:GroupMessage:{target}"
        return None

    def parse_daily_times(self) -> list[tuple[int, int]]:
        raw_times = self.config.get("daily_check_times", []) or []
        if isinstance(raw_times, str):
            raw_times = re.split(r"[\n,，]+", raw_times)

        times: list[tuple[int, int]] = []
        for raw in raw_times:
            value = str(raw).strip().replace("：", ":")
            if not value:
                continue
            try:
                hour_s, minute_s = value.split(":", 1)
                hour, minute = int(hour_s), int(minute_s)
            except (TypeError, ValueError):
                logger.warning(f"[NitterTweets] invalid daily_check_times entry: {raw!r}")
                continue
            if 0 <= hour < 24 and 0 <= minute < 60:
                times.append((hour, minute))
            else:
                logger.warning(f"[NitterTweets] daily_check_times out of range: {raw!r}")
        return times
