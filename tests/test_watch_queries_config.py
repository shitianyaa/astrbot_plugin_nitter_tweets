from __future__ import annotations

from scheduler.config import GROUP_TYPE_TAG, SchedulerConfigReader


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
