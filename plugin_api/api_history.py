"""推送历史查询、孤儿清理与回放。

`NitterWebAPI` 的 mixin：只通过 `self` 协作，不 import 宿主类。
"""

from __future__ import annotations

import math
from typing import Any

try:
    from ..scheduler import ScheduleGroup
    from ..shared import format_subscription_source
    from ..shared.group_ids import normalize_stable_group_id
    from ..storage import PushHistoryGroupSummary, PushHistoryRecord
    from .api_serializers import WebAPISerializersMixin
except ImportError:
    from plugin_api.api_serializers import WebAPISerializersMixin
    from scheduler import ScheduleGroup
    from shared import format_subscription_source
    from shared.group_ids import normalize_stable_group_id
    from storage import PushHistoryGroupSummary, PushHistoryRecord


class WebAPIHistoryMixin:
    """push history 读取与序列化。"""

    async def build_history(
        self,
        group_id: str = "",
        username: str = "",
        limit: int = 10,
        offset: int = 0,
    ) -> dict[str, Any]:
        group_id = str(group_id or "").strip()
        username = str(username or "").strip().lstrip("@")
        limit = max(1, min(int(limit or 10), 50))
        offset = max(0, int(offset or 0))
        if group_id:
            group, error = self._resolve_group(group_id)
            if error:
                return self._error(error)
            group_id = group.group_id
        total_count = await self.storage.count_push_history(group_id, username)
        total_pages = max(1, math.ceil(total_count / limit))
        records = await self.storage.get_push_history(
            group_id,
            username,
            limit + 1,
            offset,
        )
        group_names = {group.group_id: group.name for group in self._schedule_groups()}
        groups_by_id = {group.group_id: group for group in self._schedule_groups()}
        grouped_records = self._group_history_records(
            records, group_names, groups_by_id
        )
        has_next = len(grouped_records) > limit
        visible_records = grouped_records[:limit]
        return self._ok(
            selected_group_id=group_id,
            selected_username=username,
            limit=limit,
            offset=offset,
            page=(offset // limit) + 1,
            total_count=total_count,
            total_pages=total_pages,
            has_prev=offset > 0,
            has_next=has_next,
            prev_offset=max(0, offset - limit),
            next_offset=offset + limit if has_next else offset,
            records=visible_records,
            terminology=self._terminology(),
        )

    async def build_history_orphans(self) -> dict[str, Any]:
        groups = self._schedule_groups()
        configured_ids = {normalize_stable_group_id(group.group_id) for group in groups}
        summaries = await self.storage.get_push_history_group_summaries()
        orphans = [
            self._serialize_history_group_summary(summary)
            for summary in summaries
            if normalize_stable_group_id(summary.group_id) not in configured_ids
        ]
        return self._ok(
            orphans=orphans,
            terminology=self._terminology(),
        )

    async def delete_history_orphan(self, data: dict[str, Any]) -> dict[str, Any]:
        raw_group_id = self._data_text(data, "group_id")
        if not raw_group_id:
            return self._error("请选择要清理的分组 ID")
        group_id = normalize_stable_group_id(raw_group_id)
        configured_ids = {
            normalize_stable_group_id(group.group_id)
            for group in self._schedule_groups()
        }
        if group_id in configured_ids:
            return self._error(f"分组仍存在，不能作为失效分组清理：{group_id}")
        if self._data_text(data, "confirm") != "DELETE":
            return self._error("清理失效分组运行数据需要显式确认")

        summary = await self.storage.delete_orphan_group_runtime_data(group_id)
        return self._ok(
            group_id=group_id,
            summary=summary,
        )

    async def replay_history(self, data: dict[str, Any]) -> dict[str, Any]:
        record_id = self._parse_int(
            self._data_text(data, "record_id") or data.get("record_id"),
            0,
            minimum=0,
            maximum=10_000_000_000,
        )
        if record_id <= 0:
            return self._error("请选择要重新推送的记录")
        target_umos = self._data_text_list(data, "target_umos")
        result = await self.scheduler.replay_push_history(record_id, target_umos)
        if not result.get("success"):
            return result
        return self._ok(**result)

    @staticmethod
    def _serialize_history_record(
        record: PushHistoryRecord,
        group_names: dict[str, str],
        group_type: str = "blogger",
    ) -> dict[str, Any]:
        tweet = record.tweet
        return {
            "id": record.id,
            "group_id": record.group_id,
            "group_name": group_names.get(record.group_id, record.group_id),
            "username": record.username,
            "subscription_source": format_subscription_source(
                record.username, group_type
            ),
            "status_id": record.status_id,
            "original_link": record.original_link or tweet.x_url,
            "target_umo": record.target_umo,
            "source": record.source,
            "instance": record.instance,
            "pushed_at": record.pushed_at,
            "delivery_status": record.delivery_status,
            "delivery_error": record.delivery_error,
            "published": tweet.published,
            "text_preview": WebAPISerializersMixin._text_preview(tweet.text),
            "translation_preview": WebAPISerializersMixin._text_preview(
                tweet.translation
            ),
        }

    @staticmethod
    def _serialize_history_group_summary(
        summary: PushHistoryGroupSummary,
    ) -> dict[str, Any]:
        return {
            "group_id": summary.group_id,
            "record_count": summary.record_count,
            "user_count": summary.user_count,
            "latest_pushed_at": summary.latest_pushed_at,
        }

    @staticmethod
    def _group_history_records(
        records: list[PushHistoryRecord],
        group_names: dict[str, str],
        groups_by_id: dict[str, ScheduleGroup],
    ) -> list[dict[str, Any]]:
        grouped: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
        order: list[tuple[str, str, str, str, str]] = []
        latest_delivery_by_key: dict[
            tuple[str, str, str, str, str],
            dict[str, tuple[int, int, str, str]],
        ] = {}
        for record in records:
            key = (
                record.group_id,
                record.username,
                record.status_id,
                record.source,
                record.original_link or record.tweet.x_url,
            )
            group = groups_by_id.get(record.group_id)
            group_type = str(getattr(group, "group_type", "") or "").strip().lower()
            if group_type not in {"blogger", "tag", "list"}:
                account_key = str(record.username or "").strip().lower()
                if account_key.startswith("q:"):
                    group_type = "tag"
                elif account_key.startswith("list:"):
                    group_type = "list"
                else:
                    group_type = "blogger"
            serialized = WebAPIHistoryMixin._serialize_history_record(
                record, group_names, group_type
            )
            item = grouped.get(key)
            if item is None:
                current_targets = list(getattr(group, "targets", []) or [])
                item = {
                    **serialized,
                    "group_type": group_type,
                    "subscription_source": format_subscription_source(
                        record.username, group_type
                    ),
                    "target_umos": [],
                    "target_count": 0,
                    "replay_target_options": [
                        {
                            "umo": target,
                            "historical": False,
                            "available": True,
                        }
                        for target in current_targets
                    ],
                }
                grouped[key] = item
                order.append(key)
                latest_delivery_by_key[key] = {}
            if record.target_umo and record.target_umo not in item["target_umos"]:
                item["target_umos"].append(record.target_umo)
            item["target_count"] = len(item["target_umos"])
            if int(record.pushed_at or 0) > int(item.get("pushed_at") or 0):
                item.update(serialized)
            target_key = record.target_umo or f"__record__:{record.id}"
            delivery_stamp = (int(record.pushed_at or 0), int(record.id or 0))
            latest_delivery = latest_delivery_by_key[key]
            previous = latest_delivery.get(target_key)
            if previous is None or delivery_stamp > previous[:2]:
                latest_delivery[target_key] = (
                    delivery_stamp[0],
                    delivery_stamp[1],
                    record.delivery_status,
                    record.delivery_error,
                )
            options_by_umo = {
                option["umo"]: option for option in item["replay_target_options"]
            }
            if record.target_umo:
                option = options_by_umo.get(record.target_umo)
                if option is None:
                    item["replay_target_options"].append(
                        {
                            "umo": record.target_umo,
                            "historical": True,
                            "available": False,
                        }
                    )
                else:
                    option["historical"] = True
        for key, item in grouped.items():
            latest_states = list(latest_delivery_by_key[key].values())
            has_failed = any(
                status == "failed"
                for _pushed_at, _record_id, status, _error in latest_states
            )
            has_partial = any(
                status == "partial_failed"
                for _pushed_at, _record_id, status, _error in latest_states
            )
            has_success = any(
                status == "success"
                for _pushed_at, _record_id, status, _error in latest_states
            )
            delivery_errors = list(
                dict.fromkeys(
                    str(error).strip()
                    for _pushed_at, _record_id, status, error in latest_states
                    if status in {"failed", "partial_failed"} and str(error).strip()
                )
            )
            if has_failed and not has_partial and not has_success:
                item["delivery_status"] = "failed"
                item["delivery_error"] = "; ".join(delivery_errors)
            elif has_failed or has_partial:
                item["delivery_status"] = "partial_failed"
                item["delivery_error"] = "; ".join(delivery_errors)
            else:
                item["delivery_status"] = "success"
                item["delivery_error"] = ""
        return [grouped[key] for key in order]
