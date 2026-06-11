from __future__ import annotations

from urllib.parse import urlparse

try:
    from astrbot.api.message_components import Image, Node, Nodes, Plain, Video
except ImportError:
    from astrbot.core.message.components import Image, Node, Nodes, Plain, Video

try:
    from .utils import (
        TweetItem,
        TweetMedia,
        file_uri,
        node_uin,
        normalize_external_links,
        strip_external_links,
    )
except ImportError:
    from utils import (
        TweetItem,
        TweetMedia,
        file_uri,
        node_uin,
        normalize_external_links,
        strip_external_links,
    )


TweetBatch = tuple[str, str, list[TweetItem]]


class TweetMessageRenderer:
    def __init__(
        self,
        send_image_attachments: bool = True,
        send_video_attachments: bool = False,
    ):
        self.send_image_attachments = send_image_attachments
        self.send_video_attachments = send_video_attachments

    def build_nodes(
        self,
        event,
        username: str,
        instance: str,
        tweets: list[TweetItem],
        exclude_videos: bool = False,
        notices: list[str] | None = None,
        group_label: str = "",
        header_text: str = "",
    ):
        return self.build_nodes_for_uin(
            node_uin(event),
            username,
            instance,
            tweets,
            exclude_videos,
            notices,
            group_label,
            header_text,
        )

    def build_nodes_for_uin(
        self,
        uin,
        username: str,
        instance: str,
        tweets: list[TweetItem],
        exclude_videos: bool = False,
        notices: list[str] | None = None,
        group_label: str = "",
        header_text: str = "",
    ):
        nodes = Nodes([])
        nodes.nodes.append(
            Node(
                uin=uin,
                name="Nitter",
                content=[
                    Plain(
                        self.format_header(
                            username,
                            instance,
                            len(tweets),
                            notices,
                            group_label,
                            header_text,
                        )
                    )
                ],
            )
        )

        for index, tweet in enumerate(tweets, 1):
            nodes.nodes.append(
                Node(
                    uin=uin,
                    name=f"@{username}",
                    content=self.build_components(
                        index, username, tweet, exclude_videos=exclude_videos
                    ),
                )
            )
        return nodes

    def build_merged_nodes_for_uin(
        self,
        uin,
        batches: list[TweetBatch],
        exclude_videos: bool = False,
        group_label: str = "",
    ):
        nodes = Nodes([])
        nodes.nodes.append(
            Node(
                uin=uin,
                name="Nitter",
                content=[Plain(self.format_merged_header(batches, group_label))],
            )
        )

        index = 1
        for username, instance, tweets in batches:
            for tweet in tweets:
                nodes.nodes.append(
                    Node(
                        uin=uin,
                        name=f"@{username}",
                        content=self.build_components(
                            index,
                            username,
                            tweet,
                            source=instance,
                            exclude_videos=exclude_videos,
                        ),
                    )
                )
                index += 1
        return nodes

    def build_direct_components(
        self,
        username: str,
        instance: str,
        tweets: list[TweetItem],
        exclude_videos: bool = False,
        notices: list[str] | None = None,
        group_label: str = "",
        header_text: str = "",
    ):
        components = [
            Plain(
                self.format_header(
                    username,
                    instance,
                    len(tweets),
                    notices,
                    group_label,
                    header_text,
                )
            )
        ]
        for index, tweet in enumerate(tweets, 1):
            components.extend(
                self.build_direct_tweet_components(
                    index,
                    username,
                    tweet,
                    exclude_videos=exclude_videos,
                )
            )
        return components

    def build_merged_direct_components(
        self,
        batches: list[TweetBatch],
        exclude_videos: bool = False,
        group_label: str = "",
    ):
        components = [Plain(self.format_merged_header(batches, group_label))]
        index = 1
        for username, instance, tweets in batches:
            for tweet in tweets:
                components.extend(
                    self.build_direct_tweet_components(
                        index,
                        username,
                        tweet,
                        source=instance,
                        exclude_videos=exclude_videos,
                    )
                )
                index += 1
        return components

    def build_direct_tweet_components(
        self,
        index: int,
        username: str,
        tweet: TweetItem,
        source: str = "",
        exclude_videos: bool = False,
    ):
        components = self.build_components(
            index,
            username,
            tweet,
            source=source,
            exclude_videos=exclude_videos,
        )
        if components and isinstance(components[0], Plain):
            components[0].text = "\n\n" + components[0].text
        return components

    def build_components(
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

    def build_onebot_nodes(
        self,
        event,
        username: str,
        instance: str,
        tweets: list[TweetItem],
        notices: list[str] | None = None,
        group_label: str = "",
        header_text: str = "",
    ) -> list[dict]:
        uin = str(node_uin(event))
        items = [
            {
                "name": "Nitter",
                "uin": uin,
                "content": [
                    self.raw_text(
                        self.format_header(
                            username,
                            instance,
                            len(tweets),
                            notices,
                            group_label,
                            header_text,
                        )
                    )
                ],
            }
        ]
        for index, tweet in enumerate(tweets, 1):
            content = [self.raw_text(self.format_tweet(index, username, tweet))]
            content.extend(
                self.raw_media(media)
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
    def raw_text(text: str) -> dict:
        return {"type": "text", "data": {"text": text}}

    @staticmethod
    def raw_media(media: TweetMedia) -> dict:
        uri = file_uri(media.path)
        if media.is_image:
            return {"type": "image", "data": {"file": uri}}
        return {"type": "video", "data": {"file": uri}}

    def format_plain(
        self,
        username: str,
        instance: str,
        tweets: list[TweetItem],
        notices: list[str] | None = None,
        group_label: str = "",
        header_text: str = "",
    ) -> str:
        blocks = [
            self.format_header(
                username,
                instance,
                len(tweets),
                notices,
                group_label,
                header_text,
            )
        ]
        notice_text = self.format_notices(notices)
        if notice_text and notice_text not in blocks[0]:
            blocks.append(notice_text)
        blocks.extend(
            self.format_tweet(index, username, tweet)
            for index, tweet in enumerate(tweets, 1)
        )
        return "\n\n".join(blocks)

    def format_merged_plain(
        self, batches: list[TweetBatch], group_label: str = ""
    ) -> str:
        blocks = [self.format_merged_header(batches, group_label)]
        index = 1
        for username, instance, tweets in batches:
            for tweet in tweets:
                blocks.append(
                    self.format_tweet_with_source(index, username, tweet, instance)
                )
                index += 1
        return "\n\n".join(blocks)

    @staticmethod
    def format_merged_header(
        batches: list[TweetBatch], group_label: str = ""
    ) -> str:
        total = sum(len(tweets) for _, _, tweets in batches)
        counts: dict[str, int] = {}
        for username, _, tweets in batches:
            counts[username] = counts.get(username, 0) + len(tweets)
        accounts = "，".join(
            f"@{username} {count} 条" for username, count in counts.items()
        )
        lines = [f"Nitter 本次检查发现 {total} 条新推文"]
        if group_label:
            lines.append(f"分组：{group_label}")
        lines.append(f"更新账号：{accounts}")
        return "\n".join(lines)

    @staticmethod
    def format_tweet_with_source(
        index: int, username: str, tweet: TweetItem, source: str = ""
    ) -> str:
        return TweetMessageRenderer.format_tweet(index, username, tweet, source=source)

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

        media_summary = TweetMessageRenderer.format_media_summary(tweet)
        if media_summary:
            blocks.append(media_summary)

        if source:
            blocks.append(f"Nitter：{TweetMessageRenderer.format_instance_label(source)}")

        return "\n\n".join(blocks)

    @classmethod
    def format_header(
        cls,
        username: str,
        instance: str,
        tweet_count: int,
        notices: list[str] | None = None,
        group_label: str = "",
        header_text: str = "",
    ) -> str:
        lines = [
            header_text.strip() or f"@{username} 最近 {tweet_count} 条推文",
        ]
        if group_label:
            lines.append(f"分组：{group_label}")
        if instance:
            lines.append(f"Nitter：{cls.format_instance_label(instance)}")
        notice_text = cls.format_notices(notices)
        if notice_text:
            lines.append(notice_text)
        return "\n".join(lines)

    @staticmethod
    def format_notices(notices: list[str] | None = None) -> str:
        clean_notices = [
            notice.strip() for notice in notices or [] if notice and notice.strip()
        ]
        if not clean_notices:
            return ""
        return "\n".join(
            ["处理提示：", *[f"- {notice}" for notice in clean_notices]]
        )

    @staticmethod
    def format_media_summary(tweet: TweetItem) -> str:
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
    def format_instance_label(instance: str) -> str:
        parsed = urlparse(instance)
        return parsed.netloc or parsed.path or instance
