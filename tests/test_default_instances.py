# -*- coding: utf-8 -*-
"""Shipped defaults: RSS=net, search=tie+poast+kareem; no blogger HTML list."""
from __future__ import annotations

import json
import asyncio
from pathlib import Path
from types import SimpleNamespace

from command_handlers.manual import ManualCommandMixin
from media_support.client import NitterClient
from media_support.html_backend.service import (
    DEFAULT_HTML_INSTANCES,
    DEFAULT_SEARCH_INSTANCES,
    DEFAULT_TIEKOETTER,
    HtmlBackendConfig,
)
from main import NitterTweetsPlugin
from shared.utils import DEFAULT_INSTANCES
from config.compat import migrate_legacy_grouped_config

ROOT = Path(__file__).resolve().parents[1]


def test_code_defaults_rss_net_search_tie_poast_kareem():
    """Code defaults: RSS nitter.net, search tiekoetter+poast+kareem."""
    assert DEFAULT_INSTANCES == ["https://nitter.net"]
    assert DEFAULT_TIEKOETTER == "https://nitter.tiekoetter.com"
    assert DEFAULT_SEARCH_INSTANCES == [
        "https://nitter.tiekoetter.com",
        "https://nitter.poast.org",
        "https://nitter.kareem.one",
    ]
    assert DEFAULT_HTML_INSTANCES == DEFAULT_SEARCH_INSTANCES
    blob = " ".join(DEFAULT_SEARCH_INSTANCES)
    assert "poast" in blob and "kareem" in blob and "tiekoetter" in blob
    assert "nitter.net" not in blob  # RSS only, not for search
    cfg = HtmlBackendConfig()
    assert cfg.user_html_fallback is False
    assert cfg.blogger_html_instances == []
    assert cfg.search_instances == DEFAULT_SEARCH_INSTANCES


def test_schema_no_blogger_html_instances_key():
    schema = json.loads((ROOT / "_conf_schema.json").read_text(encoding="utf-8"))
    basic = schema["basic"]["items"]
    assert "blogger_html_instances" not in basic
    assert basic["instances"]["default"] == ["https://nitter.net"]
    assert basic["search_instances"]["default"] == [
        "https://nitter.tiekoetter.com",
        "https://nitter.poast.org",
        "https://nitter.kareem.one",
    ]
    assert basic["user_html_fallback"]["default"] is False
    assert basic["user_html_fallback"].get("invisible") is True
    joined = " ".join(basic["search_instances"]["default"])
    assert "poast" in joined and "kareem" in joined and "tiekoetter" in joined
    marker = schema["_search_instances_default_v17_migrated"]
    assert marker["type"] == "bool"
    assert marker["default"] is False
    assert marker.get("invisible") is True


def test_html_backend_builder_parses_legacy_string_values_safely():
    plugin = NitterTweetsPlugin.__new__(NitterTweetsPlugin)
    plugin.config = {
        "user_html_fallback": "false",
        "search_enabled": "0",
        "filter_reposts_enabled": "off",
        "brief_log_enabled": "no",
        "html_max_pages": "not-a-number",
    }

    backend = plugin._build_html_backend()

    assert backend.config.user_html_fallback is False
    assert backend.config.search_enabled is False
    assert backend.config.filter_reposts is False
    assert backend.config.html_max_pages == 1
    assert backend.log.brief is False


def test_rss_client_and_manual_fallback_parse_string_false_values():
    client = NitterClient(
        {
            "filter_reposts_enabled": "false",
            "brief_log_enabled": "off",
        }
    )
    assert client.filter_reposts_enabled is False
    assert client.brief_log_enabled is False

    class Host(ManualCommandMixin):
        config = {"user_html_fallback": "false"}
        html_backend = SimpleNamespace(
            fetch_user=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("disabled fallback must not fetch")
            )
        )

    assert asyncio.run(Host()._fetch_user_with_html_fallback("nasa", 5)) == ("", [])


def test_migration_keeps_current_default_list_unchanged():
    """Migration no longer replaces the current default (now all three mirrors)."""
    config = {
        "basic": {
            "blogger_html_instances": ["https://retired.example"],
            "search_instances": [
                "https://nitter.tiekoetter.com",
                "https://nitter.poast.org",
                "https://nitter.kareem.one",
            ]
        }
    }
    migrate_legacy_grouped_config(config)
    # Current default matches legacy, so no replacement happens
    assert config["basic"]["search_instances"] == [
        "https://nitter.tiekoetter.com",
        "https://nitter.poast.org",
        "https://nitter.kareem.one",
    ]
    assert "blogger_html_instances" not in config["basic"]

    custom = {
        "basic": {"search_instances": ["https://self-hosted.example"]}
    }
    migrate_legacy_grouped_config(custom)
    assert custom["basic"]["search_instances"] == [
        "https://self-hosted.example"
    ]
