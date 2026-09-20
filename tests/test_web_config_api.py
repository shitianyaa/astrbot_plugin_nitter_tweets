"""『web/config/schema』序列化测试:分组过滤、值兜底、排除规则。"""

from __future__ import annotations

import asyncio
import json
import logging
from types import SimpleNamespace

import pytest

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


def test_schema_skips_invisible_items():
    config = _FakeConfig({"push": {"target_blocked_users": ["12345"]}})
    result = asyncio.run(_Host(config).build_config_schema())
    push = next(g for g in result["groups"] if g["key"] == "push")
    assert "target_blocked_users" not in {i["key"] for i in push["items"]}


def test_update_coerces_and_writes_grouped_location():
    config = _FakeConfig()
    host = _Host(config)
    result = asyncio.run(
        host.update_config_item({"key": "default_limit", "value": "15"})
    )
    assert result["success"] is True
    assert result["value"] == 15
    assert config["basic"]["default_limit"] == 15
    assert config.saved == 1


def test_batch_update_is_atomic_and_saves_once():
    config = _FakeConfig()
    host = _Host(config)
    result = asyncio.run(
        host.update_config_items(
            {
                "changes": {
                    "default_limit": "15",
                    "send_image_attachments": False,
                }
            }
        )
    )
    assert result["success"] is True
    assert result["count"] == 2
    assert config["basic"]["default_limit"] == 15
    assert config["media"]["send_image_attachments"] is False
    assert config.saved == 1

    invalid_config = _FakeConfig()
    invalid_host = _Host(invalid_config)
    invalid = asyncio.run(
        invalid_host.update_config_items(
            {"changes": {"default_limit": "15", "request_timeout": "bad"}}
        )
    )
    assert invalid["success"] is False
    assert invalid_config == {}
    assert invalid_config.saved == 0


def test_batch_update_restores_config_when_save_fails():
    class _FailingConfig(_FakeConfig):
        def save_config(self):
            self.saved += 1
            raise OSError("save failed")

    original_basic = {"default_limit": 7, "request_timeout": 12}
    config = _FailingConfig({"basic": original_basic})
    host = _Host(config)

    with pytest.raises(OSError, match="save failed"):
        asyncio.run(
            host.update_config_items(
                {
                    "changes": {
                        "default_limit": "15",
                        "send_image_attachments": False,
                    }
                }
            )
        )

    assert config == {"basic": original_basic}
    assert config["basic"] is original_basic
    assert config.saved == 1


def test_save_config_reloads_exact_current_plugin_once():
    config = _FakeConfig()
    calls = []

    class _Manager:
        async def reload(self, plugin_name):
            calls.append(plugin_name)
            return True, None

    plugin = SimpleNamespace()
    metadata = SimpleNamespace(name="astrbot_plugin_nitter_tweets", star_cls=plugin)
    plugin.context = SimpleNamespace(
        _star_manager=_Manager(), get_all_stars=lambda: [metadata]
    )
    host = _Host(config)
    host.plugin = plugin

    result = asyncio.run(
        host.save_config_and_reload({"changes": {"default_limit": "9"}})
    )

    assert result["success"] is True
    assert result["reloaded"] is True
    assert config.saved == 1
    assert calls == ["astrbot_plugin_nitter_tweets"]


def test_save_config_does_not_reload_when_validation_fails():
    config = _FakeConfig()
    calls = []

    class _Manager:
        async def reload(self, plugin_name):
            calls.append(plugin_name)
            return True, None

    plugin = SimpleNamespace()
    metadata = SimpleNamespace(name="astrbot_plugin_nitter_tweets", star_cls=plugin)
    plugin.context = SimpleNamespace(
        _star_manager=_Manager(), get_all_stars=lambda: [metadata]
    )
    host = _Host(config)
    host.plugin = plugin

    result = asyncio.run(
        host.save_config_and_reload({"changes": {"request_timeout": "bad"}})
    )

    assert result["success"] is False
    assert config.saved == 0
    assert calls == []


