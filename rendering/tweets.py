from __future__ import annotations

import re

from urllib.parse import urlparse

try:
    from astrbot.api.message_components import Image, Node, Nodes, Plain, Video
except ImportError:
    from astrbot.core.message.components import Image, Node, Nodes, Plain, Video

try:
    from ..shared import (
        TweetItem,
        TweetMedia,
        file_uri,
        node_uin,
        normalize_external_links,
        strip_external_links,
    )
except ImportError:
    from shared import (
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
        start_index: int = 1,
        exclude_videos: bool = False,
        notices: list[str] | None = None,
        group_label: str = "",
        header_text: str = "",
        batch_summary: str = "",
        media_only: bool = False,
        omit_status_url: bool = True,
        link_style: str = "plain",
    ):
        return self.build_nodes_for_uin(
            node_uin(event),
            username,
            instance,
            tweets,
            start_index=start_index,
            exclude_videos=exclude_videos,
            notices=notices,
            group_label=group_label,
            header_text=header_text,
            batch_summary=batch_summary,
            media_only=media_only,
        )

    def build_nodes_for_uin(
        self,
        uin,
        username: str,
        instance: str,
        tweets: list[TweetItem],
        start_index: int = 1,
        exclude_videos: bool = False,
        notices: list[str] | None = None,
        group_label: str = "",
        header_text: str = "",
        batch_summary: str = "",
        media_only: bool = False,
        omit_status_url: bool = True,
        link_style: str = "plain",
    ):
        nodes = Nodes([])
        header = self.format_header(
            username,
            instance,
            len(tweets),
            notices,
            group_label,
            header_text,
            batch_summary,
            media_only=media_only,
        )
        if header:
            nodes.nodes.append(
                Node(uin=uin, name="Nitter", content=[Plain(header)])
            )

        for offset, tweet in enumerate(tweets):
            index = start_index + offset
            nodes.nodes.append(
                Node(
                    uin=uin,
                    name=f"@{username}",
                    content=self.build_components(
                        index,
                        username,
                        tweet,
                        exclude_videos=exclude_videos,
                        include_videos=False,
                        include_images=False,
                        media_only=media_only,
                    omit_status_url=omit_status_url,
                    link_style=link_style,
                    ),
                )
            )
            for media in tweet.media:
                if media.path and media.is_image and self.send_image_attachments:
                    nodes.nodes.append(
                        Node(
                            uin=uin,
                            name=f"@{username}",
                            content=self.build_image_node_components(
                                index,
                                username,
                                tweet,
                                media,
                                source=instance,
                                media_only=media_only,
                            ),
                        )
                    )
            if not exclude_videos and self.send_video_attachments:
                for media in tweet.media:
                    if media.path and media.is_video:
                        nodes.nodes.append(
                            Node(
                                uin=uin,
                                name=f"@{username}",
                                content=self.build_video_node_components(
                                    index,
                                    username,
                                    tweet,
                                    media,
                                    source=instance,
                                    media_only=media_only,
                                ),
                            )
                        )
        return nodes

    def build_merged_nodes_for_uin(
        self,
        uin,
        batches: list[TweetBatch],
        start_index: int = 1,
        exclude_videos: bool = False,
        group_label: str = "",
        batch_summary: str = "",
        media_only: bool = False,
        omit_status_url: bool = True,
        link_style: str = "plain",
    ):
        nodes = Nodes([])
        header = self.format_merged_header(batches, group_label, batch_summary)
        if header:
            nodes.nodes.append(Node(uin=uin, name="Nitter", content=[Plain(header)]))

        index = start_index
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
                            include_videos=False,
                            include_images=False,
                            media_only=media_only,
                    omit_status_url=omit_status_url,
                    link_style=link_style,
                        ),
                    )
                )
                for media in tweet.media:
                    if media.path and media.is_image and self.send_image_attachments:
                        nodes.nodes.append(
                            Node(
                                uin=uin,
                                name=f"@{username}",
                                content=self.build_image_node_components(
                                    index,
                                    username,
                                    tweet,
                                    media,
                                    source=instance,
                                    media_only=media_only,
                                ),
                            )
                        )
                if not exclude_videos and self.send_video_attachments:
                    for media in tweet.media:
                        if media.path and media.is_video:
                            nodes.nodes.append(
                                Node(
                                    uin=uin,
                                    name=f"@{username}",
                                    content=self.build_video_node_components(
                                        index,
                                        username,
                                        tweet,
                                        media,
                                        source=instance,
                                        media_only=media_only,
                                    ),
                                )
                            )
                index += 1
        return nodes

    def build_merged_onebot_nodes_for_uin(
        self,
        uin,
        batches: list[TweetBatch],
        start_index: int = 1,
        exclude_videos: bool = False,
        group_label: str = "",
        batch_summary: str = "",
        media_only: bool = False,
        omit_status_url: bool = True,
        link_style: str = "plain",
    ) -> list[dict]:
        items = []
        header = self.format_merged_header(batches, group_label, batch_summary)
        if header:
            items.append(
                {
                    "name": "Nitter",
                    "uin": str(uin),
                    "content": [self.raw_text(header)],
                }
            )

        index = start_index
        for username, instance, tweets in batches:
            for tweet in tweets:
                content = self._build_onebot_tweet_content(
                    index,
                    username,
                    instance,
                    tweet,
                    exclude_videos=exclude_videos,
                    include_videos=False,
                    include_images=False,
                    media_only=media_only,
                omit_status_url=omit_status_url,
                link_style=link_style,
                )
                items.append(
                    {
                        "name": f"@{username}",
                        "uin": str(uin),
                        "content": content,
                    }
                )
                for media in tweet.media:
                    if media.path and media.is_image and self.send_image_attachments:
                        items.append(
                            {
                                "name": f"@{username}",
                                "uin": str(uin),
                                "content": self._build_onebot_image_content(
                                    index,
                                    username,
                                    tweet,
                                    media,
                                    source=instance,
                                    media_only=media_only,
                                ),
                            }
                        )
                if not exclude_videos and self.send_video_attachments:
                    for media in tweet.media:
                        if media.path and media.is_video:
                            items.append(
                                {
                                    "name": f"@{username}",
                                    "uin": str(uin),
                                    "content": self._build_onebot_video_content(
                                        index,
                                        username,
                                        tweet,
                                        media,
                                        source=instance,
                                        media_only=media_only,
                                    ),
                                }
                            )
                index += 1

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

    def build_direct_components(
        self,
        username: str,
        instance: str,
        tweets: list[TweetItem],
        start_index: int = 1,
        exclude_videos: bool = False,
        include_videos: bool = True,
        include_images: bool = True,
        notices: list[str] | None = None,
        group_label: str = "",
        header_text: str = "",
        batch_summary: str = "",
        media_only: bool = False,
        omit_status_url: bool = True,
        link_style: str = "plain",
    ):
        components = []
        header = self.format_header(
            username,
            instance,
            len(tweets),
            notices,
            group_label,
            header_text,
            batch_summary,
            media_only=media_only,
        )
        if header:
            components.append(Plain(header))
        for offset, tweet in enumerate(tweets):
            index = start_index + offset
            tweet_components = self.build_direct_tweet_components(
                index,
                username,
                tweet,
                exclude_videos=exclude_videos,
                include_videos=include_videos,
                include_images=include_images,
                media_only=media_only,
                omit_status_url=omit_status_url,
                link_style=link_style,
            )
            self._prepend_component_separator(tweet_components, bool(components))
            components.extend(tweet_components)
        return components

    def build_media_only_components(
        self,
        username: str,
        tweet: TweetItem,
        *,
        exclude_videos: bool = False,
        include_videos: bool = True,
        include_images: bool = True,
        omit_status_url: bool = True,
        link_style: str = "plain",
    ):
        """Render only the author marker and successfully prepared media."""
        author = f"@{username}"
        status_url = (tweet.x_url or tweet.link or "").strip()
        if link_style == "telegram_md" and status_url:
            preview = TweetMessageRenderer.telegram_link_preview(
                tweet, username, max_chars=40
            )
            author = TweetMessageRenderer.telegram_markdown_link(preview, status_url)
        components = [Plain(author)]
        for media in tweet.media:
            if not media.path:
                continue
            if media.is_image and self.send_image_attachments and include_images:
                components.append(Image.fromFileSystem(str(media.path)))
            elif (
                media.is_video
                and self.send_video_attachments
                and include_videos
                and not exclude_videos
            ):
                components.append(Video.fromFileSystem(str(media.path)))
        return components

    def build_merged_direct_components(
        self,
        batches: list[TweetBatch],
        start_index: int = 1,
        exclude_videos: bool = False,
        group_label: str = "",
        batch_summary: str = "",
        media_only: bool = False,
        omit_status_url: bool = True,
        link_style: str = "plain",
    ):
        components = []
        header = self.format_merged_header(batches, group_label, batch_summary)
        if header:
            components.append(Plain(header))
        index = start_index
        for username, instance, tweets in batches:
            for tweet in tweets:
                tweet_components = self.build_direct_tweet_components(
                    index,
                    username,
                    tweet,
                    source=instance,
                    exclude_videos=exclude_videos,
                    include_images=True,
                    media_only=media_only,
                omit_status_url=omit_status_url,
                link_style=link_style,
                )
                self._prepend_component_separator(tweet_components, bool(components))
                components.extend(tweet_components)
                index += 1
        return components

    def build_direct_tweet_components(
        self,
        index: int,
        username: str,
        tweet: TweetItem,
        source: str = "",
        exclude_videos: bool = False,
        include_videos: bool = True,
        include_images: bool = True,
        media_only: bool = False,
        omit_status_url: bool = True,
        link_style: str = "plain",
    ):
        components = self.build_components(
            index,
            username,
            tweet,
            source=source,
            exclude_videos=exclude_videos,
            include_videos=include_videos,
            include_images=include_images,
            media_only=media_only,
            omit_status_url=omit_status_url,
            link_style=link_style,
        )
        return components

    @staticmethod
    def _prepend_component_separator(components, needed: bool) -> None:
        if not needed or not components or not isinstance(components[0], Plain):
            return
        if components[0].text:
            components[0].text = "\n\n" + components[0].text

    def build_direct_image_components(self, tweets: list[TweetItem]):
        components = []
        if not self.send_image_attachments:
            return components
        for tweet in tweets:
            for media in tweet.media:
                if media.path and media.is_image:
                    components.append(Image.fromFileSystem(str(media.path)))
        return components

    def build_direct_video_components(self, tweets: list[TweetItem]):
        components = []
        for tweet in tweets:
            for media in tweet.media:
                if media.path and media.is_video:
                    components.append(Video.fromFileSystem(str(media.path)))
        return components

    def build_video_omitted_notice_components(self, tweets: list[TweetItem]):
        lines = []
        seen_links = set()
        for tweet in tweets:
            if not any(media.path and media.is_video for media in tweet.media):
                continue
            original_link = tweet.x_url or tweet.link
            if original_link in seen_links:
                continue
            seen_links.add(original_link)
            lines.append(f"视频/GIF 附件未作为消息发送，请打开原文查看：{original_link}")
        if not lines:
            return []
        return [Plain("\n".join(lines))]

    def build_components(
        self, index: int, username: str, tweet: TweetItem, source: str = "",
        exclude_videos: bool = False,
        include_videos: bool = True,
        include_images: bool = True,
        media_only: bool = False,
        omit_status_url: bool = True,
        link_style: str = "plain",
    ):
        if media_only:
            return self.build_media_only_components(
                username,
                tweet,
                exclude_videos=exclude_videos,
                include_videos=include_videos,
                include_images=include_images,
                omit_status_url=omit_status_url,
                link_style=link_style,
            )

        text = self.format_tweet_with_source(
            index,
            username,
            tweet,
            source,
            omit_status_url=omit_status_url,
            link_style=link_style,
        )
        components = [Plain(text)]
        video_notice_added = False
        for media in tweet.media:
            if not media.path:
                continue
            if media.is_video and exclude_videos:
                if not video_notice_added:
                    components.append(
                        Plain(
                            "视频/GIF 附件未作为消息发送。"
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
            if media.is_video and not include_videos:
                continue
            if media.is_image and self.send_image_attachments and include_images:
                components.append(Image.fromFileSystem(str(media.path)))
            elif media.is_video:
                components.append(Video.fromFileSystem(str(media.path)))
        return components

    def build_video_node_components(
        self,
        index: int,
        username: str,
        tweet: TweetItem,
        media: TweetMedia,
        source: str = "",
        media_only: bool = False,
        omit_status_url: bool = True,
        link_style: str = "plain",
    ):
        if media_only:
            return [Video.fromFileSystem(str(media.path))]
        return [
            Plain(
                self.format_video_attachment_text(
                    index, username, tweet, source, media_only=media_only
                )
            ),
            Video.fromFileSystem(str(media.path)),
        ]

    def build_image_node_components(
        self,
        index: int,
        username: str,
        tweet: TweetItem,
        media: TweetMedia,
        source: str = "",
        media_only: bool = False,
        omit_status_url: bool = True,
        link_style: str = "plain",
    ):
        if media_only:
            return [Image.fromFileSystem(str(media.path))]
        return [
            Plain(
                self.format_image_attachment_text(
                    index, username, tweet, source, media_only=media_only
                )
            ),
            Image.fromFileSystem(str(media.path)),
        ]

    def build_onebot_nodes(
        self,
        event,
        username: str,
        instance: str,
        tweets: list[TweetItem],
        start_index: int = 1,
        notices: list[str] | None = None,
        group_label: str = "",
        header_text: str = "",
        media_only: bool = False,
        omit_status_url: bool = True,
        link_style: str = "plain",
    ) -> list[dict]:
        uin = str(node_uin(event))
        items = []
        header = self.format_header(
            username,
            instance,
            len(tweets),
            notices,
            group_label,
            header_text,
            media_only=media_only,
        )
        if header:
            items.append(
                {
                    "name": "Nitter",
                    "uin": uin,
                    "content": [self.raw_text(header)],
                }
            )
        for offset, tweet in enumerate(tweets):
            index = start_index + offset
            content = self._build_onebot_tweet_content(
                index,
                username,
                instance,
                tweet,
                include_videos=False,
                include_images=False,
                media_only=media_only,
                omit_status_url=omit_status_url,
                link_style=link_style,
            )
            items.append({"name": f"@{username}", "uin": uin, "content": content})
            for media in tweet.media:
                if media.path and media.is_image and self.send_image_attachments:
                    items.append(
                        {
                            "name": f"@{username}",
                            "uin": uin,
                            "content": self._build_onebot_image_content(
                                index,
                                username,
                                tweet,
                                media,
                                source=instance,
                                media_only=media_only,
                            ),
                        }
                    )
            if self.send_video_attachments:
                for media in tweet.media:
                    if media.path and media.is_video:
                        items.append(
                            {
                                "name": f"@{username}",
                                "uin": uin,
                                "content": self._build_onebot_video_content(
                                    index,
                                    username,
                                    tweet,
                                    media,
                                    source=instance,
                                    media_only=media_only,
                                ),
                            }
                        )

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

    def _build_onebot_video_content(
        self,
        index: int,
        username: str,
        tweet: TweetItem,
        media: TweetMedia,
        source: str = "",
        media_only: bool = False,
        omit_status_url: bool = True,
        link_style: str = "plain",
    ) -> list[dict]:
        if media_only:
            return [self.raw_media(media)]
        return [
            self.raw_text(
                self.format_video_attachment_text(
                    index, username, tweet, source, media_only=media_only
                )
            ),
            self.raw_media(media),
        ]

    def _build_onebot_image_content(
        self,
        index: int,
        username: str,
        tweet: TweetItem,
        media: TweetMedia,
        source: str = "",
        media_only: bool = False,
        omit_status_url: bool = True,
        link_style: str = "plain",
    ) -> list[dict]:
        if media_only:
            return [self.raw_media(media)]
        return [
            self.raw_text(
                self.format_image_attachment_text(
                    index, username, tweet, source, media_only=media_only
                )
            ),
            self.raw_media(media),
        ]

    def _build_onebot_tweet_content(
        self,
        index: int,
        username: str,
        instance: str,
        tweet: TweetItem,
        exclude_videos: bool = False,
        include_videos: bool = True,
        include_images: bool = True,
        media_only: bool = False,
        omit_status_url: bool = True,
        link_style: str = "plain",
    ) -> list[dict]:
        if media_only:
            content = [self.raw_text(f"@{username}")]
        else:
            content = [
                self.raw_text(
                    self.format_tweet_with_source(index, username, tweet, instance, omit_status_url=omit_status_url, link_style=link_style)
                )
            ]
        video_notice_added = False
        for media in tweet.media:
            if not media.path:
                continue
            if media.is_video and exclude_videos:
                if media_only:
                    continue
                if not video_notice_added:
                    content.append(
                        self.raw_text(
                            "视频/GIF 附件未作为消息发送。"
                        )
                    )
                    video_notice_added = True
                continue
            if media.is_image and self.send_image_attachments and include_images:
                content.append(self.raw_media(media))
            elif (
                media.is_video
                and self.send_video_attachments
                and not exclude_videos
                and include_videos
            ):
                content.append(self.raw_media(media))
        return content

    def format_plain(
        self,
        username: str,
        instance: str,
        tweets: list[TweetItem],
        start_index: int = 1,
        notices: list[str] | None = None,
        group_label: str = "",
        header_text: str = "",
        batch_summary: str = "",
        media_only: bool = False,
        omit_status_url: bool = True,
        link_style: str = "plain",
    ) -> str:
        # format_header already embeds notices when media_only is false.
        blocks = []
        header = self.format_header(
            username,
            instance,
            len(tweets),
            notices,
            group_label,
            header_text,
            batch_summary,
            media_only=media_only,
        )
        if header:
            blocks.append(header)
        blocks.extend(
            (
                f"@{username}"
                if media_only
                else self.format_tweet_with_source(
                    start_index + offset,
                    username,
                    tweet,
                    instance,
                    omit_status_url=omit_status_url,
                    link_style=link_style,
                )
            )
            for offset, tweet in enumerate(tweets)
        )
        return "\n\n".join(block for block in blocks if block)

    def format_merged_plain(
        self,
        batches: list[TweetBatch],
        start_index: int = 1,
        group_label: str = "",
        batch_summary: str = "",
        media_only: bool = False,
        omit_status_url: bool = True,
        link_style: str = "plain",
    ) -> str:
        blocks = [self.format_merged_header(batches, group_label, batch_summary)]
        index = start_index
        for username, instance, tweets in batches:
            for tweet in tweets:
                blocks.append(
                    (
                        f"@{username}"
                        if media_only
                        else self.format_tweet_with_source(
                        index,
                        username,
                        tweet,
                        instance,
                        omit_status_url=omit_status_url,
                        link_style=link_style,
                    )
                    )
                )
                index += 1
        return "\n\n".join(blocks)

    @staticmethod
    def format_merged_header(
        batches: list[TweetBatch],
        group_label: str = "",
        batch_summary: str = "",
    ) -> str:
        if batch_summary.strip():
            return batch_summary.strip()
        return TweetMessageRenderer.format_batch_summary(batches, group_label)

    @staticmethod
    def format_batch_summary(
        batches: list[TweetBatch],
        group_label: str = "",
        action_text: str = "本次检查发现",
    ) -> str:
        total = sum(len(tweets) for _, _, tweets in batches)
        counts: dict[str, int] = {}
        for username, _, tweets in batches:
            counts[username] = counts.get(username, 0) + len(tweets)
        lines = [f"Nitter {action_text}更新"]
        lines.append(f"博主：{len(counts)} 个")
        lines.append(f"推文：{total} 条")
        if group_label:
            lines.append(f"分组：{group_label}")
        return "\n".join(lines)

    @staticmethod
    def format_tweet_with_source(
        index: int,
        username: str,
        tweet: TweetItem,
        source: str = "",
        **kwargs,
    ) -> str:
        return TweetMessageRenderer.format_tweet(
            index, username, tweet, source=source, **kwargs
        )

    @staticmethod
    def format_tweet(
        index: int,
        username: str,
        tweet: TweetItem,
        source: str = "",
        *,
        omit_status_url: bool = True,
        link_style: str = "plain",
        link_preview_max_chars: int = 40,
    ) -> str:
        status_url = (tweet.x_url or tweet.link or "").strip()
        author_line = f"@{username}"
        if link_style == "telegram_md" and status_url:
            preview = TweetMessageRenderer.telegram_link_preview(
                tweet, username, max_chars=link_preview_max_chars
            )
            author_line = TweetMessageRenderer.telegram_markdown_link(
                preview, status_url
            )
        blocks = [author_line]
        if tweet.published:
            blocks[0] = blocks[0] + "\n时间：" + str(tweet.published)

        original_text = normalize_external_links(tweet.text).strip()
        if omit_status_url:
            original_text = strip_external_links(original_text)
        if original_text:
            blocks.append("原文：\n" + original_text)

        translation = (tweet.translation or "").strip()
        if translation:
            if omit_status_url:
                translation = strip_external_links(translation)
            else:
                translation = normalize_external_links(translation).strip()
        if translation:
            blocks.append("翻译：\n" + translation)

        if tweet.ai_warnings:
            warns = "\n".join(f"- {w}" for w in tweet.ai_warnings if w)
            blocks.append("AI提示：\n" + warns)

        if not omit_status_url and status_url:
            blocks.append("原文链接：\n" + status_url)

        if tweet.media_warnings:
            warns = "\n".join(f"- {w}" for w in tweet.media_warnings)
            blocks.append("媒体提示：\n" + warns)

        media_summary = TweetMessageRenderer.format_media_summary(tweet)
        if media_summary:
            blocks.append(media_summary)

        if source:
            blocks.append(
                "Nitter：" + TweetMessageRenderer.format_instance_label(source)
            )

        return "\n\n".join(blocks)

    @staticmethod
    def telegram_link_preview(
        tweet: TweetItem,
        username: str,
        *,
        max_chars: int = 40,
    ) -> str:
        text = strip_external_links(tweet.text or "").replace("\n", " ").strip()
        if not text:
            text = f"@{username}"
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) > max_chars:
            text = text[: max(1, max_chars - 1)].rstrip() + "…"
        return text or f"@{username}"

    @staticmethod
    def telegram_markdown_link(label: str, url: str) -> str:
        safe_label = str(label or "")
        for ch in ("\\", "`", "*", "_", "["):
            safe_label = safe_label.replace(ch, "\\" + ch)
        safe_label = safe_label.replace("]", "\\]")
        safe_url = str(url or "").strip()
        if safe_url and not safe_url.startswith(("http://", "https://")):
            safe_url = "https://" + safe_url.lstrip("/")
        safe_url = safe_url.replace("(", "%28").replace(")", "%29")
        return "[" + safe_label + "](" + safe_url + ")"

    def format_video_attachment_text(
        index: int,
        username: str,
        tweet: TweetItem,
        source: str = "",
        media_only: bool = False,
        omit_status_url: bool = True,
        link_style: str = "plain",
    ) -> str:
        if media_only:
            return f"@{username}"
        text = TweetMessageRenderer.format_tweet(
            index,
            username,
            tweet,
            source=source,
            omit_status_url=omit_status_url,
            link_style=link_style,
        )
        if text:
            return f"{text}\n\n视频/GIF 附件"
        return f"@{username}\n视频/GIF 附件"

    @staticmethod
    def format_image_attachment_text(
        index: int,
        username: str,
        tweet: TweetItem,
        source: str = "",
        media_only: bool = False,
        omit_status_url: bool = True,
        link_style: str = "plain",
    ) -> str:
        if media_only:
            return f"@{username}"
        lines = [f"@{username}", "图片附件"]
        if not omit_status_url:
            original_link = tweet.x_url or tweet.link
            if original_link:
                lines.append("原帖：" + original_link)
        if source:
            lines.append(
                "Nitter：" + TweetMessageRenderer.format_instance_label(source)
            )
        return "\n".join(lines)


    @classmethod
    def format_header(
        cls,
        username: str,
        instance: str,
        tweet_count: int,
        notices: list[str] | None = None,
        group_label: str = "",
        header_text: str = "",
        batch_summary: str = "",
        media_only: bool = False,
        omit_status_url: bool = True,
        link_style: str = "plain",
    ) -> str:
        summary = batch_summary.strip()
        lines = []
        if summary:
            lines.append(summary)
        if header_text.strip():
            lines.append(header_text.strip())
        if group_label and (summary or header_text.strip()) and f"分组：{group_label}" not in summary:
            lines.append(f"分组：{group_label}")
        notice_text = "" if media_only else cls.format_notices(notices)
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
