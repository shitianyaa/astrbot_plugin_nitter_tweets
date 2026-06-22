from __future__ import annotations

from astrbot.api.all import AstrBotConfig, Context, Star, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import register
from astrbot.core.star.filter.command import GreedyStr

try:
    from .command_handlers import (
        MaintenanceCommandMixin,
        ManualCommandMixin,
        SubscriptionCommandMixin,
    )
    from .config_compat import (
        config_get,
        migrate_default_group_config,
        migrate_legacy_grouped_config,
    )
    from .enricher import TweetEnricher, TweetTranslator
    from .media import MediaService, NitterClient
    from .scheduler import NitterTweetScheduler
    from .sender import TweetSender
    from .utils import clamp_float
except ImportError:
    from command_handlers import (
        MaintenanceCommandMixin,
        ManualCommandMixin,
        SubscriptionCommandMixin,
    )
    from config_compat import (
        config_get,
        migrate_default_group_config,
        migrate_legacy_grouped_config,
    )
    from enricher import TweetEnricher, TweetTranslator
    from media import MediaService, NitterClient
    from scheduler import NitterTweetScheduler
    from sender import TweetSender
    from utils import clamp_float


@register(
    "astrbot_plugin_nitter_tweets",
    "shitianyaa",
    "Fetch recent public tweets from Nitter and send them as chat records.",
    "0.10.0",
    "https://github.com/shitianyaa/astrbot_plugin_nitter_tweets",
)
class NitterTweetsPlugin(
    ManualCommandMixin,
    MaintenanceCommandMixin,
    SubscriptionCommandMixin,
    Star,
):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        migrate_legacy_grouped_config(self.config)
        migrate_default_group_config(self.config)
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
        """查询指定公开 X/Twitter 用户最近推文。用法：/推文 用户名 [数量]"""
        return await self._cmd_tweets_impl(event, username, limit)

    @filter.command("镜像测试")
    async def cmd_mirror_probe(self, event: AstrMessageEvent, args=GreedyStr):
        """测试当前配置的 Nitter 镜像站 RSS 可用性。用法：/镜像测试 [用户名]"""
        return await self._cmd_mirror_probe_impl(event, args)

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("推文状态")
    async def cmd_tweets_status(self, event: AstrMessageEvent):
        """查看 Nitter 推文调度状态、关注账号、推送目标和分组配置。"""
        return await self._cmd_tweets_status_impl(event)

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("推文检查")
    async def cmd_tweets_check(
        self,
        event: AstrMessageEvent,
        group_name: str = "",
    ):
        """立即检查订阅账号是否有新推文。用法：/推文检查 [分组名]"""
        return await self._cmd_tweets_check_impl(event, group_name)

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("推文缓存清理")
    async def cmd_tweets_clear_cache(self, event: AstrMessageEvent):
        """清理本地推文内容缓存，下次检查时重新获取推文数据。"""
        return await self._cmd_tweets_clear_cache_impl(event)

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("推文记录清理")
    async def cmd_tweets_clear_seen(self, event: AstrMessageEvent, args=GreedyStr):
        """清理已推送记录，可按分组清理。用法：/推文记录清理 [分组名] 确认"""
        return await self._cmd_tweets_clear_seen_impl(event, args)

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("推文队列")
    async def cmd_tweets_queue(
        self,
        event: AstrMessageEvent,
        group_name: str = "",
    ):
        """查看暂存发布队列中的待发送推文。用法：/推文队列 [分组名]"""
        return await self._cmd_tweets_queue_impl(event, group_name)

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("推文发布")
    async def cmd_tweets_publish(
        self,
        event: AstrMessageEvent,
        group_name: str = "",
    ):
        """立即发布暂存队列中的推文。用法：/推文发布 [分组名]"""
        return await self._cmd_tweets_publish_impl(event, group_name)

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("订阅列表")
    async def cmd_tweets_list(self, event: AstrMessageEvent):
        """查看当前推文订阅账号、分组和推送目标配置。"""
        return await self._cmd_tweets_list_impl(event)

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("订阅导出")
    async def cmd_tweets_export_subscriptions(self, event: AstrMessageEvent):
        """导出当前推文订阅配置，便于备份或迁移。"""
        return await self._cmd_tweets_export_subscriptions_impl(event)

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("订阅删除")
    async def cmd_tweets_delete_subscriptions(
        self, event: AstrMessageEvent, args=GreedyStr
    ):
        """删除一个或多个推文订阅账号。用法：/订阅删除 用户名[,用户名] [分组名]"""
        return await self._cmd_tweets_delete_subscriptions_impl(event, args)

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("订阅去重")
    async def cmd_tweets_dedup(self, event: AstrMessageEvent):
        """去除重复的推文订阅项，并保留已有分组与目标配置。"""
        return await self._cmd_tweets_dedup_impl(event)

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("订阅导入")
    async def cmd_tweets_import(self, event: AstrMessageEvent, args=GreedyStr):
        """批量导入推文订阅账号。用法：/订阅导入 用户名[,用户名] [分组名]"""
        return await self._cmd_tweets_import_impl(event, args)
