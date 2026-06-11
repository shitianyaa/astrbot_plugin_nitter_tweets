from __future__ import annotations

LEGACY_CONFIG_MIGRATION_KEY = "_legacy_grouped_config_migrated"

CONFIG_GROUP_BY_KEY = {
    "storage_backend": "basic",
    "instances": "basic",
    "default_limit": "basic",
    "request_timeout": "basic",
    "cooldown_seconds": "basic",
    "user_agent": "basic",
    "send_image_attachments": "media",
    "send_video_attachments": "media",
    "max_media_per_tweet": "media",
    "media_timeout": "media",
    "media_max_size_mb": "media",
    "media_cache_retention_days": "media",
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
    "max_media_per_tweet",
    "media_timeout",
    "media_max_size_mb",
    "media_cache_retention_days",
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
    "merge_tweet_threshold",
    "send_target_interval",
    "send_user_interval",
    "watch_users",
    "push_targets",
    "tweet_groups",
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
