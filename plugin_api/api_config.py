"""插件配置面板:schema 驱动的配置查看与单键更新。

`NitterWebAPI` 的 mixin：只通过 `self` 协作，不 import 宿主类。
"""

from __future__ import annotations

import asyncio
import json
import math
from pathlib import Path
from typing import Any

try:
    from astrbot.api import logger
except ImportError:
    import logging

    logger = logging.getLogger(__name__)

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
                if item_schema.get("invisible"):
                    continue
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
                        "default": item_schema.get("default"),
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

    async def update_config_item(self, data: dict[str, Any]) -> dict[str, Any]:
        key = self._data_text(data, "key")
        raw = data.get("value")
        schema = await asyncio.to_thread(_load_schema)
        found: tuple[str, dict[str, Any]] | None = None
        for group_key, group_schema in schema.items():
            if (
                not isinstance(group_schema, dict)
                or group_schema.get("type") != "object"
            ):
                continue
            item_schema = group_schema.get("items", {}).get(key)
            if item_schema is not None:
                found = (group_key, item_schema)
                break
        if found is None:
            return self._error(f"未知配置项：{key}")
        group_key, item_schema = found
        item_type = str(item_schema.get("type", "string"))
        if item_type in _NON_EDITABLE_ITEM_TYPES:
            return self._error("该配置项在「分组订阅管理」维护，不支持此处修改")
        try:
            value = _coerce_config_value(item_type, raw, item_schema)
        except (TypeError, ValueError) as exc:
            return self._error(str(exc) or "取值不合法")
        config = self.config
        group = config.get(group_key)
        if not isinstance(group, dict):
            group = {}
        group[key] = value
        config[group_key] = group
        save_config = getattr(config, "save_config", None)
        if callable(save_config):
            save_config()
        return self._ok(key=key, value=value)

    async def list_providers(self) -> dict[str, Any]:
        """枚举 AstrBot 已装配的 LLM Provider,供配置面板下拉选择。"""
        providers: list[dict[str, Any]] = []
        seen: set[str] = set()
        try:
            context = getattr(self, "context", None)
            manager = getattr(context, "provider_manager", None)
            raw = None
            if callable(getattr(context, "get_all_providers", None)):
                raw = context.get_all_providers()
            elif manager is not None:
                raw = manager.get_all_providers()
            if isinstance(raw, dict):
                iterable = list(raw.values())
            elif isinstance(raw, (list, tuple)):
                iterable = list(raw)
            else:
                iterable = []
            for provider in iterable:
                entry = _provider_entry(provider)
                if entry and entry["id"] not in seen:
                    seen.add(entry["id"])
                    providers.append(entry)
        except Exception as exc:
            logger.warning(
                f"[NitterTweets] 枚举 Provider 列表失败: {type(exc).__name__}: {exc}"
            )
        return self._ok(providers=providers)


def _provider_entry(provider: Any) -> dict[str, Any] | None:
    meta = provider.meta() if callable(getattr(provider, "meta", None)) else None
    pid = str(
        getattr(meta, "id", None)
        or getattr(provider, "id", None)
        or getattr(provider, "provider_id", None)
        or ""
    ).strip()
    if not pid:
        return None
    name = str(
        getattr(meta, "name", None)
        or getattr(meta, "model", None)
        or getattr(provider, "name", None)
        or pid
    ).strip()
    ptype = str(getattr(meta, "provider_type", "") or "")
    label = f"{name} [{pid}]" if name != pid else pid
    return {"id": pid, "name": name, "type": ptype, "label": label}


def _coerce_config_value(item_type: str, raw: Any, item_schema: dict[str, Any]) -> Any:
    if item_type == "bool":
        if isinstance(raw, bool):
            return raw
        raise ValueError("该配置项需要布尔值")
    if item_type in {"int", "float"}:
        try:
            number = float(raw)
        except (TypeError, ValueError):
            raise ValueError("该配置项需要数字")
        if not math.isfinite(number):
            raise ValueError("该配置项需要有限数字")
        if item_type == "int":
            if number != int(number):
                raise ValueError("该配置项需要整数")
            return int(number)
        return number
    if item_type == "list":
        if isinstance(raw, list):
            return [str(line).strip() for line in raw if str(line).strip()]
        if isinstance(raw, str):
            return [line.strip() for line in raw.splitlines() if line.strip()]
        raise ValueError("该配置项需要字符串列表")
    text = "" if raw is None else str(raw)
    options = item_schema.get("options")
    if options and text not in {str(o) for o in options}:
        raise ValueError(f"取值必须是 {list(options)} 之一")
    return text
