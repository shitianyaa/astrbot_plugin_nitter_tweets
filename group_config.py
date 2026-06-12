from __future__ import annotations

import re
from dataclasses import dataclass, field

from astrbot.api import logger

try:
    from .utils import clamp_float, clamp_int, normalize_username
except ImportError:
    from utils import clamp_float, clamp_int, normalize_username

DEFAULT_GROUP_ID = "default"
_GROUPS_KEY = "groups"
_MIGRATION_MARKER = "_migrated_to_groups_v2"


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
class GroupConfig:
    group_id: str
    name: str
    aliases: list[str] = field(default_factory=list)
    enabled: bool = True

    # ── basic ──
    instances: list[str] = field(default_factory=lambda: ["https://nitter.net"])
    default_limit: int = 5
    request_timeout: float = 12.0
    cooldown_seconds: float = 15.0
    user_agent: str = "Mozilla/5.0 (compatible; AstrBotNitterTweets/0.4)"

    # ── nitter / rss ──
    deduplicate_retweets: bool = False

    # ── media ──
    send_image_attachments: bool = True
    send_video_attachments: bool = False
    max_media_per_tweet: int = 4
    media_timeout: float = 25.0
    media_max_size_mb: float = 25.0
    media_cache_retention_days: float = 3.0
    xdown_api_url: str = "https://xdown.app/api/ajaxSearch"
    media_user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
    preferred_video_resolution: str = "highest"

    # ── ai translation ──
    translate_enabled: bool = False
    translation_provider_id: str = ""
    translate_min_chars: int = 8
    translate_max_chars: int = 2000
    translate_chinese_ratio_threshold: float = 0.2
    translate_prompt: str = (
        "你是专业翻译助手。请把下面这条推文翻译成自然简体中文。"
        "保留人名、账号、标签和原有换行；不要添加解释，不要输出原文。\n\n{text}"
    )

    # ── ai comment ──
    comment_enabled: bool = False
    comment_provider_id: str = ""
    comment_probability: float = 0.3
    comment_max_chars: int = 2000
    comment_prompt: str = (
        "你是社交媒体评论助手。请基于下面的推文内容和可选图片描述，"
        "生成一句简短、自然、有信息量的中文点评。不要复述原文，不要使用 Markdown。"
        "\n\n推文：{text}\n中文翻译：{translation}\n图片描述：{image_caption}"
    )

    # ── ai vision ──
    vision_enabled: bool = False
    vision_provider_id: str = ""
    vision_probability: float = 0.3
    vision_prompt: str = (
        "请简要描述这张图片的主要内容、可见文字、关键信息和可能的语境。"
        "输出自然简体中文，不要使用 Markdown。"
    )
    vision_max_images: int = 1
    vision_max_total: int = 6

    # ── schedule ──
    schedule_enabled: bool = False
    notify_no_updates: bool = False
    check_on_startup: bool = False
    interval_check_enabled: bool = True
    check_interval_minutes: int = 30
    daily_check_enabled: bool = False
    daily_check_times: list[tuple[int, int]] = field(default_factory=list)
    scheduled_fetch_limit: int = 5

    # ── deferred ──
    deferred_publish_enabled: bool = False
    deferred_publish_times: list[tuple[int, int]] = field(default_factory=list)
    deferred_publish_batch_limit: int = 50
    deferred_prefetch_media: bool = True
    deferred_media_retention_hours: float = 72.0
    deferred_media_download_interval_seconds: float = 0.5

    # ── push ──
    send_target_interval: float = 1.5
    send_user_interval: float = 2.0
    merge_tweet_threshold: int = 2
    watch_users_info: WatchUsersInfo = field(default_factory=lambda: WatchUsersInfo(raw_count=0))
    push_targets_info: PushTargetParseResult = field(default_factory=PushTargetParseResult)

    @property
    def users(self) -> list[str]:
        return self.watch_users_info.users

    @property
    def targets(self) -> list[str]:
        return self.push_targets_info.targets

    @property
    def invalid_targets(self) -> list[str]:
        return self.push_targets_info.invalid_targets


# ================================================================
# config_get — 从分组 dict 读取 key
# ================================================================

def config_get(group_dict: dict, key: str, default=None):
    return group_dict.get(key, default)


