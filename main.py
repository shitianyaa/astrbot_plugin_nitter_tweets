from __future__ import annotations

import time

from astrbot.api.all import At, AstrBotConfig, Context, MessageChain, Plain, Star, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import register
from astrbot.core.star.filter.command import GreedyStr

try:
    from .enricher import TweetEnricher, TweetTranslator
    from .media import MediaService, NitterClient
    from .scheduler import NitterTweetScheduler
    from .sender import TweetSender
    from .utils import clamp_float, clamp_int, normalize_username, safe_call
except ImportError:
    from enricher import TweetEnricher, TweetTranslator
    from media import MediaService, NitterClient
    from scheduler import NitterTweetScheduler
    from sender import TweetSender
    from utils import clamp_float, clamp_int, normalize_username, safe_call


@register(
    "astrbot_plugin_nitter_tweets",
    "shitianyaa",
    "Fetch recent public tweets from Nitter and send them as chat records.",
    "0.6.10",
    "https://github.com/shitianyaa/astrbot_plugin_nitter_tweets",
)
class NitterTweetsPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
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
        self.default_limit = clamp_int(config.get("default_limit", 5), 1, 20)
        self.max_limit = clamp_int(config.get("max_limit", 10), 1, 20)
        self.cooldown_seconds = clamp_float(
            config.get("cooldown_seconds", 15.0), 0.0, 3600.0
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

    @filter.command("推文", alias={"x推文"})
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
            try:
                requested_limit = int(limit_text)
            except ValueError:
                await event.send(event.plain_result("数量需要是整数，例如：/推文 nasa 5"))
                return
        else:
            requested_limit = self.default_limit
        limit = clamp_int(requested_limit, 1, self.max_limit)
        self._mark_cooldown(event)
        await event.send(
            event.plain_result(f"正在获取 @{username} 最近 {limit} 条推文...")
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

    @filter.command(
        "镜像测试",
        alias={"推文镜像测试"},
    )
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
                f"正在测试 {instance_text}：获取 @{username} 最近 {limit} 条推文..."
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
        await self.translator.attach_translations(tweets, event.unified_msg_origin)
        await self.media.attach_media(tweets)
        enrich_report = await self.enricher.attach_enrichments(
            tweets, event.unified_msg_origin
        )
        notices = enrich_report.visible_notices()
        if not await self.sender.send(event, username, instance, tweets, notices=notices):
            fallback_text = self.sender.renderer.format_plain(
                username, instance, tweets, notices=notices
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

    def _parse_mirror_probe_args(
        self,
        event: AstrMessageEvent,
        args: str,
    ) -> tuple[str, int, str, str]:
        tokens = self._command_tokens(event, args)
        usage = (
            "用法：/镜像测试 [用户名] [数量] 镜像站\n"
            "例如：/镜像测试 nitter.top\n"
            "也可以：/镜像测试 nasa 3 nitter.top"
        )
        if not tokens:
            return "", 0, "", usage

        instance_index = -1
        for index, token in enumerate(tokens):
            if self._looks_like_instance(token):
                instance_index = index
        if instance_index < 0:
            return "", 0, "", "请提供 Nitter 镜像站，例如：/镜像测试 nitter.top"

        instance_text = tokens[instance_index]
        extras = tokens[:instance_index] + tokens[instance_index + 1 :]
        if len(extras) > 2:
            return "", 0, "", usage

        username = "nasa"
        requested_limit = 1
        seen_username = False
        seen_limit = False
        for token in extras:
            if token.isdigit():
                if seen_limit:
                    return "", 0, "", "数量只能填写一次，例如：/镜像测试 3 nitter.top"
                requested_limit = int(token)
                seen_limit = True
                continue

            normalized = normalize_username(token)
            if not normalized:
                return "", 0, "", usage
            if seen_username:
                return "", 0, "", "用户名只能填写一次，例如：/镜像测试 nasa nitter.top"
            username = normalized
            seen_username = True

        return username, clamp_int(requested_limit, 1, self.max_limit), instance_text, ""

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
        if value.startswith(("http://", "https://")):
            return "." in value or "localhost" in value
        return "." in value or value.startswith(("localhost", "127.0.0.1"))

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
        self.scheduler.start(reason="manual_check")
        group_label = group_name or "全局分组"
        await event.send(event.plain_result(f"正在执行 Nitter 定时检查：{group_label}..."))
        result = await self.scheduler.run_check(
            reason="manual_command",
            notify_no_updates=False,
            group_name=group_name,
        )
        await event.send(event.plain_result(result.format_message()))

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("推文订阅列表", alias={"推文关注列表"})
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
            lines.extend(f"{index}. @{user}" for index, user in enumerate(info.users, 1))
        else:
            lines.append("作者列表为空。")
        if info.duplicates:
            lines.append("重复项: " + ", ".join(info.duplicates[:10]))
        if info.invalid_entries:
            lines.append("无效项: " + ", ".join(info.invalid_entries[:10]))

        await event.send(event.plain_result("\n".join(lines)))

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("推文订阅去重", alias={"推文关注去重"})
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
            lines.append("作者列表: " + ", ".join(f"@{user}" for user in info.users))
        if info.duplicates:
            lines.append("已移除重复: " + ", ".join(info.duplicates[:10]))
        if info.invalid_entries:
            lines.append("已移除无效: " + ", ".join(info.invalid_entries[:10]))

        await event.send(event.plain_result("\n".join(lines)))

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
