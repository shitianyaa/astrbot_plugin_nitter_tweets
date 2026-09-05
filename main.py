from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

from astrbot.api.all import AstrBotConfig, Context, Star, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import register
from astrbot.core.star.filter.command import GreedyStr

try:
    from .ai import TweetTranslator
    from .command_handlers import (
        LinkPreviewMixin,
        MaintenanceCommandMixin,
        ManualCommandMixin,
        SubscriptionCommandMixin,
        TargetBlacklistCommandMixin,
    )
    from .config import (
        MEDIA_CACHE_CLEANUP_MIGRATION_KEY,
        MEDIA_CACHE_SEND_DELETE_MIGRATION_KEY,
        config_get,
        migrate_default_group_config,
        migrate_legacy_grouped_config,
        parse_config_bool,
    )
    from .delivery import TweetSender
    from .media_support import MediaService, NitterService
    from .media_support.status_link import STATUS_LINK_REGEX
    from .plugin_api import NitterWebAPI
    from .scheduler import NitterTweetScheduler
    from .shared import clamp_float
except ImportError:
    from ai import TweetTranslator
    from command_handlers import (
        LinkPreviewMixin,
        MaintenanceCommandMixin,
        ManualCommandMixin,
        SubscriptionCommandMixin,
        TargetBlacklistCommandMixin,
    )
    from config import (
        MEDIA_CACHE_CLEANUP_MIGRATION_KEY,
        MEDIA_CACHE_SEND_DELETE_MIGRATION_KEY,
        config_get,
        migrate_default_group_config,
        migrate_legacy_grouped_config,
        parse_config_bool,
    )
    from delivery import TweetSender
    from media_support import MediaService, NitterService
    from media_support.status_link import STATUS_LINK_REGEX
    from plugin_api import NitterWebAPI
    from scheduler import NitterTweetScheduler
    from shared import clamp_float


@register(
    "astrbot_plugin_nitter_tweets",
    "shitianyaa",
    "Fetch recent public tweets from Nitter and send them as chat records.",
    "1.4.0",
    "https://github.com/shitianyaa/astrbot_plugin_nitter_tweets",
)
class NitterTweetsPlugin(
    ManualCommandMixin,
    MaintenanceCommandMixin,
    SubscriptionCommandMixin,
    TargetBlacklistCommandMixin,
    LinkPreviewMixin,
    Star,
):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        migrate_legacy_grouped_config(self.config)
        migrate_default_group_config(self.config)
        self.nitter = NitterService(config, session_dir=self._html_session_dir())
        for key, values in self.nitter.ignored_legacy_instances.items():
            labels = ", ".join(self._instance_log_label(value) for value in values)
            logger.warning(
                f"[NitterTweets] 已忽略已删除配置 {key} 中的实例: {labels}；"
                "请手动填写到 instances，插件不会迁移或写回旧字段"
            )
        if not self.nitter.instances:
            logger.warning(
                "[NitterTweets] 未配置可用的自建 Nitter 实例；"
                "RSS、搜索和 List 功能将不可用"
            )
        self.media = MediaService(config)
        self._cleanup_legacy_media_cache_once()
        self.sender = TweetSender(config)
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
        self.web_api = NitterWebAPI(self)
        self.web_api.register(context)
        self.default_limit = self._parse_positive_limit(
            config_get(config, "default_limit", 5), 5
        )
        self.cooldown_seconds = clamp_float(
            config_get(config, "cooldown_seconds", 15.0), 0.0, 3600.0
        )
        self.search_cooldown_seconds = self.cooldown_seconds
        self.search_default_limit = self.default_limit
        self.search_max_limit = self._parse_positive_limit(
            config_get(config, "search_max_limit", 10), 10
        )
        self._cooldowns: dict[str, float] = {}
        self._search_session_store = None  # lazy SearchSessionStore
        self.scheduler.start(reason="__init__")

    def _html_session_dir(self) -> Path | None:
        try:
            from astrbot.api.star import StarTools

            data_dir = StarTools.get_data_dir(self.name)
        except Exception:
            return None
        return Path(data_dir) / "html_sessions"

    @staticmethod
    def _instance_log_label(value: str) -> str:
        """Keep startup diagnostics useful without logging URL paths."""
        try:
            parsed = urlsplit(str(value or "").strip())
            host = parsed.hostname or ""
            port = f":{parsed.port}" if parsed.port else ""
            return f"{parsed.scheme}://{host}{port}" if parsed.scheme and host else host
        except ValueError:
            return "<invalid>"

    def _cleanup_legacy_media_cache_once(self) -> None:
        if parse_config_bool(
            self.config.get(MEDIA_CACHE_CLEANUP_MIGRATION_KEY, False), False
        ):
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

    @filter.regex(STATUS_LINK_REGEX)
    async def cmd_auto_parse_tweet_links(self, event: AstrMessageEvent):
        """被动解析聊天中的公开 X/Twitter 推文链接（需开启配置开关）。"""
        return await self._cmd_link_preview_impl(event)

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

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("镜像测试")
    async def cmd_mirror_probe(self, event: AstrMessageEvent, args=GreedyStr):
        """测试自建 Nitter 实例。用法：/镜像测试 [用户名] [数量] 实例URL"""
        return await self._cmd_mirror_probe_impl(event, args)

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("推文状态")
    async def cmd_tweets_status(self, event: AstrMessageEvent):
        """查看 Nitter 推文调度状态、订阅源、推送目标和分组配置。"""
        return await self._cmd_tweets_status_impl(event)

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("推文检查")
    async def cmd_tweets_check(
        self,
        event: AstrMessageEvent,
        group_name: str = "",
    ):
        """立即检查订阅源是否有新推文。用法：/推文检查 [分组名]"""
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

    @filter.command_group("推文黑名单")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def cmd_tweets_target_blacklist(self, event: AstrMessageEvent):
        """按推送目标维护跨分组共享的作者黑名单。"""

    @cmd_tweets_target_blacklist.command("添加", alias={"add", "增加"})
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def cmd_tweets_target_blacklist_add(
        self, event: AstrMessageEvent, args=GreedyStr
    ):
        """将作者加入当前或指定推送目标的黑名单。"""
        return await self._cmd_target_blacklist_add_impl(event, args)

    @cmd_tweets_target_blacklist.command(
        "删除", alias={"remove", "del", "delete", "移除"}
    )
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def cmd_tweets_target_blacklist_remove(
        self, event: AstrMessageEvent, args=GreedyStr
    ):
        """从当前或指定推送目标的黑名单移除作者。"""
        return await self._cmd_target_blacklist_remove_impl(event, args)

    @cmd_tweets_target_blacklist.command("查看", alias={"list", "show", "查询"})
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def cmd_tweets_target_blacklist_list(
        self, event: AstrMessageEvent, args=GreedyStr
    ):
        """查看当前或指定推送目标的作者黑名单。"""
        return await self._cmd_target_blacklist_list_impl(event, args)

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
