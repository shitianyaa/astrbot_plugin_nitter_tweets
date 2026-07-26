"""WebUI 侧订阅导入与删除。

`NitterWebAPI` 的 mixin：只通过 `self` 协作，不 import 宿主类。
"""

from __future__ import annotations

from typing import Any

try:
    from ..config.subscriptions import (
        ensure_default_import_group,
        normalize_import_username,
        set_import_group_users,
        sync_import_config_groups,
    )
    from ..scheduler import ScheduleGroup
except ImportError:
    from config.subscriptions import (
        ensure_default_import_group,
        normalize_import_username,
        set_import_group_users,
        sync_import_config_groups,
    )
    from scheduler import ScheduleGroup

class WebAPISubscriptionsMixin:
    """subscriptions 批量维护。"""

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
            username = normalize_import_username(raw)
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
            set_import_group_users(
                self.config,
                self.scheduler.config_reader,
                group,
                [*existing_users, *added],
            )
            save_error = self._save_config()
            sync_error = await sync_import_config_groups(self.scheduler)
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
            },
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
            username = normalize_import_username(raw)
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
        missing = [user for user in requested if user.lower() not in existing_by_key]
        remaining = [user for user in existing_users if user.lower() not in delete_keys]

        if removed:
            set_import_group_users(
                self.config,
                self.scheduler.config_reader,
                group,
                remaining,
            )
            save_error = self._save_config()
            sync_error = await sync_import_config_groups(self.scheduler)
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
            },
        )

    def _subscription_group(
        self, data: dict[str, Any]
    ) -> tuple[ScheduleGroup | None, str]:
        group_id = self._data_text(data, "group_id") or self._data_text(
            data, "group_name"
        )
        if group_id:
            return self._resolve_group(group_id)
        return ensure_default_import_group(
            self.config,
            self.scheduler.config_reader,
        ), ""

    def _subscription_entries(self, data: dict[str, Any]) -> list[str]:
        raw = data.get("entries", data.get("users", ""))
        if isinstance(raw, list):
            return [str(item).strip() for item in raw if str(item).strip()]
        return [item.strip() for item in str(raw or "").split(",") if item.strip()]

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
