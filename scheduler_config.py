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
        groups = [self.global_group(log_invalid_targets=log_invalid_targets)]
        seen_group_ids = {normalize_group_id(GLOBAL_GROUP_ID)}

        raw_groups = self.config.get("tweet_groups", []) or []
        if isinstance(raw_groups, dict):
            raw_groups = [raw_groups]
        elif not isinstance(raw_groups, list):
            logger.warning(
                "[NitterTweets] tweet_groups must be a list, "
                f"got {type(raw_groups).__name__}"
            )
            return groups

        for index, raw_group in enumerate(raw_groups, 1):
            group = self.parse_schedule_group(
                raw_group,
                index,
                log_invalid_targets=log_invalid_targets,
            )
            if group is None:
                continue

            normalized_group_id = normalize_group_id(group.group_id)
            if normalized_group_id in seen_group_ids:
                logger.warning(
                    "[NitterTweets] duplicate tweet group ignored: "
                    f"{group.name} ({group.group_id})"
                )
                continue

            seen_group_ids.add(normalized_group_id)
            groups.append(group)
        return groups

    def parse_schedule_group(
        self,
        raw_group,
        index: int,
        log_invalid_targets: bool = True,
    ) -> ScheduleGroup | None:
        if not isinstance(raw_group, dict):
            logger.warning(
                "[NitterTweets] invalid tweet_groups item ignored: "
                f"{raw_group!r}"
            )
            return None

        name = str(raw_group.get("name") or "").strip()
        raw_group_id = str(raw_group.get("group_id") or "").strip()
        group_id = normalize_group_id(raw_group_id or name or f"group_{index}")
        if group_id == GLOBAL_GROUP_ID:
            logger.warning(
                "[NitterTweets] tweet group id 'global' is reserved; "
                f"ignored group {name or index!r}"
            )
            return None
        if not name:
            name = group_id

        return ScheduleGroup(
            group_id=group_id,
            name=name,
            enabled=self.parse_bool(raw_group.get("enabled", True), True),
            check_on_startup=self.parse_bool(
                raw_group.get("check_on_startup", False), False
            ),
            interval_check_enabled=self.parse_bool(
                raw_group.get("interval_check_enabled", True), True
            ),
            check_interval_minutes=clamp_int(
                raw_group.get("check_interval_minutes", 30), 1, 1440
            ),
            daily_check_enabled=self.parse_bool(
                raw_group.get("daily_check_enabled", False), False
            ),
            daily_check_times=self.parse_daily_times(
                raw_group.get("daily_check_times", [])
            ),
            scheduled_fetch_limit=clamp_int(
                raw_group.get("scheduled_fetch_limit", 5), 1, 20
            ),
            send_target_interval=clamp_float(
                raw_group.get("send_target_interval", 1.5), 0.0, 60.0
            ),
            send_user_interval=clamp_float(
                raw_group.get("send_user_interval", 2.0), 0.0, 60.0
            ),
            notify_no_updates=self.parse_bool(
                raw_group.get("notify_no_updates", False), False
            ),
            users_info=self.parse_watch_users(raw_group.get("watch_users", [])),
            target_info=self.parse_push_targets(
                raw_group.get("push_targets", []),
                log_invalid=log_invalid_targets,
                group_id=group_id,
            ),
            aliases=self.config_list(raw_group.get("aliases")),
        )

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
        return self.parse_watch_users(self.config.get("watch_users", []))

    def parse_watch_users(self, raw_users) -> WatchUsersInfo:
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

    def parse_push_targets(
        self,
        raw_targets=None,
        log_invalid: bool = True,
        group_id: str = GLOBAL_GROUP_ID,
    ) -> PushTargetParseResult:
        default_platform = self.platform()
        if raw_targets is None:
            raw_targets = self.config.get("push_targets", []) or []
        if isinstance(raw_targets, str):
            raw_targets = re.split(r"[\n,，]+", raw_targets)
        elif not isinstance(raw_targets, list):
            raw_targets = [raw_targets]
        result = PushTargetParseResult()
        seen: set[str] = set()
        for raw in raw_targets:
            if not isinstance(raw, str):
                invalid = repr(raw)
                result.invalid_targets.append(invalid)
                if log_invalid:
                    logger.warning(
                        "[NitterTweets] invalid push target: "
                        f"group={group_id}, target={invalid}"
                    )
                continue

            target = raw.strip().replace("：", ":")
            if not target:
                continue
            umo = self.parse_target_to_umo(target, default_platform)
            if umo is None:
                result.invalid_targets.append(raw)
                if log_invalid:
                    logger.warning(
                        "[NitterTweets] invalid push target: "
                        f"group={group_id}, target={raw!r}"
                    )
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

    def parse_daily_times(self, raw_times=None) -> list[tuple[int, int]]:
        if raw_times is None:
            raw_times = self.config.get("daily_check_times", []) or []
        if isinstance(raw_times, str):
            raw_times = re.split(r"[\n,，]+", raw_times)
        elif not isinstance(raw_times, list):
            raw_times = [raw_times]

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

    @staticmethod
    def config_list(value) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            raw_items = re.split(r"[\n,，]+", value)
        elif isinstance(value, list):
            raw_items = value
        else:
            raw_items = [value]
        return [str(item).strip() for item in raw_items if str(item).strip()]

    @staticmethod
    def parse_bool(value, default: bool = False) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on", "enable", "enabled", "是", "开", "开启"}:
                return True
            if normalized in {"0", "false", "no", "off", "disable", "disabled", "否", "关", "关闭"}:
                return False
            return default
        return bool(value)