def config_get_with_fallback(group_dict: dict, default_group_dict: dict, key: str, default=None):
    if key in group_dict:
        return group_dict[key]
    if default_group_dict and key in default_group_dict:
        return default_group_dict[key]
    return default


# ================================================================
# 分组查找
# ================================================================

def get_groups(config) -> list[dict]:
    groups = config.get(_GROUPS_KEY, []) if isinstance(config, dict) else []
    if not isinstance(groups, list):
        groups = []
    return [g for g in groups if isinstance(g, dict)]


def get_default_group_dict(config) -> dict:
    groups = get_groups(config)
    if groups:
        return groups[0]
    return {}


def find_group_dict(config, group_id: str) -> dict | None:
    normalized = normalize_group_id(group_id)
    for g in get_groups(config):
        gid = normalize_group_id(str(g.get("group_id", "")))
        if gid == normalized:
            return g
    return None


# ================================================================
# GroupConfig 构建
# ================================================================

def build_group_config(
    raw_group: dict,
    default_group_dict: dict | None = None,
    context=None,
    log_invalid_targets: bool = True,
) -> GroupConfig:
    default_group_dict = default_group_dict or {}
    dg = default_group_dict

    group_id_raw = str(_g(raw_group, dg, "group_id", DEFAULT_GROUP_ID)).strip()
    group_id = normalize_group_id(group_id_raw) or DEFAULT_GROUP_ID
    name = str(_g(raw_group, dg, "name", group_id)).strip() or group_id
    enabled = _parse_bool(_g(raw_group, dg, "enabled", True), True)
    aliases = _config_list(_g(raw_group, dg, "aliases", []))

    daily_times = _parse_daily_times(_g(raw_group, dg, "daily_check_times", []))
    deferred_times = _parse_daily_times(_g(raw_group, dg, "deferred_publish_times", []))

    cfg = GroupConfig(
        group_id=group_id,
        name=name,
        aliases=aliases,
        enabled=enabled,
        instances=_config_list(_g(raw_group, dg, "instances", ["https://nitter.net"])),
        default_limit=clamp_int(_g(raw_group, dg, "default_limit", 5), 1, 100),
        request_timeout=clamp_float(_g(raw_group, dg, "request_timeout", 12.0), 3.0, 60.0),
        cooldown_seconds=clamp_float(_g(raw_group, dg, "cooldown_seconds", 15.0), 0.0, 3600.0),
        user_agent=str(_g(raw_group, dg, "user_agent", "Mozilla/5.0 (compatible; AstrBotNitterTweets/0.4)")),
        deduplicate_retweets=_parse_bool(_g(raw_group, dg, "deduplicate_retweets", False), False),
        send_image_attachments=_parse_bool(_g(raw_group, dg, "send_image_attachments", True), True),
        send_video_attachments=_parse_bool(_g(raw_group, dg, "send_video_attachments", False), False),
        max_media_per_tweet=clamp_int(_g(raw_group, dg, "max_media_per_tweet", 4), 0, 12),
        media_timeout=clamp_float(_g(raw_group, dg, "media_timeout", 25.0), 5.0, 120.0),
        media_max_size_mb=clamp_float(_g(raw_group, dg, "media_max_size_mb", 25.0), 1.0, 200.0),
        media_cache_retention_days=clamp_float(_g(raw_group, dg, "media_cache_retention_days", 3.0), 0.0, 3650.0),
        xdown_api_url=str(_g(raw_group, dg, "xdown_api_url", "https://xdown.app/api/ajaxSearch")),
        media_user_agent=str(_g(raw_group, dg, "media_user_agent", GroupConfig.media_user_agent)),
        preferred_video_resolution=str(_g(raw_group, dg, "preferred_video_resolution", "highest")).strip().lower(),
        translate_enabled=_parse_bool(_g(raw_group, dg, "translate_enabled", False), False),
        translation_provider_id=str(_g(raw_group, dg, "translation_provider_id", "")).strip(),
        translate_min_chars=clamp_int(_g(raw_group, dg, "translate_min_chars", 8), 0, 1000),
        translate_max_chars=clamp_int(_g(raw_group, dg, "translate_max_chars", 2000), 100, 10000),
        translate_chinese_ratio_threshold=clamp_float(_g(raw_group, dg, "translate_chinese_ratio_threshold", 0.2), 0.0, 1.0),
        translate_prompt=str(_g(raw_group, dg, "translate_prompt", GroupConfig.translate_prompt)),
        comment_enabled=_parse_bool(_g(raw_group, dg, "comment_enabled", False), False),
        comment_provider_id=str(_g(raw_group, dg, "comment_provider_id", "")).strip(),
        comment_probability=clamp_float(_g(raw_group, dg, "comment_probability", 0.3), 0.0, 1.0),
        comment_max_chars=clamp_int(_g(raw_group, dg, "comment_max_chars", 2000), 100, 10000),
        comment_prompt=str(_g(raw_group, dg, "comment_prompt", GroupConfig.comment_prompt)),
        vision_enabled=_parse_bool(_g(raw_group, dg, "vision_enabled", False), False),
        vision_provider_id=str(_g(raw_group, dg, "vision_provider_id", "")).strip(),
        vision_probability=clamp_float(_g(raw_group, dg, "vision_probability", 0.3), 0.0, 1.0),
        vision_prompt=str(_g(raw_group, dg, "vision_prompt", GroupConfig.vision_prompt)),
        vision_max_images=clamp_int(_g(raw_group, dg, "vision_max_images", 1), 1, 20),
        vision_max_total=clamp_int(_g(raw_group, dg, "vision_max_total", 6), 1, 50),
        schedule_enabled=_parse_bool(_g(raw_group, dg, "schedule_enabled", False), False),
        notify_no_updates=_parse_bool(_g(raw_group, dg, "notify_no_updates", False), False),
        check_on_startup=_parse_bool(_g(raw_group, dg, "check_on_startup", False), False),
        interval_check_enabled=_parse_bool(_g(raw_group, dg, "interval_check_enabled", True), True),
        check_interval_minutes=clamp_int(_g(raw_group, dg, "check_interval_minutes", 30), 1, 1440),
        daily_check_enabled=_parse_bool(_g(raw_group, dg, "daily_check_enabled", False), False),
        daily_check_times=daily_times,
        scheduled_fetch_limit=clamp_int(_g(raw_group, dg, "scheduled_fetch_limit", 5), 1, 20),
        deferred_publish_enabled=_parse_bool(_g(raw_group, dg, "deferred_publish_enabled", False), False),
        deferred_publish_times=deferred_times,
        deferred_publish_batch_limit=clamp_int(_g(raw_group, dg, "deferred_publish_batch_limit", 50), 1, 500),
        deferred_prefetch_media=_parse_bool(_g(raw_group, dg, "deferred_prefetch_media", True), True),
        deferred_media_retention_hours=clamp_float(_g(raw_group, dg, "deferred_media_retention_hours", 72.0), 1.0, 8760.0),
        deferred_media_download_interval_seconds=clamp_float(
            _g(raw_group, dg, "deferred_media_download_interval_seconds", 0.5), 0.0, 60.0
        ),
        send_target_interval=clamp_float(_g(raw_group, dg, "send_target_interval", 1.5), 0.0, 60.0),
        send_user_interval=clamp_float(_g(raw_group, dg, "send_user_interval", 2.0), 0.0, 60.0),
        merge_tweet_threshold=clamp_int(_g(raw_group, dg, "merge_tweet_threshold", 2), 0, 20),
        watch_users_info=_parse_watch_users(_g(raw_group, dg, "watch_users", [])),
        push_targets_info=_parse_push_targets(
            _g(raw_group, dg, "push_targets", []),
            log_invalid=log_invalid_targets,
            group_id=group_id,
            context=context,
        ),
    )
    return cfg


