from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from typing import Any

from astrbot.api import logger
from quart import jsonify, request

try:
    from ..config import (
        config_get,
        configured_merge_tweet_threshold,
    )
    from ..config.subscriptions import (
        save_subscription_config,
    )
    from ..scheduler import ScheduleGroup
    from .api_history import WebAPIHistoryMixin
    from .api_overview import WebAPIOverviewMixin
    from .api_probe import WebAPIProbeMixin
    from .api_serializers import WebAPISerializersMixin
    from .api_subscriptions import WebAPISubscriptionsMixin
    from .target_blacklist import WebAPITargetBlacklistMixin
    from .groups import WebUIGroupEditor
except ImportError:
    from config import (
        config_get,
        configured_merge_tweet_threshold,
    )
    from config.subscriptions import (
        save_subscription_config,
    )
    from plugin_api.api_history import WebAPIHistoryMixin
    from plugin_api.api_overview import WebAPIOverviewMixin
    from plugin_api.api_probe import WebAPIProbeMixin
    from plugin_api.api_serializers import WebAPISerializersMixin
    from plugin_api.api_subscriptions import WebAPISubscriptionsMixin
    from plugin_api.target_blacklist import WebAPITargetBlacklistMixin
    from plugin_api.groups import WebUIGroupEditor
    from scheduler import ScheduleGroup


PLUGIN_NAME = "astrbot_plugin_nitter_tweets"


