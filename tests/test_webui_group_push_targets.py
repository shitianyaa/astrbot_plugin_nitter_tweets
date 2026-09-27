"""WebUI 分组保存对无效推送目标 / 无效订阅源的回写契约。

前端 draft 会把有效条目与后端隔离的无效条目合并后整体提交；
`update_group` 不做 UMO 校验、原样落盘：
- 提交里包含无效条目 = 显式保留（原文不动，去重/去空仍生效）；
- 提交里缺失无效条目 = 显式删除。

回归背景：旧前端 draft 只含有效列表，保存任意字段都会把配置里的
无效条目静默清除，且这些条目在 WebUI 无任何查看/删除出口。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from config.compat import config_get
from config.subscriptions import set_import_group_users
from plugin_api.groups import WebUIGroupEditor
from scheduler.config import SchedulerConfigReader

ROOT = Path(__file__).resolve().parents[1]


class _FakeConfig(dict):
    def save_config(self) -> None:
        return None


def _make_editor(config: _FakeConfig) -> WebUIGroupEditor:
    plugin = MagicMock()
    plugin.config = config
    plugin.scheduler = MagicMock()
    plugin.scheduler.config_reader.config_list = lambda raw: (
        list(raw) if isinstance(raw, list) else ([] if raw in (None, "") else [raw])
    )
    plugin.scheduler.config_reader.parse_daily_times = lambda values: [
        (int(v.split(":")[0]), int(v.split(":")[1])) for v in values
    ]
    return WebUIGroupEditor(plugin)


def _group_raw(config: _FakeConfig) -> dict:
    # update_group 经 config_set 写入配置分组层（schedule.tweet_groups），
    # 用 config_get 读取与生产一致的解析顺序
    groups = config_get(config, "tweet_groups")
    return groups[0]


def test_update_group_preserves_invalid_targets_verbatim():
    config = _FakeConfig(
        {
            "tweet_groups": [
                {
                    "name": "默认分组",
                    "group_id": "default",
                    "group_type": "blogger",
                    "watch_users": ["nasa"],
                    "push_targets": [
                        "aiocqhttp:GroupMessage:1",
                        "not-a-target",
                    ],
                }
            ]
        }
    )
    editor = _make_editor(config)
    result = editor.update_group(
        {
            "group_id": "default",
            "name": "默认分组",
            "push_targets": [
                "aiocqhttp:GroupMessage:1",
                "not-a-target",
                "aiocqhttp:GroupMessage:2",
            ],
        }
    )
    assert result["success"] is True
    stored = _group_raw(config)["push_targets"]
    # 无效条目按原文保留，新有效条目照常写入
    assert "not-a-target" in stored
    assert "aiocqhttp:GroupMessage:2" in stored
    assert stored.count("not-a-target") == 1


def test_update_group_drops_invalid_target_when_absent():
    config = _FakeConfig(
        {
            "tweet_groups": [
                {
                    "name": "默认分组",
                    "group_id": "default",
                    "group_type": "blogger",
                    "watch_users": ["nasa"],
                    "push_targets": [
                        "aiocqhttp:GroupMessage:1",
                        "not-a-target",
                    ],
                }
            ]
        }
    )
    editor = _make_editor(config)
    result = editor.update_group(
        {
            "group_id": "default",
            "name": "默认分组",
            "push_targets": ["aiocqhttp:GroupMessage:1"],
        }
    )
    assert result["success"] is True
    stored = _group_raw(config)["push_targets"]
    assert stored == ["aiocqhttp:GroupMessage:1"]


def test_update_group_preserves_and_drops_invalid_watch_users():
    config = _FakeConfig(
        {
            "tweet_groups": [
                {
                    "name": "默认分组",
                    "group_id": "default",
                    "group_type": "blogger",
                    "watch_users": ["nasa", "!!bad!!"],
                    "push_targets": ["aiocqhttp:GroupMessage:1"],
                }
            ]
        }
    )
    editor = _make_editor(config)
    result = editor.update_group(
        {
            "group_id": "default",
            "name": "默认分组",
            "watch_users": ["nasa", "!!bad!!", "spacex"],
        }
    )
    assert result["success"] is True
    assert _group_raw(config)["watch_users"] == ["nasa", "!!bad!!", "spacex"]

    result = editor.update_group(
        {"group_id": "default", "name": "默认分组", "watch_users": ["nasa"]}
    )
    assert result["success"] is True
    assert _group_raw(config)["watch_users"] == ["nasa"]


def test_set_import_group_users_preserves_invalid_watch_users():
    """批量导入/移除只应改动有效列表，不得静默清除隔离的无效条目。"""
    config = _FakeConfig(
        {
            "tweet_groups": [
                {
                    "name": "默认分组",
                    "group_id": "default",
                    "group_type": "blogger",
                    "watch_users": ["nasa", "!!bad!!"],
                    "push_targets": ["aiocqhttp:GroupMessage:1"],
                }
            ]
        }
    )
    reader = SchedulerConfigReader(config, None)
    group = reader.schedule_groups()[0]
    set_import_group_users(config, reader, group, ["nasa", "spacex"])
    assert config_get(config, "tweet_groups")[0]["watch_users"] == [
        "nasa",
        "spacex",
        "!!bad!!",
    ]
