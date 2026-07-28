"""分组类型解析：数据优先，但不得推翻空分组的显式声明。

`_ensure_tweet_group_template_key` 会按解析结果清空“另一侧”的订阅列表，
所以解析错误会直接造成订阅数据丢失或新建空分组被改判类型。
"""

from __future__ import annotations

from config.compat import (
    TWEET_GROUP_TEMPLATE_KEY_BLOGGER,
    TWEET_GROUP_TEMPLATE_KEY_FIELD,
    TWEET_GROUP_TEMPLATE_KEY_TAG,
    _ensure_tweet_group_template_key,
    resolve_tweet_group_template_key,
)


def test_empty_tag_group_keeps_explicit_type():
    group = {
        "group_id": "g1",
        "group_type": "tag",
        "watch_users": [],
        "watch_queries": [],
    }

    assert resolve_tweet_group_template_key(group) == TWEET_GROUP_TEMPLATE_KEY_TAG

    _ensure_tweet_group_template_key(group)
    assert group["group_type"] == TWEET_GROUP_TEMPLATE_KEY_TAG
    assert group[TWEET_GROUP_TEMPLATE_KEY_FIELD] == TWEET_GROUP_TEMPLATE_KEY_TAG


def test_empty_blogger_group_keeps_explicit_type():
    group = {
        "group_id": "g1",
        "group_type": "blogger",
        "watch_users": [],
        "watch_queries": [],
    }

    assert resolve_tweet_group_template_key(group) == TWEET_GROUP_TEMPLATE_KEY_BLOGGER


def test_explicit_tag_type_yields_to_existing_users():
    group = {
        "group_id": "g1",
        "group_type": "tag",
        "watch_users": ["nasa"],
        "watch_queries": [],
    }

    assert resolve_tweet_group_template_key(group) == TWEET_GROUP_TEMPLATE_KEY_BLOGGER

    _ensure_tweet_group_template_key(group)
    # 订阅数据不能因为标签这个标签被清空。
    assert group["watch_users"] == ["nasa"]


def test_explicit_blogger_type_yields_to_existing_queries():
    group = {
        "group_id": "g1",
        "group_type": "blogger",
        "watch_users": [],
        "watch_queries": ["#nasa"],
    }

    assert resolve_tweet_group_template_key(group) == TWEET_GROUP_TEMPLATE_KEY_TAG

    _ensure_tweet_group_template_key(group)
    assert group["watch_queries"] == ["#nasa"]


def test_mixed_group_keeps_both_lists():
    group = {
        "group_id": "g1",
        "group_type": "tag",
        "watch_users": ["nasa"],
        "watch_queries": ["#nasa"],
    }

    assert resolve_tweet_group_template_key(group) == TWEET_GROUP_TEMPLATE_KEY_TAG

    _ensure_tweet_group_template_key(group)
    assert group["watch_users"] == ["nasa"]
    assert group["watch_queries"] == ["#nasa"]


def test_missing_type_falls_back_to_template_key():
    group = {
        "group_id": "g1",
        TWEET_GROUP_TEMPLATE_KEY_FIELD: TWEET_GROUP_TEMPLATE_KEY_TAG,
        "watch_users": [],
        "watch_queries": [],
    }

    assert resolve_tweet_group_template_key(group) == TWEET_GROUP_TEMPLATE_KEY_TAG


def test_legacy_group_without_any_hint_is_blogger():
    group = {"group_id": "g1", "watch_users": [], "watch_queries": []}

    assert resolve_tweet_group_template_key(group) == TWEET_GROUP_TEMPLATE_KEY_BLOGGER
