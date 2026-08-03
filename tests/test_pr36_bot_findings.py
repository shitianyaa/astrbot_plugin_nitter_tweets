"""Regression probes for PR #36 CodeRabbit findings (P0–P2).

Write tests first: failures prove the bug still exists; then fix production code.
"""

from __future__ import annotations

import asyncio
import inspect
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from config.compat import config_get
from plugin_api.api import NitterWebAPI
from plugin_api.groups import WebUIGroupEditor
from rendering.tweets import TweetMessageRenderer
from scheduler.config import SchedulerConfigReader
from scheduler.models import PendingTweetBatch, ScheduledCheckResult
from shared.utils import TweetItem, TweetMedia

ROOT = Path(__file__).resolve().parents[1]


def _tweet(
    text: str = "hello world",
    link: str = "https://x.com/nasa/status/1234567890",
    translation: str = "",
) -> TweetItem:
    return TweetItem(
        text=text, link=link, published="2026-01-01", translation=translation
    )


def _history_record(
    *, record_id: int, target: str, pushed_at: int, status: str, error: str = ""
):
    return SimpleNamespace(
        id=record_id,
        group_id="default",
        username="nasa",
        status_id="123",
        original_link="https://x.com/nasa/status/123",
        target_umo=target,
        source="scheduled",
        instance="https://nitter.example",
        pushed_at=pushed_at,
        tweet=_tweet(),
        delivery_status=status,
        delivery_error=error,
    )


def test_history_group_uses_latest_delivery_status_per_target():
    records = [
        _history_record(
            record_id=3,
            target="telegram:FriendMessage:1",
            pushed_at=200,
            status="success",
        ),
        _history_record(
            record_id=2,
            target="telegram:FriendMessage:1",
            pushed_at=100,
            status="partial_failed",
            error="old media failure",
        ),
    ]

    grouped = NitterWebAPI._group_history_records(records, {}, {})

    assert grouped[0]["delivery_status"] == "success"
    assert grouped[0]["delivery_error"] == ""


def test_history_group_keeps_partial_status_when_error_text_is_empty():
    records = [
        _history_record(
            record_id=1,
            target="lark:GroupMessage:1",
            pushed_at=100,
            status="partial_failed",
            error="",
        )
    ]

    grouped = NitterWebAPI._group_history_records(records, {}, {})

    assert grouped[0]["delivery_status"] == "partial_failed"
    assert grouped[0]["delivery_error"] == ""


def test_history_group_exposes_failed_status_and_error():
    record = _history_record(
        record_id=1,
        target="qq:GroupMessage:1",
        pushed_at=100,
        status="failed",
        error="消息内容违规",
    )

    grouped = NitterWebAPI._group_history_records([record], {}, {})

    assert grouped[0]["delivery_status"] == "failed"
    assert grouped[0]["delivery_error"] == "消息内容违规"


def test_history_group_exposes_tag_type_for_query_display():
    record = _history_record(
        record_id=1,
        target="telegram:FriendMessage:1",
        pushed_at=100,
        status="success",
    )
    record.username = "q:#Space"

    grouped = NitterWebAPI._group_history_records(
        [record],
        {},
        {"default": SimpleNamespace(targets=[], group_type="tag")},
    )

    assert grouped[0]["group_type"] == "tag"


def test_dashboard_history_uses_generic_partial_and_query_labels():
    src = (ROOT / "pages" / "dashboard" / "app.js").read_text(encoding="utf-8")

    assert 'text: "部分送达"' in src
    assert 'className: "badge badge-danger"' in src
    assert 'text: "发送失败"' in src
    assert 'text: "订阅源"' in src
    assert 'text: "账号/查询"' not in src
    assert "function historyAccountLabel(row)" in src
    assert 'text: "媒体失败"' not in src


def test_dashboard_disables_delete_for_legacy_default_group_alias():
    src = (ROOT / "pages" / "dashboard" / "app.js").read_text(encoding="utf-8")

    assert "function isDefaultGroupId(value)" in src
    assert 'groupId === "global"' in src
    assert "isDefaultGroupId(group.group_id)" in src


# ---------------------------------------------------------------------------
# P0-1: WebUIGroupEditor._bool extra default arg
# ---------------------------------------------------------------------------


