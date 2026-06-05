from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from astrbot.api import logger

try:
    from astrbot.api.all import MessageChain
except ImportError:
    from astrbot.api.event import MessageChain

try:
    from astrbot.api.message_components import Image, Node, Nodes, Plain, Video
except ImportError:
    from astrbot.core.message.components import Image, Node, Nodes, Plain, Video

try:
    from .utils import (
        TweetItem, TweetMedia, file_uri, node_uin, normalize_external_links,
        safe_call, strip_external_links,
    )
except ImportError:
    from utils import (
        TweetItem, TweetMedia, file_uri, node_uin, normalize_external_links,
        safe_call, strip_external_links,
    )


TweetBatch = tuple[str, str, list[TweetItem]]


@dataclass(slots=True)
class MergedSendOutcome:
    success: bool
    mode: str
    omitted_videos: int = 0
    error: str = ""


class TweetSender:
    FORWARD_MESSAGE_PLATFORMS = {"aiocqhttp"}

    def __init__(self, config=None):
        config = config or {}
        image_config = config.get("send_image_attachments", None)
        if image_config is None:
            image_config = bool(config.get("download_media", True)) and bool(
                config.get("download_images", True)
            )
        self.send_image_attachments = bool(image_config)
        self.send_video_attachments = bool(
            config.get("send_video_attachments", False)
        )

    async def send(
        self,
        event,
        username: str,
        instance: str,
        tweets: list[TweetItem],
        notices: list[str] | None = None,
    ) -> bool:
        if not self._should_use_forward_for_event(event):
            return await self._send_direct_event(
                event, username, instance, tweets, notices=notices
            )

        nodes = self._build_nodes(event, username, instance, tweets, notices=notices)
        raw_nodes = self._build_onebot_nodes(
            event, username, instance, tweets, notices=notices
        )
        try:
            await event.send(event.chain_result([nodes]))
            return True
        except Exception as exc:
            logger.warning(f"Failed to send forwarded tweet nodes: {exc}")

        # 去掉视频后重试
        if any(m.is_video for t in tweets for m in t.media if m.path):
            try:
                nodes_nv = self._build_nodes(
                    event, username, instance, tweets,
                    exclude_videos=True, notices=notices
                )
                await event.send(event.chain_result([nodes_nv]))
                logger.info("Sent forwarded tweets without videos after initial failure")
                return True
            except Exception as exc:
                logger.warning(
                    f"Failed to send forwarded tweet nodes without videos: {exc}"
                )

        try:
            return await self._send_onebot_forward(event, raw_nodes)
        except Exception as exc:
            logger.warning(f"Failed to send OneBot forward message: {exc}")
            return False

    async def send_to_umo(
        self,
        context,
        umo: str,
        username: str,
        instance: str,
        tweets: list[TweetItem],
    ) -> bool:
        if not self._should_use_forward_for_umo(context, umo):
            return await self._send_direct_to_umo(
                context, umo, username, instance, tweets
            )

        nodes = self._build_nodes_for_uin(10000, username, instance, tweets)
        success, _ = await self._send_context_message(
            context, umo, MessageChain([nodes]), "scheduled forwarded tweets"
        )
        if success:
            return True

        # 去掉视频后重试
        if any(m.is_video for t in tweets for m in t.media if m.path):
            nodes_nv = self._build_nodes_for_uin(
                10000, username, instance, tweets, exclude_videos=True
            )
            success, _ = await self._send_context_message(
                context,
                umo,
                MessageChain([nodes_nv]),
                "scheduled tweets without videos",
            )
            if success:
                logger.info(
                    f"Sent scheduled tweets to {umo} without videos after initial failure"
                )
                return True

        success, _ = await self._send_context_message(
            context,
            umo,
            MessageChain([Plain(self.format_plain(username, instance, tweets))]),
            "scheduled tweet fallback",
        )
        return success

    async def send_merged_to_umo(
        self,
        context,
        umo: str,
        batches: list[TweetBatch],
    ) -> MergedSendOutcome:
        if not self._should_use_forward_for_umo(context, umo):
            return await self._send_merged_direct_to_umo(context, umo, batches)

        omitted_videos = self._count_attached_videos(batches)
        nodes = self._build_merged_nodes_for_uin(10000, batches)
        success, error = await self._send_context_message(
            context, umo, MessageChain([nodes]), "merged scheduled tweets"
        )
        if success:
            return MergedSendOutcome(success=True, mode="full_forward")

        if omitted_videos:
            nodes_nv = self._build_merged_nodes_for_uin(
                10000, batches, exclude_videos=True
            )
            success, retry_error = await self._send_context_message(
                context,
                umo,
                MessageChain([nodes_nv]),
                "merged tweets without videos",
            )
            if success:
                logger.warning(
                    f"Sent merged tweets to {umo} without {omitted_videos} "
                    "video/GIF attachments after initial failure"
                )
                return MergedSendOutcome(
                    success=True,
                    mode="forward_without_videos",
                    omitted_videos=omitted_videos,
                    error=error,
                )
            error = retry_error or error

        success, fallback_error = await self._send_context_message(
            context,
            umo,
            MessageChain([Plain(self.format_merged_plain(batches))]),
            "merged scheduled tweet fallback",
        )
        if success:
            return MergedSendOutcome(
                success=True,
                mode="plain_fallback",
                omitted_videos=omitted_videos,
                error=error,
            )
        return MergedSendOutcome(
            success=False,
            mode="failed",
            omitted_videos=omitted_videos,
            error=fallback_error or error,
        )

    async def _send_direct_event(
        self,
        event,
        username: str,
        instance: str,
        tweets: list[TweetItem],
        notices: list[str] | None = None,
    ) -> bool:
        try:
            await event.send(
                MessageChain(
                    self._build_direct_components(
                        username, instance, tweets, notices=notices
                    )
                )
            )
            return True
        except Exception as exc:
            logger.warning(f"Failed to send direct tweets: {exc}")

        if self._has_attached_videos(tweets):
            try:
                await event.send(
                    MessageChain(
                        self._build_direct_components(
                            username, instance, tweets,
                            exclude_videos=True, notices=notices
                        )
                    )
                )
                logger.info(
                    "Sent direct tweets without videos after initial failure"
                )
                return True
            except Exception as exc:
                logger.warning(
                    f"Failed to send direct tweets without videos: {exc}"
                )

        try:
            await event.send(
                MessageChain(
                    [Plain(self.format_plain(username, instance, tweets, notices=notices))]
                )
            )
            return True
        except Exception as exc:
            logger.warning(f"Failed to send direct tweet fallback: {exc}")
            return False

    async def _send_direct_to_umo(
        self,
        context,
        umo: str,
        username: str,
        instance: str,
        tweets: list[TweetItem],
    ) -> bool:
        success, _ = await self._send_context_message(
            context,
            umo,
            MessageChain(self._build_direct_components(username, instance, tweets)),
            "direct scheduled tweets",
        )
        if success:
            return True

        if self._has_attached_videos(tweets):
            success, _ = await self._send_context_message(
                context,
                umo,
                MessageChain(
                    self._build_direct_components(
                        username, instance, tweets, exclude_videos=True
                    )
                ),
                "direct scheduled tweets without videos",
            )
            if success:
                logger.info(
                    f"Sent direct scheduled tweets to {umo} without videos "
                    "after initial failure"
                )
                return True

        success, _ = await self._send_context_message(
            context,
            umo,
            MessageChain([Plain(self.format_plain(username, instance, tweets))]),
            "direct scheduled fallback",
        )
        return success

    async def _send_merged_direct_to_umo(
        self,
        context,
        umo: str,
        batches: list[TweetBatch],
    ) -> MergedSendOutcome:
        omitted_videos = self._count_attached_videos(batches)
        success, error = await self._send_context_message(
            context,
            umo,
            MessageChain(self._build_merged_direct_components(batches)),
            "direct merged tweets",
        )
        if success:
            return MergedSendOutcome(success=True, mode="direct_message")

        if omitted_videos:
            success, retry_error = await self._send_context_message(
                context,
                umo,
                MessageChain(
                    self._build_merged_direct_components(
                        batches, exclude_videos=True
                    )
                ),
                "direct merged tweets without videos",
            )
            if success:
                logger.warning(
                    f"Sent direct merged tweets to {umo} without {omitted_videos} "
                    "video/GIF attachments after initial failure"
                )
                return MergedSendOutcome(
                    success=True,
                    mode="direct_without_videos",
                    omitted_videos=omitted_videos,
                    error=error,
                )
            error = retry_error or error

        success, fallback_error = await self._send_context_message(
            context,
            umo,
            MessageChain([Plain(self.format_merged_plain(batches))]),
            "direct merged fallback",
        )
        if success:
            return MergedSendOutcome(
                success=True,
                mode="plain_fallback",
                omitted_videos=omitted_videos,
                error=error,
            )
        return MergedSendOutcome(
            success=False,
            mode="failed",
            omitted_videos=omitted_videos,
            error=fallback_error or error,
        )

    async def _send_context_message(
        self,
        context,
        umo: str,
        chain: MessageChain,
        label: str,
    ) -> tuple[bool, str]:
        try:
            sent = await context.send_message(umo, chain)
        except Exception as exc:
            error = str(exc)
            logger.warning(f"Failed to send {label} to {umo}: {error}")
            return False, error

        if sent is False:
            error = "target platform not found or proactive send is unsupported"
            logger.warning(f"Failed to send {label} to {umo}: {error}")
            return False, error

        return True, ""

    def _build_nodes(
        self, event, username: str, instance: str, tweets: list[TweetItem],
        exclude_videos: bool = False, notices: list[str] | None = None,
    ):
        return self._build_nodes_for_uin(
            node_uin(event), username, instance, tweets, exclude_videos, notices
        )

    def _build_nodes_for_uin(
        self, uin, username: str, instance: str, tweets: list[TweetItem],
        exclude_videos: bool = False, notices: list[str] | None = None,
    ):
        nodes = Nodes([])
        nodes.nodes.append(
            Node(
                uin=uin,
                name="Nitter",
                content=[
                    Plain(self._format_header(username, instance, len(tweets), notices))
                ],
            )
        )

        for index, tweet in enumerate(tweets, 1):
            nodes.nodes.append(
                Node(
                    uin=uin,
                    name=f"@{username}",
                    content=self._build_components(
                        index, username, tweet, exclude_videos=exclude_videos
                    ),
                )
            )
        return nodes

    def _build_merged_nodes_for_uin(
        self, uin, batches: list[TweetBatch], exclude_videos: bool = False,
    ):
        nodes = Nodes([])
        nodes.nodes.append(
            Node(
                uin=uin,
                name="Nitter",
                content=[Plain(self.format_merged_header(batches))],
            )
        )

        index = 1
        for username, instance, tweets in batches:
            for tweet in tweets:
                nodes.nodes.append(
                    Node(
                        uin=uin,
                        name=f"@{username}",
                        content=self._build_components(
                            index, username, tweet, source=instance,
                            exclude_videos=exclude_videos,
                        ),
                    )
                )
                index += 1
        return nodes

    def _build_direct_components(
        self,
        username: str,
        instance: str,
        tweets: list[TweetItem],
        exclude_videos: bool = False,
        notices: list[str] | None = None,
    ):
        components = [
            Plain(self._format_header(username, instance, len(tweets), notices))
        ]
        for index, tweet in enumerate(tweets, 1):
            components.extend(
                self._build_direct_tweet_components(
                    index,
                    username,
                    tweet,
                    exclude_videos=exclude_videos,
                )
            )
        return components

    def _build_merged_direct_components(
        self, batches: list[TweetBatch], exclude_videos: bool = False,
    ):
        components = [Plain(self.format_merged_header(batches))]
        index = 1
        for username, instance, tweets in batches:
            for tweet in tweets:
                components.extend(
                    self._build_direct_tweet_components(
                        index,
                        username,
                        tweet,
                        source=instance,
                        exclude_videos=exclude_videos,
                    )
                )
                index += 1
        return components

    def _build_direct_tweet_components(
        self,
        index: int,
        username: str,
        tweet: TweetItem,
        source: str = "",
        exclude_videos: bool = False,
    ):
        components = self._build_components(
            index,
            username,
            tweet,
            source=source,
            exclude_videos=exclude_videos,
        )
        if components and isinstance(components[0], Plain):
            components[0].text = "\n\n" + components[0].text
        return components

    @staticmethod
    def _count_attached_videos(batches: list[TweetBatch]) -> int:
        return sum(
            1
            for _, _, tweets in batches
            for tweet in tweets
            for media in tweet.media
            if media.path and media.is_video
        )

    @staticmethod
    def _has_attached_videos(tweets: list[TweetItem]) -> bool:
        return any(
            media.is_video for tweet in tweets for media in tweet.media if media.path
        )

    @classmethod
    def _should_use_forward_for_umo(cls, context, umo: str) -> bool:
        platform = cls._platform_from_umo(umo)
        if cls._is_forward_platform(platform):
            return True
        return cls._is_forward_platform(cls._platform_type_from_context(context, platform))

    @classmethod
    def _should_use_forward_for_event(cls, event) -> bool:
        return cls._is_forward_platform(cls._event_platform(event))

    @classmethod
    def _is_forward_platform(cls, platform: str) -> bool:
        return platform.strip().lower() in cls.FORWARD_MESSAGE_PLATFORMS

    @staticmethod
    def _platform_from_umo(umo: str) -> str:
        return str(umo or "").split(":", 1)[0].strip()

    @classmethod
    def _platform_type_from_context(cls, context, platform_id: str) -> str:
        if not platform_id:
            return ""

        platform = None
        get_platform_inst = getattr(context, "get_platform_inst", None)
        if callable(get_platform_inst):
            try:
                platform = get_platform_inst(platform_id)
            except Exception as exc:
                logger.debug(
                    f"[NitterTweets] platform lookup failed for {platform_id}: {exc}"
                )

        if platform is None:
            manager = getattr(context, "platform_manager", None)
            for candidate in getattr(manager, "platform_insts", []) or []:
                meta = cls._safe_platform_meta(candidate)
                if str(getattr(meta, "id", "") or "") == platform_id:
                    platform = candidate
                    break

        if platform is None:
            return ""

        meta = cls._safe_platform_meta(platform)
        for attr in ("name", "id"):
            value = getattr(meta, attr, None)
            if value:
                return str(value)

        config = getattr(platform, "config", None)
        if isinstance(config, dict):
            return str(config.get("type") or "")
        return ""

    @staticmethod
    def _safe_platform_meta(platform):
        meta = getattr(platform, "meta", None)
        if not callable(meta):
            return None
        try:
            return meta()
        except Exception:
            return None

    @classmethod
    def _event_platform(cls, event) -> str:
        for method_name in ("get_platform_name", "get_platform_id"):
            value = safe_call(event, method_name)
            if value:
                return str(value)

        meta = getattr(event, "platform_meta", None)
        for attr in ("name", "id"):
            value = getattr(meta, attr, None)
            if value:
                return str(value)

        try:
            umo = getattr(event, "unified_msg_origin", "")
        except Exception:
            umo = ""
        return cls._platform_from_umo(str(umo))

    def _build_components(
        self, index: int, username: str, tweet: TweetItem, source: str = "",
        exclude_videos: bool = False,
    ):
        text = self.format_tweet_with_source(index, username, tweet, source)
        components = [Plain(text)]
        video_notice_added = False
        for media in tweet.media:
            if not media.path:
                continue
            if media.is_video and exclude_videos:
                if not video_notice_added:
                    components.append(
                        Plain(
                            "视频/GIF 附件未作为消息发送，请打开原文查看："
                            f"{tweet.x_url}"
                        )
                    )
                    video_notice_added = True
                continue
            if media.is_video and not self.send_video_attachments:
                if not video_notice_added:
                    components.append(
                        Plain(
                            "视频/GIF 附件发送功能仍在优化，当前按配置不发送，"
                            f"请打开原文查看：{tweet.x_url}"
                        )
                    )
                    video_notice_added = True
                continue
            if media.is_image and self.send_image_attachments:
                components.append(Image.fromFileSystem(str(media.path)))
            elif media.is_video:
                components.append(Video.fromFileSystem(str(media.path)))
        return components

    def _build_onebot_nodes(
        self,
        event,
        username: str,
        instance: str,
        tweets: list[TweetItem],
        notices: list[str] | None = None,
    ) -> list[dict]:
        uin = str(node_uin(event))
        items = [
            {
                "name": "Nitter",
                "uin": uin,
                "content": [
                    self._raw_text(
                        self._format_header(username, instance, len(tweets), notices)
                    )
                ],
            }
        ]
        for index, tweet in enumerate(tweets, 1):
            content = [self._raw_text(self.format_tweet(index, username, tweet))]
            content.extend(
                self._raw_media(media)
                for media in tweet.media
                if media.path
                and (
                    (media.is_image and self.send_image_attachments)
                    or (media.is_video and self.send_video_attachments)
                )
            )
            items.append({"name": f"@{username}", "uin": uin, "content": content})

        return [
            {
                "type": "node",
                "data": {
                    "name": item["name"],
                    "uin": item["uin"],
                    "content": item["content"],
                },
            }
            for item in items
        ]

    @staticmethod
    def _raw_text(text: str) -> dict:
        return {"type": "text", "data": {"text": text}}

    @staticmethod
    def _raw_media(media: TweetMedia) -> dict:
        uri = file_uri(media.path)
        if media.is_image:
            return {"type": "image", "data": {"file": uri}}
        return {"type": "video", "data": {"file": uri}}

    async def _send_onebot_forward(self, event, raw_nodes: list[dict]) -> bool:
        client = getattr(event, "bot", None)
        if client is None:
            return False

        call_action = None
        if hasattr(client, "api") and hasattr(client.api, "call_action"):
            call_action = client.api.call_action
        elif hasattr(client, "call_action"):
            call_action = client.call_action
        if call_action is None:
            return False

        group_id = safe_call(event, "get_group_id")
        if group_id:
            await self._call_forward_action(
                call_action,
                "send_group_forward_msg",
                {"group_id": int(group_id)},
                raw_nodes,
            )
            return True

        user_id = safe_call(event, "get_sender_id")
        if user_id:
            await self._call_forward_action(
                call_action,
                "send_private_forward_msg",
                {"user_id": int(user_id)},
                raw_nodes,
            )
            return True

        return False

    @staticmethod
    async def _call_forward_action(
        call_action,
        action: str,
        base_payload: dict,
        raw_nodes: list[dict],
    ) -> None:
        try:
            await call_action(action, **base_payload, messages=raw_nodes)
        except TypeError:
            await call_action(action, **base_payload, message=raw_nodes)

    def format_plain(
        self,
        username: str,
        instance: str,
        tweets: list[TweetItem],
        notices: list[str] | None = None,
    ) -> str:
        blocks = [self._format_header(username, instance, len(tweets), notices)]
        notice_text = self._format_notices(notices)
        if notice_text and notice_text not in blocks[0]:
            blocks.append(notice_text)
        blocks.extend(
            self.format_tweet(index, username, tweet)
            for index, tweet in enumerate(tweets, 1)
        )
        return "\n\n".join(blocks)

    def format_merged_plain(self, batches: list[TweetBatch]) -> str:
        blocks = [self.format_merged_header(batches)]
        index = 1
        for username, instance, tweets in batches:
            for tweet in tweets:
                blocks.append(
                    self.format_tweet_with_source(index, username, tweet, instance)
                )
                index += 1
        return "\n\n".join(blocks)

    @staticmethod
    def format_merged_header(batches: list[TweetBatch]) -> str:
        total = sum(len(tweets) for _, _, tweets in batches)
        accounts = "，".join(
            f"@{username} {len(tweets)} 条" for username, _, tweets in batches
        )
        lines = [
            f"Nitter 本次检查发现 {total} 条新推文",
            f"更新账号：{accounts}",
        ]
        return "\n".join(lines)

    @staticmethod
    def format_tweet_with_source(
        index: int, username: str, tweet: TweetItem, source: str = ""
    ) -> str:
        return TweetSender.format_tweet(index, username, tweet, source=source)

    @staticmethod
    def format_tweet(
        index: int,
        username: str,
        tweet: TweetItem,
        source: str = "",
    ) -> str:
        blocks = [f"#{index} @{username}"]
        if tweet.published:
            blocks[0] = f"{blocks[0]}\n时间：{tweet.published}"

        original_text = normalize_external_links(tweet.text).strip()
        if original_text:
            blocks.append(f"原文：\n{original_text}")

        translation = strip_external_links(tweet.translation)
        if translation:
            blocks.append(f"翻译：\n{translation}")

        image_caption = normalize_external_links(tweet.image_caption).strip()
        if image_caption:
            blocks.append(f"识图：\n{image_caption}")

        ai_comment = normalize_external_links(tweet.ai_comment).strip()
        if ai_comment:
            blocks.append(f"评论：\n{ai_comment}")

        original_link = tweet.x_url or tweet.link
        if original_link:
            blocks.append(f"原帖：\n{original_link}")

        if tweet.media_warnings:
            blocks.append(
                "媒体提示：\n"
                + "\n".join(f"- {warning}" for warning in tweet.media_warnings)
            )

        media_summary = TweetSender._format_media_summary(tweet)
        if media_summary:
            blocks.append(media_summary)

        if source:
            blocks.append(f"Nitter：{TweetSender._format_instance_label(source)}")

        return "\n\n".join(blocks)

    @classmethod
    def _format_header(
        cls,
        username: str,
        instance: str,
        tweet_count: int,
        notices: list[str] | None = None,
    ) -> str:
        lines = [
            f"@{username} 最近 {tweet_count} 条推文",
        ]
        if instance:
            lines.append(f"Nitter：{cls._format_instance_label(instance)}")
        notice_text = cls._format_notices(notices)
        if notice_text:
            lines.append(notice_text)
        return "\n".join(lines)

    @staticmethod
    def _format_notices(notices: list[str] | None = None) -> str:
        clean_notices = [
            notice.strip() for notice in notices or [] if notice and notice.strip()
        ]
        if not clean_notices:
            return ""
        return "\n".join(
            ["处理提示：", *[f"- {notice}" for notice in clean_notices]]
        )

    @staticmethod
    def _format_media_summary(tweet: TweetItem) -> str:
        image_count = sum(1 for item in tweet.media if item.is_image)
        video_count = sum(1 for item in tweet.media if item.is_video)
        parts = []
        if image_count:
            parts.append(f"图片 {image_count} 张")
        if video_count:
            parts.append(f"视频/GIF {video_count} 个")
        if not parts:
            return ""
        return "媒体：" + "，".join(parts)

    @staticmethod
    def _format_instance_label(instance: str) -> str:
        parsed = urlparse(instance)
        return parsed.netloc or parsed.path or instance
