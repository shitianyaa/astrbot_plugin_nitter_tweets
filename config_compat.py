from __future__ import annotations


try:
    from .group_config import (
        DEFAULT_GROUP_ID,
        _GROUPS_KEY,
        _MIGRATION_MARKER,
        config_get as _group_config_get,
        migrate_to_groups,
    )
except ImportError:
    from group_config import (
        DEFAULT_GROUP_ID,
        _GROUPS_KEY,
        _MIGRATION_MARKER,
        config_get as _group_config_get,
        migrate_to_groups,
    )


def config_get(config, key: str, default=None):
    if isinstance(config, dict):
        if _GROUPS_KEY in config:
            default_group = _get_default_group_dict(config)
            if default_group and key in default_group:
                return default_group[key]
        if key in config:
            return config[key]
    return default


def config_get_from_group(group_dict: dict, key: str, default=None):
    return _group_config_get(group_dict, key, default)


def config_set(config, key: str, value) -> None:
    if isinstance(config, dict) and _GROUPS_KEY in config:
        groups = config.get(_GROUPS_KEY, [])
        if isinstance(groups, list) and groups and isinstance(groups[0], dict):
            groups[0][key] = value
            return
    config[key] = value


def _get_default_group_dict(config: dict) -> dict:
    groups = config.get(_GROUPS_KEY, [])
    if isinstance(groups, list) and groups and isinstance(groups[0], dict):
        return groups[0]
    return {}


# ── legacy compat ──
KV_KEY_MIGRATION_MARKER = _MIGRATION_MARKER
LEGACY_CONFIG_MIGRATION_KEY = _MIGRATION_MARKER
migrate_legacy_grouped_config = migrate_to_groups
GLOBAL_GROUP_ID = DEFAULT_GROUP_ID


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
