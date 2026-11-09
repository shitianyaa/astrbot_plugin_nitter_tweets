"""Twitter List config, HTML backend, WebUI, and status regressions."""

import json
import re
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

# Dashboard JS 已按分节拆为多文件（classic script 按序加载，见 index.html）；
# 源码字符串断言统一读「按加载顺序拼接」的全文，行为与拆分前的单文件等价。
DASHBOARD_JS_FILES = (
    "core.js",
    "ui.js",
    "data.js",
    "groups.js",
    "views.js",
    "config.js",
    "wizard.js",
    "boot.js",
)


def _dashboard_js_source() -> str:
    return "\n".join(
        (ROOT / "pages" / "dashboard" / name).read_text(encoding="utf-8")
        for name in DASHBOARD_JS_FILES
    )


def test_dashboard_script_tags_match_load_order():
    """index.html 的 <script src> 顺序必须与 DASHBOARD_JS_FILES 一致。

    classic script 的顶层 let/const/function 跨文件共享全局词法环境，
    顺序错乱（boot 提前、core 殿后）在运行时才炸，这里把加载顺序钉死。
    """
    index = (ROOT / "pages" / "dashboard" / "index.html").read_text(encoding="utf-8")
    srcs = re.findall(r'<script src="\./([\w-]+\.js)"></script>', index)
    assert srcs == list(DASHBOARD_JS_FILES)


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
    assert tweets.host_attempts == ["#1=空结果", "#2=成功"]


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


def test_dashboard_sandbox_does_not_access_local_storage():
    source = _dashboard_js_source()
    index = (ROOT / "pages/dashboard/index.html").read_text(encoding="utf-8")
    # AstrBot Pages uses an opaque origin; accessing localStorage breaks startup.
    for text in (source, index):
        assert not re.search(
            r"localStorage\s*[.\[]|window\s*\[\s*[\"']localStorage[\"']\s*\]", text
        )
    assert '<script src="/api/plugin/page/bridge-sdk.js"></script>' in index


def test_dashboard_guards_busy_actions_and_unsaved_edits():
    source = _dashboard_js_source()
    assert "if (state.actionBusy) return null;" in source
    assert "sheetHasDraftChanges()" in source
    assert "if (state.selectedGroupId === gid) {" in source
    assert "if (sheetOpen) closeSheet({ force: true });" in source
    # Orphan cleanup runs inside an action; nesting withAction would skip it.
    assert (
        'await withAction(() => renderHistoryOrphans(), "检测完成", { reload: false });'
        in source
    )


def test_dashboard_entity_removal_does_not_use_stale_indices():
    source = _dashboard_js_source()
    assert "next.splice(idx, 1);" not in source
    assert "current.filter(x => entityValue(x) !== val)" in source
    assert "current.filter(x => x !== t)" in source


def test_dashboard_preserves_dirty_groups_and_pending_history_filters():
    source = _dashboard_js_source()
    assert (
        'if (view === "groups" && state.groups.some(g => isGroupDirty(g.group_id))) return;'
        in source
    )
    assert (
        "if (state.actionBusy) { state.pendingHistoryApply = true; return; }" in source
    )
    for control in ("historyLimitSelect", "historyGroupSelect"):
        assert (
            f"els.{control}?.onChange?.(() => {{ applyHistoryFilters(); }});" in source
        )


def test_dashboard_log_polling_guards_against_duplicate_appends():
    """日志轮询必须防重复：接口慢于轮询间隔时，两次请求拿到同一批 seq 各自
    concat，同一批日志会在终端里出现两遍（实测 8 条里有 4 条重复）。"""
    source = _dashboard_js_source()

    # 在途守卫 + reset 让位
    assert "let logsInFlight = null;" in source
    assert "let logsResetPending = false;" in source
    assert "} else if (logsInFlight || logsResetPending) {" in source
    # 增量去重和会话重启已由 test_dashboard_log_polling 执行验证；
    # 这里保留乱序游标和旧服务端没有 session_id 时的二级兜底。
    assert (
        "state.logsAfterSeq = Math.max(state.logsAfterSeq, ...fresh.map(e => e.seq));"
        in source
    )
    assert "res.next_seq && res.next_seq <= state.logsAfterSeq" in source
    # 跳过的一轮不能算成功，否则「请求比 3s 间隔还慢 + 一直失败」时失败计数
    # 会在 0/1 之间振荡，永远到不了停止阀值
    assert 'generation === logsGeneration && result !== "skipped"' in source


