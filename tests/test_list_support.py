"""Twitter List config, HTML backend, WebUI, and status regressions."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import media_support.html_backend.pool as pool_module
from command_handlers.subscriptions import SubscriptionCommandMixin
from config import config_get
from media_support.host_score import HostScoreBook
from media_support.html_backend.pool import HtmlNitterPool, HtmlSearchResult, PoolConfig
from media_support.html_backend.service import HtmlBackendConfig, HtmlNitterService
from plugin_api.api import NitterWebAPI
from plugin_api.groups import WebUIGroupEditor
from scheduler.config import (
    GROUP_TYPE_BLOGGER,
    GROUP_TYPE_LIST,
    GROUP_TYPE_TAG,
    SchedulerConfigReader,
)
from scheduler.runner_status import SchedulerStatusMixin
from shared.utils import TweetItem

ROOT = Path(__file__).resolve().parents[1]


def _tweet(status_id: str, *, retweet: bool = False) -> TweetItem:
    return TweetItem(
        text=f"tweet {status_id}",
        link=f"https://x.com/user/status/{status_id}",
        published="",
        is_retweet=retweet,
    )


def _pool(*, filter_reposts: bool = True, max_pages: int = 2) -> HtmlNitterPool:
    pool = HtmlNitterPool.__new__(HtmlNitterPool)
    pool.config = PoolConfig(
        instances=["https://a.example", "https://b.example"],
        filter_reposts=filter_reposts,
        max_pages=max_pages,
    )
    pool.instances = list(pool.config.instances)
    pool.scores = HostScoreBook()
    pool.log = MagicMock()
    pool.session = MagicMock()
    pool.session.host_of = lambda base: base.removeprefix("https://")
    pool.limiter = MagicMock()
    pool.limiter.is_cooling.return_value = False
    pool.limiter.cooldown_remaining.return_value = 0.0
    return pool


class TestListConfigParsing:
    """Test List ID validation and config parsing."""

    def test_valid_list_ids(self):
        """Valid numeric List IDs (15-20 digits) are accepted."""
        reader = SchedulerConfigReader({}, None)
        result = reader.parse_watch_lists(
            [
                "1553232306718257152",  # 19 digits (valid CF test list)
                "123456789012345",  # 15 digits (min)
                "12345678901234567890",  # 20 digits (max)
                "18446744073709551615",  # uint64 max
            ]
        )
        assert len(result.list_ids) == 4
        assert result.list_ids == [
            "1553232306718257152",
            "123456789012345",
            "12345678901234567890",
            "18446744073709551615",
        ]
        assert result.raw_count == 4
        assert len(result.invalid_entries) == 0

    def test_invalid_list_ids(self):
        """Invalid List IDs (non-numeric, zero, too long, empty) are rejected."""
        reader = SchedulerConfigReader({}, None)
        result = reader.parse_watch_lists(
            [
                "abc123",  # non-numeric
                "0",  # zero is not a valid ID
                "18446744073709551616",  # uint64 overflow
                "123456789012345678901",  # too long (> 20 digits)
                "",  # empty
                "   ",  # whitespace only
            ]
        )
        assert len(result.list_ids) == 0
        assert result.raw_count == 4  # empty/whitespace not counted
        assert len(result.invalid_entries) == 4
        assert "abc123" in result.invalid_entries
        assert "0" in result.invalid_entries
        assert "18446744073709551616" in result.invalid_entries
        assert "123456789012345678901" in result.invalid_entries

    def test_duplicate_list_ids(self):
        """Duplicate List IDs are filtered and tracked."""
        reader = SchedulerConfigReader({}, None)
        result = reader.parse_watch_lists(
            [
                "1553232306718257152",
                "1553232306718257152",  # duplicate
                "123456789012345",
                "1553232306718257152",  # duplicate again
            ]
        )
        assert len(result.list_ids) == 2
        assert result.list_ids == ["1553232306718257152", "123456789012345"]
        assert len(result.duplicates) == 2
        assert result.changed is True

    def test_list_ids_from_string_split(self):
        """List IDs can be split from newline/comma-separated strings."""
        reader = SchedulerConfigReader({}, None)
        result = reader.parse_watch_lists(
            "1553232306718257152\n123456789012345,999999999999999"
        )
        assert len(result.list_ids) == 3
        assert "1553232306718257152" in result.list_ids
        assert "123456789012345" in result.list_ids
        assert "999999999999999" in result.list_ids

    def test_legacy_short_numeric_list_id_is_accepted(self):
        reader = SchedulerConfigReader({}, None)
        result = reader.parse_watch_lists(["12345"])
        assert result.list_ids == ["12345"]
        assert result.invalid_entries == []


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


def test_list_pagination_uses_cursor_and_global_repost_filter(monkeypatch):
    pool = _pool(filter_reposts=True, max_pages=2)
    pool._get_html = MagicMock(side_effect=[b"page-1", b"page-2"])
    pages = {
        "page-1": SimpleNamespace(
            tweets=[_tweet("10", retweet=True), _tweet("9")],
            next_cursor="cursor-2",
            raw_item_count=2,
        ),
        "page-2": SimpleNamespace(
            tweets=[_tweet("9"), _tweet("8")],
            next_cursor="",
            raw_item_count=2,
        ),
    }
    monkeypatch.setattr(
        pool_module,
        "parse_timeline_html",
        lambda body, _base, source="", **_kw: pages[body],
    )

    tweets = pool._paginate_list("https://a.example", "12345", 20)

    assert [tweet.status_id for tweet in tweets] == ["9", "8"]
    assert tweets.raw_item_count == 4
    assert tweets.retweet_filtered == 1
    assert tweets.anchor_status_ids == ["10", "9"]
    assert pool._get_html.call_args_list[0].args[1] == "/i/lists/12345"
    assert "cursor=cursor-2" in pool._get_html.call_args_list[1].args[1]

    pool._get_html = MagicMock(side_effect=[b"page-1", b"page-2"])
    unfiltered = pool._paginate_list(
        "https://a.example",
        "12345",
        20,
        filter_reposts=False,
    )
    assert [tweet.status_id for tweet in unfiltered] == ["10", "9", "8"]
    assert unfiltered.retweet_filtered == 0


def test_list_pagination_scans_past_limit_until_watermark(monkeypatch):
    pool = _pool(filter_reposts=False, max_pages=3)
    pool._get_html = MagicMock(side_effect=[b"page-1", b"page-2"])
    pages = {
        "page-1": SimpleNamespace(
            tweets=[_tweet("10"), _tweet("9")],
            next_cursor="cursor-2",
            raw_item_count=2,
        ),
        "page-2": SimpleNamespace(
            tweets=[_tweet("8"), _tweet("7"), _tweet("6")],
            next_cursor="cursor-3",
            raw_item_count=3,
        ),
    }
    monkeypatch.setattr(
        pool_module,
        "parse_timeline_html",
        lambda body, _base, source="", **_kw: pages[body],
    )

    tweets = pool._paginate_list(
        "https://a.example",
        "12345",
        2,
        anchor_ids=["7"],
    )

    assert [tweet.status_id for tweet in tweets] == ["10", "9", "8", "7"]
    assert tweets.scan_complete is True
    assert tweets.anchor_status_ids == ["10", "9"]
    assert pool._get_html.call_count == 2


def test_list_pagination_marks_scan_incomplete_at_page_limit(monkeypatch):
    pool = _pool(filter_reposts=False, max_pages=2)
    pool._get_html = MagicMock(side_effect=[b"page-1", b"page-2"])
    pages = {
        "page-1": SimpleNamespace(
            tweets=[_tweet("10"), _tweet("9")],
            next_cursor="cursor-2",
            raw_item_count=2,
        ),
        "page-2": SimpleNamespace(
            tweets=[_tweet("8"), _tweet("7")],
            next_cursor="cursor-3",
            raw_item_count=2,
        ),
    }
    monkeypatch.setattr(
        pool_module,
        "parse_timeline_html",
        lambda body, _base, source="", **_kw: pages[body],
    )

    tweets = pool._paginate_list(
        "https://a.example",
        "12345",
        2,
        anchor_ids=["1"],
    )

    assert [tweet.status_id for tweet in tweets] == ["10", "9", "8", "7"]
    assert tweets.scan_complete is False
    assert tweets.anchor_status_ids == ["10", "9"]
    assert tweets.limited(2).scan_complete is False
    assert tweets.limited(2).anchor_status_ids == ["10", "9"]


def test_search_pagination_scans_past_limit_until_watermark(monkeypatch):
    pool = _pool(filter_reposts=False, max_pages=3)
    pool._get_html = MagicMock(side_effect=[b"page-1", b"page-2"])
    pages = {
        "page-1": SimpleNamespace(
            tweets=[_tweet("10"), _tweet("9")],
            next_cursor="cursor-2",
            raw_item_count=2,
        ),
        "page-2": SimpleNamespace(
            tweets=[_tweet("8"), _tweet("7")],
            next_cursor="cursor-3",
            raw_item_count=2,
        ),
    }
    monkeypatch.setattr(
        pool_module,
        "parse_timeline_html",
        lambda body, _base, source="", **_kw: pages[body],
    )

    tweets = pool._paginate_search(
        "https://a.example",
        "#foo",
        2,
        kind="tag",
        anchor_ids=["7"],
    )

    assert [tweet.status_id for tweet in tweets] == ["10", "9", "8", "7"]
    assert tweets.scan_complete is True
    assert tweets.anchor_status_ids == ["10", "9"]
    assert pool._get_html.call_count == 2


def test_search_pagination_marks_scan_incomplete_at_page_limit(monkeypatch):
    pool = _pool(filter_reposts=False, max_pages=2)
    pool._get_html = MagicMock(side_effect=[b"page-1", b"page-2"])
    pages = {
        "page-1": SimpleNamespace(
            tweets=[_tweet("10"), _tweet("9")],
            next_cursor="cursor-2",
            raw_item_count=2,
        ),
        "page-2": SimpleNamespace(
            tweets=[_tweet("8"), _tweet("7")],
            next_cursor="cursor-3",
            raw_item_count=2,
        ),
    }
    monkeypatch.setattr(
        pool_module,
        "parse_timeline_html",
        lambda body, _base, source="", **_kw: pages[body],
    )

    tweets = pool._paginate_search(
        "https://a.example",
        "#foo",
        2,
        kind="tag",
        anchor_ids=["1"],
    )

    assert [tweet.status_id for tweet in tweets] == ["10", "9", "8", "7"]
    assert tweets.scan_complete is False
    assert tweets.anchor_status_ids == ["10", "9"]


def test_list_empty_host_rotates_to_later_hit():
    pool = _pool()
    tried = []

    def paginate(base, list_id, limit):
        del list_id, limit
        tried.append(base)
        if base.endswith("a.example"):
            return HtmlSearchResult([], raw_item_count=0)
        return HtmlSearchResult([_tweet("42")], raw_item_count=1)

    pool._paginate_list = paginate
    base, tweets = pool.fetch_list("12345", 20)

    assert base == "https://b.example"
    assert [tweet.status_id for tweet in tweets] == ["42"]
    assert tried == ["https://a.example", "https://b.example"]
    assert tweets.host_attempts == ["a.example=空结果", "b.example=成功"]


def test_list_pool_inherits_global_repost_filter():
    enabled = HtmlNitterService(HtmlBackendConfig(instances=[], filter_reposts=True))
    disabled = HtmlNitterService(HtmlBackendConfig(instances=[], filter_reposts=False))

    assert enabled.pool.config.filter_reposts is True
    assert disabled.pool.config.filter_reposts is False


class _Config(dict):
    def save_config(self):
        return None


def test_webui_creates_and_updates_list_group():
    config = _Config({"tweet_groups": []})
    plugin = MagicMock()
    plugin.config = config
    plugin.scheduler.config_reader = SchedulerConfigReader(config, context=None)
    editor = WebUIGroupEditor(plugin)

    created = editor.create_group({"name": "列表", "group_type": "list"})
    assert created["success"] is True
    group_id = created["group_id"]
    assert config_get(config, "tweet_groups", [])[0]["filter_reposts_enabled"] is True
    updated = editor.update_group(
        {
            "group_id": group_id,
            "name": "列表",
            "watch_lists": ["12345", "2081623084780671084"],
            "filter_reposts_enabled": False,
        }
    )

    assert updated["success"] is True
    saved = config_get(config, "tweet_groups", [])[0]
    assert saved["group_type"] == "list"
    assert saved["__template_key"] == "list"
    assert saved["watch_lists"] == ["12345", "2081623084780671084"]
    assert saved["filter_reposts_enabled"] is False

    reloaded = SchedulerConfigReader(config, context=None).schedule_groups()[0]
    payload = NitterWebAPI(plugin)._serialize_group(reloaded)
    assert payload["group_type"] == "list"
    assert payload["watch_lists"] == ["12345", "2081623084780671084"]
    assert payload["subscription_label"] == "2 个 List"
    assert payload["filter_reposts_enabled"] is False
    assert payload["global_filter_reposts_enabled"] is True
    assert payload["effective_filter_reposts_enabled"] is False


def test_webui_list_update_rejects_invalid_and_duplicate_ids():
    config = _Config({"tweet_groups": []})
    plugin = MagicMock()
    plugin.config = config
    plugin.scheduler.config_reader = SchedulerConfigReader(config, context=None)
    editor = WebUIGroupEditor(plugin)
    group_id = editor.create_group({"name": "列表", "group_type": "list"})["group_id"]

    invalid = editor.update_group(
        {
            "group_id": group_id,
            "name": "列表",
            "watch_lists": ["not-a-list"],
        }
    )
    duplicate = editor.update_group(
        {
            "group_id": group_id,
            "name": "列表",
            "watch_lists": ["12345", "12345"],
        }
    )

    assert invalid["success"] is False
    assert "List ID 无效" in invalid["error"]
    assert duplicate["success"] is False
    assert "List ID 重复" in duplicate["error"]


def test_dashboard_source_contains_list_editor_and_probe_all_payload():
    source = (ROOT / "pages" / "dashboard" / "app.js").read_text(encoding="utf-8")
    style = (ROOT / "pages" / "dashboard" / "style.css").read_text(encoding="utf-8")
    index = (ROOT / "pages" / "dashboard" / "index.html").read_text(encoding="utf-8")

    assert 'value: "list"' in source
    assert 'name: "createGroupType"' in source
    assert 'type: "radio"' in source
    assert 'attrs: { id: "createGroupType" }' not in source
    assert 'label: "List 分组"' in source
    assert "不建议创建或启用标签分组和 List 分组" in source
    assert source.count("text: PRIVATE_QQ_GROUP_WARNING") >= 2
    assert ".group-type-options" in style
    assert ".group-type-radio:checked + .group-type-option-body" in style
    assert "function addWatchList(groupId)" in source
    assert "watch_lists: [...(group.watch_lists || [])]" in source
    assert "filter_reposts_enabled: group.filter_reposts_enabled !== false" in source
    assert '"filter_reposts_enabled"' in source
    assert "全局转发过滤总开关" in source
    assert "List ID 必须是 1-20 位正整数" in source
    assert "List ID 已存在" in source
    assert "list_id: els.mirrorListId.value.trim()" in source
    assert 'rss_user: "用户 RSS"' in source
    assert "localStorage" not in source
    assert '<script src="/api/plugin/page/bridge-sdk.js"></script>' in index


def test_status_and_export_render_list_group():
    config = {
        "tweet_groups": [
            {
                "name": "列表",
                "group_id": "lists1",
                "group_type": "list",
                "watch_lists": ["12345"],
                "push_targets": [],
            }
        ]
    }
    group = SchedulerConfigReader(config, None).schedule_groups()[0]
    status = SchedulerStatusMixin.__new__(SchedulerStatusMixin)
    subscriptions = SubscriptionCommandMixin.__new__(SubscriptionCommandMixin)
    lines = []
    status._append_group_status(lines, group)
    exported = subscriptions._format_export_group_line(group)

    rendered = "\n".join(lines)
    assert "类型 列表" in rendered
    assert "List ID: 12345" in rendered
    assert "转发过滤: 开启（全局 开，分组 开）" in rendered
    assert "(lists1, List, 1 个): 12345" in exported
