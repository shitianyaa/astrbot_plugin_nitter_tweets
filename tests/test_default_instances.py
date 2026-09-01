"""Self-hosted instance defaults and deleted-field behavior."""

from __future__ import annotations

import json
from pathlib import Path

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
from shared.utils import DEFAULT_INSTANCES

ROOT = Path(__file__).resolve().parents[1]


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