def build_default_group(config, context=None, log_invalid_targets: bool = True) -> GroupConfig:
    dg = get_default_group_dict(config)
    return build_group_config(dg, default_group_dict=None, context=context, log_invalid_targets=log_invalid_targets)


def build_all_groups(config, context=None, log_invalid_targets: bool = True) -> list[GroupConfig]:
    groups_dicts = get_groups(config)
    if not groups_dicts:
        return []
    default_dict = groups_dicts[0]
    result = []
    seen_ids: set[str] = set()
    for i, raw_g in enumerate(groups_dicts):
        if not isinstance(raw_g, dict):
            continue
        gc = build_group_config(
            raw_g,
            default_group_dict=default_dict if i > 0 else None,
            context=context,
            log_invalid_targets=log_invalid_targets,
        )
        norm_id = normalize_group_id(gc.group_id)
        if norm_id in seen_ids:
            logger.warning(f"[NitterTweets] duplicate group ignored: {gc.name} ({gc.group_id})")
            continue
        seen_ids.add(norm_id)
        result.append(gc)
    return result


# ================================================================
# 旧配置迁移
# ================================================================

_OLD_SECTION_KEYS = {
    "basic": {"instances", "default_limit", "request_timeout", "cooldown_seconds", "user_agent", "platform_id", "storage_backend"},
    "media": {
        "send_image_attachments", "send_video_attachments", "max_media_per_tweet",
        "media_timeout", "media_max_size_mb", "media_cache_retention_days",
        "xdown_api_url", "media_user_agent",
    },
    "ai_translation": {
        "translate_enabled", "translation_provider_id", "translate_min_chars",
        "translate_max_chars", "translate_chinese_ratio_threshold",
        "translate_prompt", "translate_system_prompt", "translate_prompt_template",
    },
    "ai_comment": {
        "comment_enabled", "comment_provider_id", "comment_probability",
        "comment_max_chars", "comment_prompt",
    },
    "ai_vision": {
        "vision_enabled", "vision_provider_id", "vision_probability",
        "vision_prompt", "vision_max_images", "vision_max_total",
    },
    "schedule": {
        "schedule_enabled", "notify_no_updates", "check_on_startup",
        "interval_check_enabled", "check_interval_minutes",
        "daily_check_enabled", "daily_check_times", "scheduled_fetch_limit",
    },
    "deferred": {
        "deferred_publish_enabled", "deferred_publish_times",
        "deferred_publish_batch_limit", "deferred_prefetch_media",
        "deferred_media_retention_hours", "deferred_media_download_interval_seconds",
    },
    "push": {
        "merge_tweet_threshold", "send_target_interval", "send_user_interval",
        "watch_users", "push_targets",
    },
}

