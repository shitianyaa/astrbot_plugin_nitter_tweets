"""Configuration schema, migration, defaults, and subscription parsing contracts."""

from __future__ import annotations

import json
from pathlib import Path

import config.compat as compat
from config.compat import (
    LEGACY_CONFIG_MIGRATION_KEY,
    MAX_VIDEO_DURATION_GROUP_MIGRATION_KEY,
    TARGET_BLOCKED_USERS_LIST_MIGRATION_KEY,
    migrate_legacy_grouped_config,
)
from main import NitterTweetsPlugin
from media_support.client import NitterClient
from media_support.html_backend.service import HtmlBackendConfig
from media_support.nitter import NitterService
from scheduler.config import (
    GROUP_TYPE_BLOGGER,
    GROUP_TYPE_LIST,
    GROUP_TYPE_TAG,
    SchedulerConfigReader,
)
from shared.utils import DEFAULT_INSTANCES

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "_conf_schema.json"


def _migration_keys() -> set[str]:
    return {
        value
        for name, value in vars(compat).items()
        if name.endswith("MIGRATION_KEY") and isinstance(value, str)
    }


def test_every_migration_marker_is_declared_invisible():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    keys = _migration_keys()
    # Guard the guard: a renamed constant suffix would silently empty this set.
    assert len(keys) >= 7

    missing = sorted(key for key in keys if key not in schema)
    assert not missing, f"migration markers missing from _conf_schema.json: {missing}"

    visible = sorted(key for key in keys if not schema[key].get("invisible"))
    assert not visible, f"migration markers must be invisible in WebUI: {visible}"

    wrong_type = sorted(key for key in keys if schema[key].get("type") != "bool")
    assert not wrong_type, f"migration markers must be bool: {wrong_type}"


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


def test_code_defaults_are_empty_for_self_hosted_only():
    assert DEFAULT_INSTANCES == []
    assert HtmlBackendConfig().instances == []


def test_deleted_instance_fields_are_not_migrated_or_removed():
    config = {
        "basic": {
            "instances": ["http://nitter:8080"],
            "search_instances": ["http://old-search:8080"],
            "blogger_html_instances": ["http://old-user:8080"],
        }
    }
    before = json.loads(json.dumps(config))

    migrate_legacy_grouped_config(config)

    assert config["basic"] == before["basic"]


def test_schema_exposes_only_instances():
    schema = json.loads((ROOT / "_conf_schema.json").read_text(encoding="utf-8"))
    basic = schema["basic"]["items"]
    assert basic["instances"]["default"] == []
    for key in (
        "storage_backend",
        "search_instances",
        "blogger_html_instances",
        "concurrent_fetch_instances",
        "user_html_fallback",
    ):
        assert key not in basic
    for key in (
        "search_cooldown_seconds",
        "search_default_limit",
        "html_request_timeout",
    ):
        assert key not in basic
    assert "storage_backend" not in basic
    assert basic["filter_reposts_enabled"]["default"] is True
    assert basic["filter_reposts_enabled"]["description"] == "转发过滤总开关"


def test_removed_user_agent_config_is_persisted_by_startup_migration():
    class SavingConfig(dict):
        save_calls = 0

        def save_config(self):
            self.save_calls += 1

    config = SavingConfig(
        {
            "basic": {"user_agent": "legacy-rss", "request_timeout": 12.0},
            "media": {"media_user_agent": "legacy-media", "media_timeout": 25.0},
            "user_agent": "legacy-top-level-rss",
            "media_user_agent": "legacy-top-level-media",
            LEGACY_CONFIG_MIGRATION_KEY: True,
            MAX_VIDEO_DURATION_GROUP_MIGRATION_KEY: True,
            TARGET_BLOCKED_USERS_LIST_MIGRATION_KEY: True,
        }
    )

    assert migrate_legacy_grouped_config(config) is True
    assert config["basic"] == {"request_timeout": 12.0}
    assert config["media"] == {"media_timeout": 25.0}
    assert "user_agent" not in config
    assert "media_user_agent" not in config
    assert config.save_calls == 1


def test_unified_service_uses_instances_for_rss_and_html():
    service = NitterService(
        {
            "instances": ["http://nitter:8080"],
            "filter_reposts_enabled": "off",
            "brief_log_enabled": "no",
            "html_max_pages": "4",
        }
    )

    assert service.instances == ["http://nitter:8080"]
    assert service.html.config.instances == service.instances
    assert service.html.config.filter_reposts is False
    assert service.html.config.max_pages == 4
    assert service.html.log.brief is False


def test_legacy_instances_are_diagnostic_only():
    client = NitterClient(
        {
            "basic": {
                "instances": [],
                "search_instances": ["http://old-search:8080"],
                "blogger_html_instances": ["http://old-user:8080"],
            },
            "performance": {
                "concurrent_fetch_instances": ["http://old-concurrent:8080"],
            },
        }
    )

    assert client.instances == []
    assert client.ignored_legacy_instances == {
        "search_instances": ["http://old-search:8080"],
        "blogger_html_instances": ["http://old-user:8080"],
        "concurrent_fetch_instances": ["http://old-concurrent:8080"],
    }


