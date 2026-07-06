from __future__ import annotations

try:
    from ..shared.group_ids import (
        DEFAULT_GROUP_ALIASES,
        DEFAULT_GROUP_ID,
        DEFAULT_GROUP_NAME,
        normalize_group_id,
    )
except ImportError:
    from shared.group_ids import (
        DEFAULT_GROUP_ALIASES,
        DEFAULT_GROUP_ID,
        DEFAULT_GROUP_NAME,
        normalize_group_id,
    )

LEGACY_CONFIG_MIGRATION_KEY = "_legacy_grouped_config_migrated"
DEFAULT_GROUP_CONFIG_MIGRATION_KEY = "_default_group_config_migrated"
MEDIA_CACHE_SEND_DELETE_MIGRATION_KEY = "_media_cache_send_delete_migrated"
TWEET_GROUP_TEMPLATE_KEY_FIELD = "__template_key"
TWEET_GROUP_TEMPLATE_KEY = "group"

CONFIG_GROUP_BY_KEY = {
    "storage_backend": "basic",
    "instances": "basic",
    "default_limit": "basic",
    "request_timeout": "basic",
    "cooldown_seconds": "basic",
    "user_agent": "basic",
    "filter_reposts_enabled": "basic",
    "send_image_attachments": "media",
    "send_video_attachments": "media",
    "video_resolution_preference": "media",
    "max_media_per_tweet": "media",
    "media_timeout": "media",
    "media_max_size_mb": "media",
    "xdown_api_url": "media",
    "media_user_agent": "media",
    "translate_enabled": "ai_translation",
    "translation_provider_id": "ai_translation",
    "translate_min_chars": "ai_translation",
    "translate_max_chars": "ai_translation",
    "translate_chinese_ratio_threshold": "ai_translation",
    "translate_prompt": "ai_translation",
    "translate_system_prompt": "ai_translation",
    "translate_prompt_template": "ai_translation",
    "comment_enabled": "ai_comment",
    "comment_provider_id": "ai_comment",
    "comment_probability": "ai_comment",
    "comment_max_chars": "ai_comment",
    "comment_prompt": "ai_comment",
    "vision_enabled": "ai_vision",
    "vision_provider_id": "ai_vision",
    "vision_probability": "ai_vision",
    "vision_prompt": "ai_vision",
    "vision_max_images": "ai_vision",
    "vision_max_total": "ai_vision",
    "schedule_enabled": "schedule",
    "notify_no_updates": "schedule",
    "check_on_startup": "schedule",
    "interval_check_enabled": "schedule",
    "check_interval_minutes": "schedule",
    "daily_check_enabled": "schedule",
    "daily_check_times": "schedule",
    "scheduled_fetch_limit": "schedule",
    "deferred_publish_enabled": "deferred",
    "deferred_publish_times": "deferred",
    "deferred_publish_batch_limit": "deferred",
    "deferred_prefetch_media": "deferred",
    "deferred_media_retention_hours": "deferred",
    "deferred_media_download_interval_seconds": "deferred",
    "brief_log_enabled": "logging",
    "concurrent_fetch_enabled": "performance",
    "fetch_concurrency": "performance",
    "concurrent_fetch_instances": "performance",
    "concurrent_prepare_enabled": "performance",
    "prepare_concurrency": "performance",
    "merge_tweet_threshold": "push",
    "merge_scheduled_updates": "push",
    "send_target_interval": "push",
    "send_user_interval": "push",
    "watch_users": "push",
    "push_targets": "push",
    "tweet_groups": "push",
    "platform_id": "basic",
}

MIGRATABLE_CONFIG_KEYS = {
    "storage_backend",
    "instances",
    "default_limit",
    "request_timeout",
    "cooldown_seconds",
    "user_agent",
    "send_image_attachments",
    "send_video_attachments",
    "video_resolution_preference",
    "max_media_per_tweet",
    "media_timeout",
    "media_max_size_mb",
    "xdown_api_url",
    "media_user_agent",
    "translate_enabled",
    "translation_provider_id",
    "translate_min_chars",
    "translate_max_chars",
    "translate_chinese_ratio_threshold",
    "translate_prompt",
    "comment_enabled",
    "comment_provider_id",
    "comment_probability",
    "comment_max_chars",
    "comment_prompt",
    "vision_enabled",
    "vision_provider_id",
    "vision_probability",
    "vision_prompt",
    "vision_max_images",
    "schedule_enabled",
    "notify_no_updates",
    "check_on_startup",
    "interval_check_enabled",
    "check_interval_minutes",
    "daily_check_enabled",
    "daily_check_times",
    "scheduled_fetch_limit",
    "deferred_publish_enabled",
    "deferred_publish_times",
    "deferred_publish_batch_limit",
    "deferred_prefetch_media",
    "deferred_media_retention_hours",
    "deferred_media_download_interval_seconds",
    "concurrent_fetch_enabled",
    "fetch_concurrency",
    "concurrent_fetch_instances",
    "concurrent_prepare_enabled",
    "prepare_concurrency",
    "merge_tweet_threshold",
    "send_target_interval",
    "send_user_interval",
    "watch_users",
    "push_targets",
    "tweet_groups",
}

