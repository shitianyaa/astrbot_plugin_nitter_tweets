from __future__ import annotations

from dataclasses import dataclass

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
    from .utils import TweetItem, TweetMedia, file_uri, node_uin, safe_call
except ImportError:
    from utils import TweetItem, TweetMedia, file_uri, node_uin, safe_call


TweetBatch = tuple[str, str, list[TweetItem]]


@dataclass(slots=True)
class MergedSendOutcome:
    success: bool
    mode: str
    omitted_videos: int = 0
    error: str = ""


class TweetSender:
    async def send(
        self,
        event,
        username: str,
        instance: str,
        tweets: list[TweetItem],
        notices: list[str] | None = None,
    ) -> bool:
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
        nodes = self._build_nodes_for_uin(10000, username, instance, tweets)
        try:
            await context.send_message(umo, MessageChain([nodes]))
            return True
        except Exception as exc:
            logger.warning(f"Failed to send scheduled forwarded tweets to {umo}: {exc}")

        # 去掉视频后重试
        if any(m.is_video for t in tweets for m in t.media if m.path):
            try:
                nodes_nv = self._build_nodes_for_uin(
                    10000, username, instance, tweets, exclude_videos=True
                )
                await context.send_message(umo, MessageChain([nodes_nv]))
                logger.info(
                    f"Sent scheduled tweets to {umo} without videos after initial failure"
                )
                return True
            except Exception as exc:
                logger.warning(
                    f"Failed to send scheduled tweets to {umo} without videos: {exc}"
                )

        try:
            await context.send_message(
                umo, MessageChain([Plain(self.format_plain(username, instance, tweets))])
            )
            return True
        except Exception as exc:
            logger.warning(f"Failed to send scheduled tweet fallback to {umo}: {exc}")
            return False

    async def send_merged_to_umo(
        self,
        context,
        umo: str,
        batches: list[TweetBatch],
    ) -> MergedSendOutcome:
        omitted_videos = self._count_attached_videos(batches)
        nodes = self._build_merged_nodes_for_uin(10000, batches)
        try:
            await context.send_message(umo, MessageChain([nodes]))
            return MergedSendOutcome(success=True, mode="full_forward")
        except Exception as exc:
            error = str(exc)
            logger.warning(f"Failed to send merged scheduled tweets to {umo}: {exc}")

        if omitted_videos:
            try:
                nodes_nv = self._build_merged_nodes_for_uin(
                    10000, batches, exclude_videos=True
                )
                await context.send_message(umo, MessageChain([nodes_nv]))
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
            except Exception as exc:
                error = str(exc)
                logger.warning(
                    f"Failed to send merged tweets to {umo} without videos: {exc}"
                )

        try:
            await context.send_message(
                umo, MessageChain([Plain(self.format_merged_plain(batches))])
            )
            return MergedSendOutcome(
                success=True,
                mode="plain_fallback",
                omitted_videos=omitted_videos,
                error=error,
            )
        except Exception as exc:
            logger.warning(f"Failed to send merged scheduled tweet fallback to {umo}: {exc}")
            return MergedSendOutcome(
                success=False,
                mode="failed",
                omitted_videos=omitted_videos,
                error=str(exc),
            )

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

    @staticmethod
    def _count_attached_videos(batches: list[TweetBatch]) -> int:
        return sum(
            1
            for _, _, tweets in batches
            for tweet in tweets
            for media in tweet.media
            if media.path and media.is_video
        )

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
            uri = file_uri(media.path)
            if media.is_image:
                components.append(Image(uri))
            elif media.is_video:
                components.append(Video(uri))
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
            content.extend(self._raw_media(media) for media in tweet.media if media.path)
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
        blocks = [
            f"@{username} 最近 {len(tweets)} 条公开推文",
            f"来源：{instance}",
        ]
        notice_text = self._format_notices(notices)
        if notice_text:
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
            "提示：公共实例可能不稳定，请勿高频请求。",
        ]
        return "\n".join(lines)

    @staticmethod
    def format_tweet_with_source(
        index: int, username: str, tweet: TweetItem, source: str = ""
    ) -> str:
        text = TweetSender.format_tweet(index, username, tweet)
        if source:
            text = f"{text}\n来源：{source}"
        return text

    @staticmethod
    def format_tweet(index: int, username: str, tweet: TweetItem) -> str:
        lines = [f"#{index} @{username}"]
        if tweet.published:
            lines.append(tweet.published)
        if tweet.text:
            lines.append(tweet.text)
        if tweet.translation:
            lines.append("中文翻译：")
            lines.append(tweet.translation)
        if tweet.image_caption:
            lines.append("AI识图：")
            lines.append(tweet.image_caption)
        if tweet.ai_comment:
            lines.append("AI评论：")
            lines.append(tweet.ai_comment)
        if tweet.link:
            lines.append(tweet.link)
        if tweet.media_warnings:
            lines.append("媒体提示：" + "；".join(tweet.media_warnings))
        if tweet.media:
            image_count = sum(1 for item in tweet.media if item.is_image)
            video_count = sum(1 for item in tweet.media if item.is_video)
            parts = []
            if image_count:
                parts.append(f"{image_count} 张图片")
            if video_count:
                parts.append(f"{video_count} 个视频/GIF")
            if parts:
                lines.append("媒体：" + "，".join(parts))
        return "\n".join(lines)

    @classmethod
    def _format_header(
        cls,
        username: str,
        instance: str,
        tweet_count: int,
        notices: list[str] | None = None,
    ) -> str:
        lines = [
            f"@{username} 最近 {tweet_count} 条公开推文",
            f"来源：{instance}",
            "提示：公共实例可能不稳定，请勿高频请求。",
        ]
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
            ["AI增强提示：", *[f"- {notice}" for notice in clean_notices]]
        )
