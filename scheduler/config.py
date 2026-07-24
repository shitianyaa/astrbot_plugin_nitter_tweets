from __future__ import annotations

import re
from dataclasses import dataclass, field

from astrbot.api import logger

try:
    from ..config import config_get, migrate_default_group_config
    from ..shared.group_ids import (
        DEFAULT_GROUP_ALIASES,
        DEFAULT_GROUP_ID,
        DEFAULT_GROUP_NAME,
        GLOBAL_GROUP_ID,
        infer_legacy_group_id_from_name,
        is_default_group,
        normalize_group_id,
        normalize_stable_group_id,
    )
    from ..shared import clamp_float, clamp_int, load_instances, normalize_username
except ImportError:
    from config import config_get, migrate_default_group_config
    from shared.group_ids import (
        DEFAULT_GROUP_ALIASES,
        DEFAULT_GROUP_ID,
        DEFAULT_GROUP_NAME,
        GLOBAL_GROUP_ID,
        infer_legacy_group_id_from_name,
        is_default_group,
        normalize_group_id,
        normalize_stable_group_id,
    )
    from shared import clamp_float, clamp_int, load_instances, normalize_username


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
class WatchQueryItem:
    query: str
    type: str  # tag | phrase
    account_key: str  # q:<casefold query> for seen isolation


@dataclass(slots=True)
class WatchQueriesInfo:
    raw_count: int
    queries: list[WatchQueryItem] = field(default_factory=list)
    duplicates: list[str] = field(default_factory=list)
    invalid_entries: list[str] = field(default_factory=list)
    changed: bool = False


GROUP_TYPE_BLOGGER = "blogger"
GROUP_TYPE_TAG = "tag"


