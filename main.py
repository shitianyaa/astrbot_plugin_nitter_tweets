from __future__ import annotations

import time

from astrbot.api.all import AstrBotConfig, Context, Star, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import register

try:
    from .enricher import TweetEnricher
    from .media import MediaService
    from .nitter_client import NitterClient
    from .scheduler import NitterTweetScheduler
    from .sender import TweetSender
    from .translator import TweetTranslator
    from .utils import clamp_float, clamp_int, normalize_username, safe_call
except ImportError:
    from enricher import TweetEnricher
    from media import MediaService
    from nitter_client import NitterClient
    from scheduler import NitterTweetScheduler
    from sender import TweetSender
    from translator import TweetTranslator
    from utils import clamp_float, clamp_int, normalize_username, safe_call


@register(
    "astrbot_plugin_nitter_tweets",
    "shitianyaa",
    "Fetch recent public tweets from Nitter and send them as chat records.",
    "0.5.0",
    "https://github.com/shitianyaa/astrbot_plugin_nitter_tweets",
)
class NitterTweetsPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.nitter = NitterClient(config)
        self.media = MediaService(config)
        self.sender = TweetSender()
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
            f"media={'on' if self.media.enabled else 'off'}, "
            f"translate={'on' if self.translator.enabled else 'off'}, "
            f"ai_enrich={'on' if self.enricher.enabled else 'off'}, "
            f"merge_updates={'on' if self.config.get('merge_scheduled_updates', False) else 'off'}"
        )
        self.scheduler.start(reason="initialize")

    @filter.on_astrbot_loaded()
    async def on_loaded(self):
        self.scheduler.start(reason="on_astrbot_loaded")

    async def terminate(self):
        await self.scheduler.stop()

    @filter.command("推文", alias={"tweets", "tweet", "twitter", "x推文"})
    async def cmd_tweets(
        self, event: AstrMessageEvent, username: str = "", limit: int = 0
    ):
        """Fetch recent tweets for a public X/Twitter user."""
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

        limit = clamp_int(limit or self.default_limit, 1, self.max_limit)
        self._mark_cooldown(event)
        await event.send(event.plain_result(f"正在获取 @{username} 最近 {limit} 条推文..."))

        try:
            instance, tweets = await self.nitter.fetch_tweets(username, limit)
        except Exception as exc:
            logger.warning(f"Failed to fetch tweets for @{username}: {exc}")
            await event.send(
                event.plain_result(
                    f"获取 @{username} 推文失败：公共 Nitter 实例暂时不可用或该用户无公开 RSS。"
                )
            )
            return

        if not tweets:
            await event.send(event.plain_result(f"没有找到 @{username} 的公开推文。"))
            return

        await self.translator.attach_translations(tweets, event.unified_msg_origin)
        await self.media.attach_media(tweets)
        await self.enricher.attach_enrichments(tweets, event.unified_msg_origin)
        if not await self.sender.send(event, username, instance, tweets):
            await event.send(
                event.plain_result(self.sender.format_plain(username, instance, tweets))
            )

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("推文状态", alias={"nitter_status", "tweets_status"})
    async def cmd_tweets_status(self, event: AstrMessageEvent):
        """Show scheduled tweet check status."""
        event.stop_event()
        self.scheduler.start(reason="status_command")
        await event.send(event.plain_result(await self.scheduler.status_summary()))

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("推文检查", alias={"nitter_check", "tweets_check"})
    async def cmd_tweets_check(self, event: AstrMessageEvent):
        """Run one scheduled tweet check immediately."""
        event.stop_event()
        self.scheduler.start(reason="manual_check")
        await event.send(event.plain_result("正在执行 Nitter 定时检查..."))
        result = await self.scheduler.run_check(
            reason="manual_command",
            notify_no_updates=False,
        )
        await event.send(event.plain_result(result.format_message()))

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("推文订阅去重", alias={"nitter_dedup", "tweets_dedup", "推文关注去重"})
    async def cmd_tweets_dedup(self, event: AstrMessageEvent):
        """Normalize and deduplicate scheduled watch users."""
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
