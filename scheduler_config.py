from __future__ import annotations

import re
from dataclasses import dataclass, field

from astrbot.api import logger

try:
    from .config_compat import config_get, migrate_default_group_config
    from .group_ids import (
        DEFAULT_GROUP_ALIASES,
        DEFAULT_GROUP_ID,
        DEFAULT_GROUP_NAME,
        GLOBAL_GROUP_ID,
        normalize_group_id,
    )
    from .utils import clamp_float, clamp_int, normalize_username
except ImportError:
    from config_compat import config_get, migrate_default_group_config
    from group_ids import (
        DEFAULT_GROUP_ALIASES,
        DEFAULT_GROUP_ID,
        DEFAULT_GROUP_NAME,
        GLOBAL_GROUP_ID,
        normalize_group_id,
    )
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
    deferred_publish_enabled: bool
    deferred_publish_times: list[tuple[int, int]]
    deferred_publish_batch_limit: int
    deferred_prefetch_media: bool
    deferred_media_retention_hours: float
    deferred_media_download_interval_seconds: float
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
        migrate_default_group_config(config, save=False)
        self.config = config
        self.context = context

    def global_group(self, log_invalid_targets: bool = True) -> ScheduleGroup:
        return ScheduleGroup(
            group_id=DEFAULT_GROUP_ID,
            name=DEFAULT_GROUP_NAME,
            enabled=False,
            check_on_startup=False,
            interval_check_enabled=True,
            check_interval_minutes=30,
            daily_check_enabled=False,
            daily_check_times=[],
            scheduled_fetch_limit=5,
            send_target_interval=1.5,
            send_user_interval=2.0,
            notify_no_updates=False,
            deferred_publish_enabled=False,
            deferred_publish_times=[],
            deferred_publish_batch_limit=50,
            deferred_prefetch_media=True,
            deferred_media_retention_hours=72.0,
            deferred_media_download_interval_seconds=0.5,
            users_info=self.parse_watch_users([]),
            target_info=self.parse_push_targets(
                [], log_invalid=log_invalid_targets, group_id=DEFAULT_GROUP_ID
            ),
            aliases=list(DEFAULT_GROUP_ALIASES),
        )

    def schedule_groups(self, log_invalid_targets: bool = True) -> list[ScheduleGroup]:
        groups: list[ScheduleGroup] = []
        seen_group_ids: set[str] = set()

        raw_groups = config_get(self.config, "tweet_groups", []) or []
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
        if not name:
            name = DEFAULT_GROUP_NAME if group_id == DEFAULT_GROUP_ID else group_id

        aliases = self.config_list(raw_group.get("aliases"))
        if group_id == DEFAULT_GROUP_ID:
            aliases = self.merge_unique_strings(aliases, DEFAULT_GROUP_ALIASES)

        daily_check_times = self.parse_daily_times(
            raw_group.get(
                "daily_check_times",
                self.default_group_legacy_config(group_id, "daily_check_times", []),
            )
        )
        daily_check_enabled = bool(daily_check_times)
        if "daily_check_enabled" in raw_group:
            daily_check_enabled = self.parse_bool(
                raw_group.get("daily_check_enabled"), False
            ) and bool(daily_check_times)
        elif group_id == DEFAULT_GROUP_ID:
            daily_check_enabled = self.parse_bool(
                config_get(self.config, "daily_check_enabled", daily_check_enabled),
                daily_check_enabled,
            ) and bool(daily_check_times)
        if not daily_check_enabled:
            daily_check_times = []

        interval_check_default = self.default_group_legacy_config(
            group_id, "interval_check_enabled", True
        )
        deferred_publish_default = self.default_group_legacy_config(
            group_id, "deferred_publish_enabled", False
        )

        return ScheduleGroup(
            group_id=group_id,
            name=name,
            enabled=self.parse_bool(raw_group.get("enabled", True), True),
            check_on_startup=self.parse_bool(
                config_get(self.config, "check_on_startup", False), False
            ),
            interval_check_enabled=self.parse_bool(
                raw_group.get("interval_check_enabled", interval_check_default), True
            ),
            check_interval_minutes=clamp_int(
                config_get(self.config, "check_interval_minutes", 30), 1, 1440
            ),
            daily_check_enabled=daily_check_enabled,
            daily_check_times=daily_check_times,
            scheduled_fetch_limit=clamp_int(
                config_get(self.config, "scheduled_fetch_limit", 5), 1, 20
            ),
            send_target_interval=clamp_float(
                config_get(self.config, "send_target_interval", 1.5), 0.0, 60.0
            ),
            send_user_interval=clamp_float(
                config_get(self.config, "send_user_interval", 2.0), 0.0, 60.0
            ),
            notify_no_updates=self.parse_bool(
                config_get(self.config, "notify_no_updates", False), False
            ),
            deferred_publish_enabled=self.parse_bool(
                raw_group.get("deferred_publish_enabled", deferred_publish_default),
                False,
            ),
            deferred_publish_times=self.parse_daily_times(
                config_get(self.config, "deferred_publish_times", [])
            ),
            deferred_publish_batch_limit=clamp_int(
                config_get(self.config, "deferred_publish_batch_limit", 50),
                1,
                500,
            ),
            deferred_prefetch_media=self.parse_bool(
                config_get(self.config, "deferred_prefetch_media", True),
                True,
            ),
            deferred_media_retention_hours=clamp_float(
                config_get(self.config, "deferred_media_retention_hours", 72.0),
                1.0,
                8760.0,
            ),
            deferred_media_download_interval_seconds=clamp_float(
                config_get(
                    self.config, "deferred_media_download_interval_seconds", 0.5
                ),
                0.0,
                60.0,
            ),
            users_info=self.parse_watch_users(raw_group.get("watch_users", [])),
            target_info=self.parse_push_targets(
                raw_group.get("push_targets", []),
                log_invalid=log_invalid_targets,
                group_id=group_id,
            ),
            aliases=aliases,
        )

    def default_group_legacy_config(self, group_id: str, key: str, default=None):
        if group_id != DEFAULT_GROUP_ID:
            return default
        return config_get(self.config, key, default)

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
        group = self.schedule_group(DEFAULT_GROUP_ID, log_invalid_targets=False)
        if group is None:
            return self.parse_watch_users([])
        return group.users_info

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
            raw_targets = config_get(self.config, "push_targets", []) or []
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
        configured = (config_get(self.config, "platform_id", "") or "").strip()
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
            raw_times = config_get(self.config, "daily_check_times", []) or []
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
    def merge_unique_strings(left: list[str], right: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for item in [*left, *right]:
            text = str(item or "").strip()
            if not text:
                continue
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            result.append(text)
        return result

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