@dataclass(slots=True)
class ScheduleGroup:
    group_id: str
    name: str
    enabled: bool
    group_type: str
    check_on_startup: bool
    interval_check_enabled: bool
    check_interval_minutes: int
    daily_check_enabled: bool
    daily_check_times: list[tuple[int, int]]
    scheduled_fetch_limit: int
    send_target_interval: float
    send_user_interval: float
    notify_no_updates: bool
    concurrent_fetch_enabled: bool
    fetch_concurrency: int
    concurrent_fetch_instances: list[str]
    concurrent_prepare_enabled: bool
    prepare_concurrency: int
    filter_plain_text_enabled: bool
    media_only_enabled: bool
    omit_status_url: bool
    hide_original_when_translated: bool
    users_info: WatchUsersInfo
    queries_info: WatchQueriesInfo
    target_info: PushTargetParseResult
    aliases: list[str] = field(default_factory=list)

    @property
    def is_tag_group(self) -> bool:
        return self.group_type == GROUP_TYPE_TAG

    @property
    def is_blogger_group(self) -> bool:
        return not self.is_tag_group

    @property
    def users(self) -> list[str]:
        return self.users_info.users

    @property
    def queries(self) -> list[WatchQueryItem]:
        return self.queries_info.queries

    @property
    def account_keys(self) -> list[str]:
        """Seen/account iteration keys for this group."""
        if self.is_tag_group:
            return [item.account_key for item in self.queries]
        return list(self.users)

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
            group_type=GROUP_TYPE_BLOGGER,
            check_on_startup=False,
            interval_check_enabled=True,
            check_interval_minutes=30,
            daily_check_enabled=False,
            daily_check_times=[],
            scheduled_fetch_limit=20,
            send_target_interval=1.5,
            send_user_interval=2.0,
            notify_no_updates=False,
            concurrent_fetch_enabled=False,
            fetch_concurrency=3,
            concurrent_fetch_instances=[],
            concurrent_prepare_enabled=False,
            prepare_concurrency=2,
            filter_plain_text_enabled=False,
            media_only_enabled=False,
            omit_status_url=True,
            hide_original_when_translated=False,
            users_info=self.parse_watch_users([]),
            queries_info=self.parse_watch_queries([]),
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
                "[NitterTweets] tweet_groups 必须是列表: "
                f"type={type(raw_groups).__name__}"
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
                    "[NitterTweets] 已忽略重复推文分组: "
                    f"{group.name} ({group.group_id})"
                )
                continue

            seen_group_ids.add(normalized_group_id)
            groups.append(group)

        if any(
            group.is_tag_group and group.queries_info.changed for group in groups
        ):
            self._heal_watch_queries_config(groups)
        return groups

    def _heal_watch_queries_config(self, groups: list[ScheduleGroup]) -> None:
        """Persist normalized watch_queries when type/query was auto-fixed."""
        try:
            from ..config.compat import config_set
        except ImportError:  # pragma: no cover
            from config.compat import config_set

        raw_groups = config_get(self.config, "tweet_groups", []) or []
        if not isinstance(raw_groups, list):
            return

        by_id = {
            g.group_id: g for g in groups if g.is_tag_group and g.queries_info.changed
        }
        if not by_id:
            return

        try:
            from ..shared.group_ids import normalize_stable_group_id
        except ImportError:  # pragma: no cover
            from shared.group_ids import normalize_stable_group_id

        changed_any = False
        for raw in raw_groups:
            if not isinstance(raw, dict):
                continue
            raw_gid = str(raw.get("group_id") or "").strip()
            # Match parse_schedule_group: stable id keeps explicit global, etc.
            gid = normalize_stable_group_id(raw_gid) if raw_gid else ""
            if not gid:
                name = str(raw.get("name") or "").strip()
                gid = normalize_stable_group_id(name) if name else ""
            group = by_id.get(gid)
            if group is None:
                continue
            # Persist plain strings so AstrBot WebUI list fields do not show
            # "[object Object]" (list items are string-only in the schema UI).
            # Type remains recoverable: leading # => tag, else phrase.
            healed = [item.query for item in group.queries_info.queries]
            if raw.get("watch_queries") != healed:
                raw["watch_queries"] = healed
                changed_any = True

        if not changed_any:
            return
        config_set(self.config, "tweet_groups", raw_groups)
        save_config = getattr(self.config, "save_config", None)
        if callable(save_config):
            try:
                save_config()
                logger.info(
                    "[NitterTweets] 已回写规范化后的标签订阅 watch_queries"
                )
            except Exception as exc:  # pragma: no cover
                logger.warning(
                    f"[NitterTweets] 回写 watch_queries 失败: {exc}"
                )

    def parse_schedule_group(
        self,
        raw_group,
        index: int,
        log_invalid_targets: bool = True,
    ) -> ScheduleGroup | None:
        if not isinstance(raw_group, dict):
            logger.warning(f"[NitterTweets] 已忽略无效 tweet_groups 项: {raw_group!r}")
            return None

        name = str(raw_group.get("name") or "").strip()
        raw_group_id = str(raw_group.get("group_id") or "").strip()
        group_id = (
            normalize_stable_group_id(raw_group_id)
            if raw_group_id
            else (
                infer_legacy_group_id_from_name(name)
                or normalize_stable_group_id(f"group_{index}")
            )
        )
        if not name:
            name = DEFAULT_GROUP_NAME if is_default_group(group_id) else group_id

        aliases = self.config_list(raw_group.get("aliases"))
        if is_default_group(group_id):
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
        elif is_default_group(group_id):
            daily_check_enabled = self.parse_bool(
                config_get(self.config, "daily_check_enabled", daily_check_enabled),
                daily_check_enabled,
            ) and bool(daily_check_times)
        if not daily_check_enabled:
            daily_check_times = []

        interval_check_default = self.default_group_legacy_config(
            group_id, "interval_check_enabled", True
        )
        filter_plain_text_default = self.default_group_legacy_config(
            group_id, "filter_plain_text_enabled", False
        )

        group_type = self.parse_group_type(raw_group.get("group_type"))
        users_info = self.parse_watch_users(raw_group.get("watch_users", []))
        queries_info = self.parse_watch_queries(raw_group.get("watch_queries", []))
        # Tag groups only follow queries; blogger groups only follow users.
        if group_type == GROUP_TYPE_TAG:
            users_info = WatchUsersInfo(raw_count=0)
        else:
            queries_info = WatchQueriesInfo(raw_count=0)

        return ScheduleGroup(
            group_id=group_id,
            name=name,
            enabled=self.parse_bool(raw_group.get("enabled", True), True),
            group_type=group_type,
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
            scheduled_fetch_limit=20,
            send_target_interval=clamp_float(
                config_get(self.config, "send_target_interval", 1.5), 0.0, 60.0
            ),
            send_user_interval=clamp_float(
                config_get(self.config, "send_user_interval", 2.0), 0.0, 60.0
            ),
            notify_no_updates=self.parse_bool(
                config_get(self.config, "notify_no_updates", False), False
            ),
            concurrent_fetch_enabled=self.parse_bool(
                config_get(self.config, "concurrent_fetch_enabled", False),
                False,
            ),
            fetch_concurrency=clamp_int(
                config_get(self.config, "fetch_concurrency", 3), 1, 8
            ),
            concurrent_fetch_instances=self.parse_instances(
                config_get(self.config, "concurrent_fetch_instances", [])
            ),
            concurrent_prepare_enabled=self.parse_bool(
                config_get(self.config, "concurrent_prepare_enabled", False),
                False,
            ),
            prepare_concurrency=clamp_int(
                config_get(self.config, "prepare_concurrency", 2), 1, 8
            ),
            filter_plain_text_enabled=self.parse_bool(
                raw_group.get("filter_plain_text_enabled", filter_plain_text_default),
                False,
            ),
            media_only_enabled=self.parse_bool(
                raw_group.get("media_only_enabled", False),
                False,
            ),
            omit_status_url=self.parse_bool(
                raw_group.get("omit_status_url", True),
                True,
            ),
            hide_original_when_translated=self.parse_bool(
                raw_group.get("hide_original_when_translated", False),
                False,
            ),
            users_info=users_info,
            queries_info=queries_info,
            target_info=self.parse_push_targets(
                raw_group.get("push_targets", []),
                log_invalid=log_invalid_targets,
                group_id=group_id,
            ),
            aliases=aliases,
        )

    def default_group_legacy_config(self, group_id: str, key: str, default=None):
        if not is_default_group(group_id):
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

    @staticmethod
    def parse_group_type(raw_type) -> str:
        text = str(raw_type or "").strip().lower()
        if text in {GROUP_TYPE_TAG, "search", "query", "keyword"}:
            return GROUP_TYPE_TAG
        return GROUP_TYPE_BLOGGER

    def parse_watch_queries(self, raw_queries) -> WatchQueriesInfo:
        try:
            from ..media_support.html_backend import (
                normalize_watch_query,
                seen_account_key_for_query,
            )
        except ImportError:  # pragma: no cover
            from media_support.html_backend import (
                normalize_watch_query,
                seen_account_key_for_query,
            )

        if isinstance(raw_queries, str):
            raw_queries = re.split(r"[\n]+", raw_queries)
        elif not isinstance(raw_queries, list):
            raw_queries = [raw_queries] if raw_queries else []

        raw_count = 0
        queries: list[WatchQueryItem] = []
        seen_keys: set[str] = set()
        duplicates: list[str] = []
        invalid_entries: list[str] = []
        changed = False

        for raw in raw_queries:
            if raw is None:
                continue
            if isinstance(raw, dict):
                query_raw = str(raw.get("query") or raw.get("q") or "").strip()
                type_hint = str(raw.get("type") or raw.get("kind") or "").strip()
                display = query_raw or "(object)"
                # Object form is accepted for runtime, but disk prefers strings.
                changed = True
            else:
                query_raw = str(raw).strip()
                type_hint = ""
                display = query_raw
            if not query_raw and not display:
                continue
            raw_count += 1
            # AstrBot list UI stringifies dicts as this literal; drop & re-enter.
            if query_raw.casefold() in {"[object object]", "object object"}:
                invalid_entries.append("[object Object]（请重新填写 #标签 或短语）")
                changed = True
                continue
            if not query_raw:
                invalid_entries.append(display)
                changed = True
                continue
            query, kind = normalize_watch_query(query_raw, type_hint or None)
            if not query:
                invalid_entries.append(display)
                continue
            # Prefer plain-string persistence for schema UI compatibility.
            if not isinstance(raw, str) or raw.strip() != query:
                changed = True
            account_key = seen_account_key_for_query(query)
            if account_key in seen_keys:
                duplicates.append(display)
                continue
            seen_keys.add(account_key)
            queries.append(
                WatchQueryItem(query=query, type=kind, account_key=account_key)
            )

        return WatchQueriesInfo(
            raw_count=raw_count,
            queries=queries,
            duplicates=duplicates,
            invalid_entries=invalid_entries,
            changed=changed,
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
                        "[NitterTweets] 无效推送目标: "
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
                        f"[NitterTweets] 无效推送目标: group={group_id}, target={raw!r}"
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
            logger.debug(f"[NitterTweets] 平台自动检测失败: {exc}")

        try:
            manager = getattr(self.context, "platform_manager", None)
            platform_id = self.first_platform_id(
                getattr(manager, "platform_insts", []) or []
            )
            if platform_id:
                return platform_id
        except Exception as exc:
            logger.debug(f"[NitterTweets] 平台管理器查找失败: {exc}")

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
                logger.warning(f"[NitterTweets] 无效每日检查时间: {raw!r}")
                continue
            if 0 <= hour < 24 and 0 <= minute < 60:
                times.append((hour, minute))
            else:
                logger.warning(f"[NitterTweets] 每日检查时间超出范围: {raw!r}")
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

    @classmethod
    def parse_instances(cls, value) -> list[str]:
        items = cls.config_list(value)
        return load_instances(items) if items else []

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
            if normalized in {
                "1",
                "true",
                "yes",
                "on",
                "enable",
                "enabled",
                "是",
                "开",
                "开启",
            }:
                return True
            if normalized in {
                "0",
                "false",
                "no",
                "off",
                "disable",
                "disabled",
                "否",
                "关",
                "关闭",
            }:
                return False
            return default
        return bool(value)
