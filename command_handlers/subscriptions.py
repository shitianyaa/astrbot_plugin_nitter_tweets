from __future__ import annotations

import re

from astrbot.api.all import logger
from astrbot.api.event import AstrMessageEvent
from astrbot.core.star.filter.command import GreedyStr

try:
    from ..config_compat import (
        TWEET_GROUP_TEMPLATE_KEY,
        TWEET_GROUP_TEMPLATE_KEY_FIELD,
        config_get,
        config_set,
    )
    from ..group_ids import (
        DEFAULT_GROUP_ALIASES,
        DEFAULT_GROUP_ID,
        DEFAULT_GROUP_NAME,
        normalize_group_id,
    )
    from ..scheduler_config import ScheduleGroup
    from ..utils import normalize_username
except ImportError:
    from config_compat import (
        TWEET_GROUP_TEMPLATE_KEY,
        TWEET_GROUP_TEMPLATE_KEY_FIELD,
        config_get,
        config_set,
    )
    from group_ids import (
        DEFAULT_GROUP_ALIASES,
        DEFAULT_GROUP_ID,
        DEFAULT_GROUP_NAME,
        normalize_group_id,
    )
    from scheduler_config import ScheduleGroup
    from utils import normalize_username


class SubscriptionCommandMixin:
    async def _cmd_tweets_list_impl(self, event: AstrMessageEvent):
        """查看已配置的定时订阅账号列表。"""
        event.stop_event()
        info = self.scheduler.watch_users_info()

        lines = [
            "Nitter 订阅账号列表",
            f"原配置项: {info.raw_count} 个",
            f"有效账号: {len(info.users)} 个",
            f"重复项: {len(info.duplicates)} 个",
            f"无效项: {len(info.invalid_entries)} 个",
        ]
        if info.users:
            lines.append("账号列表:")
            lines.extend(
                f"{index}. @{user}"
                for index, user in enumerate(info.users[:10], 1)
            )
            if len(info.users) > 10:
                lines.append(f"... 还有 {len(info.users) - 10} 个")
        else:
            lines.append("账号列表为空。")
        if info.duplicates:
            lines.append("重复项: " + self._format_limited_values(info.duplicates))
        if info.invalid_entries:
            lines.append(
                "无效项: " + self._format_limited_values(info.invalid_entries)
            )

        await event.send(event.plain_result("\n".join(lines)))

    async def _cmd_tweets_export_subscriptions_impl(self, event: AstrMessageEvent):
        """按分组导出已配置的订阅账号。"""
        event.stop_event()
        await event.send(
            event.plain_result("\n".join(self._export_subscription_lines()))
        )

    async def _cmd_tweets_delete_subscriptions_impl(self, event: AstrMessageEvent, args=GreedyStr):
        """批量删除定时订阅账号，可指定分组。"""
        event.stop_event()

        raw_entries, group, group_error = self._parse_subscription_import_args(args)
        if not raw_entries:
            await event.send(
                event.plain_result(
                    "用法：/订阅删除 nasa,@BBCWorld\n"
                    "指定分组：/订阅删除 nasa,@BBCWorld 科技"
                )
            )
            return
        if group_error:
            await event.send(
                event.plain_result(
                    "未找到分组："
                    f"{group_error}\n"
                    "可用分组: "
                    + self._format_limited_values(self._available_group_labels())
                )
            )
            return
        if len(raw_entries) > 50:
            await event.send(
                event.plain_result(
                    f"单次最多删除 50 个账号，本次输入 {len(raw_entries)} 个；"
                    "请分批删除。"
                )
            )
            return

        existing_users = group.users if group else self.scheduler.watch_users_info().users
        existing_by_key = {user.lower(): user for user in existing_users}
        delete_keys: set[str] = set()
        requested_users: list[str] = []
        duplicate_requests: list[str] = []
        invalid_entries: list[str] = []

        for raw in raw_entries:
            username = self._normalize_import_username(raw)
            if not username:
                invalid_entries.append(raw)
                continue
            username_key = username.lower()
            if username_key in delete_keys:
                duplicate_requests.append(raw)
                continue
            delete_keys.add(username_key)
            requested_users.append(username)

        removed = [
            existing_by_key[user.lower()]
            for user in requested_users
            if user.lower() in existing_by_key
        ]
        missing = [
            user for user in requested_users if user.lower() not in existing_by_key
        ]
        remaining_users = [
            user for user in existing_users if user.lower() not in delete_keys
        ]

        if removed:
            try:
                self._set_import_group_users(group, remaining_users)
            except RuntimeError as exc:
                await event.send(event.plain_result(str(exc)))
                return

        save_error = ""
        sync_error = ""
        if removed:
            save_config = getattr(self.config, "save_config", None)
            if callable(save_config):
                try:
                    save_config()
                except Exception as exc:
                    save_error = str(exc)
                    logger.warning(f"Failed to save deleted watch_users: {save_error}")
            else:
                save_error = "当前配置对象不支持 save_config()"
            sync_error = await self._sync_import_config_groups()

        group_label = self._import_group_label(group)
        config_target = self._import_config_target(group)
        lines = [
            "Nitter 订阅删除",
            f"删除分组: {group_label}",
            f"输入项: {len(raw_entries)} 个",
            f"删除: {len(removed)} 个",
            f"未关注: {len(missing)} 个",
            f"重复输入: {len(duplicate_requests)} 个",
            f"无效: {len(invalid_entries)} 个",
            f"当前分组关注: {len(remaining_users)} 个",
        ]
        if removed:
            lines.append(
                "已删除账号: "
                + self._format_limited_values([f"@{user}" for user in removed])
            )
            if save_error:
                lines.append(f"保存结果: 已更新运行时配置，但保存失败：{save_error}")
            else:
                lines.append(f"保存结果: 已写入 {config_target}。")
            if sync_error:
                lines.append(f"同步结果: 配置已更新，但数据库同步失败：{sync_error}")
        else:
            lines.append("保存结果: 没有删除账号。")
        if missing:
            lines.append(
                "未关注账号: "
                + self._format_limited_values([f"@{user}" for user in missing])
            )
        if duplicate_requests:
            lines.append("重复输入: " + self._format_limited_values(duplicate_requests))
        if invalid_entries:
            lines.append("无效项: " + self._format_limited_values(invalid_entries))

        await event.send(event.plain_result("\n".join(lines)))

    async def _cmd_tweets_dedup_impl(self, event: AstrMessageEvent):
        """规范化并去重定时订阅账号列表。"""
        event.stop_event()
        info = self.scheduler.deduplicate_watch_users()

        lines = [
            "Nitter 订阅账号去重",
            f"原配置项: {info.raw_count} 个",
            f"有效账号: {len(info.users)} 个",
            f"重复项: {len(info.duplicates)} 个",
            f"无效项: {len(info.invalid_entries)} 个",
        ]
        if info.changed:
            if info.saved:
                lines.append("结果: 已规范化并保存到默认分组。")
            elif info.save_error:
                lines.append(f"结果: 已更新运行时配置，但保存失败：{info.save_error}")
            else:
                lines.append("结果: 已更新运行时配置。")
        else:
            lines.append("结果: 默认分组订阅账号已经是去重后的规范列表。")

        if info.users:
            lines.append(
                "账号列表: "
                + self._format_limited_values([f"@{user}" for user in info.users])
            )
        if info.duplicates:
            lines.append("已移除重复: " + self._format_limited_values(info.duplicates))
        if info.invalid_entries:
            lines.append(
                "已移除无效: " + self._format_limited_values(info.invalid_entries)
            )

        await event.send(event.plain_result("\n".join(lines)))

    async def _cmd_tweets_import_impl(self, event: AstrMessageEvent, args=GreedyStr):
        """批量导入定时订阅账号，可指定分组。"""
        event.stop_event()

        raw_entries, group, group_error = self._parse_subscription_import_args(args)
        if not raw_entries:
            await event.send(
                event.plain_result(
                    "用法：/订阅导入 nasa,@BBCWorld,SpaceX\n"
                    "指定分组：/订阅导入 nasa,@BBCWorld 科技"
                )
            )
            return
        if group_error:
            await event.send(
                event.plain_result(
                    "未找到分组："
                    f"{group_error}\n"
                    "可用分组: "
                    + self._format_limited_values(self._available_group_labels())
                )
            )
            return
        existing_users = group.users if group else self.scheduler.watch_users_info().users
        seen = {user.lower() for user in existing_users}
        added: list[str] = []
        duplicates: list[str] = []
        invalid_entries: list[str] = []

        for raw in raw_entries:
            username = self._normalize_import_username(raw)
            if not username:
                invalid_entries.append(raw)
                continue
            username_key = username.lower()
            if username_key in seen:
                duplicates.append(raw)
                continue
            seen.add(username_key)
            added.append(username)

        if added:
            try:
                self._set_import_group_users(group, [*existing_users, *added])
            except RuntimeError as exc:
                await event.send(event.plain_result(str(exc)))
                return

        save_error = ""
        sync_error = ""
        if added:
            save_config = getattr(self.config, "save_config", None)
            if callable(save_config):
                try:
                    save_config()
                except Exception as exc:
                    save_error = str(exc)
                    logger.warning(
                        f"Failed to save imported watch_users: {save_error}"
                    )
            else:
                save_error = "当前配置对象不支持 save_config()"
            sync_error = await self._sync_import_config_groups()

        group_label = self._import_group_label(group)
        config_target = self._import_config_target(group)
        lines = [
            "Nitter 订阅导入",
            f"导入分组: {group_label}",
            f"输入项: {len(raw_entries)} 个",
            f"新增: {len(added)} 个",
            f"重复: {len(duplicates)} 个",
            f"无效: {len(invalid_entries)} 个",
            f"当前分组关注: {len(existing_users) + len(added)} 个",
        ]
        if added:
            lines.append(
                "新增账号: "
                + self._format_limited_values([f"@{user}" for user in added])
            )
            if save_error:
                lines.append(f"保存结果: 已更新运行时配置，但保存失败：{save_error}")
            else:
                lines.append(f"保存结果: 已写入 {config_target}。")
            if sync_error:
                lines.append(f"同步结果: 配置已更新，但数据库同步失败：{sync_error}")
        else:
            lines.append("保存结果: 没有新增账号。")
        if duplicates:
            lines.append("重复项: " + self._format_limited_values(duplicates))
        if invalid_entries:
            lines.append("无效项: " + self._format_limited_values(invalid_entries))

        await event.send(event.plain_result("\n".join(lines)))

    def _parse_subscription_import_args(
        self, args: str
    ) -> tuple[list[str], ScheduleGroup | None, str]:
        raw_text = str(args or "").strip()
        group: ScheduleGroup | None = None
        group_error = ""

        entries_text = raw_text
        match = re.match(r"(?s)^(.+?)\s+([^\s,]+)$", raw_text)
        if match:
            candidate = match.group(2).strip()
            resolved_group = self._resolve_import_group(candidate)
            if resolved_group is not None:
                group = resolved_group
                entries_text = match.group(1).strip()
            elif (
                "," in match.group(1)
                and not self._normalize_import_username(candidate)
            ):
                group_error = candidate

        entries = [
            item.strip()
            for item in entries_text.split(",")
            if item.strip()
        ]
        if entries and group is None and not group_error:
            group = self._ensure_default_import_group()
        return entries, group, group_error

    def _resolve_import_group(self, group_name: str) -> ScheduleGroup | None:
        group_name = str(group_name or "").strip()
        if not group_name:
            return None
        return self.scheduler.config_reader.schedule_group(
            group_name, log_invalid_targets=False
        )

    def _resolve_check_group_for_target(
        self, group_name: str, target_umo: str
    ) -> tuple[ScheduleGroup | None, str]:
        group_name = str(group_name or "").strip()
        target_umo = str(target_umo or "").strip()
        if not target_umo or target_umo == "unknown":
            return None, "无法识别当前对话，不能执行 /推文检查。"

        if group_name:
            group = self.scheduler.config_reader.schedule_group(
                group_name,
                log_invalid_targets=False,
            )
            if group is None:
                return (
                    None,
                    "未找到分组："
                    f"{group_name}\n可用分组: "
                    + self._format_limited_values(self._available_group_labels()),
                )
            if not group.enabled:
                return None, f"分组已禁用：{self._check_group_label(group)}"
            if target_umo not in group.targets:
                return (
                    None,
                    "当前对话不属于分组："
                    f"{self._check_group_label(group)}\n"
                    f"当前对话: {target_umo}",
                )
            return group, ""

        matches = [
            group
            for group in self.scheduler.config_reader.schedule_groups(
                log_invalid_targets=False
            )
            if (
                target_umo in group.targets
                and group.enabled
            )
        ]
        if matches:
            if len(matches) > 1:
                labels = [self._check_group_label(group) for group in matches]
                return (
                    None,
                    "当前对话匹配到多个推文分组，请使用 /推文检查 分组名 指定。\n"
                    "匹配分组: " + self._format_limited_values(labels),
                )
            return matches[0], ""

        return (
            None,
            "当前对话不在任何已启用用户分组的 push_targets 中，"
            "不会执行 /推文检查。\n"
            f"当前对话: {target_umo}",
        )

    def _available_group_labels(self) -> list[str]:
        groups = self.scheduler.config_reader.schedule_groups(
            log_invalid_targets=False
        )
        return [f"{group.name} ({group.group_id})" for group in groups]

    def _export_subscription_lines(self) -> list[str]:
        groups = self.scheduler.config_reader.schedule_groups(
            log_invalid_targets=False
        )
        return [
            f"{self._export_group_label(group)}: {','.join(group.users)}"
            for group in groups
        ]

    @staticmethod
    def _export_group_label(group: ScheduleGroup) -> str:
        if group.group_id == DEFAULT_GROUP_ID:
            return DEFAULT_GROUP_NAME
        return group.name or group.group_id

    @staticmethod
    def _import_group_label(group: ScheduleGroup | None) -> str:
        if group is None or group.group_id == DEFAULT_GROUP_ID:
            return f"{DEFAULT_GROUP_NAME} ({DEFAULT_GROUP_ID})"
        return f"{group.name} ({group.group_id})"

    @staticmethod
    def _check_group_label(group: ScheduleGroup) -> str:
        return f"{group.name} ({group.group_id})"

    @staticmethod
    def _import_config_target(group: ScheduleGroup | None) -> str:
        if group is None:
            return f"tweet_groups[{DEFAULT_GROUP_ID}].watch_users"
        return f"tweet_groups[{group.group_id}].watch_users"

    def _set_import_group_users(
        self, group: ScheduleGroup | None, users: list[str]
    ) -> None:
        if group is None:
            group = self._ensure_default_import_group()

        raw_groups = config_get(self.config, "tweet_groups", []) or []
        if isinstance(raw_groups, dict):
            group_items = [raw_groups]
        elif isinstance(raw_groups, list):
            group_items = raw_groups
        else:
            group_items = []

        target_group_id = normalize_group_id(group.group_id)
        for index, raw_group in enumerate(group_items, 1):
            parsed = self.scheduler.config_reader.parse_schedule_group(
                raw_group,
                index,
                log_invalid_targets=False,
            )
            if parsed is None:
                continue
            if normalize_group_id(parsed.group_id) != target_group_id:
                continue
            raw_group["watch_users"] = users
            config_set(self.config, "tweet_groups", raw_groups)
            return

        raise RuntimeError(f"未找到分组配置：{group.name} ({group.group_id})")

    def _ensure_default_import_group(self) -> ScheduleGroup:
        group = self.scheduler.config_reader.schedule_group(
            DEFAULT_GROUP_ID, log_invalid_targets=False
        )
        if group is not None:
            return group

        raw_groups = config_get(self.config, "tweet_groups", []) or []
        if isinstance(raw_groups, dict):
            raw_groups = [raw_groups]
        elif not isinstance(raw_groups, list):
            raw_groups = []

        default_group = {
            TWEET_GROUP_TEMPLATE_KEY_FIELD: TWEET_GROUP_TEMPLATE_KEY,
            "name": DEFAULT_GROUP_NAME,
            "group_id": DEFAULT_GROUP_ID,
            "aliases": list(DEFAULT_GROUP_ALIASES),
            "enabled": True,
            "watch_users": [],
            "push_targets": [],
        }
        raw_groups.insert(0, default_group)
        config_set(self.config, "tweet_groups", raw_groups)

        parsed = self.scheduler.config_reader.parse_schedule_group(
            default_group, 1, log_invalid_targets=False
        )
        if parsed is None:
            raise RuntimeError("无法创建默认分组配置")
        return parsed

    async def _sync_import_config_groups(self) -> str:
        try:
            schedule_groups = self.scheduler.config_reader.schedule_groups(
                log_invalid_targets=False
            )
            await self.scheduler.storage.migrate_and_sync(schedule_groups)
        except Exception as exc:
            logger.warning(f"Failed to sync imported watch_users: {exc}")
            return str(exc)
        return ""

    @staticmethod
    def _normalize_import_username(value: str) -> str:
        value = str(value or "").strip()
        if value.startswith("@"):
            value = value[1:].strip()
        if value.startswith(("http://", "https://")) or "/" in value:
            return ""
        return normalize_username(value)

    @staticmethod
    def _format_limited_values(values: list[str], limit: int = 10) -> str:
        shown = [str(item) for item in values[:limit]]
        if len(values) > limit:
            shown.append(f"... 还有 {len(values) - limit} 个")
        return ", ".join(shown)