_IGNORED_KEYS = {
    _MIGRATION_MARKER, "_legacy_grouped_config_migrated", "tweet_groups",
    "performance", "groups",
}


def needs_migration(config) -> bool:
    if not isinstance(config, dict):
        return False
    if bool(config.get(_MIGRATION_MARKER, False)):
        return False
    if _GROUPS_KEY in config and isinstance(config[_GROUPS_KEY], list) and len(config[_GROUPS_KEY]) > 0:
        return False
    # 检测 flat 格式: key 在 config 顶层
    for section_keys in _OLD_SECTION_KEYS.values():
        for k in section_keys:
            if k in config:
                return True
    if "schedule_enabled" in config or "instances" in config:
        return True
    # 检测 section 格式: key 在 config["schedule"] / config["push"] 等嵌套 dict 内
    for section_name, section_keys in _OLD_SECTION_KEYS.items():
        section_dict = config.get(section_name, {})
        if isinstance(section_dict, dict):
            for k in section_keys:
                if k in section_dict:
                    return True
    return False


def migrate_to_groups(config) -> bool:
    if not needs_migration(config):
        return False

    default_group: dict = {
        "group_id": DEFAULT_GROUP_ID,
        "name": "默认分组",
        "aliases": ["默认", "default"],
        "enabled": True,
    }

    for section_name, section_keys in _OLD_SECTION_KEYS.items():
        section_dict = config.get(section_name, {})
        for key in section_keys:
            value = None
            if isinstance(section_dict, dict) and key in section_dict:
                value = section_dict[key]
            elif key in config:
                value = config[key]
            if value is not None:
                default_group[key] = value

    for key in _OLD_SECTION_KEYS.get("push", set()):
        if key not in default_group and key in config:
            default_group[key] = config[key]

    groups = [default_group]

    raw_tweet_groups = config.get("tweet_groups", []) or []
    if isinstance(raw_tweet_groups, dict):
        raw_tweet_groups = [raw_tweet_groups]
    if isinstance(raw_tweet_groups, list):
        for raw_g in raw_tweet_groups:
            if not isinstance(raw_g, dict):
                continue
            new_g = dict(default_group)
            for k, v in raw_g.items():
                if k not in ("watch_users", "push_targets"):
                    new_g[k] = v
            if "watch_users" in raw_g:
                new_g["watch_users"] = raw_g["watch_users"]
            if "push_targets" in raw_g:
                new_g["push_targets"] = raw_g["push_targets"]
            if raw_g.get("name"):
                new_g["name"] = raw_g["name"]
            if raw_g.get("group_id"):
                new_g["group_id"] = raw_g["group_id"]
            if raw_g.get("aliases"):
                new_g["aliases"] = raw_g["aliases"]
            groups.append(new_g)

    config[_GROUPS_KEY] = groups
    config[_MIGRATION_MARKER] = True

    # 清理旧的 section / flat keys 和 tweet_groups，避免 config_get 回退读到过期数据
    for section_name in _OLD_SECTION_KEYS:
        config.pop(section_name, None)
    for section_keys in _OLD_SECTION_KEYS.values():
        for k in section_keys:
            config.pop(k, None)
    config.pop("tweet_groups", None)
    config.pop("performance", None)
    config.pop("_legacy_grouped_config_migrated", None)

    save_config = getattr(config, "save_config", None)
    if callable(save_config):
        save_config()

    logger.info("[NitterTweets] config migrated to unified groups format")
    return True