def test_p0_bool_single_arg_and_update_call_sites():
    """_bool is one-arg; update_group must not pass a second default."""
    sig = inspect.signature(WebUIGroupEditor._bool)
    assert list(sig.parameters) == ["value"]
    assert WebUIGroupEditor._bool("true") is True
    assert WebUIGroupEditor._bool("false") is False
    assert WebUIGroupEditor._bool(1) is True

    src = (ROOT / "plugin_api" / "groups.py").read_text(encoding="utf-8")
    # no self._bool(..., True/False) two-arg form
    assert not re.search(
        r"self\._bool\(\s*data\.get\([\s\S]*?\),\s*(True|False)\s*\)",
        src,
    )


def test_p0_update_group_omit_and_hide_does_not_typeerror():
    """Saving omit_status_url / hide_original via WebUI must not crash."""

    class FakeConfig(dict):
        def save_config(self) -> None:
            return None

    config = FakeConfig(
        {
            "tweet_groups": [
                {
                    "name": "默认分组",
                    "group_id": "default",
                    "enabled": True,
                    "group_type": "blogger",
                    "watch_users": ["nasa"],
                    "watch_queries": [],
                    "push_targets": ["aiocqhttp:GroupMessage:1"],
                    "interval_check_enabled": True,
                    "daily_check_times": [],
                    "filter_plain_text_enabled": False,
                    "media_only_enabled": False,
                    "omit_status_url": True,
                    "hide_original_when_translated": False,
                }
            ]
        }
    )
    plugin = MagicMock()
    plugin.config = config
    plugin.scheduler = MagicMock()
    plugin.scheduler.config_reader.config_list = lambda raw: (
        list(raw) if isinstance(raw, list) else ([] if raw in (None, "") else [raw])
    )
    plugin.scheduler.config_reader.parse_daily_times = lambda values: [
        (int(v.split(":")[0]), int(v.split(":")[1])) for v in values
    ]

    editor = WebUIGroupEditor(plugin)
    result = editor.update_group(
        {
            "group_id": "default",
            "name": "默认分组",
            "omit_status_url": False,
            "hide_original_when_translated": True,
        }
    )
    assert result.get("success") is True, result
    from config.compat import config_get

    groups = config_get(config, "tweet_groups", [])
    assert groups, config
    saved = groups[0]
    assert saved["omit_status_url"] is False
    assert saved["hide_original_when_translated"] is True


def test_webui_update_finds_explicit_legacy_global_group_id():
    class FakeConfig(dict):
        def save_config(self) -> None:
            return None

    config = FakeConfig(
        {
            "tweet_groups": [
                {
                    "name": "默认分组",
                    "group_id": "global",
                    "enabled": True,
                    "group_type": "blogger",
                    "watch_users": ["nasa"],
                    "watch_queries": [],
                    "push_targets": [],
                    "interval_check_enabled": True,
                    "daily_check_times": [],
                }
            ]
        }
    )
    plugin = MagicMock()
    plugin.config = config
    plugin.scheduler.config_reader.config_list = lambda raw: (
        list(raw) if isinstance(raw, list) else ([] if raw in (None, "") else [raw])
    )
    plugin.scheduler.config_reader.parse_daily_times = lambda _values: []

    result = WebUIGroupEditor(plugin).update_group(
        {"group_id": "global", "name": "默认分组", "enabled": False}
    )

    assert result.get("success") is True, result
    saved = config_get(config, "tweet_groups", [])[0]
    assert saved["group_id"] == "global"
    assert saved["enabled"] is False


def test_webui_update_by_alias_preserves_stable_group_id():
    class FakeConfig(dict):
        def save_config(self) -> None:
            return None

    config = FakeConfig(
        {
            "tweet_groups": [
                {
                    "name": "Current name",
                    "group_id": "stable_id",
                    "aliases": ["old_alias"],
                    "group_type": "blogger",
                    "watch_users": ["nasa"],
                    "push_targets": [],
                }
            ]
        }
    )
    plugin = MagicMock()
    plugin.config = config
    plugin.scheduler.config_reader = SchedulerConfigReader(config, context=None)

    result = WebUIGroupEditor(plugin).update_group(
        {
            "group_id": "old_alias",
            "name": "Updated name",
            "enabled": False,
        }
    )

    assert result == {"success": True, "group_id": "stable_id"}
    saved = config_get(config, "tweet_groups", [])[0]
    assert saved["group_id"] == "stable_id"
    assert saved["name"] == "Updated name"


