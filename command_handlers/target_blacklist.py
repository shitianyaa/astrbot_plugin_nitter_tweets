from __future__ import annotations

from astrbot.api.event import AstrMessageEvent
from astrbot.core.star.filter.command import GreedyStr

try:
    from ..config import config_set
    from ..config.subscriptions import save_subscription_config
    from ..delivery import TweetSender
except ImportError:
    from config import config_set
    from config.subscriptions import save_subscription_config
    from delivery import TweetSender


class TargetBlacklistCommandMixin:
    """管理员命令：维护按推送目标共享的作者黑名单。"""

    async def _cmd_target_blacklist_impl(self, event: AstrMessageEvent, args=GreedyStr):
        """兼容旧的单命令入口，实际注册入口使用原生指令组子命令。"""
        tokens = self._command_tokens(event, args)
        action = tokens.pop(0).lower() if tokens else "list"
        aliases = {
            "add": "add",
            "添加": "add",
            "增加": "add",
            "remove": "remove",
            "del": "remove",
            "delete": "remove",
            "删除": "remove",
            "移除": "remove",
            "list": "list",
            "show": "list",
            "查看": "list",
            "查询": "list",
        }
        return await self._run_target_blacklist_action(
            event, aliases.get(action, ""), tokens
        )

    async def _cmd_target_blacklist_add_impl(
        self, event: AstrMessageEvent, args=GreedyStr
    ):
        return await self._run_target_blacklist_action(
            event, "add", self._command_tokens(event, args)
        )

    async def _cmd_target_blacklist_remove_impl(
        self, event: AstrMessageEvent, args=GreedyStr
    ):
        return await self._run_target_blacklist_action(
            event, "remove", self._command_tokens(event, args)
        )

    async def _cmd_target_blacklist_list_impl(
        self, event: AstrMessageEvent, args=GreedyStr
    ):
        return await self._run_target_blacklist_action(
            event, "list", self._command_tokens(event, args)
        )

    async def _run_target_blacklist_action(
        self, event: AstrMessageEvent, action: str, tokens: list[str]
    ):
        event.stop_event()
        if not action:
            await event.send(event.plain_result(self._target_blacklist_usage()))
            return

        target_umo, values = self._parse_target_blacklist_args(event, tokens)
        if action == "list":
            if values:
                await event.send(event.plain_result(self._target_blacklist_usage()))
                return
            await event.send(
                event.plain_result(self._format_target_blacklist(target_umo))
            )
            return

        if not target_umo or not values:
            await event.send(event.plain_result(self._target_blacklist_usage()))
            return

        parsed_users: list[tuple[str, str]] = []
        invalid: list[str] = []
        for raw_value in values:
            username = self.scheduler.config_reader.parse_watch_users([raw_value])
            if username.invalid_entries:
                invalid.extend(username.invalid_entries)
                continue
            if username.users:
                parsed_users.append((raw_value, username.users[0]))
        if invalid:
            await event.send(
                event.plain_result(
                    "无效博主用户名：" + self._format_limited_values(invalid)
                )
            )
            return

        normalized: list[str] = []
        duplicates: list[str] = []
        async with self.scheduler._target_blacklist_lock:
            info = self.scheduler.config_reader.parse_target_blocked_users()
            current = {
                target: list(users) for target, users in info.blocked_users.items()
            }
            users = current.setdefault(target_umo, [])
            seen = {username.casefold() for username in users}
            for raw_value, normalized_username in parsed_users:
                key = normalized_username.casefold()
                if action == "add":
                    if key in seen:
                        duplicates.append(raw_value)
                        continue
                    seen.add(key)
                    users.append(normalized_username)
                    normalized.append(normalized_username)
                else:
                    if key not in seen:
                        duplicates.append(raw_value)
                        continue
                    users[:] = [item for item in users if item.casefold() != key]
                    seen.remove(key)
                    normalized.append(normalized_username)
            if action == "remove" and not users:
                current.pop(target_umo, None)
            previous = {
                target: list(items) for target, items in info.blocked_users.items()
            }
            config_set(self.config, "target_blocked_users", current)
            save_error = save_subscription_config(self.config)
            if save_error:
                config_set(self.config, "target_blocked_users", previous)
            else:
                save_error = ""

        if save_error:
            await event.send(event.plain_result(f"保存失败：{save_error}"))
            return

        action_label = "已加入" if action == "add" else "已移除"
        lines = [
            f"目标：{target_umo}",
            f"{action_label}：{self._format_limited_values(normalized) if normalized else '无变化'}",
            f"当前黑名单：{len(users)} 个",
        ]
        if duplicates:
            lines.append("已存在或未找到：" + self._format_limited_values(duplicates))
        await event.send(event.plain_result("\n".join(lines)))

    def _parse_target_blacklist_args(
        self, event: AstrMessageEvent, tokens: list[str]
    ) -> tuple[str, list[str]]:
        target = ""
        values = list(tokens)
        if values and self._looks_like_target_umo(values[0]):
            target = self._normalize_target_umo(values.pop(0))
        else:
            target = TweetSender.event_target(event)
            target = self._normalize_target_umo(target)
        flattened: list[str] = []
        for value in values:
            flattened.extend(self.scheduler.config_reader.config_list(value))
        return target, flattened

    def _normalize_target_umo(self, value: str) -> str:
        target = str(value or "").strip().replace("：", ":")
        if not target or target == "unknown":
            return ""
        return (
            self.scheduler.config_reader.parse_target_to_umo(
                target, self.scheduler.config_reader.platform()
            )
            or ""
        )

    @staticmethod
    def _looks_like_target_umo(value: str) -> bool:
        text = str(value or "").strip()
        return text.count(":") >= 2 or text.startswith(("group:", "private:"))

    def _format_target_blacklist(self, target_umo: str) -> str:
        if target_umo:
            users = self.scheduler.config_reader.target_blocked_users().get(
                target_umo, []
            )
            if not users:
                return f"目标：{target_umo}\n黑名单为空。"
            lines = [f"目标：{target_umo}", f"黑名单：{len(users)} 个"]
            lines.extend(
                f"{index}. @{user}" for index, user in enumerate(users[:20], 1)
            )
            if len(users) > 20:
                lines.append(f"... 还有 {len(users) - 20} 个")
            return "\n".join(lines)

        mapping = self.scheduler.config_reader.target_blocked_users()
        if not mapping:
            return "当前没有配置推送目标黑名单。"
        lines = ["推送目标黑名单"]
        for target, users in mapping.items():
            lines.append(f"- {target}: {len(users)} 个")
        return "\n".join(lines)

    @staticmethod
    def _target_blacklist_usage() -> str:
        return (
            "用法：\n"
            "/推文黑名单 添加 用户名[,用户名]（使用当前会话目标）\n"
            "/推文黑名单 删除 用户名[,用户名]\n"
            "/推文黑名单 查看\n"
            "/推文黑名单 添加 <目标UMO> 用户名\n"
            "/推文黑名单 查看 <目标UMO>"
        )
