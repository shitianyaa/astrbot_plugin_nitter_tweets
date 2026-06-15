from __future__ import annotations


DEFAULT_GROUP_ID = "default"
LEGACY_GLOBAL_GROUP_ID = "global"

# Backward-compatible name for existing imports. Runtime storage should use
# DEFAULT_GROUP_ID; LEGACY_GLOBAL_GROUP_ID is accepted only as input/migration.
GLOBAL_GROUP_ID = DEFAULT_GROUP_ID

DEFAULT_GROUP_NAME = "默认分组"
DEFAULT_GROUP_ALIASES = ["default", "默认", "global", "全局"]


def normalize_group_id(value: str) -> str:
    group_id = str(value or "").strip().lower()
    if group_id in {"", DEFAULT_GROUP_ID, LEGACY_GLOBAL_GROUP_ID}:
        return DEFAULT_GROUP_ID
    if group_id in {"默认", "默认分组", "全局", "全局分组"}:
        return DEFAULT_GROUP_ID
    return group_id


def is_default_group(value: str) -> bool:
    return normalize_group_id(value) == DEFAULT_GROUP_ID
