from __future__ import annotations

from pathlib import Path

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
    from .config import (
        MEDIA_CACHE_CLEANUP_MIGRATION_KEY,
        MEDIA_CACHE_SEND_DELETE_MIGRATION_KEY,
        config_get,
        migrate_default_group_config,
        migrate_legacy_grouped_config,
    )
    from .ai import TweetTranslator
    from .media_support import MediaService, NitterClient
    from .media_support.html_backend import (
        DEFAULT_HTML_INSTANCES,
        HtmlBackendConfig,
        HtmlNitterService,
    )
    from .plugin_api import NitterWebAPI
    from .scheduler import NitterTweetScheduler
    from .delivery import TweetSender
    from .shared import clamp_float
except ImportError:
    from command_handlers import (
        MaintenanceCommandMixin,
        ManualCommandMixin,
        SubscriptionCommandMixin,
    )
    from config import (
        MEDIA_CACHE_CLEANUP_MIGRATION_KEY,
        MEDIA_CACHE_SEND_DELETE_MIGRATION_KEY,
        config_get,
        migrate_default_group_config,
        migrate_legacy_grouped_config,
    )
    from ai import TweetTranslator
    from media_support import MediaService, NitterClient
    from media_support.html_backend import (
        DEFAULT_HTML_INSTANCES,
        HtmlBackendConfig,
        HtmlNitterService,
    )
    from plugin_api import NitterWebAPI
    from scheduler import NitterTweetScheduler
    from delivery import TweetSender
    from shared import clamp_float


