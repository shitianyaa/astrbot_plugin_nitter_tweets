from __future__ import annotations

import re


DEFAULT_GROUP_ID = "default"
LEGACY_GLOBAL_GROUP_ID = "global"
SAFE_LEGACY_GROUP_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")

# Backward-compatible name for existing imports. New default groups use
# DEFAULT_GROUP_ID, while explicit legacy IDs such as "global" stay stable.
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


def normalize_stable_group_id(value: str) -> str:
    group_id = str(value or "").strip().lower()
    if group_id in {"默认", "默认分组", "全局", "全局分组"}:
        return DEFAULT_GROUP_ID
    return group_id or DEFAULT_GROUP_ID


def infer_legacy_group_id_from_name(value: str) -> str:
    group_id = str(value or "").strip().lower()
    if not group_id:
        return ""
    if normalize_group_id(group_id) == DEFAULT_GROUP_ID:
        return DEFAULT_GROUP_ID
    if SAFE_LEGACY_GROUP_ID_RE.fullmatch(group_id):
        return group_id
    return ""


def is_default_group(value: str) -> bool:
    return normalize_group_id(value) == DEFAULT_GROUP_ID