def test_webui_delete_by_alias_returns_stable_group_id():
    class FakeConfig(dict):
        def save_config(self) -> None:
            return None

    config = FakeConfig(
        {
            "tweet_groups": [
                {
                    "name": "Disposable group",
                    "group_id": "stable_id",
                    "aliases": ["old_alias"],
                    "group_type": "blogger",
                    "watch_users": ["nasa"],
                    "push_targets": [],
                }
            ]
        }
    )
    plugin = MagicMock()
    plugin.config = config
    plugin.scheduler.config_reader = SchedulerConfigReader(config, context=None)

    result = WebUIGroupEditor(plugin).delete_group(
        {"group_id": "old_alias", "force": True, "confirm": "DELETE"}
    )

    assert result["success"] is True
    assert result["group_id"] == "stable_id"
    assert config_get(config, "tweet_groups", []) == []


def test_webui_default_group_alias_cannot_bypass_delete_protection():
    class FakeConfig(dict):
        def save_config(self) -> None:
            return None

    config = FakeConfig(
        {
            "tweet_groups": [
                {
                    "name": "Default group",
                    "group_id": "default",
                    "aliases": ["legacy_default_alias"],
                    "group_type": "blogger",
                    "watch_users": ["nasa"],
                    "push_targets": [],
                }
            ]
        }
    )
    plugin = MagicMock()
    plugin.config = config
    plugin.scheduler.config_reader = SchedulerConfigReader(config, context=None)

    result = WebUIGroupEditor(plugin).delete_group(
        {
            "group_id": "legacy_default_alias",
            "force": True,
            "confirm": "DELETE",
        }
    )

    assert result == {"success": False, "error": "默认分组不能在 WebUI 中删除"}
    assert config_get(config, "tweet_groups", [])[0]["group_id"] == "default"


def test_dashboard_update_preserves_inactive_mixed_legacy_watch_lists():
    class FakeConfig(dict):
        def save_config(self) -> None:
            return None

    config = FakeConfig(
        {
            "_default_group_config_migrated": True,
            "push": {
                "tweet_groups": [
                    {
                        "name": "mixed blogger",
                        "group_id": "mixed_blogger",
                        "group_type": "blogger",
                        "watch_users": ["nasa"],
                        "watch_queries": ["#space"],
                        "push_targets": [],
                    },
                    {
                        "name": "mixed tag",
                        "group_id": "mixed_tag",
                        "group_type": "tag",
                        "watch_users": ["legacy_user"],
                        "watch_queries": ["#space"],
                        "push_targets": [],
                    },
                ]
            },
        }
    )
    plugin = MagicMock()
    plugin.config = config
    plugin.scheduler.config_reader = SchedulerConfigReader(config, context=None)
    editor = WebUIGroupEditor(plugin)

    blogger_result = editor.update_group(
        {
            "group_id": "mixed_blogger",
            "name": "mixed blogger",
            "enabled": False,
        }
    )
    tag_result = editor.update_group(
        {
            "group_id": "mixed_tag",
            "name": "mixed tag",
            "enabled": False,
        }
    )

    assert blogger_result.get("success") is True, blogger_result
    assert tag_result.get("success") is True, tag_result
    groups = {
        group["group_id"]: group for group in config_get(config, "tweet_groups", [])
    }
    assert groups["mixed_blogger"]["watch_queries"] == ["#space"]
    assert groups["mixed_tag"]["watch_users"] == ["legacy_user"]


def test_dashboard_group_serialization_preserves_hide_original_toggle():
    config = {
        "tweet_groups": [
            {
                "name": "默认分组",
                "group_id": "default",
                "group_type": "blogger",
                "watch_users": ["nasa"],
                "push_targets": ["aiocqhttp:GroupMessage:1"],
                "hide_original_when_translated": True,
            }
        ]
    }
    group = SchedulerConfigReader(config, context=None).schedule_groups()[0]
    plugin = MagicMock()
    plugin.config = config

    payload = NitterWebAPI(plugin)._serialize_group(group)

    assert payload["hide_original_when_translated"] is True


