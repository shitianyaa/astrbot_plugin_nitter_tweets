from __future__ import annotations

import asyncio

from astrbot.api.event import AstrMessageEvent
from astrbot.core.star.filter.command import GreedyStr

try:
    from ..delivery import TweetSender
except ImportError:
    from delivery import TweetSender


class MaintenanceCommandMixin:
    async def _cmd_tweets_status_impl(self, event: AstrMessageEvent):
        """查看定时推文检查状态。"""
        event.stop_event()
        self.scheduler.start(reason="status_command")
        await event.send(event.plain_result(await self.scheduler.status_summary()))

    async def _cmd_tweets_check_impl(
        self,
        event: AstrMessageEvent,
        group_name: str = "",
    ):
        """立即执行一次定时推文检查。"""
        event.stop_event()
        group_name = self._strip_self_at_argument(event, group_name)
        target_umo = TweetSender.event_target(event)
        group, error = self._resolve_check_group_for_target(group_name, target_umo)
        if error:
            await event.send(event.plain_result(error))
            return

        self.scheduler.start(reason="manual_check")
        group_label = self._check_group_label(group)
        await event.send(event.plain_result(f"正在执行 Nitter 定时检查：{group_label}..."))
        result = await self.scheduler.run_check(
            reason="manual_command",
            notify_no_updates=False,
            group_name=group.group_id,
            target_override=[target_umo],
        )
        await event.send(event.plain_result(result.format_message()))

    async def _cmd_tweets_clear_cache_impl(self, event: AstrMessageEvent):
        """清理普通图片/视频缓存。"""
        event.stop_event()
        result = await asyncio.to_thread(self.media.clear_cache)
        await event.send(
            event.plain_result(
                "Nitter 普通媒体缓存清理完成\n"
                f"已删除文件: {result.removed}\n"
                f"删除失败: {result.failed}\n"
                f"已跳过目录: {result.skipped_dirs}"
            )
        )

    async def _cmd_tweets_clear_seen_impl(self, event: AstrMessageEvent, args=GreedyStr):
        """清理定时检查推送记录，并移除旧版 KV 推送记录。"""
        event.stop_event()
        tokens = self._command_tokens(event, args)
        if not tokens or tokens[-1] != "确认":
            await event.send(
                event.plain_result(
                    "用法：/推文记录清理 确认\n"
                    "指定分组：/推文记录清理 分组名 确认\n"
                    "会清理定时检查的防重复推送记录，不会删除订阅或媒体文件。"
                )
            )
            return

        group_name = " ".join(tokens[:-1]).strip()
        group = None
        if group_name and group_name.lower() not in {"all", "全部"}:
            group = self.scheduler.config_reader.schedule_group(
                group_name,
                log_invalid_targets=False,
            )
            if group is None:
                await event.send(
                    event.plain_result(
                        "未找到分组："
                        f"{group_name}\n可用分组: "
                        + self._format_limited_values(self._available_group_labels())
                    )
                )
                return

        deleted = await self.scheduler.storage.clear_seen_records(
            group.group_id if group else None
        )
        legacy_deleted = await self.scheduler.storage.delete_legacy_seen_kv()
        scope = self._check_group_label(group) if group else "全部分组"
        await event.send(
            event.plain_result(
                "Nitter 推送记录清理完成\n"
                f"范围: {scope}\n"
                f"SQLite 推送记录删除: {deleted} 条\n"
                f"旧版 KV 推送记录清理: {'已执行' if legacy_deleted else '无记录或不支持'}\n"
                "订阅配置和媒体文件未删除。"
            )
        )