DEFAULT_GROUP_MIGRATION_KEYS = {
    "watch_users",
    "push_targets",
    "interval_check_enabled",
    "daily_check_enabled",
    "daily_check_times",
    "deferred_publish_enabled",
    "filter_plain_text_enabled",
}

LIST_MERGE_KEYS = {
    "watch_users",
    "push_targets",
    "daily_check_times",
    "deferred_publish_times",
    "aliases",
}


def config_get(config, key: str, default=None):
    group_name = CONFIG_GROUP_BY_KEY.get(key)
    if group_name:
        group = _dict_get(config, group_name, {})
        if isinstance(group, dict) and key in group:
            return group.get(key, default)
    return _dict_get(config, key, default)


def migrate_legacy_grouped_config(config) -> bool:
    if bool(_dict_get(config, LEGACY_CONFIG_MIGRATION_KEY, False)):
        return False

    changed = False
    for key in MIGRATABLE_CONFIG_KEYS:
        group_name = CONFIG_GROUP_BY_KEY[key]
        if not _dict_has(config, key):
            continue

        legacy_value = _dict_get(config, key)
        group = _dict_get(config, group_name, {})
        if not isinstance(group, dict):
            group = {}
            changed = True

        if group.get(key) != legacy_value:
            group[key] = legacy_value
            config[group_name] = group
            changed = True

    config[LEGACY_CONFIG_MIGRATION_KEY] = True
    changed = True

    save_config = getattr(config, "save_config", None)
    if changed and callable(save_config):
        save_config()
    return changed


def migrate_default_group_config(config, *, save: bool = True) -> bool:
    if bool(_dict_get(config, DEFAULT_GROUP_CONFIG_MIGRATION_KEY, False)):
        return ensure_tweet_group_template_keys(config, save=save)

    raw_groups = config_get(config, "tweet_groups", []) or []
    if isinstance(raw_groups, dict):
        groups = [raw_groups]
        changed = True
    elif isinstance(raw_groups, list):
        groups = raw_groups
        changed = False
    else:
        groups = []
        changed = bool(raw_groups)

    default_group = None
    merged_groups: list = []
    for group in groups:
        if not isinstance(group, dict):
            merged_groups.append(group)
            continue
        group_id = normalize_group_id(group.get("group_id") or group.get("name") or "")
        if group_id == DEFAULT_GROUP_ID:
            if default_group is None:
                default_group = group
                merged_groups.append(default_group)
            else:
                _merge_default_group_into(default_group, group)
                changed = True
                continue

            if str(default_group.get("group_id") or "").strip() != DEFAULT_GROUP_ID:
                default_group["group_id"] = DEFAULT_GROUP_ID
                changed = True
            if _is_legacy_default_name(default_group.get("name")):
                default_group["name"] = DEFAULT_GROUP_NAME
                changed = True
        else:
            merged_groups.append(group)
    if len(merged_groups) != len(groups):
        groups = merged_groups
        changed = True

    if default_group is not None:
        for group in groups:
            if group is not default_group or not isinstance(group, dict):
                continue
            if str(group.get("group_id") or "").strip() != DEFAULT_GROUP_ID:
                group["group_id"] = DEFAULT_GROUP_ID
                changed = True
            break

    legacy_values = {
        key: config_get(config, key)
        for key in DEFAULT_GROUP_MIGRATION_KEYS
        if _has_non_empty_config(config, key)
    }
    should_create_default = (
        default_group is not None
        or _has_non_empty_config(config, "watch_users")
        or _has_non_empty_config(config, "push_targets")
    )
    if should_create_default and default_group is None:
        default_group = {
            TWEET_GROUP_TEMPLATE_KEY_FIELD: TWEET_GROUP_TEMPLATE_KEY,
            "name": DEFAULT_GROUP_NAME,
            "group_id": DEFAULT_GROUP_ID,
        }
        groups.insert(0, default_group)
        changed = True

    if default_group is not None:
        if _ensure_tweet_group_template_key(default_group):
            changed = True
        if not str(default_group.get("name") or "").strip():
            default_group["name"] = DEFAULT_GROUP_NAME
            changed = True
        aliases = _merge_list_values(
            default_group.get("aliases", []), DEFAULT_GROUP_ALIASES
        )
        if aliases != _normalize_list(default_group.get("aliases", [])):
            default_group["aliases"] = aliases
            changed = True

        for key, value in legacy_values.items():
            if key in LIST_MERGE_KEYS:
                merged = _merge_list_values(default_group.get(key, []), value)
                if merged != _normalize_list(default_group.get(key, [])):
                    default_group[key] = merged
                    changed = True
            elif key not in default_group or _is_empty_value(default_group.get(key)):
                default_group[key] = value
                changed = True

    if _ensure_tweet_group_template_keys(groups):
        changed = True
    if _ensure_tweet_group_stable_ids(groups):
        changed = True

    if not changed:
        return False

    config_set(config, "tweet_groups", groups)
    config[DEFAULT_GROUP_CONFIG_MIGRATION_KEY] = True

    save_config = getattr(config, "save_config", None)
    if save and callable(save_config):
        save_config()
    return changed


