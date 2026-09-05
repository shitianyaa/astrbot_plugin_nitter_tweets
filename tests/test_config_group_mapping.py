"""schema 分组键必须都有 CONFIG_GROUP_BY_KEY 映射。

`update_config_item` 按 schema 分组写入，而面板展示值经 `config_get` 按
`CONFIG_GROUP_BY_KEY` 的分组读取。缺映射（或映射分组与 schema 分组不一致）时
保存会成功，但面板刷新后仍显示旧值。
"""

from __future__ import annotations

import json
from pathlib import Path

import config.compat as compat

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "_conf_schema.json"

# 允许不入映射的 schema 分组键。tweet_groups 由「分组订阅管理」专用路径读写，
# 但当前仍保留 push 分组映射供面板展示，因此初始为空集合；出现新的例外时在此
# 如实登记。
_UNMAPPED_ALLOWED: frozenset[str] = frozenset()


def _schema_object_group_item_groups() -> dict[str, str]:
    """返回 schema 中 type=object 分组的 {item_key: group_key}。"""
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    item_groups: dict[str, str] = {}
    for group_key, group_schema in schema.items():
        if not isinstance(group_schema, dict):
            continue
        if group_schema.get("type") != "object":
            continue
        for item_key in group_schema.get("items", {}):
            item_groups[item_key] = group_key
    return item_groups


def test_every_schema_group_item_key_is_mapped():
    item_groups = _schema_object_group_item_groups()
    assert item_groups, "未能从 _conf_schema.json 解析出 object 分组的 items"

    unmapped = set(item_groups) - set(compat.CONFIG_GROUP_BY_KEY)
    assert unmapped == _UNMAPPED_ALLOWED, (
        "以下 _conf_schema.json 分组键缺少 CONFIG_GROUP_BY_KEY 映射，"
        f"保存后面板会显示旧值: {sorted(unmapped - _UNMAPPED_ALLOWED)}；"
        f"例外清单中已失效的键: {sorted(_UNMAPPED_ALLOWED - unmapped)}"
    )

    mismatched = {
        key: (group, compat.CONFIG_GROUP_BY_KEY.get(key))
        for key, group in item_groups.items()
        if compat.CONFIG_GROUP_BY_KEY.get(key) not in (None, group)
    }
    assert not mismatched, (
        "以下键的 CONFIG_GROUP_BY_KEY 分组与 schema 声明分组不一致，"
        f"单键更新会写错分组: {mismatched}"
    )
