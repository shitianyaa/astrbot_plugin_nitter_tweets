from __future__ import annotations

import asyncio
import re
import time

from astrbot.api.all import At, AstrBotConfig, Context, MessageChain, Plain, Star, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import register
from astrbot.core.star.filter.command import GreedyStr

try:
    from .config_compat import config_get, config_set, migrate_legacy_grouped_config
    from .enricher import TweetEnricher, TweetTranslator, format_ai_tweet_summary
    from .media import MediaService, NitterClient
    from .scheduler import NitterTweetScheduler
    from .scheduler_config import ScheduleGroup
    from .seen_store import GLOBAL_GROUP_ID, normalize_group_id
    from .sender import TweetSender
    from .utils import clamp_float, normalize_username, safe_call
except ImportError:
    from config_compat import config_get, config_set, migrate_legacy_grouped_config
    from enricher import TweetEnricher, TweetTranslator, format_ai_tweet_summary
    from media import MediaService, NitterClient
    from scheduler import NitterTweetScheduler
    from scheduler_config import ScheduleGroup
    from seen_store import GLOBAL_GROUP_ID, normalize_group_id
    from sender import TweetSender
    from utils import clamp_float, normalize_username, safe_call


@register(
    "astrbot_plugin_nitter_tweets",
    "shitianyaa",
    "Fetch recent public tweets from Nitter and send them as chat records.",
    "0.9.0",
    "https://github.com/shitianyaa/astrbot_plugin_nitter_tweets",
)
class NitterTweetsPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        migrate_legacy_grouped_config(self.config)
        self.nitter = NitterClient(config)
        self.media = MediaService(config)
        self.sender = TweetSender(config)
        self.translator = TweetTranslator(context, config)
        self.enricher = TweetEnricher(context, config)
        self.scheduler = NitterTweetScheduler(
            self,
            context,
            config,
            self.nitter,
            self.media,
            self.sender,
            self.translator,
            self.enricher,
        )
        self.default_limit = self._parse_positive_limit(
            config_get(config, "default_limit", 5), 5
        )
        self.cooldown_seconds = clamp_float(
            config_get(config, "cooldown_seconds", 15.0), 0.0, 3600.0
        )
        self._cooldowns: dict[str, float] = {}
        self.scheduler.start(reason="__init__")

    async def initialize(self):
        logger.info(
            "Nitter tweets plugin loaded: "
            f"{len(self.nitter.instances)} instances, "
            "media="
            f"image:{'on' if self.media.send_image_attachments else 'off'},"
            f"video:{'on' if self.media.send_video_attachments else 'off'}, "
            f"translate={'on' if self.translator.enabled else 'off'}, "
            f"ai_enrich={'on' if self.enricher.enabled else 'off'}, "
            f"qq_merge_threshold={self.sender.merge_tweet_threshold}"
        )
        self.scheduler.start(reason="initialize")

    @filter.on_astrbot_loaded()
    async def on_loaded(self):
        """AstrBot 加载完成后启动 Nitter 定时推文调度器。"""
        self.scheduler.start(reason="on_astrbot_loaded")

    async def terminate(self):
        await self.scheduler.stop()

    @filter.command("推文")
    async def cmd_tweets(
        self,
        event: AstrMessageEvent,
        username: str = "",
        limit: str = "",
    ):
        """获取指定公开 X/Twitter 用户的最近推文。"""
        event.stop_event()

        username = normalize_username(username)
        if not username:
            await event.send(
                event.plain_result(
                    "用法：/推文 用户名 [数量]\n例如：/推文 nasa 5"
                )
            )
            return

        cooldown_left = self._cooldown_left(event)
        if cooldown_left > 0:
            await event.send(event.plain_result(f"请求太快啦，{cooldown_left:.0f} 秒后再试。"))
            return

        limit_text = self._strip_self_at_argument(event, limit)
        if limit_text:
            parsed_limit, limit_error = self._parse_command_limit(limit_text)
            if limit_error:
                await event.send(event.plain_result(limit_error))
                return
            requested_limit = parsed_limit
        else:
            requested_limit = self.default_limit
        limit = requested_limit
        self._mark_cooldown(event)
        await event.send(
            event.plain_result(f"正在获取 @{username} 最近最多 {limit} 条推文...")
        )

        try:
            instance, tweets = await self.nitter.fetch_tweets(username, limit)
        except Exception as exc:
            logger.warning(f"Failed to fetch tweets for @{username}: {exc}")
            await event.send(
                event.plain_result(
                    f"获取 @{username} 推文失败：Nitter 实例暂时不可用或该用户无公开 RSS。"
                )
            )
            return

        if not tweets:
            await event.send(event.plain_result(f"没有找到 @{username} 的公开推文。"))
            return

        await self._send_tweets_response(event, username, instance, tweets)

    @filter.command("镜像测试")
    async def cmd_mirror_probe(self, event: AstrMessageEvent, args=GreedyStr):
        """用临时 Nitter 镜像站测试获取推文。"""
        event.stop_event()

        parsed = self._parse_mirror_probe_args(event, args)
        if parsed[3]:
            await event.send(event.plain_result(parsed[3]))
            return
        username, limit, instance_text, _ = parsed

        cooldown_left = self._cooldown_left(event)
        if cooldown_left > 0:
            await event.send(event.plain_result(f"请求太快啦，{cooldown_left:.0f} 秒后再试。"))
            return

        self._mark_cooldown(event)
        await event.send(
            event.plain_result(
                f"正在测试 {instance_text}：获取 @{username} 最近最多 {limit} 条推文..."
            )
        )

        try:
            instance, tweets = await self.nitter.fetch_tweets_from_instance(
                instance_text, username, limit
            )
        except Exception as exc:
            logger.warning(
                f"Failed to test Nitter instance {instance_text} for @{username}: {exc}"
            )
            await event.send(
                event.plain_result(
                    f"通过 {instance_text} 获取 @{username} 推文失败："
                    "Nitter 镜像站暂时不可用或该用户无公开 RSS。"
                )
            )
            return

        if not tweets:
            await event.send(event.plain_result(f"没有找到 @{username} 的公开推文。"))
            return

        await self._send_tweets_response(event, username, instance, tweets)

    async def _send_tweets_response(
        self,
        event: AstrMessageEvent,
        username: str,
        instance: str,
        tweets,
    ) -> None:
        if self.sender.should_merge_for_event(event, len(tweets)):
            notices = []
            try:
                for tweet_index, tweet in enumerate(tweets, 1):
                    notices.extend(
                        await self._prepare_manual_tweets(
                            [tweet],
                            event.unified_msg_origin,
                            username=username,
                            progress_index=tweet_index,
                            progress_total=len(tweets),
                        )
                    )
                await self._send_manual_tweets_with_fallback(
                    event,
                    username,
                    instance,
                    tweets,
                    notices=self._dedupe_texts(notices),
                )
            finally:
                await asyncio.to_thread(self.media.cleanup_after_send, tweets)
            return

        sent_notices: set[str] = set()
        total = len(tweets)
        for index, tweet in enumerate(tweets, 1):
            try:
                notices = await self._prepare_manual_tweets(
                    [tweet],
                    event.unified_msg_origin,
                    username=username,
                    progress_index=index,
                    progress_total=total,
                )
                notices = [
                    notice for notice in notices if notice not in sent_notices
                ]
                sent_notices.update(notices)
                await self._send_manual_tweets_with_fallback(
                    event,
                    username,
                    instance,
                    [tweet],
                    notices=notices,
                    header_text=f"@{username} 本次结果 {index}/{total}",
                )
            finally:
                await asyncio.to_thread(self.media.cleanup_after_send, [tweet])

    async def _prepare_manual_tweets(
        self,
        tweets,
        umo: str | None,
        username: str = "",
        progress_index: int = 0,
        progress_total: int = 0,
    ) -> list[str]:
        translation_report = await self.translator.attach_translations(tweets, umo)
        await self.media.attach_media(tweets)
        enrich_report = await self.enricher.attach_enrichments(tweets, umo)
        if username:
            self._log_ai_process_results(
                username,
                tweets,
                translation_report,
                enrich_report,
                progress_index,
                progress_total,
            )
        return enrich_report.visible_notices()

    def _log_ai_process_results(
        self,
        username: str,
        tweets,
        translation_report=None,
        enrich_report=None,
        progress_index: int = 0,
        progress_total: int = 0,
    ) -> None:
        total = progress_total or len(tweets)
        start = progress_index or 1
        for offset, tweet in enumerate(tweets):
            logger.info(
                format_ai_tweet_summary(
                    username,
                    tweet,
                    translation_report,
                    enrich_report,
                    start + offset,
                    total,
                )
            )

    async def _send_manual_tweets_with_fallback(
        self,
        event: AstrMessageEvent,
        username: str,
        instance: str,
        tweets,
        notices: list[str] | None = None,
        header_text: str = "",
    ) -> None:
        notices = notices or []
        if await self.sender.send(
            event,
            username,
            instance,
            tweets,
            notices=notices,
            header_text=header_text,
        ):
            return
        fallback_text = self.sender.renderer.format_plain(
            username,
            instance,
            tweets,
            notices=notices,
            header_text=header_text,
        )
        try:
            await event.send(MessageChain([Plain(fallback_text)]))
        except Exception as exc:
            logger.warning(f"Failed to send manual tweet fallback: {exc}")
            try:
                await event.send(
                    MessageChain(
                        [
                            Plain(
                                f"已获取 @{username} 的推文，但发送失败。"
                                "请查看插件日志或稍后重试。"
                            )
                        ]
                    )
                )
            except Exception as notice_exc:
                logger.warning(
                    "Failed to send manual tweet failure notice: "
                    f"{notice_exc}"
                )

    @staticmethod
    def _dedupe_texts(values: list[str]) -> list[str]:
        result = []
        seen = set()
        for value in values:
            if value in seen:
                continue
            seen.add(value)
            result.append(value)
        return result

    def _parse_mirror_probe_args(
        self,
        event: AstrMessageEvent,
        args: str,
    ) -> tuple[str, int, str, str]:
        tokens = self._command_tokens(event, args)
        usage = (
            "用法：/镜像测试 [用户名] [数量] 镜像站\n"
            "镜像站必须填写完整 http:// 或 https:// 地址\n"
            "例如：/镜像测试 https://nitter.net\n"
            "也可以：/镜像测试 nasa 3 https://nitter.net"
        )
        if not tokens:
            return "", 0, "", usage

        instance_index = -1
        for index, token in enumerate(tokens):
            if self._looks_like_instance(token):
                instance_index = index
        if instance_index < 0:
            return "", 0, "", (
                "请提供完整 Nitter 镜像站地址，例如：/镜像测试 https://nitter.net"
            )

        instance_text = tokens[instance_index]
        extras = tokens[:instance_index] + tokens[instance_index + 1 :]
        if len(extras) > 2:
            return "", 0, "", usage

        username = "nasa"
        requested_limit = self.default_limit
        seen_username = False
        seen_limit = False
        for token in extras:
            if self._looks_like_limit(token):
                if seen_limit:
                    return "", 0, "", (
                        "数量只能填写一次，例如：/镜像测试 3 https://nitter.net"
                    )
                parsed_limit, limit_error = self._parse_command_limit(token)
                if limit_error:
                    return "", 0, "", limit_error
                requested_limit = parsed_limit
                seen_limit = True
                continue

            normalized = normalize_username(token)
            if not normalized:
                return "", 0, "", usage
            if seen_username:
                return "", 0, "", (
                    "用户名只能填写一次，例如：/镜像测试 nasa https://nitter.net"
                )
            username = normalized
            seen_username = True

        return username, requested_limit, instance_text, ""

    @staticmethod
    def _parse_positive_limit(value, fallback: int) -> int:
        try:
            number = int(value)
        except (TypeError, ValueError):
            return fallback
        return number if number > 0 else fallback

    @classmethod
    def _parse_command_limit(cls, value: str) -> tuple[int, str]:
        try:
            number = int(str(value).strip())
        except (TypeError, ValueError):
            return 0, "数量需要是整数，例如：/推文 nasa 5"
        if number <= 0:
            return 0, "数量需要大于 0，例如：/推文 nasa 5"
        return number, ""

    @staticmethod
    def _looks_like_limit(value: str) -> bool:
        return bool(re.fullmatch(r"[+-]?\d+", str(value or "").strip()))

    def _command_tokens(self, event: AstrMessageEvent, args: str) -> list[str]:
        return [
            token
            for token in str(args or "").split()
            if not self._is_self_at_argument(event, token)
        ]

    def _strip_self_at_argument(self, event: AstrMessageEvent, value: str) -> str:
        value = str(value or "").strip()
        return "" if self._is_self_at_argument(event, value) else value

    def _is_self_at_argument(self, event: AstrMessageEvent, value: str) -> bool:
        value = str(value or "").strip()
        if not value.startswith("@"):
            return False

        self_id = str(safe_call(event, "get_self_id") or "").strip()
        if not self_id:
            return False

        for component in safe_call(event, "get_messages") or []:
            if not isinstance(component, At):
                continue
            at_id = str(getattr(component, "qq", "") or "").strip()
            at_name = str(getattr(component, "name", "") or "").strip()
            if self_id not in {at_id, at_name}:
                continue
            if value in {f"@{at_id}", f"@{at_name}"}:
                return True
        return False

    @staticmethod
    def _looks_like_instance(value: str) -> bool:
        value = str(value or "").strip().lower()
        if not value or value.startswith("@") or " " in value:
            return False
        if not value.startswith(("http://", "https://")):
            return False
        return "." in value or "localhost" in value

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("推文状态")
    async def cmd_tweets_status(self, event: AstrMessageEvent):
        """查看定时推文检查状态。"""
        event.stop_event()
        self.scheduler.start(reason="status_command")
        await event.send(event.plain_result(await self.scheduler.status_summary()))

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("推文检查")
    async def cmd_tweets_check(
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

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("推文缓存清理")
    async def cmd_tweets_clear_cache(self, event: AstrMessageEvent):
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

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("推文队列")
    async def cmd_tweets_queue(
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

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("推文发布")
    async def cmd_tweets_publish(
        self,
        event: AstrMessageEvent,
        group_name: str = "",
    ):
        """立即发布暂存队列中的推文。"""
        event.stop_event()
        group_name = self._strip_self_at_argument(event, group_name)
        self.scheduler.start(reason="publish_command")
        group_label = group_name or "全局分组"
        await event.send(event.plain_result(f"正在发布 Nitter 暂存队列：{group_label}..."))
        result = await self.scheduler.publish_pending(
            group_name=group_name,
            reason="manual_publish_command",
        )
        await event.send(event.plain_result(result.format_message("Nitter 暂存发布结果")))

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("推文订阅列表")
    async def cmd_tweets_list(self, event: AstrMessageEvent):
        """查看已配置的定时订阅账号列表。"""
        event.stop_event()
        info = self.scheduler.watch_users_info()

        lines = [
            "Nitter 订阅作者列表",
            f"原配置项: {info.raw_count} 个",
            f"有效作者: {len(info.users)} 个",
            f"重复项: {len(info.duplicates)} 个",
            f"无效项: {len(info.invalid_entries)} 个",
        ]
        if info.users:
            lines.append("作者列表:")
            lines.extend(
                f"{index}. @{user}"
                for index, user in enumerate(info.users[:10], 1)
            )
            if len(info.users) > 10:
                lines.append(f"... 还有 {len(info.users) - 10} 个")
        else:
            lines.append("作者列表为空。")
        if info.duplicates:
            lines.append("重复项: " + self._format_limited_values(info.duplicates))
        if info.invalid_entries:
            lines.append(
                "无效项: " + self._format_limited_values(info.invalid_entries)
            )

        await event.send(event.plain_result("\n".join(lines)))

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("博主导出")
    async def cmd_tweets_export_bloggers(self, event: AstrMessageEvent):
        """按分组导出已配置的订阅博主。"""
        event.stop_event()
        await event.send(event.plain_result("\n".join(self._export_bloggers_lines())))

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("推文订阅去重")
    async def cmd_tweets_dedup(self, event: AstrMessageEvent):
        """规范化并去重定时订阅账号列表。"""
        event.stop_event()
        info = self.scheduler.deduplicate_watch_users()

        lines = [
            "Nitter 订阅作者去重",
            f"原配置项: {info.raw_count} 个",
            f"有效作者: {len(info.users)} 个",
            f"重复项: {len(info.duplicates)} 个",
            f"无效项: {len(info.invalid_entries)} 个",
        ]
        if info.changed:
            if info.saved:
                lines.append("结果: 已规范化并保存到 watch_users。")
            elif info.save_error:
                lines.append(f"结果: 已更新运行时配置，但保存失败：{info.save_error}")
            else:
                lines.append("结果: 已更新运行时配置。")
        else:
            lines.append("结果: watch_users 已经是去重后的规范列表。")

        if info.users:
            lines.append(
                "作者列表: "
                + self._format_limited_values([f"@{user}" for user in info.users])
            )
        if info.duplicates:
            lines.append("已移除重复: " + self._format_limited_values(info.duplicates))
        if info.invalid_entries:
            lines.append(
                "已移除无效: " + self._format_limited_values(info.invalid_entries)
            )

        await event.send(event.plain_result("\n".join(lines)))

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("订阅导入")
    async def cmd_tweets_import(self, event: AstrMessageEvent, args=GreedyStr):
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
        if len(raw_entries) > 50:
            await event.send(
                event.plain_result(
                    f"单次最多导入 50 个账号，本次输入 {len(raw_entries)} 个；"
                    "请分批导入。"
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
            group = self._resolve_import_group(candidate)
            if group is not None:
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
            if group.enabled and target_umo in group.targets
        ]
        if not matches:
            return (
                None,
                "当前对话不在任何已启用推文分组的 push_targets 中，"
                "不会执行 /推文检查。\n"
                f"当前对话: {target_umo}",
            )
        if len(matches) > 1:
            labels = [self._check_group_label(group) for group in matches]
            return (
                None,
                "当前对话匹配到多个推文分组，请使用 /推文检查 分组名 指定。\n"
                "匹配分组: " + self._format_limited_values(labels),
            )
        return matches[0], ""

    def _available_group_labels(self) -> list[str]:
        groups = self.scheduler.config_reader.schedule_groups(
            log_invalid_targets=False
        )
        return [f"{group.name} ({group.group_id})" for group in groups]

    def _export_bloggers_lines(self) -> list[str]:
        groups = self.scheduler.config_reader.schedule_groups(
            log_invalid_targets=False
        )
        return [
            f"{self._export_group_label(group)}: {','.join(group.users)}"
            for group in groups
        ]

    @staticmethod
    def _export_group_label(group: ScheduleGroup) -> str:
        if group.group_id == GLOBAL_GROUP_ID:
            return "全局分组"
        return group.name or group.group_id

    @staticmethod
    def _import_group_label(group: ScheduleGroup | None) -> str:
        if group is None or group.group_id == GLOBAL_GROUP_ID:
            return "全局分组 (global)"
        return f"{group.name} ({group.group_id})"

    @staticmethod
    def _check_group_label(group: ScheduleGroup) -> str:
        return f"{group.name} ({group.group_id})"

    @staticmethod
    def _import_config_target(group: ScheduleGroup | None) -> str:
        if group is None or group.group_id == GLOBAL_GROUP_ID:
            return "watch_users"
        return f"tweet_groups[{group.group_id}].watch_users"

    def _set_import_group_users(
        self, group: ScheduleGroup | None, users: list[str]
    ) -> None:
        if group is None or group.group_id == GLOBAL_GROUP_ID:
            config_set(self.config, "watch_users", users)
            return

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

    def _cooldown_key(self, event: AstrMessageEvent) -> str:
        sender = safe_call(event, "get_sender_id") or "unknown"
        group = safe_call(event, "get_group_id") or "private"
        return f"{group}:{sender}"

    def _cooldown_left(self, event: AstrMessageEvent) -> float:
        if self.cooldown_seconds <= 0:
            return 0
        last = self._cooldowns.get(self._cooldown_key(event), 0)
        return max(0.0, self.cooldown_seconds - (time.time() - last))

    def _mark_cooldown(self, event: AstrMessageEvent) -> None:
        self._cooldowns[self._cooldown_key(event)] = time.time()