def test_cache_result_serializes_active_lease_skips():
    payload = NitterWebAPI._serialize_cache_result(SimpleNamespace(skipped_active=2))

    assert payload["skipped_active"] == 2


def test_dashboard_query_editor_preserves_explicit_phrase_type():
    config = {"tweet_groups": []}
    plugin = MagicMock()
    plugin.config = config
    plugin.scheduler.config_reader = SchedulerConfigReader(config, context=None)
    editor = WebUIGroupEditor(plugin)

    stored = editor._normalized_watch_queries([{"query": "#literal", "type": "phrase"}])

    assert stored == ["nitter-query:phrase:#literal"]


# ---------------------------------------------------------------------------
# P0-2: format_video_attachment_text missing @staticmethod
# ---------------------------------------------------------------------------


def test_p0_format_video_is_staticmethod_like_image():
    video = inspect.getattr_static(TweetMessageRenderer, "format_video_attachment_text")
    image = inspect.getattr_static(TweetMessageRenderer, "format_image_attachment_text")
    assert isinstance(image, staticmethod)
    assert isinstance(video, staticmethod), (
        "format_video_attachment_text must be @staticmethod; "
        "instance call currently binds self into index/tweet slots"
    )


def test_p0_instance_format_video_and_build_video_node_work():
    renderer = TweetMessageRenderer()
    tweet = _tweet()
    text = renderer.format_video_attachment_text(1, "nasa", tweet)
    assert "视频" in text or "GIF" in text
    assert "nasa" in text.lower() or "@" in text

    media = TweetMedia(kind="video", url="https://example.com/v.mp4", path=Path("."))
    components = renderer.build_video_node_components(1, "nasa", tweet, media)
    assert components  # must not raise TypeError/AttributeError


# ---------------------------------------------------------------------------
# P0-3: configuration.md top garbage
# ---------------------------------------------------------------------------


def test_p0_configuration_md_title_not_corrupted():
    path = ROOT / "docs" / "project" / "configuration.md"
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    assert lines[0].startswith("#")
    # known corruption from PR #36 bot review
    joined = "\n".join(lines[:8])
    assert "（默认 true，去推文链接）" not in joined
    assert not re.search(r"^（默认", joined, re.MULTILINE)


# ---------------------------------------------------------------------------
# P1-1/2: attachment formatters must receive omit/hide/link_style
# ---------------------------------------------------------------------------


def test_p1_build_video_forwards_omit_status_url_false():
    renderer = TweetMessageRenderer()
    tweet = _tweet()
    media = TweetMedia(kind="video", url="https://example.com/v.mp4", path=Path("."))
    components = renderer.build_video_node_components(
        1,
        "nasa",
        tweet,
        media,
        omit_status_url=False,
        hide_original_when_translated=False,
        link_style="plain",
    )
    plain_parts = [
        getattr(c, "text", None) or str(c)
        for c in components
        if getattr(c, "text", None) or "Plain" in type(c).__name__
    ]
    blob = "\n".join(str(p) for p in plain_parts if p)
    # When omit is False, status/original link should appear in attachment caption
    assert "1234567890" in blob or "x.com/nasa" in blob or "原文" in blob, blob


def test_p1_build_image_forwards_omit_status_url_false():
    renderer = TweetMessageRenderer()
    tweet = _tweet()
    media = TweetMedia(kind="image", url="https://example.com/a.jpg", path=Path("."))
    components = renderer.build_image_node_components(
        1,
        "nasa",
        tweet,
        media,
        omit_status_url=False,
    )
    plain_parts = [
        getattr(c, "text", None) for c in components if getattr(c, "text", None)
    ]
    blob = "\n".join(str(p) for p in plain_parts if p)
    assert "x.com/nasa" in blob or "1234567890" in blob, blob


def test_p1_onebot_video_call_sites_pass_omit_kwargs():
    """Static check: onebot/node builders must not only pass media_only."""
    src = (ROOT / "rendering" / "tweets.py").read_text(encoding="utf-8")
    # Find call blocks for format_video_attachment_text that are not the def
    for m in re.finditer(
        r"format_video_attachment_text\(\s*([^)]+)\)",
        src,
    ):
        args = m.group(1)
        if "index: int" in args:  # definition
            continue
        assert "omit_status_url=" in args, (
            f"call missing omit_status_url= near:\n{args}"
        )
        assert "hide_original_when_translated=" in args
        assert "link_style=" in args


