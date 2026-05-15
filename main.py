from __future__ import annotations

import time

from astrbot.api.all import AstrBotConfig, Context, Star, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import register

try:
    from .media import MediaService
    from .nitter_client import NitterClient
    from .scheduler import NitterTweetScheduler
    from .sender import TweetSender
    from .translator import TweetTranslator
    from .utils import clamp_float, clamp_int, normalize_username, safe_call
except ImportError:
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
    "0.4.2",
    "https://github.com/shitianyaa/astrbot_plugin_nitter_tweets",
)
class NitterTweetsPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.nitter = NitterClient(config)
        self.media = MediaService(config)
        self.sender = TweetSender()
        self.translator = TweetTranslator(context, config)
        self.scheduler = NitterTweetScheduler(
            self,
            context,
            config,
            self.nitter,
            self.media,
            self.sender,
            self.translator,
        )
        self.default_limit = clamp_int(config.get("default_limit", 5), 1, 20)
        self.max_limit = clamp_int(config.get("max_limit", 10), 1, 20)
        self.cooldown_seconds = clamp_float(
            config.get("cooldown_seconds", 15.0), 0.0, 3600.0
        )
        self._cooldowns: dict[str, float] = {}

    async def initialize(self):
        logger.info(
            "Nitter tweets plugin loaded: "
            f"{len(self.nitter.instances)} instances, "
            f"media={'on' if self.media.enabled else 'off'}, "
            f"translate={'on' if self.translator.enabled else 'off'}"
        )
        self.scheduler.start(reason="initialize")

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
        if not await self.sender.send(event, username, instance, tweets):
            await event.send(
                event.plain_result(self.sender.format_plain(username, instance, tweets))
            )

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
