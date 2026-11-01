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


def test_update_group_partial_payload_preserves_untouched_fields():
    """缺省字段保留原值：卡片启停只提交 {group_id, enabled}。

    回归背景：卡片上的启用开关曾用整份分组快照拼 payload，于是
    - 别处刚改过的 push_targets / watch_* 会被本页旧值写回；
    - tag/list 分组里通不过校验的无效订阅条目被整段抹掉（这些条目
      无法原样回写：_normalized_watch_queries / _normalized_watch_lists
      遇到无效条目直接抛错）。
    """
    config = _FakeConfig(
        {
            "tweet_groups": [
                {
                    "name": "列表组",
                    "group_id": "lists",
                    "group_type": "list",
                    "watch_lists": ["12345", "not-a-list"],
                    "push_targets": ["aiocqhttp:GroupMessage:1"],
                    "enabled": True,
                }
            ]
        }
    )
    plugin = MagicMock()
    plugin.config = config
    plugin.scheduler.config_reader = SchedulerConfigReader(config, context=None)
    editor = WebUIGroupEditor(plugin)

    result = editor.update_group({"group_id": "lists", "enabled": False})

    assert result["success"] is True
    raw = _group_raw(config)
    assert raw["enabled"] is False
    assert raw["name"] == "列表组"
    assert raw["watch_lists"] == ["12345", "not-a-list"]
    assert raw["push_targets"] == ["aiocqhttp:GroupMessage:1"]


def _partial_update_editor(groups: list[dict]) -> tuple[WebUIGroupEditor, _FakeConfig]:
    config = _FakeConfig({"tweet_groups": groups})
    plugin = MagicMock()
    plugin.config = config
    plugin.scheduler.config_reader = SchedulerConfigReader(config, context=None)
    return WebUIGroupEditor(plugin), config


def test_update_group_still_rejects_blank_name():
    """缺省 name 才保留原值；显式提交空名必须照旧报错。

    回归背景：缺省回退曾用真值判断（`self._text(data,"name") or 旧名`），
    于是 {"name": "   "} 被当成「未提交」静默回退，用户在抽屉里清空名字
    点保存会收到「分组已保存」但名字没变。
    """
    editor, _ = _partial_update_editor(
        [
            {
                "name": "G",
                "group_id": "g",
                "group_type": "blogger",
                "watch_users": ["nasa"],
            }
        ]
    )

    result = editor.update_group({"group_id": "g", "name": "   "})

    assert result["success"] is False
    assert "分组名称不能为空" in result["error"]


def test_update_group_partial_skips_stale_daily_check_times_validation():
    """缺省 daily_check_times 不回写也不校验：存量脏值不该挡住启停。

    回归背景：运行期 parse_daily_times 对越界/非法时间只 warning 跳过，
    AstrBot 设置页可手填出这种值。部分更新若把存量原值拿回来重跑校验，
    这类分组连启停都点不动。显式提交脏时间仍然要报错。
    """
    editor, config = _partial_update_editor(
        [
            {
                "name": "G",
                "group_id": "g",
                "group_type": "blogger",
                "watch_users": ["nasa"],
                "daily_check_times": ["09:00", "not-a-time"],
            }
        ]
    )

    toggled = editor.update_group({"group_id": "g", "enabled": False})
    assert toggled["success"] is True
    raw = _group_raw(config)
    assert raw["enabled"] is False
    # 脏值原样留着，等用户在抽屉里自己修
    assert raw["daily_check_times"] == ["09:00", "not-a-time"]

    rejected = editor.update_group({"group_id": "g", "daily_check_times": ["25:00"]})
    assert rejected["success"] is False
    assert "每日检查时间格式无效" in rejected["error"]


def test_update_group_partial_enabled_works_without_stored_name():
    """存量无 name 的分组也要能启停。

    回归背景：解析器会用 group_id 兜底展示这类分组，但缺省回退读的是
    raw_group 里的空 name，交给 _validated_name 会直接报「名称不能为空」，
    于是卡片开关对这类分组整体不可用。
    """
    editor, config = _partial_update_editor(
        [{"group_id": "noname", "group_type": "blogger", "watch_users": ["nasa"]}]
    )

    result = editor.update_group({"group_id": "noname", "enabled": False})

    assert result["success"] is True
    assert _group_raw(config)["enabled"] is False
    # 显式提交空名仍然要报错
    assert editor.update_group({"group_id": "noname", "name": "  "})["success"] is False


def test_update_group_partial_enabled_survives_dirty_stored_name():
    """存量脏名（重名/与标识冲突）也不能卡住启停。

    调用方没提交 name，就没有可校验的东西；重跑 _validated_name 会让这类
    分组在卡片上点不动。与 daily_check_times 的「缺省 = 不校验也不回写」
    同一契约。
    """
    editor, config = _partial_update_editor(
        [
            {
                "name": "同名",
                "group_id": "a",
                "group_type": "blogger",
                "watch_users": ["nasa"],
            },
            {
                "name": "同名",
                "group_id": "b",
                "group_type": "blogger",
                "watch_users": ["spacex"],
            },
        ]
    )

    for gid in ("a", "b"):
        result = editor.update_group({"group_id": gid, "enabled": False})
        assert result["success"] is True, result

    groups = config_get(config, "tweet_groups")
    assert [g["name"] for g in groups] == ["同名", "同名"]
    assert [g["enabled"] for g in groups] == [False, False]
