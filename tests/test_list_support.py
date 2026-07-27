# -*- coding: utf-8 -*-
"""Test Twitter List support (group_type=list, fetch_list, config parsing)."""

import pytest

from scheduler.config import (
    GROUP_TYPE_LIST,
    GROUP_TYPE_BLOGGER,
    GROUP_TYPE_TAG,
    SchedulerConfigReader,
    WatchListsInfo,
)


class TestListConfigParsing:
    """Test List ID validation and config parsing."""

    def test_valid_list_ids(self):
        """Valid numeric List IDs (15-20 digits) are accepted."""
        reader = SchedulerConfigReader({}, None)
        result = reader.parse_watch_lists([
            "1553232306718257152",  # 19 digits (valid CF test list)
            "123456789012345",      # 15 digits (min)
            "12345678901234567890", # 20 digits (max)
        ])
        assert len(result.list_ids) == 3
        assert result.list_ids == [
            "1553232306718257152",
            "123456789012345",
            "12345678901234567890",
        ]
        assert result.raw_count == 3
        assert len(result.invalid_entries) == 0

    def test_invalid_list_ids(self):
        """Invalid List IDs (non-numeric, too short/long, empty) are rejected."""
        reader = SchedulerConfigReader({}, None)
        result = reader.parse_watch_lists([
            "abc123",              # non-numeric
            "12345",               # too short (< 15 digits)
            "123456789012345678901",  # too long (> 20 digits)
            "",                    # empty
            "   ",                 # whitespace only
        ])
        assert len(result.list_ids) == 0
        assert result.raw_count == 3  # empty/whitespace not counted
        assert len(result.invalid_entries) == 3
        assert "abc123" in result.invalid_entries
        assert "12345" in result.invalid_entries
        assert "123456789012345678901" in result.invalid_entries

    def test_duplicate_list_ids(self):
        """Duplicate List IDs are filtered and tracked."""
        reader = SchedulerConfigReader({}, None)
        result = reader.parse_watch_lists([
            "1553232306718257152",
            "1553232306718257152",  # duplicate
            "123456789012345",
            "1553232306718257152",  # duplicate again
        ])
        assert len(result.list_ids) == 2
        assert result.list_ids == ["1553232306718257152", "123456789012345"]
        assert len(result.duplicates) == 2
        assert result.changed is True

    def test_list_ids_from_string_split(self):
        """List IDs can be split from newline/comma-separated strings."""
        reader = SchedulerConfigReader({}, None)
        result = reader.parse_watch_lists("1553232306718257152\n123456789012345,999999999999999")
        assert len(result.list_ids) == 3
        assert "1553232306718257152" in result.list_ids
        assert "123456789012345" in result.list_ids
        assert "999999999999999" in result.list_ids


class TestListGroupTypeResolution:
    """Test group_type=list resolution and filtering."""

    def test_explicit_list_type(self):
        """Explicit group_type=list is recognized."""
        reader = SchedulerConfigReader({}, None)
        resolved = reader.parse_group_type(
            raw_type="list",
            raw_users=None,
            raw_queries=None,
            raw_lists=["1553232306718257152"],
        )
        assert resolved == GROUP_TYPE_LIST

    def test_list_alias_types(self):
        """'lists' is recognized as GROUP_TYPE_LIST."""
        reader = SchedulerConfigReader({}, None)
        resolved = reader.parse_group_type(
            raw_type="lists",
            raw_users=None,
            raw_queries=None,
            raw_lists=["1553232306718257152"],
        )
        assert resolved == GROUP_TYPE_LIST

    def test_list_inferred_from_watch_lists_only(self):
        """watch_lists alone (no users/queries) infers list type."""
        reader = SchedulerConfigReader({}, None)
        resolved = reader.parse_group_type(
            raw_type=None,
            raw_users=[],
            raw_queries=[],
            raw_lists=["1553232306718257152"],
        )
        assert resolved == GROUP_TYPE_LIST

    def test_list_template_key(self):
        """__template_key=list sets list type."""
        reader = SchedulerConfigReader({}, None)
        resolved = reader.parse_group_type(
            raw_type=None,
            raw_users=None,
            raw_queries=None,
            raw_lists=None,
            raw_template_key="list",
        )
        assert resolved == GROUP_TYPE_LIST


class TestListGroupFiltering:
    """Test that list groups only contain watch_lists (no users/queries)."""

    def test_list_group_drops_users_and_queries(self):
        """A list group ignores watch_users and watch_queries."""
        config = {
            "tweet_groups": [
                {
                    "name": "List Group",
                    "group_type": "list",
                    "watch_users": ["NASA", "SpaceX"],
                    "watch_queries": ["#space"],
                    "watch_lists": ["1553232306718257152"],
                    "push_targets": [],
                }
            ]
        }
        reader = SchedulerConfigReader(config, None)
        groups = reader.schedule_groups(log_invalid_targets=False)
        assert len(groups) == 1
        group = groups[0]
        assert group.group_type == GROUP_TYPE_LIST
        assert len(group.list_ids) == 1
        assert group.list_ids[0] == "1553232306718257152"
        # Users and queries should be dropped
        assert len(group.users) == 0
        assert len(group.queries) == 0

    def test_blogger_group_drops_lists(self):
        """A blogger group ignores watch_lists."""
        config = {
            "tweet_groups": [
                {
                    "name": "Blogger Group",
                    "group_type": "blogger",
                    "watch_users": ["NASA"],
                    "watch_lists": ["1553232306718257152"],
                    "push_targets": [],
                }
            ]
        }
        reader = SchedulerConfigReader(config, None)
        groups = reader.schedule_groups(log_invalid_targets=False)
        assert len(groups) == 1
        group = groups[0]
        assert group.group_type == GROUP_TYPE_BLOGGER
        assert len(group.users) == 1
        assert group.users[0] == "NASA"
        assert len(group.list_ids) == 0

    def test_tag_group_drops_lists(self):
        """A tag group ignores watch_lists."""
        config = {
            "tweet_groups": [
                {
                    "name": "Tag Group",
                    "group_type": "tag",
                    "watch_queries": ["#space"],
                    "watch_lists": ["1553232306718257152"],
                    "push_targets": [],
                }
            ]
        }
        reader = SchedulerConfigReader(config, None)
        groups = reader.schedule_groups(log_invalid_targets=False)
        assert len(groups) == 1
        group = groups[0]
        assert group.group_type == GROUP_TYPE_TAG
        assert len(group.queries) == 1
        assert len(group.list_ids) == 0


class TestListAccountKeys:
    """Test account_keys generation for list groups (seen storage)."""

    def test_list_account_keys(self):
        """List groups return account_keys as 'list:{id}'."""
        config = {
            "tweet_groups": [
                {
                    "name": "Test List",
                    "group_type": "list",
                    "watch_lists": ["1553232306718257152", "123456789012345"],
                    "push_targets": [],
                }
            ]
        }
        reader = SchedulerConfigReader(config, None)
        groups = reader.schedule_groups(log_invalid_targets=False)
        assert len(groups) == 1
        group = groups[0]
        keys = group.account_keys
        assert len(keys) == 2
        assert "list:1553232306718257152" in keys
        assert "list:123456789012345" in keys