def test_dashboard_overview_recent_pushes_use_own_snapshot():
    """总览「最新推送记录」必须独立取数，不得切历史页快照。

    历史页快照带分组/状态/作者筛选与分页 offset；总览若复用它，用户翻页或加
    筛选后总览仍显示旧行，点开时 openHistoryDetail 在 history.records 里查不到
    该 id 便静默 return——表现为「点击没反应，刷新一下才好」。
    """
    source = _dashboard_js_source()

    # 独立数据通道与独立取数函数
    assert 'recent: ["overview"]' in source
    assert "recentPushes: []" in source
    assert "const RECENT_PUSH_LIMIT = 5;" in source
    assert "async function refreshRecentPushes()" in source
    # 取数不带任何筛选，固定 offset=0（全局最新）
    recent_fn = source.split("async function refreshRecentPushes()", 1)[1].split(
        "\n}", 1
    )[0]
    assert "limit: RECENT_PUSH_LIMIT" in recent_fn
    assert "offset: 0" in recent_fn
    assert "historyGroupId" not in recent_fn
    assert "historyStatus" not in recent_fn
    assert "historyOffset" not in recent_fn
    # 总览渲染不再切历史页快照
    assert "const records = state.recentPushes;" in source
    assert "state.history?.records || []).slice(0, 5)" not in source
    # 详情抽屉两个快照都查：总览点开的行不在 history.records 里
    detail_fn = source.split("function openHistoryDetail(recordId)", 1)[1].split(
        "\n}", 1
    )[0]
    assert "state.history.records" in detail_fn
    assert "state.recentPushes.find" in detail_fn
    # 三处刷新入口都要带上最近推送
    assert "reloadGroupState(), refreshHistoryData(), refreshRecentPushes()" in source
    assert "Promise.all([reloadOverviewData(), refreshRecentPushes()])" in source
    assert (
        "reloadGroupState(), reloadConfigState(), refreshHistoryData(), refreshRecentPushes()"
        in source
    )


def test_dashboard_history_redacts_instance_labels():
    source = _dashboard_js_source()
    assert "function redactInstanceLabel(raw)" in source
    assert "redactInstanceLabel(r.instance)" in source


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


def test_attention_nav_covers_every_overview_attention_key():
    """总览「需要关注」的每个 key 都要有跳转目标（自带 group_id 的除外）。

    回归背景：ATTENTION_NAV 曾只覆盖 _overview_attention_items 自己产出的 9 个
    key，漏掉它 extend 进来的 _overview_group_diagnostics 聚合条目——那些行
    渲染成不可点，而 CHANGELOG 写的是「均可点击跳转」。
    """
    import ast

    tree = ast.parse(
        (ROOT / "plugin_api" / "api_overview.py").read_text(encoding="utf-8")
    )
    backend_keys = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        if node.name not in {
            "_overview_attention_items",
            "_overview_group_diagnostics",
        }:
            continue
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Dict):
                continue
            names = {k.value for k in sub.keys if isinstance(k, ast.Constant)}
            consts = {
                k.value: v.value
                for k, v in zip(sub.keys, sub.values)
                if isinstance(k, ast.Constant) and isinstance(v, ast.Constant)
            }
            # 带 group_id 的条目由 jumpAttention 直达抽屉，不需要进导航表
            if "key" in consts and "group_id" not in names:
                backend_keys.add(consts["key"])

    nav_block = re.search(
        r"const ATTENTION_NAV = \{(.*?)\n\};", _dashboard_js_source(), re.S
    ).group(1)
    nav_keys = set(re.findall(r"^\s*(\w+):\s*\{", nav_block, re.M))

    assert backend_keys, "没解析到后端 attention key，断言本身失效了"
    assert backend_keys <= nav_keys, f"缺少跳转目标：{sorted(backend_keys - nav_keys)}"

    # view=config 的目标必须是 _conf_schema.json 里真实存在的顶层分组键，
    # 否则 typo（如 schedule 打成 schedul）只会静默跳到第一组
    schema_keys = set(
        json.loads((ROOT / "_conf_schema.json").read_text(encoding="utf-8"))
    )
    config_targets = re.findall(
        r'^\s*(\w+):\s*\{ view: "config", group: "(\w+)" \}', nav_block, re.M
    )
    assert config_targets, "没解析到 config 类跳转目标，断言本身失效了"
    for key, group in config_targets:
        assert group in schema_keys, f"{key} 指向不存在的配置分组 {group}"


def test_with_action_drains_pending_history_filter_replay():
    """在途期间被丢弃的历史筛选必须由收尾补跑。

    withAction 与 probeMirror 都自管 actionBusy，两条路径都要收口，
    否则筛选变更被静默吞掉、还会留到下一次动作才意外触发。
    """
    source = _dashboard_js_source()

    assert "function drainPendingHistoryApply() {" in source
    # 只数调用次数会漏掉「调用点不在 finally 里」这种错位。先按函数切块再
    # 看块内的 finally：跨函数匹配的正则会在首个候选失败后向后吞，把
    # probeMirror 的 finally 当成 withAction 的，反而比计数更弱。
    bodies = {
        m.group(1): m.group(2)
        for m in re.finditer(
            r"async function (\w+)\b(.*?)(?=\nasync function |\Z)", source, re.S
        )
    }
    for fn in ("withAction", "probeMirror"):
        body = bodies.get(fn) or ""
        assert "finally {" in body, f"{fn} 没有 finally"
        finally_body = body.split("finally {", 1)[1].split("}", 1)[0]
        assert "drainPendingHistoryApply();" in finally_body, (
            f"{fn} 的 finally 没补跑历史筛选"
        )