# ================================================================
# 内部工具
# ================================================================

def _g(group_dict: dict, default_group_dict: dict | None, key: str, fallback):
    if key in group_dict:
        return group_dict[key]
    if default_group_dict and key in default_group_dict:
        return default_group_dict[key]
    return fallback


def normalize_group_id(group_id: str) -> str:
    return (group_id or "").strip().lower()


def _parse_bool(value, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on", "enable", "enabled"}:
            return True
        if normalized in {"0", "false", "no", "off", "disable", "disabled"}:
            return False
        return default
    return bool(value)


def _parse_daily_times(raw_times=None) -> list[tuple[int, int]]:
    if raw_times is None:
        return []
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
            continue
        if 0 <= hour < 24 and 0 <= minute < 60:
            times.append((hour, minute))
    return times


def _parse_watch_users(raw_users) -> WatchUsersInfo:
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


def _parse_push_targets(
    raw_targets,
    log_invalid: bool = True,
    group_id: str = DEFAULT_GROUP_ID,
    context=None,
) -> PushTargetParseResult:
    if raw_targets is None:
        raw_targets = []
    if isinstance(raw_targets, str):
        raw_targets = re.split(r"[\n,，]+", raw_targets)
    elif not isinstance(raw_targets, list):
        raw_targets = [raw_targets]

    default_platform = _detect_platform(context)
    result = PushTargetParseResult()
    seen: set[str] = set()
    for raw in raw_targets:
        if not isinstance(raw, str):
            invalid = repr(raw)
            result.invalid_targets.append(invalid)
            if log_invalid:
                logger.warning(f"[NitterTweets] invalid push target: group={group_id}, target={invalid}")
            continue
        target = raw.strip().replace("：", ":")
        if not target:
            continue
        umo = _parse_target_to_umo(target, default_platform)
        if umo is None:
            result.invalid_targets.append(raw)
            if log_invalid:
                logger.warning(f"[NitterTweets] invalid push target: group={group_id}, target={raw!r}")
            continue
        if umo not in seen:
            seen.add(umo)
            result.targets.append(umo)
    return result


def _detect_platform(context) -> str:
    if context:
        configured = getattr(context, "platform_id", None)
        if configured and str(configured).strip():
            return str(configured).strip()
        get_all = getattr(context, "get_all_platforms", None)
        if callable(get_all):
            try:
                for p in get_all():
                    pid = _platform_id(p)
                    if pid and pid != "webchat":
                        return pid
            except Exception:
                pass
        manager = getattr(context, "platform_manager", None)
        if manager:
            try:
                for p in getattr(manager, "platform_insts", []) or []:
                    pid = _platform_id(p)
                    if pid and pid != "webchat":
                        return pid
            except Exception:
                pass
    return "aiocqhttp"


def _platform_id(platform) -> str:
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
        if metadata:
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


def _parse_target_to_umo(target: str, default_platform: str) -> str | None:
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
        platform, kind, ident = parts[0].strip(), parts[1].strip().lower(), parts[2].strip()
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


def _config_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw_items = re.split(r"[\n,，]+", value)
    elif isinstance(value, list):
        raw_items = value
    else:
        raw_items = [value]
    return [str(item).strip() for item in raw_items if str(item).strip()]
