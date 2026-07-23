from __future__ import annotations

from typing import TYPE_CHECKING, Any

from astrbot.api import logger

try:
    from ..shared import normalize_username
    from ..shared.group_ids import (
        DEFAULT_GROUP_ALIASES,
        DEFAULT_GROUP_ID,
        DEFAULT_GROUP_NAME,
        normalize_group_id,
    )
    from .compat import (
        TWEET_GROUP_TEMPLATE_KEY,
        TWEET_GROUP_TEMPLATE_KEY_FIELD,
        config_get,
        config_set,
    )
except ImportError:
    from shared import normalize_username
    from shared.group_ids import (
        DEFAULT_GROUP_ALIASES,
        DEFAULT_GROUP_ID,
        DEFAULT_GROUP_NAME,
        normalize_group_id,
    )
    from config.compat import (
        TWEET_GROUP_TEMPLATE_KEY,
        TWEET_GROUP_TEMPLATE_KEY_FIELD,
        config_get,
        config_set,
    )

if TYPE_CHECKING:
    try:
        from ..scheduler import ScheduleGroup
    except ImportError:
        from scheduler import ScheduleGroup


def normalize_import_username(value: str) -> str:
    value = str(value or "").strip()
    if value.startswith("@"):
        value = value[1:].strip()
    if value.startswith(("http://", "https://")) or "/" in value:
        return ""
    return normalize_username(value)


def ensure_default_import_group(config, config_reader) -> "ScheduleGroup":
    group = config_reader.schedule_group(DEFAULT_GROUP_ID, log_invalid_targets=False)
    if group is not None:
        return group

    raw_groups = config_get(config, "tweet_groups", []) or []
    if isinstance(raw_groups, dict):
        raw_groups = [raw_groups]
    elif not isinstance(raw_groups, list):
        raw_groups = []

    default_group = {
        TWEET_GROUP_TEMPLATE_KEY_FIELD: TWEET_GROUP_TEMPLATE_KEY,
        "name": DEFAULT_GROUP_NAME,
        "group_id": DEFAULT_GROUP_ID,
        "aliases": list(DEFAULT_GROUP_ALIASES),
        "enabled": True,
        "watch_users": [],
        "push_targets": [],
    }
    raw_groups.insert(0, default_group)
    config_set(config, "tweet_groups", raw_groups)

    parsed = config_reader.parse_schedule_group(
        default_group, 1, log_invalid_targets=False
    )
    if parsed is None:
        raise RuntimeError("无法创建默认分组配置")
    return parsed


def set_import_group_users(
    config,
    config_reader,
    group: "ScheduleGroup | None",
    users: list[str],
) -> None:
    if group is None:
        group = ensure_default_import_group(config, config_reader)

    raw_groups = config_get(config, "tweet_groups", []) or []
    if isinstance(raw_groups, dict):
        group_items = [raw_groups]
    elif isinstance(raw_groups, list):
        group_items = raw_groups
    else:
        group_items = []

    target_group_id = normalize_group_id(group.group_id)
    for index, raw_group in enumerate(group_items, 1):
        parsed = config_reader.parse_schedule_group(
            raw_group,
            index,
            log_invalid_targets=False,
        )
        if parsed is None:
            continue
        if normalize_group_id(parsed.group_id) != target_group_id:
            continue
        raw_group["watch_users"] = users
        config_set(config, "tweet_groups", raw_groups)
        return

    raise RuntimeError(f"未找到分组配置：{group.name} ({group.group_id})")


def set_import_group_queries(
    config,
    config_reader,
    group: "ScheduleGroup | None",
    queries: list[dict[str, str]],
) -> None:
    """Persist watch_queries for a tag group. Each item: {query, type}."""
    if group is None:
        raise RuntimeError("标签订阅必须指定标签分组")

    raw_groups = config_get(config, "tweet_groups", []) or []
    if isinstance(raw_groups, dict):
        group_items = [raw_groups]
    elif isinstance(raw_groups, list):
        group_items = raw_groups
    else:
        group_items = []

    target_group_id = normalize_group_id(group.group_id)
    for index, raw_group in enumerate(group_items, 1):
        parsed = config_reader.parse_schedule_group(
            raw_group,
            index,
            log_invalid_targets=False,
        )
        if parsed is None:
            continue
        if normalize_group_id(parsed.group_id) != target_group_id:
            continue
        raw_group["group_type"] = "tag"
        raw_group["watch_queries"] = [
            {
                "query": str(item.get("query") or "").strip(),
                "type": str(item.get("type") or "phrase").strip(),
            }
            for item in queries
            if str(item.get("query") or "").strip()
        ]
        raw_group["watch_users"] = []
        config_set(config, "tweet_groups", raw_groups)
        return

    raise RuntimeError(f"未找到分组配置：{group.name} ({group.group_id})")


async def sync_import_config_groups(scheduler: Any) -> str:
    try:
        schedule_groups = scheduler.config_reader.schedule_groups(
            log_invalid_targets=False
        )
        await scheduler.storage.migrate_and_sync(schedule_groups)
    except Exception as exc:
        logger.warning(f"[NitterTweets] 同步导入订阅失败: {exc}")
        return str(exc)
    return ""


def save_subscription_config(config) -> str:
    save_config = getattr(config, "save_config", None)
    if callable(save_config):
        try:
            save_config()
        except Exception as exc:
            error = str(exc)
            logger.warning(f"[NitterTweets] 保存订阅配置失败: {error}")
            return error
        return ""
    return "当前配置对象不支持 save_config()"
