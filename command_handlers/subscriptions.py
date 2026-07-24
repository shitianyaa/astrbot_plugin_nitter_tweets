from __future__ import annotations

import re

from astrbot.api.all import logger
from astrbot.api.event import AstrMessageEvent
from astrbot.core.star.filter.command import GreedyStr

try:
    from ..config.subscriptions import (
        ensure_default_import_group,
        normalize_import_username,
        set_import_group_queries,
        set_import_group_users,
        sync_import_config_groups,
    )
    from ..media_support.html_backend import normalize_watch_query
    from ..shared.group_ids import (
        DEFAULT_GROUP_ID,
        DEFAULT_GROUP_NAME,
    )
    from ..scheduler import ScheduleGroup
except ImportError:
    from config.subscriptions import (
        ensure_default_import_group,
        normalize_import_username,
        set_import_group_queries,
        set_import_group_users,
        sync_import_config_groups,
    )
    from media_support.html_backend import normalize_watch_query
    from shared.group_ids import (
        DEFAULT_GROUP_ID,
        DEFAULT_GROUP_NAME,
    )
    from scheduler import ScheduleGroup


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
                f"{index}. @{user}" for index, user in enumerate(info.users[:10], 1)
            )
            if len(info.users) > 10:
                lines.append(f"... 还有 {len(info.users) - 10} 个")
        else:
            lines.append("账号列表为空。")
        if info.duplicates:
            lines.append("重复项: " + self._format_limited_values(info.duplicates))
        if info.invalid_entries:
            lines.append("无效项: " + self._format_limited_values(info.invalid_entries))

        await event.send(event.plain_result("\n".join(lines)))

    async def _cmd_tweets_export_subscriptions_impl(
        self, event: AstrMessageEvent, args=GreedyStr
    ):
        """按分组导出订阅（博主 users / 标签 queries）。可选分组名。"""
        event.stop_event()
        # GreedyStr is only a command-marker default; runtime empty is "" or non-str.
        group_name = args.strip() if isinstance(args, str) else ""
        groups = self.scheduler.config_reader.schedule_groups(log_invalid_targets=False)
        if group_name:
            group = self.scheduler.config_reader.schedule_group(
                group_name, log_invalid_targets=False
            )
            if group is None:
                await event.send(
                    event.plain_result(
                        f"未找到分组：{group_name}\n"
                        "可用分组: "
                        + self._format_limited_values(self._available_group_labels())
                    )
                )
                return
            groups = [group]

        blogger_count = sum(
            len(group.users) for group in groups if group.is_blogger_group
        )
        query_count = sum(len(group.queries) for group in groups if group.is_tag_group)
        logger.info(
            "[NitterTweets] 导出订阅配置: "
            f"groups={len(groups)}, blogger={blogger_count}, queries={query_count}"
            + (f", filter={group_name!r}" if group_name else "")
        )
        await event.send(
            event.plain_result("\n".join(self._export_subscription_lines(groups)))
        )

    async def _cmd_tweets_delete_subscriptions_impl(
        self, event: AstrMessageEvent, args=GreedyStr
    ):
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
        if group is not None and group.is_tag_group:
            await event.send(
                event.plain_result(
                    "该分组是标签分组，请使用 /标签删除；/订阅删除 仅用于博主分组。"
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

        existing_users = (
            group.users if group else self.scheduler.watch_users_info().users
        )
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
                    logger.warning(f"[NitterTweets] 保存订阅删除结果失败: {save_error}")
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
            f"原本未关注: {len(missing)} 个",
            f"重复输入: {len(duplicate_requests)} 个",
            f"无效: {len(invalid_entries)} 个",
            f"操作后分组关注: {len(remaining_users)} 个",
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
            lines.append("保存结果: 未改动配置，没有匹配到可删除账号。")
        if missing:
            lines.append(
                "原本未关注账号: "
                + self._format_limited_values([f"@{user}" for user in missing])
            )
        if duplicate_requests:
            lines.append("重复输入: " + self._format_limited_values(duplicate_requests))
        if invalid_entries:
            lines.append("无效项: " + self._format_limited_values(invalid_entries))

        logger.info(
            "[NitterTweets] 订阅删除完成: "
            f"group={group_label}, input={len(raw_entries)}, "
            f"removed={len(removed)}, missing={len(missing)}, "
            f"duplicate_input={len(duplicate_requests)}, "
            f"invalid={len(invalid_entries)}, remaining={len(remaining_users)}, "
            f"save_error={bool(save_error)}, sync_error={bool(sync_error)}"
        )
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
        if group is not None and group.is_tag_group:
            await event.send(
                event.plain_result(
                    "该分组是标签分组，请使用 /标签导入；/订阅导入 仅用于博主分组。"
                )
            )
            return

        existing_users = (
            group.users if group else self.scheduler.watch_users_info().users
        )
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
                    logger.warning(f"[NitterTweets] 保存订阅导入结果失败: {save_error}")
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
            f"已存在或重复输入: {len(duplicates)} 个",
            f"无效: {len(invalid_entries)} 个",
            f"操作后分组关注: {len(existing_users) + len(added)} 个",
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
            lines.append("保存结果: 未改动配置，没有可新增账号。")
        if duplicates:
            lines.append("已存在或重复输入: " + self._format_limited_values(duplicates))
        if invalid_entries:
            lines.append("无效项: " + self._format_limited_values(invalid_entries))

        logger.info(
            "[NitterTweets] 订阅导入完成: "
            f"group={group_label}, input={len(raw_entries)}, "
            f"added={len(added)}, duplicate_or_existing={len(duplicates)}, "
            f"invalid={len(invalid_entries)}, "
            f"total={len(existing_users) + len(added)}, "
            f"save_error={bool(save_error)}, sync_error={bool(sync_error)}"
        )
        await event.send(event.plain_result("\n".join(lines)))

    async def _cmd_tag_import_impl(self, event: AstrMessageEvent, args=GreedyStr):
        """批量导入标签分组搜索订阅。"""
        event.stop_event()

        raw_entries, group, group_error = self._parse_subscription_import_args(args)
        if not raw_entries:
            await event.send(
                event.plain_result(
                    "用法：/标签导入 #圣娅,python programming 分组名\n"
                    "必须指定标签分组；前导 # 为标签，否则为短语。"
                )
            )
            return
        if group_error:
            await event.send(
                event.plain_result(
                    "未找到分组："
                    f"{group_error}\n"
                    "可用标签分组: "
                    + self._format_limited_values(self._available_tag_group_labels())
                )
            )
            return
        if group is None or not group.is_tag_group:
            await event.send(
                event.plain_result(
                    "请指定标签分组（group_type=tag）。\n"
                    "可用标签分组: "
                    + self._format_limited_values(self._available_tag_group_labels())
                )
            )
            return
        if len(raw_entries) > 50:
            await event.send(
                event.plain_result(
                    f"单次最多导入 50 个查询，本次输入 {len(raw_entries)} 个；请分批导入。"
                )
            )
            return

        existing = [{"query": item.query, "type": item.type} for item in group.queries]
        seen_keys = {item.account_key for item in group.queries}
        added: list[dict[str, str]] = []
        duplicates: list[str] = []
        invalid_entries: list[str] = []

        for raw in raw_entries:
            query, kind = normalize_watch_query(raw, None)
            if not query:
                invalid_entries.append(raw)
                continue
            try:
                from ..media_support.html_backend import seen_account_key_for_query
            except ImportError:
                from media_support.html_backend import seen_account_key_for_query

            key = seen_account_key_for_query(query)
            if key in seen_keys:
                duplicates.append(raw)
                continue
            seen_keys.add(key)
            added.append({"query": query, "type": kind})

        if added:
            try:
                set_import_group_queries(
                    self.config,
                    self.scheduler.config_reader,
                    group,
                    [*existing, *added],
                )
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
                    logger.warning(f"[NitterTweets] 保存标签导入结果失败: {save_error}")
            else:
                save_error = "当前配置对象不支持 save_config()"
            sync_error = await self._sync_import_config_groups()

        group_label = self._import_group_label(group)
        lines = [
            "Nitter 标签导入",
            f"导入分组: {group_label}",
            f"输入项: {len(raw_entries)} 个",
            f"新增: {len(added)} 个",
            f"已存在或重复输入: {len(duplicates)} 个",
            f"无效: {len(invalid_entries)} 个",
            f"操作后查询数: {len(existing) + len(added)} 个",
        ]
        if added:
            lines.append(
                "新增查询: "
                + self._format_limited_values(
                    [f"{item['query']} ({item['type']})" for item in added]
                )
            )
            if save_error:
                lines.append(f"保存结果: 已更新运行时配置，但保存失败：{save_error}")
            else:
                lines.append(
                    f"保存结果: 已写入 tweet_groups[{group.group_id}].watch_queries。"
                )
            if sync_error:
                lines.append(f"同步结果: 配置已更新，但数据库同步失败：{sync_error}")
        else:
            lines.append("保存结果: 未改动配置，没有可新增查询。")
        if duplicates:
            lines.append("已存在或重复输入: " + self._format_limited_values(duplicates))
        if invalid_entries:
            lines.append("无效项: " + self._format_limited_values(invalid_entries))

        logger.info(
            "[NitterTweets] 标签导入完成: "
            f"group={group_label}, input={len(raw_entries)}, added={len(added)}, "
            f"dup={len(duplicates)}, invalid={len(invalid_entries)}"
        )
        await event.send(event.plain_result("\n".join(lines)))

    async def _cmd_tag_delete_impl(self, event: AstrMessageEvent, args=GreedyStr):
        """批量删除标签分组搜索订阅。"""
        event.stop_event()

        raw_entries, group, group_error = self._parse_subscription_import_args(args)
        if not raw_entries:
            await event.send(
                event.plain_result(
                    "用法：/标签删除 #圣娅,python programming 分组名\n"
                    "必须指定标签分组。"
                )
            )
            return
        if group_error:
            await event.send(
                event.plain_result(
                    "未找到分组："
                    f"{group_error}\n"
                    "可用标签分组: "
                    + self._format_limited_values(self._available_tag_group_labels())
                )
            )
            return
        if group is None or not group.is_tag_group:
            await event.send(
                event.plain_result(
                    "请指定标签分组（group_type=tag）。\n"
                    "可用标签分组: "
                    + self._format_limited_values(self._available_tag_group_labels())
                )
            )
            return
        if len(raw_entries) > 50:
            await event.send(
                event.plain_result(
                    f"单次最多删除 50 个查询，本次输入 {len(raw_entries)} 个；请分批删除。"
                )
            )
            return

        try:
            from ..media_support.html_backend import seen_account_key_for_query
        except ImportError:
            from media_support.html_backend import seen_account_key_for_query

        existing_items = list(group.queries)
        existing_by_key = {item.account_key: item for item in existing_items}
        delete_keys: set[str] = set()
        requested: list[str] = []
        duplicates: list[str] = []
        invalid_entries: list[str] = []

        for raw in raw_entries:
            query, _kind = normalize_watch_query(raw, None)
            if not query:
                invalid_entries.append(raw)
                continue
            key = seen_account_key_for_query(query)
            if key in delete_keys:
                duplicates.append(raw)
                continue
            delete_keys.add(key)
            requested.append(query)

        removed = [
            existing_by_key[key] for key in delete_keys if key in existing_by_key
        ]
        missing = [
            query
            for query in requested
            if seen_account_key_for_query(query) not in existing_by_key
        ]
        remaining = [
            {"query": item.query, "type": item.type}
            for item in existing_items
            if item.account_key not in delete_keys
        ]

        if removed:
            try:
                set_import_group_queries(
                    self.config,
                    self.scheduler.config_reader,
                    group,
                    remaining,
                )
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
                    logger.warning(f"[NitterTweets] 保存标签删除结果失败: {save_error}")
            else:
                save_error = "当前配置对象不支持 save_config()"
            sync_error = await self._sync_import_config_groups()

        group_label = self._import_group_label(group)
        lines = [
            "Nitter 标签删除",
            f"删除分组: {group_label}",
            f"输入项: {len(raw_entries)} 个",
            f"删除: {len(removed)} 个",
            f"原本未订阅: {len(missing)} 个",
            f"重复输入: {len(duplicates)} 个",
            f"无效: {len(invalid_entries)} 个",
            f"操作后查询数: {len(remaining)} 个",
        ]
        if removed:
            lines.append(
                "已删除查询: "
                + self._format_limited_values(
                    [f"{item.query} ({item.type})" for item in removed]
                )
            )
            if save_error:
                lines.append(f"保存结果: 已更新运行时配置，但保存失败：{save_error}")
            else:
                lines.append(
                    f"保存结果: 已写入 tweet_groups[{group.group_id}].watch_queries。"
                )
            if sync_error:
                lines.append(f"同步结果: 配置已更新，但数据库同步失败：{sync_error}")
        else:
            lines.append("保存结果: 未改动配置，没有匹配到可删除查询。")
        if missing:
            lines.append("原本未订阅: " + self._format_limited_values(missing))
        if duplicates:
            lines.append("重复输入: " + self._format_limited_values(duplicates))
        if invalid_entries:
            lines.append("无效项: " + self._format_limited_values(invalid_entries))

        logger.info(
            "[NitterTweets] 标签删除完成: "
            f"group={group_label}, removed={len(removed)}, missing={len(missing)}"
        )
        await event.send(event.plain_result("\n".join(lines)))

    def _available_tag_group_labels(self) -> list[str]:
        groups = self.scheduler.config_reader.schedule_groups(log_invalid_targets=False)
        return [
            f"{group.name} ({group.group_id})" for group in groups if group.is_tag_group
        ]

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
            elif "," in match.group(1) and not self._normalize_import_username(
                candidate
            ):
                group_error = candidate

        entries = [item.strip() for item in entries_text.split(",") if item.strip()]
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
            if (target_umo in group.targets and group.enabled)
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
        groups = self.scheduler.config_reader.schedule_groups(log_invalid_targets=False)
        return [f"{group.name} ({group.group_id})" for group in groups]

    def _export_subscription_lines(
        self, groups: list[ScheduleGroup] | None = None
    ) -> list[str]:
        groups = (
            self.scheduler.config_reader.schedule_groups(log_invalid_targets=False)
            if groups is None
            else groups
        )
        blogger_count = sum(
            len(group.users) for group in groups if group.is_blogger_group
        )
        query_count = sum(len(group.queries) for group in groups if group.is_tag_group)
        lines = [
            "Nitter 订阅导出",
            f"分组数: {len(groups)} 个",
            f"博主订阅: {blogger_count} 个",
            f"搜索订阅: {query_count} 个",
        ]
        if not groups:
            lines.append("没有可导出的分组。")
            return lines

        lines.append("订阅列表:")
        for group in groups:
            lines.append(self._format_export_group_line(group))
        lines.append(
            "提示: 博主组 /订阅导入 用户列表 分组名 ；标签组 /标签导入 查询列表 分组名"
        )
        return lines

    def _format_export_group_line(self, group: ScheduleGroup) -> str:
        label = self._export_group_label(group)
        if group.is_tag_group:
            items = (
                ",".join(item.query for item in group.queries)
                if group.queries
                else "（空）"
            )
            return f"{label} ({group.group_id}, 标签, {len(group.queries)} 个): {items}"
        items = ",".join(group.users) if group.users else "（空）"
        return f"{label} ({group.group_id}, 博主, {len(group.users)} 个): {items}"

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
        set_import_group_users(
            self.config,
            self.scheduler.config_reader,
            group,
            users,
        )

    def _ensure_default_import_group(self) -> ScheduleGroup:
        return ensure_default_import_group(
            self.config,
            self.scheduler.config_reader,
        )

    async def _sync_import_config_groups(self) -> str:
        return await sync_import_config_groups(self.scheduler)

    @staticmethod
    def _normalize_import_username(value: str) -> str:
        return normalize_import_username(value)

    @staticmethod
    def _format_limited_values(values: list[str], limit: int = 10) -> str:
        shown = [str(item) for item in values[:limit]]
        if len(values) > limit:
            shown.append(f"... 还有 {len(values) - limit} 个")
        return ", ".join(shown)
