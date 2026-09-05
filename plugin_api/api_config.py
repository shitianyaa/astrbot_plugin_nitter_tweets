"""插件配置面板:schema 驱动的配置查看与单键更新。

`NitterWebAPI` 的 mixin：只通过 `self` 协作，不 import 宿主类。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

try:
    from ..config.compat import config_get
except ImportError:
    from config.compat import config_get

_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "_conf_schema.json"
_NON_EDITABLE_ITEM_TYPES = frozenset({"template_list"})


def _load_schema() -> dict[str, Any]:
    with _SCHEMA_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)


class WebAPIConfigMixin:
    """schema 驱动的插件配置读取与单键更新。"""

    async def build_config_schema(self) -> dict[str, Any]:
        schema = await asyncio.to_thread(_load_schema)
        config = self.config
        groups: list[dict[str, Any]] = []
        editable_count = 0
        for group_key, group_schema in schema.items():
            if (
                not isinstance(group_schema, dict)
                or group_schema.get("type") != "object"
            ):
                continue
            items: list[dict[str, Any]] = []
            for item_key, item_schema in group_schema.get("items", {}).items():
                item_type = str(item_schema.get("type", "string"))
                editable = item_type not in _NON_EDITABLE_ITEM_TYPES
                if editable:
                    editable_count += 1
                items.append(
                    {
                        "key": item_key,
                        "type": item_type,
                        "description": str(item_schema.get("description", item_key)),
                        "hint": str(item_schema.get("hint", "")),
                        "options": [str(o) for o in item_schema.get("options", [])]
                        or None,
                        "value": config_get(
                            config, item_key, item_schema.get("default")
                        ),
                        "editable": editable,
                    }
                )
            groups.append(
                {
                    "key": group_key,
                    "name": str(group_schema.get("description", group_key)),
                    "items": items,
                }
            )
        return self._ok(groups=groups, total=editable_count)