def ensure_tweet_group_template_keys(config, *, save: bool = True) -> bool:
    raw_groups = config_get(config, "tweet_groups", []) or []
    if isinstance(raw_groups, dict):
        groups = [raw_groups]
        changed = True
    elif isinstance(raw_groups, list):
        groups = raw_groups
        changed = False
    else:
        return False

    if _ensure_tweet_group_template_keys(groups):
        changed = True
    if _ensure_tweet_group_stable_ids(groups):
        changed = True

    if not changed:
        return False

    config_set(config, "tweet_groups", groups)
    save_config = getattr(config, "save_config", None)
    if save and callable(save_config):
        save_config()
    return True


def config_set(config, key: str, value) -> None:
    group_name = CONFIG_GROUP_BY_KEY.get(key)
    if not group_name:
        config[key] = value
        return
    group = _dict_get(config, group_name, {})
    if not isinstance(group, dict):
        group = {}
    group[key] = value
    config[group_name] = group


def _dict_get(config, key: str, default=None):
    try:
        return config.get(key, default)
    except AttributeError:
        return default


def _dict_has(config, key: str) -> bool:
    try:
        return key in config
    except TypeError:
        return _dict_get(config, key, None) is not None


def _has_non_empty_config(config, key: str) -> bool:
    if not _dict_has(config, key):
        group_name = CONFIG_GROUP_BY_KEY.get(key)
        group = _dict_get(config, group_name, {}) if group_name else {}
        if not isinstance(group, dict) or key not in group:
            return False
    return not _is_empty_value(config_get(config, key))


def _is_empty_value(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    return False


def _normalize_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, str):
        items = value.replace("，", ",").split(",")
    elif isinstance(value, list):
        items = value
    else:
        items = [value]
    return [str(item).strip() for item in items if str(item).strip()]


def _merge_list_values(existing, incoming) -> list:
    result: list[str] = []
    seen: set[str] = set()
    for item in [*_normalize_list(existing), *_normalize_list(incoming)]:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _merge_default_group_into(target: dict, source: dict) -> None:
    for key, value in source.items():
        if key == "group_id":
            continue
        if key == "name" and _is_legacy_default_name(value):
            continue
        if key in LIST_MERGE_KEYS:
            target[key] = _merge_list_values(target.get(key, []), value)
        elif key not in target or _is_empty_value(target.get(key)):
            target[key] = value


def _is_legacy_default_name(value) -> bool:
    text = str(value or "").strip()
    return text in {"", "global", "Global", "GLOBAL", "全局", "全局分组"}


def _ensure_tweet_group_template_keys(groups: list) -> bool:
    changed = False
    for group in groups:
        if not isinstance(group, dict):
            continue
        if _ensure_tweet_group_template_key(group):
            changed = True
    return changed


def _ensure_tweet_group_stable_ids(groups: list) -> bool:
    changed = False
    existing: set[str] = set()
    for group in groups:
        if not isinstance(group, dict):
            continue
        group_id = str(group.get("group_id") or "").strip()
        if group_id:
            existing.add(normalize_group_id(group_id))
    for group in groups:
        if not isinstance(group, dict):
            continue
        group_id = str(group.get("group_id") or "").strip()
        if group_id:
            continue
        if normalize_group_id(group.get("name") or "") == DEFAULT_GROUP_ID:
            group["group_id"] = DEFAULT_GROUP_ID
            existing.add(DEFAULT_GROUP_ID)
            changed = True
            continue
        candidate = _next_generated_group_id(existing)
        group["group_id"] = candidate
        existing.add(candidate)
        changed = True
    return changed


def _next_generated_group_id(existing: set[str], start_index: int = 1) -> str:
    counter = max(1, int(start_index or 1))
    while True:
        candidate = f"group_{counter}"
        if candidate not in existing:
            return candidate
        counter += 1


def _ensure_tweet_group_template_key(group: dict) -> bool:
    if group.get(TWEET_GROUP_TEMPLATE_KEY_FIELD) == TWEET_GROUP_TEMPLATE_KEY:
        return False
    group[TWEET_GROUP_TEMPLATE_KEY_FIELD] = TWEET_GROUP_TEMPLATE_KEY
    return True
