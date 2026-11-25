"""WebUI 分组保存对无效推送目标 / 无效订阅源的回写契约。

前端 draft 会把有效条目与后端隔离的无效条目合并后整体提交；
`update_group` 不做 UMO 校验、原样落盘：
- 提交里包含无效条目 = 显式保留（原文不动，去重/去空仍生效）；
- 提交里缺失无效条目 = 显式删除。

回归背景：旧前端 draft 只含有效列表，保存任意字段都会把配置里的
无效条目静默清除，且这些条目在 WebUI 无任何查看/删除出口。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from config.compat import config_get
from config.subscriptions import set_import_group_users
from plugin_api.api import NitterWebAPI
from plugin_api.groups import WebUIGroupEditor
from scheduler.config import SchedulerConfigReader

ROOT = Path(__file__).resolve().parents[1]


def test_content_mode_survives_partial_updates_and_can_switch_back():
    from config import MEDIA_ONLY_MODES

    config = _FakeConfig(
        {
            "tweet_groups": [
                {"group_id": "media", "name": "media", "media_only_enabled": True}
            ]
        }
    )
    editor = _make_editor(config)
    assert editor.update_group(
        {"group_id": "media", "media_only_enabled": MEDIA_ONLY_MODES[2]}
    )["success"]
    assert _group_raw(config)["media_only_enabled"] == MEDIA_ONLY_MODES[2]
    assert editor.update_group({"group_id": "media", "enabled": False})["success"]
    assert _group_raw(config)["media_only_enabled"] == MEDIA_ONLY_MODES[2]
    assert editor.update_group(
        {"group_id": "media", "media_only_enabled": MEDIA_ONLY_MODES[0]}
    )["success"]
    assert _group_raw(config)["media_only_enabled"] == MEDIA_ONLY_MODES[0]


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


def _make_group_api(group_type: str = "blogger"):
    config = _FakeConfig(
        tweet_groups=[
            {
                "name": "G",
                "group_id": "g",
                "enabled": True,
                "group_type": group_type,
                "watch_users": ["nasa"] if group_type == "blogger" else [],
                "watch_queries": ["#space"] if group_type == "tag" else [],
                "watch_lists": ["12345"] if group_type == "list" else [],
            }
        ]
    )
    storage = SimpleNamespace(migrate_and_sync=AsyncMock())
    plugin = SimpleNamespace(
        config=config,
        scheduler=SimpleNamespace(
            config_reader=SchedulerConfigReader(config, context=None),
            storage=storage,
            _check_lock=asyncio.Lock(),
            _ensure_storage_ready=AsyncMock(return_value=True),
        ),
    )
    return NitterWebAPI(plugin), config, storage


@pytest.mark.asyncio
@pytest.mark.parametrize("group_type", ["blogger", "tag", "list"])
async def test_update_group_response_carries_serialized_group_without_warning(
    group_type,
):
    """真实 API 保存后返回查询接口的完整分组，不给编辑器补序列化桩。"""
    api, config, storage = _make_group_api(group_type)
    with (
        patch.object(config, "save_config", wraps=config.save_config) as save,
        patch("plugin_api.groups.logger.warning") as warning,
    ):
        result = await api.update_group({"group_id": "g", "enabled": False})

    assert result["success"] is True
    assert result["group"] == (await api.build_groups())["groups"][0]
    assert result["group"]["group_id"] == "g"
    assert result["group"]["enabled"] is False
    assert "attention_items" in result["group"]
    assert _group_raw(config)["enabled"] is False
    save.assert_called_once_with()
    storage.migrate_and_sync.assert_awaited_once()
    assert storage.migrate_and_sync.await_args.args[0][0].enabled is False
    warning.assert_not_called()


@pytest.mark.asyncio
async def test_update_group_save_failure_preserves_config_and_skips_sync():
    api, config, storage = _make_group_api()
    previous = config_get(config, "tweet_groups")
    with (
        patch.object(config, "save_config", side_effect=OSError("write failed")),
        patch("plugin_api.groups.logger.warning"),
    ):
        result = await api.update_group({"group_id": "g", "enabled": False})

    assert result["success"] is False
    assert "write failed" in result["error"]
    assert config_get(config, "tweet_groups") == previous
    storage.migrate_and_sync.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_group_sync_failure_keeps_saved_group_and_reports_error():
    api, config, storage = _make_group_api()
    storage.migrate_and_sync.side_effect = RuntimeError("database unavailable")
    with patch("plugin_api.api.logger.warning") as warning:
        result = await api.update_group({"group_id": "g", "enabled": False})

    assert result["success"] is True
    assert result["sync_error"] == "database unavailable"
    assert "数据库同步失败" in result["message"]
    assert result["group"] == (await api.build_groups())["groups"][0]
    assert _group_raw(config)["enabled"] is False
    storage.migrate_and_sync.assert_awaited_once()
    warning.assert_called_once()
    assert "WebUI 分组同步失败" in warning.call_args.args[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [0, 1, 200, -1, 201, True, 1.5, "5", None])
async def test_group_limit_validation_and_partial_save(limit):
    api, config, _ = _make_group_api("list")
    result = await api.update_group({"group_id": "g", "max_tweets_per_check": limit})
    valid = type(limit) is int and 0 <= limit <= 200
    assert result["success"] is valid
    if valid:
        assert result["group"]["max_tweets_per_check"] == limit
        result = await api.update_group({"group_id": "g", "enabled": False})
        assert result["group"]["max_tweets_per_check"] == limit


@pytest.mark.asyncio
async def test_group_update_waits_for_check_lock():
    api, config, _ = _make_group_api("list")
    async with api.scheduler._check_lock:
        task = asyncio.create_task(
            api.update_group({"group_id": "g", "enabled": False})
        )
        await asyncio.sleep(0)
        assert not task.done()
        assert config_get(config, "tweet_groups")[0]["enabled"] is True
    assert (await task)["group"]["enabled"] is False


@pytest.mark.asyncio
async def test_group_sync_waits_for_storage_initialization():
    api, config, storage = _make_group_api("list")
    entered, release = asyncio.Event(), asyncio.Event()

    async def initialize():
        entered.set()
        await release.wait()
        return True

    api.scheduler._ensure_storage_ready.side_effect = initialize
    task = asyncio.create_task(api.update_group({"group_id": "g", "enabled": False}))
    await entered.wait()
    storage.migrate_and_sync.assert_not_awaited()
    release.set()
    assert (await task)["success"] is True
    storage.migrate_and_sync.assert_awaited_once()


@pytest.mark.asyncio
async def test_group_sync_reports_storage_initialization_failure():
    api, config, storage = _make_group_api("list")
    api.scheduler._ensure_storage_ready.return_value = False
    result = await api.update_group({"group_id": "g", "enabled": False})
    assert result["success"] is True
    assert result["sync_error"]
    storage.migrate_and_sync.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["create", "delete"])
async def test_group_create_delete_wait_for_check_lock(operation):
    api, config, storage = _make_group_api("list")
    storage.delete_group_runtime_data = AsyncMock(return_value={})
    async with api.scheduler._check_lock:
        if operation == "create":
            task = asyncio.create_task(
                api.create_group({"name": "new", "group_type": "tag"})
            )
        else:
            task = asyncio.create_task(
                api.delete_group({"group_id": "g", "force": True, "confirm": "DELETE"})
            )
        await asyncio.sleep(0)
        assert not task.done()
        assert [g["group_id"] for g in config_get(config, "tweet_groups")] == ["g"]
        storage.migrate_and_sync.assert_not_awaited()
        storage.delete_group_runtime_data.assert_not_awaited()
    assert (await task)["success"] is True
    storage.migrate_and_sync.assert_awaited_once()
