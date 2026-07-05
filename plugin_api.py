from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from typing import Any

from astrbot.api import logger
from quart import jsonify, request

try:
    from .config_compat import config_get
    from .scheduler_config import ScheduleGroup
    from .sqlite_storage import PendingQueueSummary, PendingTweetRecord
    from .utils import TweetItem, configured_merge_tweet_threshold, normalize_username
except ImportError:
    from config_compat import config_get
    from scheduler_config import ScheduleGroup
    from sqlite_storage import PendingQueueSummary, PendingTweetRecord
    from utils import TweetItem, configured_merge_tweet_threshold, normalize_username


PLUGIN_NAME = "astrbot_plugin_nitter_tweets"


class NitterWebAPI:
    """Backend API provider for the AstrBot Plugin Pages dashboard."""

    def __init__(self, plugin: Any) -> None:
        self.plugin = plugin

    def register(self, context) -> None:
        routes: list[tuple[str, str, list[str]]] = [
            ("web/overview", "handle_overview", ["GET"]),
            ("web/groups", "handle_groups", ["GET"]),
            ("web/pending", "handle_pending", ["GET"]),
            ("web/check", "handle_check", ["POST"]),
            ("web/publish", "handle_publish", ["POST"]),
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

    async def handle_pending(self):
        async def action():
            group_id = str(request.args.get("group_id", "") or "").strip()
            limit = self._parse_int(
                request.args.get("limit"), 50, minimum=1, maximum=200
            )
            return await self.build_pending(group_id, limit)

        return await self._json_response(action)

    async def handle_check(self):
        async def action():
            data = await self._request_json()
            return await self.run_check(data)

        return await self._json_response(action)

    async def handle_publish(self):
        async def action():
            data = await self._request_json()
            return await self.publish_pending(data)

        return await self._json_response(action)

    async def handle_cache_clear(self):
        return await self._json_response(self.clear_cache)

    async def handle_seen_clear(self):
        async def action():
            data = await self._request_json()
            group_id = self._data_text(data, "group_id") or self._data_text(
                data, "group_name"
            )
            return await self.clear_seen(group_id)

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

    async def build_overview(self) -> dict[str, Any]:
        groups = self._schedule_groups()
        summaries = await self._pending_summaries(groups)

        total_raw_users = sum(group.users_info.raw_count for group in groups)
        total_duplicates = sum(len(group.users_info.duplicates) for group in groups)
        total_invalid_users = sum(
            len(group.users_info.invalid_entries) for group in groups
        )
        counts = {
            "groups": len(groups),
            "enabled_groups": sum(1 for group in groups if group.enabled),
            "watch_users": sum(len(group.users) for group in groups),
            "raw_watch_users": total_raw_users,
            "duplicate_watch_users": total_duplicates,
            "invalid_watch_users": total_invalid_users,
            "push_targets": sum(len(group.targets) for group in groups),
            "invalid_push_targets": sum(
                len(group.invalid_targets) for group in groups
            ),
            "pending_tweets": sum(item.pending_count for item in summaries.values()),
            "failed_pending_tweets": sum(
                item.failed_count for item in summaries.values()
            ),
            "pending_media": sum(item.media_count for item in summaries.values()),
        }
        scheduler_state = {
            "running": bool(getattr(self.scheduler, "is_running", False)),
            "schedule_enabled": bool(
                getattr(self.scheduler, "schedule_enabled", False)
            ),
        }
        features = {
            "images": bool(config_get(self.config, "send_image_attachments", True)),
            "videos": bool(config_get(self.config, "send_video_attachments", False)),
            "translation": bool(config_get(self.config, "translate_enabled", False)),
            "ai_vision": bool(config_get(self.config, "vision_enabled", False)),
            "ai_comment": bool(config_get(self.config, "comment_enabled", False)),
            "deferred_publish_groups": sum(
                1 for group in groups if group.deferred_publish_enabled
            ),
        }
        instances = list(getattr(getattr(self.plugin, "nitter", None), "instances", []))
        return self._ok(
            scheduler=scheduler_state,
            counts=counts,
            features=features,
            config_summary=self._config_summary(instances, groups),
            instances=instances,
            attention_items=self._overview_attention_items(
                counts, scheduler_state, instances
            ),
            terminology=self._terminology(),
        )

    async def build_groups(self) -> dict[str, Any]:
        groups = self._schedule_groups()
        summaries = await self._pending_summaries(groups)
        return self._ok(
            groups=[
                self._serialize_group(group, summaries.get(group.group_id))
                for group in groups
            ],
            terminology=self._terminology(),
        )

    async def build_pending(self, group_id: str = "", limit: int = 50) -> dict[str, Any]:
        groups = self._schedule_groups()
        selected_groups = self._select_groups(groups, group_id)
        if group_id and not selected_groups:
            return self._error(f"未找到分组：{group_id}")

        summaries = await self._pending_summaries(groups)
        records: list[dict[str, Any]] = []
        group_names = {group.group_id: group.name for group in groups}
        remaining = max(1, int(limit))
        for group in selected_groups:
            if remaining <= 0:
                break
            group_records = await self.storage.get_pending_tweets(
                group.group_id, remaining
            )
            records.extend(
                self._serialize_pending_record(record, group_names)
                for record in group_records
            )
            remaining -= len(group_records)

        return self._ok(
            selected_group_id=group_id.strip(),
            summaries=[
                self._serialize_pending_summary(summary, group_names)
                for summary in summaries.values()
            ],
            records=records,
            limit=limit,
            terminology=self._terminology(),
        )

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
            force_immediate=True,
        )
        return self._ok(
            message=result.format_message(),
            result=self._serialize_check_result(result),
        )

    async def publish_pending(self, data: dict[str, Any]) -> dict[str, Any]:
        group_id = self._data_text(data, "group_id") or self._data_text(
            data, "group_name"
        )
        group, error = self._resolve_group(group_id)
        if error:
            return self._error(error)

        result = await self.scheduler.publish_pending(
            group_name=group.group_id,
            reason="webui_publish",
        )
        return self._ok(
            message=result.format_message("Nitter 暂存发布结果"),
            result=self._serialize_check_result(result),
        )

    async def clear_cache(self) -> dict[str, Any]:
        result = await asyncio.to_thread(self.plugin.media.clear_non_staged_cache)
        return self._ok(result=self._serialize_cache_result(result))

    async def clear_seen(self, group_id: str = "") -> dict[str, Any]:
        group_id = str(group_id or "").strip()
        group: ScheduleGroup | None = None
        if group_id and group_id.lower() not in {"all", "全部"}:
            group, error = self._resolve_group(group_id)
            if error:
                return self._error(error)

        deleted = await self.storage.clear_seen_records(group.group_id if group else None)
        legacy_deleted = await self.storage.delete_legacy_seen_kv()
        return self._ok(
            scope=self._group_label(group) if group else "全部分组",
            deleted=deleted,
            legacy_deleted=bool(legacy_deleted),
            warning=(
                "推送记录已清理；关注账号、推送目标、暂存队列和媒体文件不会被删除。"
            ),
        )

    async def import_subscriptions(self, data: dict[str, Any]) -> dict[str, Any]:
        entries = self._subscription_entries(data)
        if not entries:
            return self._error("请填写要导入的关注账号")

        group, error = self._subscription_group(data)
        if error:
            return self._error(error)

        existing_users = list(group.users)
        seen = {user.lower() for user in existing_users}
        added: list[str] = []
        duplicates: list[str] = []
        invalid: list[str] = []

        for raw in entries:
            username = self.plugin._normalize_import_username(raw)
            if not username:
                invalid.append(raw)
                continue
            key = username.lower()
            if key in seen:
                duplicates.append(raw)
                continue
            seen.add(key)
            added.append(username)

        if added:
            self.plugin._set_import_group_users(group, [*existing_users, *added])
            save_error = self._save_config()
            sync_error = await self.plugin._sync_import_config_groups()
        else:
            save_error = ""
            sync_error = ""

        return self._ok(
            message=self._subscription_message(
                "导入", bool(added), save_error, sync_error
            ),
            summary={
                "group": self._group_payload_label(group),
                "input_count": len(entries),
                "added": added,
                "duplicates": duplicates,
                "invalid": invalid,
                "total_after": len(existing_users) + len(added),
                "saved": bool(added),
                "save_error": save_error,
                "sync_error": sync_error,
            }
        )

    async def delete_subscriptions(self, data: dict[str, Any]) -> dict[str, Any]:
        entries = self._subscription_entries(data)
        if not entries:
            return self._error("请填写要删除的关注账号")
        if len(entries) > 50:
            return self._error(
                f"单次最多删除 50 个关注账号，本次输入 {len(entries)} 个"
            )

        group, error = self._subscription_group(data)
        if error:
            return self._error(error)

        existing_users = list(group.users)
        existing_by_key = {user.lower(): user for user in existing_users}
        delete_keys: set[str] = set()
        requested: list[str] = []
        duplicates: list[str] = []
        invalid: list[str] = []

        for raw in entries:
            username = self.plugin._normalize_import_username(raw)
            if not username:
                invalid.append(raw)
                continue
            key = username.lower()
            if key in delete_keys:
                duplicates.append(raw)
                continue
            delete_keys.add(key)
            requested.append(username)

        removed = [
            existing_by_key[user.lower()]
            for user in requested
            if user.lower() in existing_by_key
        ]
        missing = [
            user for user in requested if user.lower() not in existing_by_key
        ]
        remaining = [
            user for user in existing_users if user.lower() not in delete_keys
        ]

        if removed:
            self.plugin._set_import_group_users(group, remaining)
            save_error = self._save_config()
            sync_error = await self.plugin._sync_import_config_groups()
        else:
            save_error = ""
            sync_error = ""

        return self._ok(
            message=self._subscription_message(
                "删除", bool(removed), save_error, sync_error
            ),
            summary={
                "group": self._group_payload_label(group),
                "input_count": len(entries),
                "removed": removed,
                "missing": missing,
                "duplicates": duplicates,
                "invalid": invalid,
                "total_after": len(remaining),
                "saved": bool(removed),
                "save_error": save_error,
                "sync_error": sync_error,
            }
        )

    async def probe_mirror(self, data: dict[str, Any]) -> dict[str, Any]:
        instance = self._data_text(data, "instance")
        if not self.plugin._looks_like_instance(instance):
            return self._error("请填写完整 Nitter 镜像站地址，例如 https://nitter.net")

        username = normalize_username(self._data_text(data, "username") or "nasa")
        if not username:
            return self._error("关注账号格式无效")

        limit = self._parse_int(
            data.get("limit"),
            int(getattr(self.plugin, "default_limit", 5) or 5),
            minimum=1,
            maximum=200,
        )
        try:
            used_instance, tweets = await self.plugin.nitter.fetch_tweets_from_instance(
                instance,
                username,
                limit,
            )
        except Exception as exc:
            logger.warning(
                "[NitterTweets] WebUI 镜像测试失败: "
                f"instance={instance}, username={username}, error={exc}"
            )
            return self._error(
                f"通过 {instance} 获取 @{username} 推文失败：Nitter 镜像暂时不可用或该用户无公开 RSS。"
            )

        return self._ok(
            instance=used_instance,
            username=username,
            limit=limit,
            tweet_count=len(tweets),
            tweets=[self._serialize_probe_tweet(tweet) for tweet in tweets[:limit]],
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

    async def _pending_summaries(
        self, groups: list[ScheduleGroup]
    ) -> dict[str, PendingQueueSummary]:
        if not groups:
            return {}
        results = await asyncio.gather(
            *[
                self.storage.get_pending_queue_summary(group.group_id)
                for group in groups
            ]
        )
        return {group.group_id: summary for group, summary in zip(groups, results)}

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

    def _subscription_group(
        self, data: dict[str, Any]
    ) -> tuple[ScheduleGroup | None, str]:
        group_id = self._data_text(data, "group_id") or self._data_text(
            data, "group_name"
        )
        if group_id:
            return self._resolve_group(group_id)
        return self.plugin._ensure_default_import_group(), ""

    def _subscription_entries(self, data: dict[str, Any]) -> list[str]:
        raw = data.get("entries", data.get("users", ""))
        if isinstance(raw, list):
            return [str(item).strip() for item in raw if str(item).strip()]
        return [item.strip() for item in str(raw or "").split(",") if item.strip()]

    def _save_config(self) -> str:
        save_config = getattr(self.config, "save_config", None)
        if callable(save_config):
            try:
                save_config()
            except Exception as exc:
                error = str(exc)
                logger.warning(f"[NitterTweets] WebUI 保存订阅配置失败: {error}")
                return error
            return ""
        return "当前配置对象不支持 save_config()"

    @staticmethod
    def _subscription_message(
        action: str,
        changed: bool,
        save_error: str = "",
        sync_error: str = "",
    ) -> str:
        if not changed:
            return f"{action}完成，配置未改动"
        if save_error:
            return f"{action}完成，但配置保存失败：{save_error}"
        if sync_error:
            return f"{action}完成，但数据库同步失败：{sync_error}"
        return f"{action}完成"

    def _config_summary(
        self, instances: list[str], groups: list[ScheduleGroup] | None = None
    ) -> dict[str, Any]:
        effective_group = self._effective_config_group(groups or [])
        return {
            "nitter_instance_count": len(instances),
            "default_limit": self._default_limit(),
            "scheduled_fetch_limit": self._group_value(
                effective_group, "scheduled_fetch_limit", 5
            ),
            "check_interval_minutes": self._group_value(
                effective_group, "check_interval_minutes", 30
            ),
            "merge_tweet_threshold": configured_merge_tweet_threshold(self.config),
            "send_target_interval": self._group_value(
                effective_group, "send_target_interval", 1.5
            ),
            "deferred_publish_batch_limit": self._group_value(
                effective_group, "deferred_publish_batch_limit", 50
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
    def _overview_attention_items(
        counts: dict[str, int],
        scheduler_state: dict[str, bool],
        instances: list[str],
    ) -> list[dict[str, str]]:
        items: list[dict[str, str]] = []
        if not scheduler_state.get("running", False):
            items.append(
                {
                    "key": "scheduler_not_running",
                    "level": "warning",
                    "title": "调度器未运行",
                    "detail": "后台检查和暂存发布不会自动执行。",
                }
            )
        if not instances:
            items.append(
                {
                    "key": "no_instances",
                    "level": "warning",
                    "title": "未配置 Nitter 实例",
                    "detail": "手动查询、镜像测试和后台检查都需要可用实例。",
                }
            )
        if int(counts.get("groups", 0)) <= 0:
            items.append(
                {
                    "key": "no_groups",
                    "level": "info",
                    "title": "没有用户分组",
                    "detail": "关注账号和推送目标需要先在 AstrBot 设置页配置。",
                }
            )
        elif int(counts.get("enabled_groups", 0)) <= 0:
            items.append(
                {
                    "key": "no_enabled_groups",
                    "level": "warning",
                    "title": "没有启用的用户分组",
                    "detail": "后台检查不会处理已停用分组。",
                }
            )
        if int(counts.get("invalid_push_targets", 0)) > 0:
            items.append(
                {
                    "key": "invalid_push_targets",
                    "level": "warning",
                    "title": "存在无效推送目标",
                    "detail": f"{counts['invalid_push_targets']} 个推送目标未通过 UMO 校验。",
                }
            )
        if int(counts.get("invalid_watch_users", 0)) > 0:
            items.append(
                {
                    "key": "invalid_watch_users",
                    "level": "warning",
                    "title": "存在无效关注账号",
                    "detail": f"{counts['invalid_watch_users']} 个关注账号格式无效。",
                }
            )
        if int(counts.get("failed_pending_tweets", 0)) > 0:
            items.append(
                {
                    "key": "failed_pending_tweets",
                    "level": "warning",
                    "title": "暂存队列有失败记录",
                    "detail": f"{counts['failed_pending_tweets']} 条待发布推文需要关注。",
                }
            )
        if not items:
            items.append(
                {
                    "key": "ok",
                    "level": "ok",
                    "title": "当前没有需要处理的提示",
                    "detail": "关键状态未发现异常。",
                }
            )
        return items

    def _serialize_group(
        self,
        group: ScheduleGroup,
        summary: PendingQueueSummary | None = None,
    ) -> dict[str, Any]:
        pending_summary = summary or PendingQueueSummary(group_id=group.group_id)
        return {
            "group_id": group.group_id,
            "name": group.name,
            "enabled": group.enabled,
            "aliases": list(group.aliases),
            "watch_users": list(group.users),
            "watch_user_count": len(group.users),
            "raw_watch_user_count": group.users_info.raw_count,
            "duplicate_watch_users": list(group.users_info.duplicates),
            "invalid_watch_users": list(group.users_info.invalid_entries),
            "push_targets": list(group.targets),
            "push_target_count": len(group.targets),
            "invalid_push_targets": list(group.invalid_targets),
            "invalid_push_target_count": len(group.invalid_targets),
            "interval_check_enabled": group.interval_check_enabled,
            "check_interval_minutes": group.check_interval_minutes,
            "daily_check_enabled": group.daily_check_enabled,
            "daily_check_times": self._format_times(group.daily_check_times),
            "scheduled_fetch_limit": group.scheduled_fetch_limit,
            "deferred_publish_enabled": group.deferred_publish_enabled,
            "deferred_publish_times": self._format_times(
                group.deferred_publish_times
            ),
            "deferred_publish_batch_limit": group.deferred_publish_batch_limit,
            "filter_plain_text_enabled": group.filter_plain_text_enabled,
            "pending_summary": self._serialize_pending_summary(
                pending_summary,
                {group.group_id: group.name},
            ),
            "attention_items": self._group_attention_items(group, pending_summary),
        }

    @staticmethod
    def _group_attention_items(
        group: ScheduleGroup,
        summary: PendingQueueSummary,
    ) -> list[dict[str, str]]:
        items: list[dict[str, str]] = []
        if not group.enabled:
            items.append(
                {
                    "key": "group_disabled",
                    "level": "info",
                    "title": "分组停用",
                    "detail": "停用分组不会参与后台检查。",
                }
            )
        if not group.users:
            items.append(
                {
                    "key": "no_watch_users",
                    "level": "warning",
                    "title": "无关注账号",
                    "detail": "该分组没有可检查的关注账号。",
                }
            )
        if not group.targets:
            items.append(
                {
                    "key": "no_push_targets",
                    "level": "warning",
                    "title": "无推送目标",
                    "detail": "新推文没有可发送的推送目标。",
                }
            )
        if group.users_info.invalid_entries:
            items.append(
                {
                    "key": "invalid_watch_users",
                    "level": "warning",
                    "title": "关注账号无效",
                    "detail": f"{len(group.users_info.invalid_entries)} 个关注账号格式无效。",
                }
            )
        if group.invalid_targets:
            items.append(
                {
                    "key": "invalid_push_targets",
                    "level": "warning",
                    "title": "推送目标无效",
                    "detail": f"{len(group.invalid_targets)} 个推送目标未通过 UMO 校验。",
                }
            )
        if summary.failed_count > 0:
            items.append(
                {
                    "key": "failed_pending_tweets",
                    "level": "warning",
                    "title": "暂存发布失败",
                    "detail": f"{summary.failed_count} 条待发布推文有失败记录。",
                }
            )
        return items

    @staticmethod
    def _serialize_pending_summary(
        summary: PendingQueueSummary,
        group_names: dict[str, str],
    ) -> dict[str, Any]:
        return {
            "group_id": summary.group_id,
            "group_name": group_names.get(summary.group_id, summary.group_id),
            "pending_count": summary.pending_count,
            "failed_count": summary.failed_count,
            "media_count": summary.media_count,
            "oldest_created_at": summary.oldest_created_at,
            "newest_created_at": summary.newest_created_at,
            "user_counts": [
                {"username": username, "count": count}
                for username, count in summary.user_counts
            ],
        }

    @staticmethod
    def _serialize_pending_record(
        record: PendingTweetRecord,
        group_names: dict[str, str],
    ) -> dict[str, Any]:
        media_kinds = list(dict.fromkeys(media.kind for media in record.tweet.media))
        return {
            "id": record.id,
            "group_id": record.group_id,
            "group_name": group_names.get(record.group_id, record.group_id),
            "username": record.username,
            "status_id": record.status_id,
            "instance": record.instance,
            "original_link": record.tweet.x_url,
            "published": record.tweet.published,
            "text_preview": NitterWebAPI._text_preview(record.tweet.text),
            "created_at": record.created_at,
            "scheduled_at": record.scheduled_at,
            "published_at": record.published_at,
            "sent_at": record.sent_at,
            "failed_at": record.failed_at,
            "fail_count": record.fail_count,
            "last_error": record.last_error,
            "delivered_target_count": len(record.delivered_targets),
            "media_count": len(record.tweet.media),
            "media_kinds": media_kinds,
            "has_translation": bool(record.tweet.translation),
            "has_ai_comment": bool(record.tweet.ai_comment),
            "has_image_caption": bool(record.tweet.image_caption),
        }

    @staticmethod
    def _serialize_check_result(result: Any) -> dict[str, Any]:
        return {
            "group_id": getattr(result, "group_id", ""),
            "group_name": getattr(result, "group_name", ""),
            "skipped_reason": getattr(result, "skipped_reason", ""),
            "new_tweet_count": getattr(result, "new_tweet_count", 0),
            "queued_tweet_count": getattr(result, "queued_tweet_count", 0),
            "pushed_target_successes": getattr(
                result, "pushed_target_successes", 0
            ),
            "pushed_target_attempts": getattr(result, "pushed_target_attempts", 0),
        }

    @staticmethod
    def _serialize_cache_result(result: Any) -> dict[str, int]:
        return {
            "removed": int(getattr(result, "removed", 0) or 0),
            "failed": int(getattr(result, "failed", 0) or 0),
            "skipped_dirs": int(getattr(result, "skipped_dirs", 0) or 0),
            "removed_images": int(
                getattr(result, "removed_images", getattr(result, "images", 0)) or 0
            ),
            "removed_videos": int(
                getattr(result, "removed_videos", getattr(result, "videos", 0)) or 0
            ),
            "removed_other": int(
                getattr(result, "removed_other", getattr(result, "other", 0)) or 0
            ),
            "removed_empty_dirs": int(
                getattr(result, "removed_empty_dirs", 0) or 0
            ),
        }

    @staticmethod
    def _serialize_probe_tweet(tweet: TweetItem) -> dict[str, Any]:
        return {
            "status_id": tweet.status_id,
            "username": tweet.username,
            "link": tweet.x_url,
            "published": tweet.published,
            "text_preview": NitterWebAPI._text_preview(tweet.text),
            "media_count": len(tweet.media),
        }

    @staticmethod
    def _format_times(times: list[tuple[int, int]]) -> list[str]:
        return [f"{hour:02d}:{minute:02d}" for hour, minute in times]

    @staticmethod
    def _text_preview(text: str, limit: int = 160) -> str:
        text = " ".join(str(text or "").split())
        return text if len(text) <= limit else text[: limit - 1] + "…"

    @staticmethod
    def _terminology() -> dict[str, str]:
        return {
            "watch_users": "关注账号",
            "push_targets": "推送目标",
            "seen": "推送记录",
            "pending_queue": "暂存队列",
        }

    @staticmethod
    def _group_label(group: ScheduleGroup | None) -> str:
        if group is None:
            return "全部分组"
        return f"{group.name} ({group.group_id})"

    @staticmethod
    def _group_payload_label(group: ScheduleGroup) -> dict[str, str]:
        return {"group_id": group.group_id, "name": group.name}

    @staticmethod
    def _data_text(data: dict[str, Any], key: str) -> str:
        return str(data.get(key, "") or "").strip()

    @staticmethod
    def _parse_int(
        value: Any,
        fallback: int,
        *,
        minimum: int,
        maximum: int,
    ) -> int:
        try:
            number = int(value)
        except (TypeError, ValueError):
            number = fallback
        return max(minimum, min(maximum, number))

    @staticmethod
    def _parse_float(
        value: Any,
        fallback: float,
        *,
        minimum: float,
        maximum: float,
    ) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = fallback
        return max(minimum, min(maximum, number))

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
