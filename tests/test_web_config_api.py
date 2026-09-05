"""『web/config/schema』序列化测试:分组过滤、值兜底、排除规则。"""

from __future__ import annotations

import asyncio
import json

from plugin_api.api_config import WebAPIConfigMixin


class _FakeConfig(dict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.saved = 0

    def save_config(self):
        self.saved += 1


class _Host(WebAPIConfigMixin):
    def __init__(self, config):
        self.config = config

    def _ok(self, **kwargs):
        return {"success": True, **kwargs}

    def _error(self, message):
        return {"success": False, "error": message}

    def _data_text(self, data, key):
        return str(data.get(key) or "")


def _schema_default(group: str, key: str):
    schema = json.load(open("_conf_schema.json", encoding="utf-8"))
    return schema[group]["items"][key].get("default")


def test_schema_renders_groups_only_with_values():
    config = _FakeConfig({"basic": {"default_limit": 7}})
    result = asyncio.run(_Host(config).build_config_schema())
    assert result["success"] is True
    group_keys = [g["key"] for g in result["groups"]]
    assert group_keys == [
        "basic",
        "media",
        "ai_translation",
        "schedule",
        "push",
        "logging",
        "performance",
    ]
    basic = result["groups"][0]
    by_key = {i["key"]: i for i in basic["items"]}
    # 值:分组值优先于 schema default
    assert by_key["default_limit"]["value"] == 7
    # 未配置项回落到 schema default
    assert by_key["request_timeout"]["value"] == _schema_default(
        "basic", "request_timeout"
    )
    # 分组内不允许出现顶层 legacy 键
    assert "storage_backend" not in by_key


def test_schema_marks_template_list_not_editable():
    config = _FakeConfig()
    result = asyncio.run(_Host(config).build_config_schema())
    push = next(g for g in result["groups"] if g["key"] == "push")
    tg = next(i for i in push["items"] if i["key"] == "tweet_groups")
    assert tg["editable"] is False
    assert tg["type"] == "template_list"


def test_schema_value_falls_back_to_flat_then_default():
    config = _FakeConfig({"check_interval_minutes": 99})
    result = asyncio.run(_Host(config).build_config_schema())
    schedule = next(g for g in result["groups"] if g["key"] == "schedule")
    by_key = {i["key"]: i for i in schedule["items"]}
    assert by_key["check_interval_minutes"]["value"] == 99
