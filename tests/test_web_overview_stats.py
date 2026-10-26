"""overview 新增字段测试：推送统计、上次检查时间、全局转推过滤开关。

这三项是 Hero 卡与指标走廊的数据来源。零记录时成功率必须是 None（前端显示
占位而不是 0%），读取失败时整块降级为 None 而不是拖垮总览。
"""

from __future__ import annotations

import asyncio
import logging

from plugin_api.api_overview import WebAPIOverviewMixin


class _OverviewAPI(WebAPIOverviewMixin):
    """最小宿主替身：只提供 mixin 依赖的 _ok 与 storage。"""

    def __init__(self, storage=None):
        self.storage = storage

    @staticmethod
    def _ok(**payload):
        return {"success": True, "error": "", **payload}


class _Storage:
    def __init__(self, total: int, success: int, *, boom: bool = False):
        self._total = total
        self._success = success
        self._boom = boom
        self.calls: list[tuple[str, str, str]] = []

    async def count_push_history(self, group_id="", username="", status=""):
        self.calls.append((group_id, username, status))
        if self._boom:
            raise RuntimeError("db locked")
        return self._success if status == "success" else self._total


def push_stats(storage):
    return asyncio.run(_OverviewAPI(storage)._push_stats_snapshot())


def test_push_stats_computes_success_rate():
    storage = _Storage(total=200, success=150)
    assert push_stats(storage) == {"total": 200, "success": 150, "success_rate": 0.75}
    # 两次查询都必须是全量口径（空 group_id / username）
    assert storage.calls == [("", "", ""), ("", "", "success")]


def test_push_stats_rate_is_none_when_no_records():
    stats = push_stats(_Storage(total=0, success=0))
    assert stats == {"total": 0, "success": 0, "success_rate": None}


def test_push_stats_returns_none_on_storage_failure(caplog):
    with caplog.at_level(logging.WARNING):
        assert push_stats(_Storage(total=1, success=1, boom=True)) is None


class _Scheduler:
    def __init__(self, last_check_at=None):
        self.is_running = True
        self.schedule_enabled = True
        self.last_check_at = last_check_at
        self.config_reader = _ConfigReader()


class _ConfigReader:
    @staticmethod
    def parse_target_blocked_users():
        return type("Blocked", (), {"blocked_users": {}})()


def _make_overview_api(scheduler, storage=None, config=None):
    """构造只够 build_overview 跑通的最小宿主替身。"""

    class _PluginStub:
        class nitter:
            instances: list[str] = []

        class media:
            @staticmethod
            def cache_stats():
                raise RuntimeError("unused")

    class _API(_OverviewAPI):
        def __init__(self):
            self.scheduler = scheduler
            self.storage = storage or _Storage(0, 0)
            self.config = config if config is not None else {}
            self.plugin = _PluginStub()

        def _schedule_groups(self):
            return []

        def _configured_instances(self):
            return []

        async def _maintenance_snapshot(self):
            return {"cache": None, "seen": {"total": 0, "by_group": {}}}

        def _terminology(self):
            return {}

        def _config_summary(self, *args, **kwargs):
            return {}

        def _overview_attention_items(self, *args, **kwargs):
            return []

    return _API()


def test_scheduler_state_exposes_last_check_at():
    """build_overview 把调度器的 last_check_at 透传到 scheduler 段。"""
    payload = asyncio.run(
        _make_overview_api(_Scheduler(last_check_at=1792888220.0)).build_overview()
    )
    assert payload["scheduler"]["last_check_at"] == 1792888220.0
    assert payload["push_stats"] == {"total": 0, "success": 0, "success_rate": None}


def test_scheduler_state_last_check_at_defaults_to_none():
    class _BareScheduler:
        is_running = False
        schedule_enabled = False
        config_reader = _ConfigReader()
        # 刻意不定义 last_check_at：老调度器实例也必须能正常出总览

    payload = asyncio.run(_make_overview_api(_BareScheduler()).build_overview())
    assert payload["scheduler"]["last_check_at"] is None


def test_config_summary_includes_global_repost_filter():
    from plugin_api.api import NitterWebAPI

    # NitterWebAPI 的 config 是只读 property（读插件配置），
    # 这里只验证方法本身，用未绑定的函数调用绕过实例构造。
    def check(config):
        stub = type("Stub", (), {"config": config})()
        return NitterWebAPI._global_filter_reposts_enabled(stub)

    assert check({"filter_reposts_enabled": True}) is True
    assert check({"filter_reposts_enabled": False}) is False
    # 缺省按开启处理，与调度侧默认一致
    assert check({}) is True
