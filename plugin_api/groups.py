from __future__ import annotations

import copy
from typing import Any

from astrbot.api import logger

try:
    from ..config import (
        TWEET_GROUP_TEMPLATE_KEY,
        TWEET_GROUP_TEMPLATE_KEY_FIELD,
        config_get,
        config_set,
        sanitize_removed_feature_group,
    )
    from ..shared.group_ids import (
        infer_legacy_group_id_from_name,
        is_default_group,
        normalize_group_id,
        normalize_stable_group_id,
    )
except ImportError:
    from config import (
        TWEET_GROUP_TEMPLATE_KEY,
        TWEET_GROUP_TEMPLATE_KEY_FIELD,
        config_get,
        config_set,
        sanitize_removed_feature_group,
    )
    from shared.group_ids import (
        infer_legacy_group_id_from_name,
        is_default_group,
        normalize_group_id,
        normalize_stable_group_id,
    )


class WebUIGroupEditor:
    def __init__(self, plugin: Any) -> None:
        self.plugin = plugin
        self.config = plugin.config
        self.scheduler = plugin.scheduler

    def create_group(self, data: dict[str, Any] | None = None) -> dict[str, Any]:
        data = data or {}
        if self._text(data, "group_id"):
            return {"success": False, "error": "WebUI 不支持指定 group_id"}
        previous_groups = self._raw_groups()
        groups = copy.deepcopy(previous_groups)
        try:
            group_id = self._next_group_id(groups)
            group_name = self._validated_name(
                groups, self._text(data, "name") or self._next_group_name(groups)
            )
        except ValueError as exc:
            return {"success": False, "error": str(exc)}
        group_type = self._group_type(data.get("group_type"))
        template_key = (
            "tag" if group_type == "tag" else TWEET_GROUP_TEMPLATE_KEY
        )
        groups.append(
            {
                TWEET_GROUP_TEMPLATE_KEY_FIELD: template_key,
                "name": group_name,
                "group_id": group_id,
                "enabled": False,
                "group_type": group_type,
                "watch_users": [],
                "watch_queries": [],
                "push_targets": [],
                "interval_check_enabled": True,
                "daily_check_times": [],
                "filter_plain_text_enabled": False,
                "media_only_enabled": False,
                "omit_status_url", "hide_original_when_translated": True,
            }
        )
        save_error = self._save_groups(previous_groups, groups)
        if save_error:
            return {"success": False, "error": f"配置保存失败：{save_error}"}
        return {"success": True, "group_id": group_id}

    def update_group(self, data: dict[str, Any]) -> dict[str, Any]:
        if self._text(data, "new_group_id"):
            return {"success": False, "error": "WebUI 不支持修改 group_id"}

        group_id = self._text(data, "group_id")
        if not group_id:
            return {"success": False, "error": "请选择分组"}

        previous_groups = self._raw_groups()
        groups = copy.deepcopy(previous_groups)
        try:
            index, raw_group = self._find_group(groups, group_id)
        except KeyError:
            return {"success": False, "error": f"未找到分组：{group_id}"}

        try:
            name = self._validated_name(groups, self._text(data, "name"), index)
            daily_check_times = self._normalized_times(
                data.get("daily_check_times", raw_group.get("daily_check_times", []))
            )
            push_targets = self._normalized_list(
                data.get("push_targets", raw_group.get("push_targets", []))
            )
        except ValueError as exc:
            return {"success": False, "error": str(exc)}

        existing_type = self._group_type(raw_group.get("group_type"))
        if "group_type" in data:
            requested_type = self._group_type(data.get("group_type"))
            if requested_type != existing_type:
                return {
                    "success": False,
                    "error": "分组类型创建后不可修改，请新建对应类型的分组",
                }

        raw_group[TWEET_GROUP_TEMPLATE_KEY_FIELD] = (
            "tag" if existing_type == "tag" else TWEET_GROUP_TEMPLATE_KEY
        )
        raw_group["name"] = name
        raw_group["group_id"] = normalize_stable_group_id(group_id)
        raw_group["enabled"] = self._bool(
            data.get("enabled", raw_group.get("enabled", True))
        )
        raw_group["group_type"] = existing_type
        raw_group["interval_check_enabled"] = self._bool(
            data.get(
                "interval_check_enabled",
                raw_group.get("interval_check_enabled", True),
            )
        )
        raw_group["daily_check_times"] = daily_check_times
        raw_group["push_targets"] = push_targets
        raw_group["filter_plain_text_enabled"] = self._bool(
            data.get(
                "filter_plain_text_enabled",
                raw_group.get("filter_plain_text_enabled", False),
            )
        )
        raw_group["media_only_enabled"] = self._bool(
            data.get(
                "media_only_enabled",
                raw_group.get("media_only_enabled", False),
            )
        )
        raw_group["omit_status_url", "hide_original_when_translated"] = self._bool(
            data.get(
                "omit_status_url", "hide_original_when_translated",
                raw_group.get("omit_status_url", "hide_original_when_translated", True),
            ),
            True,
        )
        if existing_type == "tag":
            try:
                raw_group["watch_queries"] = self._normalized_watch_queries(
                    data.get("watch_queries", raw_group.get("watch_queries", []))
                )
            except ValueError as exc:
                return {"success": False, "error": str(exc)}
            raw_group["watch_users"] = []
        else:
            if "watch_users" in data:
                raw_group["watch_users"] = self._normalized_list(
                    data.get("watch_users")
                )
            raw_group.setdefault("watch_users", raw_group.get("watch_users") or [])
            raw_group["watch_queries"] = []
        groups[index] = raw_group
        save_error = self._save_groups(previous_groups, groups)
        if save_error:
            return {"success": False, "error": f"配置保存失败：{save_error}"}
        return {"success": True, "group_id": raw_group["group_id"]}

    def delete_group(self, data: dict[str, Any]) -> dict[str, Any]:
        group_id = self._text(data, "group_id")
        if not group_id:
            return {"success": False, "error": "请选择分组"}
        if is_default_group(group_id):
            return {"success": False, "error": "默认分组不能在 WebUI 中删除"}
        if not self._bool(data.get("force")) or self._text(data, "confirm") != "DELETE":
            return {"success": False, "error": "删除分组需要二次确认"}

        previous_groups = self._raw_groups()
        groups = copy.deepcopy(previous_groups)
        try:
            index, raw_group = self._find_group(groups, group_id)
        except KeyError:
            return {"success": False, "error": f"未找到分组：{group_id}"}

        deleted = groups.pop(index)
        save_error = self._save_groups(previous_groups, groups)
        if save_error:
            return {"success": False, "error": f"配置保存失败：{save_error}"}
        return {
            "success": True,
            "group_id": normalize_stable_group_id(group_id),
            "group_name": str(deleted.get("name") or group_id),
        }

    def _raw_groups(self) -> list[dict[str, Any]]:
        raw_groups = config_get(self.config, "tweet_groups", []) or []
        if isinstance(raw_groups, dict):
            return [copy.deepcopy(raw_groups)]
        if isinstance(raw_groups, list):
            return copy.deepcopy(raw_groups)
        return []

    def _save_groups(
        self,
        previous_groups: list[dict[str, Any]],
        next_groups: list[dict[str, Any]],
    ) -> str:
        for group in next_groups:
            if isinstance(group, dict):
                sanitize_removed_feature_group(group)
        config_set(self.config, "tweet_groups", next_groups)
        save_config = getattr(self.config, "save_config", None)
        if not callable(save_config):
            config_set(self.config, "tweet_groups", previous_groups)
            return "当前配置对象不支持 save_config()"
        try:
            save_config()
        except Exception as exc:
            config_set(self.config, "tweet_groups", previous_groups)
            error = str(exc)
            logger.warning(f"[NitterTweets] WebUI 保存分组配置失败: {error}")
            return error
        return ""

    def _next_group_id(self, groups: list[dict[str, Any]]) -> str:
        existing = {
            self._group_identifier(raw_group, index)
            for index, raw_group in enumerate(groups, 1)
        }
        counter = 1
        while True:
            candidate = f"group_{counter}"
            if candidate not in existing:
                return candidate
            counter += 1

    def _next_group_name(self, groups: list[dict[str, Any]]) -> str:
        counter = 1
        while True:
            candidate = f"新分组 {counter}"
            try:
                return self._validated_name(groups, candidate)
            except ValueError:
                counter += 1

    def _find_group(
        self, groups: list[dict[str, Any]], group_id: str
    ) -> tuple[int, dict[str, Any]]:
        target = normalize_group_id(group_id)
        for index, raw_group in enumerate(groups):
            if self._group_identifier(raw_group, index + 1) == target:
                return index, raw_group
        raise KeyError(target)

    def _validated_name(
        self,
        groups: list[dict[str, Any]],
        value: str,
        exclude_index: int | None = None,
    ) -> str:
        name = str(value or "").strip()
        if not name:
            raise ValueError("分组名称不能为空")
        normalized = normalize_group_id(name)
        for index, raw_group in enumerate(groups):
            if exclude_index is not None and index == exclude_index:
                continue
            if normalized in self._group_identifiers(raw_group, index + 1):
                raise ValueError("分组名称与现有分组标识冲突")
        return name

    def _normalized_times(self, raw_times: Any) -> list[str]:
        values = [
            str(item).strip().replace("：", ":")
            for item in self.scheduler.config_reader.config_list(raw_times)
            if str(item).strip()
        ]
        if not values:
            return []
        parsed = self.scheduler.config_reader.parse_daily_times(values)
        if len(parsed) != len(values):
            raise ValueError("每日检查时间格式无效，请使用 HH:MM")
        return [f"{hour:02d}:{minute:02d}" for hour, minute in parsed]

    def _normalized_list(self, raw_values: Any) -> list[str]:
        values: list[str] = []
        seen: set[str] = set()
        for raw in self.scheduler.config_reader.config_list(raw_values):
            value = str(raw).strip()
            if not value or value in seen:
                continue
            seen.add(value)
            values.append(value)
        return values

    @staticmethod
    def _group_type(value: Any) -> str:
        text = str(value or "").strip().lower()
        if text in {"tag", "search", "query", "keyword"}:
            return "tag"
        return "blogger"

    def _normalized_watch_queries(self, raw_values: Any) -> list[dict[str, str]]:
        info = self.scheduler.config_reader.parse_watch_queries(raw_values)
        if info.invalid_entries:
            raise ValueError("搜索订阅无效：" + ", ".join(info.invalid_entries[:5]))
        return [{"query": item.query, "type": item.type} for item in info.queries]

    @staticmethod
    def _bool(value: Any) -> bool:
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"false", "0", "off", "no", "否", "关闭"}:
                return False
            if normalized in {"true", "1", "on", "yes", "是", "开启"}:
                return True
        return bool(value)

    def _group_identifier(self, raw_group: dict[str, Any], index: int) -> str:
        raw_group_id = str(raw_group.get("group_id") or "").strip()
        name = str(raw_group.get("name") or "").strip()
        if raw_group_id:
            return normalize_stable_group_id(raw_group_id)
        inferred_group_id = infer_legacy_group_id_from_name(name)
        if inferred_group_id:
            return inferred_group_id
        return normalize_stable_group_id(f"group_{index}")

    def _group_identifiers(self, raw_group: dict[str, Any], index: int) -> set[str]:
        identifiers = {self._group_identifier(raw_group, index)}
        name = str(raw_group.get("name") or "").strip()
        if name:
            identifiers.add(normalize_group_id(name))
        for alias in self.scheduler.config_reader.config_list(raw_group.get("aliases")):
            identifiers.add(normalize_group_id(alias))
        return identifiers

    @staticmethod
    def _text(data: dict[str, Any], key: str) -> str:
        return str(data.get(key, "") or "").strip()
