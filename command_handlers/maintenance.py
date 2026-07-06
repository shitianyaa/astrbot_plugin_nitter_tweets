from __future__ import annotations

import asyncio

from astrbot.api.event import AstrMessageEvent
from astrbot.core.star.filter.command import GreedyStr

try:
    from ..shared.group_ids import DEFAULT_GROUP_ID, DEFAULT_GROUP_NAME
    from ..delivery import TweetSender
except ImportError:
    from shared.group_ids import DEFAULT_GROUP_ID, DEFAULT_GROUP_NAME
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
            force_immediate=True,
        )
        pending_brief = await self.scheduler.check_pending_brief(group)
        await event.send(
            event.plain_result(result.format_message() + "\n\n" + pending_brief)
        )

    async def _cmd_tweets_clear_cache_impl(self, event: AstrMessageEvent):
        """清理普通图片/视频缓存，保留暂存队列媒体。"""
        event.stop_event()
        result = await asyncio.to_thread(self.media.clear_non_staged_cache)
        await event.send(
            event.plain_result(
                "Nitter 普通媒体缓存清理完成\n"
                f"已删除文件: {result.removed}\n"
                f"删除失败: {result.failed}\n"
                f"已跳过目录: {result.skipped_dirs}"
            )
        )

    async def _cmd_tweets_clear_seen_impl(self, event: AstrMessageEvent, args=GreedyStr):
        """清理定时检查 seen 记录，并移除旧版 KV seen 数据。"""
        event.stop_event()
        tokens = self._command_tokens(event, args)
        if not tokens or tokens[-1] != "确认":
            await event.send(
                event.plain_result(
                    "用法：/推文记录清理 确认\n"
                    "指定分组：/推文记录清理 分组名 确认\n"
                    "会清理定时检查的已记录推文索引，不会删除订阅、暂存队列或媒体文件。"
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
                "Nitter 已记录推文索引清理完成\n"
                f"范围: {scope}\n"
                f"SQLite seen 删除: {deleted} 条\n"
                f"旧版 KV seen 清理: {'已执行' if legacy_deleted else '无记录或不支持'}\n"
                "订阅配置、暂存队列和媒体文件未删除。"
            )
        )

    async def _cmd_tweets_queue_impl(
        self,
        event: AstrMessageEvent,
        group_name: str = "",
    ):
        """查看暂存发布队列。"""
        event.stop_event()
        group_name = self._strip_self_at_argument(event, group_name)
        self.scheduler.start(reason="queue_command")
        await event.send(
            event.plain_result(await self.scheduler.pending_queue_summary(group_name))
        )

    async def _cmd_tweets_publish_impl(
        self,
        event: AstrMessageEvent,
        group_name: str = "",
    ):
        """立即发布暂存队列中的推文。"""
        event.stop_event()
        group_name = self._strip_self_at_argument(event, group_name)
        self.scheduler.start(reason="publish_command")
        group_label = group_name or f"{DEFAULT_GROUP_NAME} ({DEFAULT_GROUP_ID})"
        await event.send(event.plain_result(f"正在发布 Nitter 暂存队列：{group_label}..."))
        result = await self.scheduler.publish_pending(
            group_name=group_name,
            reason="manual_publish_command",
        )
        await event.send(event.plain_result(result.format_message("Nitter 暂存发布结果")))