def test_instance_log_label_omits_path_and_query():
    assert (
        NitterTweetsPlugin._instance_log_label("http://nitter:8080/private?q=1")
        == "http://nitter:8080"
    )


class _DummyConfig(dict):
    def get(self, key, default=None):
        return super().get(key, default)


def test_parse_watch_queries_hash_and_phrase():
    reader = SchedulerConfigReader(_DummyConfig(), context=None)
    info = reader.parse_watch_queries(
        [
            {"query": "#圣娅", "type": "tag"},
            "python programming",
            {"query": "圣娅", "type": "tag"},  # normalizes to same as first
        ]
    )
    assert len(info.queries) == 2
    assert info.queries[0].type == "tag"
    assert info.queries[0].query == "#圣娅"
    assert info.queries[0].account_key.startswith("q:")
    assert info.queries[1].type == "phrase"
    assert info.queries[1].query == "python programming"
    assert not info.queries[1].query.startswith("#")
    assert info.duplicates  # second tag form is duplicate after normalize
    assert info.changed  # objects / non-canonical strings need string heal


def test_parse_watch_queries_drops_object_object_literal():
    reader = SchedulerConfigReader(_DummyConfig(), context=None)
    info = reader.parse_watch_queries(["#ok", "[object Object]", {"foo": 1}])
    assert [q.query for q in info.queries] == ["#ok"]
    assert info.invalid_entries
    assert info.changed


def test_parse_schedule_group_tag_ignores_users():
    reader = SchedulerConfigReader(_DummyConfig({"tweet_groups": []}), context=None)
    group = reader.parse_schedule_group(
        {
            "name": "tags",
            "group_id": "tags1",
            "group_type": "tag",
            "watch_users": ["nasa"],
            "watch_queries": ["#foo", "bar"],
            "push_targets": [],
            "enabled": True,
        },
        index=1,
        log_invalid_targets=False,
    )
    assert group is not None
    assert group.group_type == GROUP_TYPE_TAG
    assert group.is_tag_group
    assert group.users == []
    assert [q.query for q in group.queries] == ["#foo", "bar"]
    assert group.account_keys[0].startswith("q:")


def test_group_repost_filter_defaults_true_and_accepts_explicit_false():
    reader = SchedulerConfigReader(_DummyConfig({"tweet_groups": []}), context=None)
    group_inputs = (
        (GROUP_TYPE_BLOGGER, {"watch_users": ["NASA"]}),
        (GROUP_TYPE_TAG, {"watch_queries": ["#foo"]}),
        (GROUP_TYPE_LIST, {"watch_lists": ["12345"]}),
    )

    for index, (group_type, subscriptions) in enumerate(group_inputs, 1):
        base = {
            "name": f"group-{index}",
            "group_id": f"group_{index}",
            "group_type": group_type,
            "push_targets": [],
            **subscriptions,
        }
        default_group = reader.parse_schedule_group(
            base,
            index=index,
            log_invalid_targets=False,
        )
        disabled_group = reader.parse_schedule_group(
            {**base, "filter_reposts_enabled": False},
            index=index,
            log_invalid_targets=False,
        )

        assert default_group is not None
        assert default_group.filter_reposts_enabled is True
        assert disabled_group is not None
        assert disabled_group.filter_reposts_enabled is False

    assert reader.global_group(log_invalid_targets=False).filter_reposts_enabled is True


def test_query_only_legacy_group_without_type_stays_tag():
    reader = SchedulerConfigReader(_DummyConfig({"tweet_groups": []}), context=None)
    group = reader.parse_schedule_group(
        {
            "name": "legacy tags",
            "group_id": "legacy_tags",
            "watch_queries": ["#foo"],
            "push_targets": [],
        },
        index=1,
        log_invalid_targets=False,
    )
    assert group is not None
    assert group.is_tag_group
    assert [item.query for item in group.queries] == ["#foo"]


def test_tag_template_key_is_respected_when_type_is_missing():
    reader = SchedulerConfigReader(_DummyConfig({"tweet_groups": []}), context=None)
    group = reader.parse_schedule_group(
        {
            "name": "empty tag",
            "group_id": "empty_tag",
            "__template_key": "tag",
            "watch_queries": [],
            "push_targets": [],
        },
        index=1,
        log_invalid_targets=False,
    )
    assert group is not None
    assert group.is_tag_group


def test_config_migration_preserves_query_only_group():
    cfg = _DummyConfig(
        {
            "tweet_groups": [
                {
                    "name": "legacy",
                    "group_id": "legacy",
                    "watch_queries": ["#foo"],
                    "push_targets": [],
                }
            ]
        }
    )
    SchedulerConfigReader(cfg, context=None)
    raw = cfg["tweet_groups"][0]
    assert raw["group_type"] == "tag"
    assert raw["__template_key"] == "tag"
    assert raw["watch_queries"] == ["#foo"]
