from __future__ import annotations

import json
from pathlib import Path

from config.compat import (
    CONFIG_GROUP_BY_KEY,
    MIGRATABLE_CONFIG_KEYS,
    config_get,
    parse_config_bool,
)

ROOT = Path(__file__).resolve().parents[1]
TOOL_NAMES = (
    "nitter_fetch_user_tweets",
    "nitter_search_tweets",
    "nitter_get_twitter_trends",
    "nitter_list_plugin_state",
)


def test_llm_switch_schema_defaults_off_and_mapping():
    schema = json.loads((ROOT / "_conf_schema.json").read_text(encoding="utf-8"))
    setting = schema["basic"]["items"]["llm_tools_enabled"]
    assert setting["type"] == "bool"
    assert setting["default"] is False
    assert "Skill" in setting["hint"]
    assert CONFIG_GROUP_BY_KEY["llm_tools_enabled"] == "basic"
    assert "llm_tools_enabled" not in MIGRATABLE_CONFIG_KEYS
    assert config_get({}, "llm_tools_enabled", False) is False
    assert (
        config_get({"basic": {"llm_tools_enabled": True}}, "llm_tools_enabled", False)
        is True
    )
    assert (
        parse_config_bool(
            config_get(
                {"basic": {"llm_tools_enabled": False}}, "llm_tools_enabled", True
            )
        )
        is False
    )


def test_skill_frontmatter_tools_permissions_and_two_switches():
    text = (ROOT / "skills/nitter-tweets/SKILL.md").read_text(encoding="utf-8")
    parts = text.split("---", 2)
    assert len(parts) == 3 and not parts[0].strip()
    import yaml

    frontmatter = yaml.safe_load(parts[1])
    assert frontmatter["name"] == "nitter-tweets"
    assert frontmatter["description"] and len(frontmatter["description"]) > 30
    assert all(name in text for name in TOOL_NAMES)
    assert "llm_tools_enabled" in text and "Skill" in text
    assert "delivery=data" in text and "delivery=media" in text
    assert "refresh" in text and "管理员" in text
    assert "UMO" in text and "不可信" in text
    assert "nitter_get_tweet_status" in text


def test_release_documents_explain_dual_switch_and_four_tools():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    advanced = (ROOT / "docs/advanced.md").read_text(encoding="utf-8")
    architecture = (ROOT / "docs/project/architecture.md").read_text(encoding="utf-8")
    for text in (readme, advanced):
        assert "llm_tools_enabled" in text
        assert "nitter-tweets" in text
        assert "默认" in text
    assert all(name in advanced for name in TOOL_NAMES)
    assert "QueryService" in architecture and "LLM" in architecture


def test_llm_observability_trigger_is_labeled_without_private_source(monkeypatch):
    import logging
    from unittest.mock import MagicMock

    from shared.observability import safe_task_log

    logger = MagicMock()
    monkeypatch.setattr("shared.observability.logger", logger)
    safe_task_log(
        logging.INFO, "LLM 查询完成", trigger="llm_tool", tweet_count=3, sent_count=0
    )
    rendered = logger.log.call_args.args[1]
    assert "触发原因: LLM 工具" in rendered
    assert "3" in rendered