@register(
    "astrbot_plugin_nitter_tweets",
    "shitianyaa",
    "Fetch recent public tweets from Nitter and send them as chat records.",
    "0.16.0",
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
        self._cleanup_legacy_media_cache_once()
        self.sender = TweetSender(config)
        self.translator = TweetTranslator(context, config)
        self.html_backend = self._build_html_backend()
        self.scheduler = NitterTweetScheduler(
            self,
            context,
            config,
            self.nitter,
            self.media,
            self.sender,
            self.translator,
            html_backend=self.html_backend,
        )
        self.web_api = NitterWebAPI(self)
        self.web_api.register(context)
        self.default_limit = self._parse_positive_limit(
            config_get(config, "default_limit", 5), 5
        )
        self.cooldown_seconds = clamp_float(
            config_get(config, "cooldown_seconds", 15.0), 0.0, 3600.0
        )
        self.search_cooldown_seconds = clamp_float(
            config_get(config, "search_cooldown_seconds", 30.0), 0.0, 3600.0
        )
        self.search_default_limit = self._parse_positive_limit(
            config_get(config, "search_default_limit", 5), 5
        )
        self.search_max_limit = self._parse_positive_limit(
            config_get(config, "search_max_limit", 10), 10
        )
        self._cooldowns: dict[str, float] = {}
        self._search_session_store = None  # lazy SearchSessionStore
        self.scheduler.start(reason="__init__")

    def _build_html_backend(self) -> HtmlNitterService:
        data_dir = None
        try:
            from astrbot.api.star import StarTools

            data_dir = StarTools.get_data_dir(self.name)
        except Exception:
            data_dir = None
        session_dir = None
        if data_dir is not None:
            session_dir = Path(data_dir) / "html_sessions"

        def _list(key: str, default: list[str]) -> list[str]:
            raw = config_get(self.config, key, default) or default
            if isinstance(raw, str):
                items = [part.strip() for part in raw.splitlines() if part.strip()]
            elif isinstance(raw, list):
                items = [str(item).strip() for item in raw if str(item).strip()]
            else:
                items = list(default)
            return items or list(default)

        return HtmlNitterService(
            HtmlBackendConfig(
                user_html_fallback=bool(
                    config_get(self.config, "user_html_fallback", True)
                ),
                blogger_html_instances=_list(
                    "blogger_html_instances", DEFAULT_HTML_INSTANCES
                ),
                search_enabled=bool(config_get(self.config, "search_enabled", True)),
                search_instances=_list("search_instances", DEFAULT_HTML_INSTANCES),
                proxy=None,
                session_dir=session_dir,
                html_timeout=clamp_float(
                    config_get(self.config, "html_request_timeout", 35.0), 5.0, 120.0
                ),
                html_min_interval=clamp_float(
                    config_get(self.config, "html_min_interval", 3.0), 0.0, 120.0
                ),
                html_max_pages=max(
                    1,
                    min(5, int(config_get(self.config, "html_max_pages", 1) or 1)),
                ),
                filter_reposts=bool(
                    config_get(self.config, "filter_reposts_enabled", True)
                ),
            ),
            log=lambda msg: logger.info(f"[NitterTweets][html] {msg}"),
            # Align HTML chatter with scheduler/RSS brief mode (default on).
            brief_log=bool(config_get(self.config, "brief_log_enabled", True)),
        )

    def _cleanup_legacy_media_cache_once(self) -> None:
        if bool(self.config.get(MEDIA_CACHE_CLEANUP_MIGRATION_KEY, False)):
            return

        try:
            result = self.media.clear_cache()
        except Exception as exc:
            logger.warning(
                f"[NitterTweets] 升级清理普通媒体缓存失败，下次启动将重试: error={exc}"
            )
            return

        if result.failed > 0:
            logger.warning(
                "[NitterTweets] 升级清理普通媒体缓存存在失败文件，"
                "下次启动将重试: "
                f"removed={result.removed}, failed={result.failed}, "
                f"skipped_dirs={result.skipped_dirs}"
            )
            return

        self.config[MEDIA_CACHE_CLEANUP_MIGRATION_KEY] = True
        # Preserve the legacy marker for older tooling/config inspectors.  It
        # is intentionally not consulted when deciding whether to run cleanup.
        self.config[MEDIA_CACHE_SEND_DELETE_MIGRATION_KEY] = True
        save_config = getattr(self.config, "save_config", None)
        if callable(save_config):
            save_config()
        logger.info(
            "[NitterTweets] 升级迁移已完成一次普通媒体缓存清理: "
            f"removed={result.removed}, failed={result.failed}, "
            f"skipped_dirs={result.skipped_dirs}"
        )

    async def initialize(self):
        logger.info(
            "[NitterTweets] 插件已加载: "
            f"instances={len(self.nitter.instances)}, "
            "media="
            f"image:{'on' if self.media.send_image_attachments else 'off'},"
            f"video:{'on' if self.media.send_video_attachments else 'off'}, "
            f"translate={'on' if self.translator.enabled else 'off'}, "
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

    @filter.command("推文搜索", alias={"tweetsearch"})
    async def cmd_tweet_search(self, event: AstrMessageEvent, args=GreedyStr):
        """搜索公开推文。标签请带 #，短语直接写。用法：/推文搜索 <query> [数量]"""
        return await self._cmd_tweet_search_impl(event, args)

    @filter.command("镜像测试")
    async def cmd_mirror_probe(self, event: AstrMessageEvent, args=GreedyStr):
        """用临时 Nitter 镜像站测试 RSS。用法：/镜像测试 [用户名] [数量] 镜像站URL"""
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
        """清理普通图片/视频缓存。"""
        return await self._cmd_tweets_clear_cache_impl(event)

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("推文记录清理")
    async def cmd_tweets_clear_seen(self, event: AstrMessageEvent, args=GreedyStr):
        """清理已推送记录，可按分组清理。用法：/推文记录清理 [分组名] 确认"""
        return await self._cmd_tweets_clear_seen_impl(event, args)

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("订阅列表")
    async def cmd_tweets_list(self, event: AstrMessageEvent):
        """查看当前推文订阅账号、分组和推送目标配置。"""
        return await self._cmd_tweets_list_impl(event)

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("订阅导出")
    async def cmd_tweets_export_subscriptions(
        self, event: AstrMessageEvent, args=GreedyStr
    ):
        """导出订阅配置（博主/标签）。用法：/订阅导出 [分组名称]"""
        return await self._cmd_tweets_export_subscriptions_impl(event, args)

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

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("标签导入")
    async def cmd_tag_import(self, event: AstrMessageEvent, args=GreedyStr):
        """批量导入标签分组搜索订阅。用法：/标签导入 #标签,短语 分组名"""
        return await self._cmd_tag_import_impl(event, args)

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("标签删除")
    async def cmd_tag_delete(self, event: AstrMessageEvent, args=GreedyStr):
        """批量删除标签分组搜索订阅。用法：/标签删除 #标签,短语 分组名"""
        return await self._cmd_tag_delete_impl(event, args)