# ---------------------------------------------------------------------------
# P1-3: Lark fallback drops render kwargs
# ---------------------------------------------------------------------------


def test_p1_lark_fallback_forwards_render_kwargs():
    src = (ROOT / "delivery" / "lark.py").read_text(encoding="utf-8")
    # The no-client fallback block
    idx = src.find("_send_default_direct_to_umo")
    assert idx > 0
    # find first call used as fallback when client is None
    # look at block around "改用通用发送"
    anchor = src.find("改用通用发送")
    assert anchor > 0
    block = src[anchor : anchor + 500]
    assert "omit_status_url=" in block, block
    assert "hide_original_when_translated=" in block, block
    assert "link_style=" in block, block


# ---------------------------------------------------------------------------
# P1-5: history replay missing omit/hide
# ---------------------------------------------------------------------------


def test_p1_replay_send_passes_omit_and_hide():
    src = (ROOT / "scheduler" / "runner.py").read_text(encoding="utf-8")
    # Heuristic: send_to_umo_with_outcome near 重新推送 / replay history
    # Find "replay" delivery_status block and require omit in nearby kwargs
    # Broader: any send_to_umo_with_outcome in runner that only passes
    # tweet_start_index without omit is a smell for the replay path.
    assert "async def" in src
    # Locate the replay send call that uses record.username
    m = re.search(
        r"send_to_umo_with_outcome\(\s*"
        r"self\.context,\s*"
        r"target,\s*"
        r"record\.username,[\s\S]{0,1200}?\)",
        src,
    )
    assert m, "could not locate history replay send_to_umo_with_outcome"
    call = m.group(0)
    assert "omit_status_url=" in call, call
    assert "hide_original_when_translated=" in call, call


# ---------------------------------------------------------------------------
# P2-1: search failure must not echo raw exception to user
# ---------------------------------------------------------------------------


def test_p2_manual_search_error_message_does_not_embed_exc():
    src = (ROOT / "command_handlers" / "manual.py").read_text(encoding="utf-8")
    # Allow logging with {exc}, forbid plain_result with {exc}
    bad = re.findall(
        r"plain_result\(\s*f?[\"']搜索失败[^\"']*\{exc\}",
        src,
    )
    assert not bad, f"user-facing search errors leak exc: {bad}"


# ---------------------------------------------------------------------------
# P2-2: no_watch_queries Chinese label
# ---------------------------------------------------------------------------


def test_p2_no_watch_queries_has_chinese_label():
    result = ScheduledCheckResult(
        reason="manual",
        skipped_reason="no_watch_queries",
        group_id="tag1",
        group_name="标签组",
    )
    msg = result.format_message()
    assert "no_watch_queries" not in msg
    assert "watch_queries" in msg or "搜索订阅" in msg or "标签" in msg


# ---------------------------------------------------------------------------
# P2-3: multi-batch cleanup best-effort
# ---------------------------------------------------------------------------


def test_p2_cleanup_batch_media_many_continues_after_one_failure():
    from scheduler.runner import NitterTweetScheduler

    scheduler = NitterTweetScheduler.__new__(NitterTweetScheduler)
    cleaned: list[str] = []

    async def cleanup_one(batch: PendingTweetBatch) -> None:
        if batch.username == "bad":
            raise RuntimeError("boom")
        cleaned.append(batch.username)
        batch.media_cleaned = True

    scheduler._cleanup_batch_media = cleanup_one  # type: ignore[method-assign]

    batches = [
        PendingTweetBatch(
            username="bad",
            instance="i",
            tweets=[],
            fetched_ids=[],
            seen_ids=[],
        ),
        PendingTweetBatch(
            username="good",
            instance="i",
            tweets=[],
            fetched_ids=[],
            seen_ids=[],
        ),
    ]

    async def run() -> None:
        await scheduler._cleanup_batch_media_many(batches)

    # Must not raise; second batch still cleaned
    asyncio.run(run())
    assert "good" in cleaned


# ---------------------------------------------------------------------------
# P0 helpers: video staticmethod callable on class
# ---------------------------------------------------------------------------


def test_p0_class_level_format_video_works():
    text = TweetMessageRenderer.format_video_attachment_text(1, "nasa", _tweet())
    assert isinstance(text, str) and text