def test_save_config_reports_saved_when_reload_fails(monkeypatch):
    config = _FakeConfig()
    log_events = []
    monkeypatch.setattr(
        "plugin_api.api_config.safe_log",
        lambda level, event_name, **fields: log_events.append(
            (level, event_name, fields)
        ),
    )

    class _Manager:
        async def reload(self, plugin_name):
            return False, "reload failed"

    plugin = SimpleNamespace()
    metadata = SimpleNamespace(name="astrbot_plugin_nitter_tweets", star_cls=plugin)
    plugin.context = SimpleNamespace(
        _star_manager=_Manager(), get_all_stars=lambda: [metadata]
    )
    host = _Host(config)
    host.plugin = plugin

    result = asyncio.run(
        host.save_config_and_reload({"changes": {"default_limit": "11"}})
    )

    assert result["success"] is True
    assert result["saved"] is True
    assert result["reloaded"] is False
    assert config.saved == 1
    assert log_events == [
        (
            logging.WARNING,
            "config_reload_failed",
            {"status": "saved", "error": "RuntimeError: reload failed"},
        )
    ]


def test_update_rejects_bad_number_and_option():
    config = _FakeConfig()
    host = _Host(config)
    bad_number = asyncio.run(
        host.update_config_item({"key": "request_timeout", "value": "abc"})
    )
    assert bad_number["success"] is False
    bad_option = asyncio.run(
        host.update_config_item({"key": "media_quality", "value": "ultra"})
    )
    assert bad_option["success"] is False
    assert config.saved == 0


def test_update_bool_and_list():
    config = _FakeConfig()
    host = _Host(config)
    ok_bool = asyncio.run(
        host.update_config_item({"key": "filter_reposts_enabled", "value": False})
    )
    assert ok_bool["success"] is True and ok_bool["value"] is False
    ok_list = asyncio.run(
        host.update_config_item(
            {"key": "instances", "value": [" http://a:8080 ", "", "http://b:8080"]}
        )
    )
    assert ok_list["value"] == ["http://a:8080", "http://b:8080"]


def test_update_rejects_non_finite_number():
    config = _FakeConfig()
    host = _Host(config)
    result = asyncio.run(
        host.update_config_item({"key": "request_timeout", "value": "inf"})
    )
    assert result["success"] is False
    assert config.saved == 0


def test_update_rejects_unknown_and_template_list():
    config = _FakeConfig()
    host = _Host(config)
    unknown = asyncio.run(host.update_config_item({"key": "nope", "value": 1}))
    assert unknown["success"] is False
    template = asyncio.run(
        host.update_config_item({"key": "tweet_groups", "value": []})
    )
    assert template["success"] is False
    assert "分组订阅管理" in template["error"]
    assert config.saved == 0


class _FakeProviderType:
    value = "chat_completion"


class _Provider:
    def __init__(self, pid, name, model="", ptype="openai_compatible"):
        self._meta = SimpleNamespace(
            id=pid, name=name, model=model, provider_type=ptype
        )

    def meta(self):
        return self._meta


def test_schema_items_carry_default():
    config = _FakeConfig()
    result = asyncio.run(_Host(config).build_config_schema())
    basic = next(g for g in result["groups"] if g["key"] == "basic")
    by_key = {i["key"]: i for i in basic["items"]}
    assert by_key["default_limit"]["default"] == _schema_default(
        "basic", "default_limit"
    )


def test_list_providers_handles_list_and_dict_shapes():
    providers_obj = SimpleNamespace(
        provider_manager=SimpleNamespace(
            get_all_providers=lambda: [
                _Provider(
                    "p1", "OpenAI 主力", model="gpt-4o", ptype=_FakeProviderType()
                ),
                _Provider("p1", "重复应去重"),
                _Provider("p2", "Gemini", ptype="gemini"),
            ]
        )
    )
    host = _Host(_FakeConfig())
    host.plugin = SimpleNamespace(context=providers_obj)
    result = asyncio.run(host.list_providers())
    ids = [p["id"] for p in result["providers"]]
    assert ids == ["p1", "p2"]
    assert result["providers"][0]["label"] == "OpenAI 主力 [p1]"
    assert result["providers"][0]["type"] == "chat_completion"

    dict_shape = SimpleNamespace(
        provider_manager=SimpleNamespace(
            get_all_providers=lambda: {"dk": SimpleNamespace(id="dk", name="字典形")}
        )
    )
    host2 = _Host(_FakeConfig())
    host2.plugin = SimpleNamespace(context=dict_shape)
    result2 = asyncio.run(host2.list_providers())
    assert [p["id"] for p in result2["providers"]] == ["dk"]