class NitterWebAPI(
    WebAPIOverviewMixin,
    WebAPIHistoryMixin,
    WebAPIProbeMixin,
    WebAPISubscriptionsMixin,
    WebAPITargetBlacklistMixin,
    WebAPISerializersMixin,
):
    """Backend API provider for the AstrBot Plugin Pages dashboard."""

    def __init__(self, plugin: Any) -> None:
        self.plugin = plugin

    def register(self, context) -> None:
        routes: list[tuple[str, str, list[str]]] = [
            ("web/overview", "handle_overview", ["GET"]),
            ("web/groups", "handle_groups", ["GET"]),
            ("web/groups/create", "handle_group_create", ["POST"]),
            ("web/groups/update", "handle_group_update", ["POST"]),
            ("web/groups/delete", "handle_group_delete", ["POST"]),
            ("web/targets/probe", "handle_targets_probe", ["POST"]),
            ("web/target-blacklists", "handle_target_blacklists", ["GET"]),
            (
                "web/target-blacklists/update",
                "handle_target_blacklist_update",
                ["POST"],
            ),
            ("web/history", "handle_history", ["GET"]),
            ("web/history/orphans", "handle_history_orphans", ["GET"]),
            ("web/history/orphans/delete", "handle_history_orphan_delete", ["POST"]),
            ("web/history/replay", "handle_history_replay", ["POST"]),
            ("web/check", "handle_check", ["POST"]),
            ("web/cache/clear", "handle_cache_clear", ["POST"]),
            ("web/seen/clear", "handle_seen_clear", ["POST"]),
            ("web/subscriptions/import", "handle_subscriptions_import", ["POST"]),
            ("web/subscriptions/delete", "handle_subscriptions_delete", ["POST"]),
            ("web/mirror/probe", "handle_mirror_probe", ["POST"]),
        ]
        for route, handler_name, methods in routes:
            context.register_web_api(
                f"/{PLUGIN_NAME}/{route}",
                getattr(self, handler_name),
                methods,
                f"Nitter WebUI: {route}",
            )

    async def handle_overview(self):
        return await self._json_response(self.build_overview)

    async def handle_groups(self):
        return await self._json_response(self.build_groups)

    async def handle_history(self):
        async def action():
            group_id = str(request.args.get("group_id", "") or "").strip()
            username = str(request.args.get("username", "") or "").strip()
            status = str(request.args.get("status", "") or "").strip()
            limit = self._parse_int(
                request.args.get("limit"), 10, minimum=1, maximum=50
            )
            offset = self._parse_int(
                request.args.get("offset"), 0, minimum=0, maximum=10_000_000
            )
            return await self.build_history(group_id, username, limit, offset, status)

        return await self._json_response(action)

    async def handle_history_orphans(self):
        return await self._json_response(self.build_history_orphans)

    async def handle_history_orphan_delete(self):
        async def action():
            data = await self._request_json()
            return await self.delete_history_orphan(data)

        return await self._json_response(action)

    async def handle_group_create(self):
        async def action():
            data = await self._request_json()
            return await self.create_group(data)

        return await self._json_response(action)

    async def handle_group_update(self):
        async def action():
            data = await self._request_json()
            return await self.update_group(data)

        return await self._json_response(action)

    async def handle_group_delete(self):
        async def action():
            data = await self._request_json()
            return await self.delete_group(data)

        return await self._json_response(action)

    async def handle_targets_probe(self):
        async def action():
            data = await self._request_json()
            return await self.probe_targets(data)

        return await self._json_response(action)

    async def handle_target_blacklists(self):
        return await self._json_response(self.build_target_blacklists)

    async def handle_target_blacklist_update(self):
        async def action():
            data = await self._request_json()
            return await self.update_target_blacklist(data)

        return await self._json_response(action)

    async def handle_history_replay(self):
        async def action():
            data = await self._request_json()
            return await self.replay_history(data)

        return await self._json_response(action)

    async def handle_check(self):
        async def action():
            data = await self._request_json()
            return await self.run_check(data)

        return await self._json_response(action)

    async def handle_cache_clear(self):
        return await self._json_response(self.clear_cache)

    async def handle_seen_clear(self):
        async def action():
            data = await self._request_json()
            group_id = self._data_text(data, "group_id")
            confirm = self._data_text(data, "confirm")
            if not group_id and self._data_text(data, "group_name"):
                return self._error("WebUI API 仅支持使用 group_id 指定分组")
            return await self.clear_seen(group_id, confirm=confirm)

        return await self._json_response(action)

    async def handle_subscriptions_import(self):
        async def action():
            data = await self._request_json()
            return await self.import_subscriptions(data)

        return await self._json_response(action)

    async def handle_subscriptions_delete(self):
        async def action():
            data = await self._request_json()
            return await self.delete_subscriptions(data)

        return await self._json_response(action)

    async def handle_mirror_probe(self):
        async def action():
            data = await self._request_json()
            return await self.probe_mirror(data)

        return await self._json_response(action)

    async def create_group(self, data: dict[str, Any]) -> dict[str, Any]:
        result = self._group_editor().create_group(data)
        if not result.get("success"):
            return result

        sync_error = await self._sync_groups()
        group, error = self._resolve_group(result["group_id"])
        if error:
            return self._error(error)
        payload = self._ok(
            group=self._serialize_group(group),
        )
        if sync_error:
            payload["sync_error"] = sync_error
            payload["message"] = f"分组已创建，但数据库同步失败：{sync_error}"
        return payload

    async def update_group(self, data: dict[str, Any]) -> dict[str, Any]:
        result = self._group_editor().update_group(data)
        if not result.get("success"):
            return result

        sync_error = await self._sync_groups()
        group, error = self._resolve_group(result["group_id"])
        if error:
            return self._error(error)
        payload = self._ok(
            group=self._serialize_group(group),
        )
        if sync_error:
            payload["sync_error"] = sync_error
            payload["message"] = f"分组已保存，但数据库同步失败：{sync_error}"
        return payload

    async def delete_group(self, data: dict[str, Any]) -> dict[str, Any]:
        result = self._group_editor().delete_group(data)
        if not result.get("success"):
            return result

        runtime_summary = None
        runtime_error = ""
        try:
            runtime_summary = await self.storage.delete_group_runtime_data(
                result["group_id"]
            )
        except Exception as exc:
            runtime_error = str(exc)
            logger.warning(
                "[NitterTweets] WebUI 删除分组运行数据清理失败: "
                f"group={result['group_id']}, error={runtime_error}"
            )
        sync_error = await self._sync_groups()
        payload = self._ok(
            group_id=result["group_id"],
            group_name=result["group_name"],
            runtime_summary=runtime_summary,
            cleanup_status=("partial_failure" if runtime_error else "ok"),
        )
        if runtime_error:
            payload["runtime_error"] = runtime_error
            payload["message"] = "分组已删除，但部分运行数据清理失败，请查看详情"
        if sync_error:
            payload["sync_error"] = sync_error
            if runtime_error:
                payload["message"] += f"；数据库同步失败：{sync_error}"
            else:
                payload["message"] = f"分组已删除，但数据库同步失败：{sync_error}"
        return payload

    async def run_check(self, data: dict[str, Any]) -> dict[str, Any]:
        group_id = self._data_text(data, "group_id") or self._data_text(
            data, "group_name"
        )
        group, error = self._resolve_group(group_id)
        if error:
            return self._error(error)
        if not group.enabled:
            return self._error(f"分组已停用：{self._group_label(group)}")

        result = await self.scheduler.run_check(
            reason="webui",
            notify_no_updates=False,
            group_name=group.group_id,
        )
        return self._ok(
            message=result.format_message(),
            result=self._serialize_check_result(result),
        )

    async def clear_cache(self) -> dict[str, Any]:
        result = await asyncio.to_thread(self.plugin.media.clear_cache)
        return self._ok(result=self._serialize_cache_result(result))

    async def clear_seen(self, group_id: str = "", confirm: str = "") -> dict[str, Any]:
        group_id = str(group_id or "").strip()
        confirm = str(confirm or "").strip()
        group: ScheduleGroup | None = None
        clear_all = not group_id or group_id.lower() in {"all", "全部"}
        if clear_all:
            if confirm != "CLEAR_ALL":
                return self._error("清理全部分组推送记录需要显式确认")
        else:
            group, error = self._resolve_group(group_id)
            if error:
                return self._error(error)

        deleted = await self.storage.clear_seen_records(
            group.group_id if group else None
        )
        legacy_deleted = await self.storage.delete_legacy_seen_kv()
        return self._ok(
            scope=self._group_label(group) if group else "全部分组",
            deleted=deleted,
            legacy_deleted=bool(legacy_deleted),
            warning=("推送记录已清理；关注账号、推送目标和媒体文件不会被删除。"),
        )

    @property
    def config(self):
        return self.plugin.config

    @property
    def scheduler(self):
        return self.plugin.scheduler

    @property
    def storage(self):
        return self.scheduler.storage

    def _schedule_groups(self) -> list[ScheduleGroup]:
        return self.scheduler.config_reader.schedule_groups(log_invalid_targets=False)

    def _group_editor(self) -> WebUIGroupEditor:
        return WebUIGroupEditor(self.plugin)

    async def _sync_groups(self) -> str:
        try:
            await self.storage.migrate_and_sync(self._schedule_groups())
        except Exception as exc:
            error = str(exc)
            logger.warning(f"[NitterTweets] WebUI 分组同步失败: {error}")
            return error
        return ""

    def _select_groups(
        self, groups: list[ScheduleGroup], group_id: str
    ) -> list[ScheduleGroup]:
        group_id = str(group_id or "").strip()
        if not group_id:
            return groups
        group = self.scheduler.config_reader.schedule_group(
            group_id,
            log_invalid_targets=False,
        )
        return [group] if group is not None else []

    def _resolve_group(self, group_id: str) -> tuple[ScheduleGroup | None, str]:
        group_id = str(group_id or "").strip()
        if not group_id:
            return None, "请选择分组"
        group = self.scheduler.config_reader.schedule_group(
            group_id,
            log_invalid_targets=False,
        )
        if group is None:
            return None, f"未找到分组：{group_id}"
        return group, ""

    def _save_config(self) -> str:
        return save_subscription_config(self.config)

    def _config_summary(
        self,
        instances: list[str],
        groups: list[ScheduleGroup] | None = None,
        instance_lists: dict[str, list[str]] | None = None,
    ) -> dict[str, Any]:
        effective_group = self._effective_config_group(groups or [])
        return {
            "nitter_instance_count": len(instances),
            "default_limit": self._default_limit(),
            "check_interval_minutes": self._group_value(
                effective_group, "check_interval_minutes", 30
            ),
            "merge_tweet_threshold": configured_merge_tweet_threshold(self.config),
            "send_target_interval": self._group_value(
                effective_group, "send_target_interval", 1.5
            ),
            "concurrent_fetch_enabled": bool(
                self._group_value(effective_group, "concurrent_fetch_enabled", False)
            ),
            "concurrent_prepare_enabled": bool(
                self._group_value(effective_group, "concurrent_prepare_enabled", False)
            ),
        }

    def _effective_config_group(
        self, groups: list[ScheduleGroup]
    ) -> ScheduleGroup | None:
        if groups:
            return groups[0]
        reader = getattr(self.scheduler, "config_reader", None)
        parse_group = getattr(reader, "parse_schedule_group", None)
        if callable(parse_group):
            return parse_group(
                {"name": "WebUI", "group_id": "webui"},
                1,
                log_invalid_targets=False,
            )
        return None

    def _default_limit(self) -> int:
        parser = getattr(self.plugin, "_parse_positive_limit", None)
        raw_value = config_get(self.config, "default_limit", 5)
        if callable(parser):
            return int(parser(raw_value, 5))
        try:
            number = int(raw_value)
        except (TypeError, ValueError):
            return 5
        return number if number > 0 else 5

    @staticmethod
    def _group_value(
        group: ScheduleGroup | None,
        name: str,
        fallback: Any,
    ) -> Any:
        if group is None:
            return fallback
        return getattr(group, name, fallback)

    @staticmethod
    def _ok(**payload) -> dict[str, Any]:
        return {"success": True, "error": "", **payload}

    @staticmethod
    def _error(error: str) -> dict[str, Any]:
        return {"success": False, "error": str(error or "操作失败")}

    @staticmethod
    async def _json_response(
        action: Callable[[], Awaitable[dict[str, Any]]],
    ) -> Any:
        try:
            return jsonify(await action())
        except Exception as exc:
            logger.warning(f"[NitterTweets] WebUI API 操作失败: {exc}")
            return jsonify(NitterWebAPI._error("操作失败，请查看 AstrBot 日志"))

    @staticmethod
    async def _request_json() -> dict[str, Any]:
        data = request.get_json(silent=True)
        if isinstance(data, Awaitable) or inspect.isawaitable(data):
            data = await data
        return data if isinstance(data, dict) else {}
