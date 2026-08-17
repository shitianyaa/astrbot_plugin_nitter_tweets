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
        format_subscription_count,
        format_subscription_source,
        format_tweet_published,
        node_uin,
        normalize_external_links,
        strip_external_links,
    )
except ImportError:
    from shared import (
        TweetItem,
        TweetMedia,
        file_uri,
        format_subscription_count,
        format_subscription_source,
        format_tweet_published,
        node_uin,
        normalize_external_links,
        strip_external_links,
    )


TweetBatch = tuple[str, str, list[TweetItem]]

_QQ_OFFICIAL_URL_RE = re.compile(r"https?://[^\s<>]+", re.IGNORECASE)
_QQ_OFFICIAL_URL_TRAILING_PUNCTUATION = frozenset(".,;:!?)]}。、！）；：，》《？")
# Renders as nothing, but breaks up a syntax run that must not be recognised.
_ZERO_WIDTH_SPACE = "\u200b"


class TweetMessageRenderer:
    def __init__(
        self,
        send_image_attachments: bool = True,
        send_video_attachments: bool = False,
    ):
        self.send_image_attachments = send_image_attachments
        self.send_video_attachments = send_video_attachments

    @staticmethod
    def _source_node_name(username: str) -> str:
        """Render internal tag/List keys without exposing their storage prefix."""
        raw = str(username or "").strip()
        if raw.lower().startswith(("q:", "list:")):
            return format_subscription_source(raw)
        return f"@{raw.lstrip('@')}" if raw else "@unknown"

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
        hide_original_when_translated: bool = False,
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
            omit_status_url=omit_status_url,
            hide_original_when_translated=hide_original_when_translated,
            link_style=link_style,
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
        hide_original_when_translated: bool = False,
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
            link_style=link_style,
        )
        if header:
            nodes.nodes.append(Node(uin=uin, name="Nitter", content=[Plain(header)]))

        for offset, tweet in enumerate(tweets):
            index = start_index + offset
            nodes.nodes.append(
                Node(
                    uin=uin,
                    name=self._source_node_name(username),
                    content=self.build_components(
                        index,
                        username,
                        tweet,
                        exclude_videos=exclude_videos,
                        include_videos=False,
                        include_images=False,
                        media_only=media_only,
                        omit_status_url=omit_status_url,
                        hide_original_when_translated=hide_original_when_translated,
                        link_style=link_style,
                    ),
                )
            )
            for media in tweet.media:
                if media.path and media.is_image and self.send_image_attachments:
                    nodes.nodes.append(
                        Node(
                            uin=uin,
                            name=self._source_node_name(username),
                            content=self.build_image_node_components(
                                index,
                                username,
                                tweet,
                                media,
                                source=instance,
                                media_only=media_only,
                                omit_status_url=omit_status_url,
                                hide_original_when_translated=hide_original_when_translated,
                                link_style=link_style,
                            ),
                        )
                    )
            if not exclude_videos and self.send_video_attachments:
                for media in tweet.media:
                    if media.path and media.is_video:
                        nodes.nodes.append(
                            Node(
                                uin=uin,
                                name=self._source_node_name(username),
                                content=self.build_video_node_components(
                                    index,
                                    username,
                                    tweet,
                                    media,
                                    source=instance,
                                    media_only=media_only,
                                    omit_status_url=omit_status_url,
                                    hide_original_when_translated=hide_original_when_translated,
                                    link_style=link_style,
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
        hide_original_when_translated: bool = False,
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
                        name=self._source_node_name(username),
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
                            hide_original_when_translated=hide_original_when_translated,
                            link_style=link_style,
                        ),
                    )
                )
                for media in tweet.media:
                    if media.path and media.is_image and self.send_image_attachments:
                        nodes.nodes.append(
                            Node(
                                uin=uin,
                                name=self._source_node_name(username),
                                content=self.build_image_node_components(
                                    index,
                                    username,
                                    tweet,
                                    media,
                                    source=instance,
                                    media_only=media_only,
                                    omit_status_url=omit_status_url,
                                    hide_original_when_translated=hide_original_when_translated,
                                    link_style=link_style,
                                ),
                            )
                        )
                if not exclude_videos and self.send_video_attachments:
                    for media in tweet.media:
                        if media.path and media.is_video:
                            nodes.nodes.append(
                                Node(
                                    uin=uin,
                                    name=self._source_node_name(username),
                                    content=self.build_video_node_components(
                                        index,
                                        username,
                                        tweet,
                                        media,
                                        source=instance,
                                        media_only=media_only,
                                        omit_status_url=omit_status_url,
                                        hide_original_when_translated=hide_original_when_translated,
                                        link_style=link_style,
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
        hide_original_when_translated: bool = False,
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
                    hide_original_when_translated=hide_original_when_translated,
                    link_style=link_style,
                )
                items.append(
                    {
                        "name": self._source_node_name(username),
                        "uin": str(uin),
                        "content": content,
                    }
                )
                for media in tweet.media:
                    if media.path and media.is_image and self.send_image_attachments:
                        items.append(
                            {
                                "name": self._source_node_name(username),
                                "uin": str(uin),
                                "content": self._build_onebot_image_content(
                                    index,
                                    username,
                                    tweet,
                                    media,
                                    source=instance,
                                    media_only=media_only,
                                    omit_status_url=omit_status_url,
                                    hide_original_when_translated=hide_original_when_translated,
                                    link_style=link_style,
                                ),
                            }
                        )
                if not exclude_videos and self.send_video_attachments:
                    for media in tweet.media:
                        if media.path and media.is_video:
                            items.append(
                                {
                                    "name": self._source_node_name(username),
                                    "uin": str(uin),
                                    "content": self._build_onebot_video_content(
                                        index,
                                        username,
                                        tweet,
                                        media,
                                        source=instance,
                                        media_only=media_only,
                                        omit_status_url=omit_status_url,
                                        hide_original_when_translated=hide_original_when_translated,
                                        link_style=link_style,
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
        hide_original_when_translated: bool = False,
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
            link_style=link_style,
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
                hide_original_when_translated=hide_original_when_translated,
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
        hide_original_when_translated: bool = False,
        link_style: str = "plain",
    ):
        """Render only the author marker and successfully prepared media."""
        author_name = TweetMessageRenderer.display_username(username, tweet)
        author = f"@{author_name}" if author_name else "@unknown"
        status_url = (tweet.x_url or tweet.link or "").strip()
        if link_style == "qq_official_md":
            author = f"**{TweetMessageRenderer.qq_official_markdown_text(author)}**"
        elif link_style == "telegram_md" and status_url:
            author = TweetMessageRenderer.telegram_tweet_header(author, status_url)
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
        hide_original_when_translated: bool = False,
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
                    hide_original_when_translated=hide_original_when_translated,
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
        hide_original_when_translated: bool = False,
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
            hide_original_when_translated=hide_original_when_translated,
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
            lines.append("视频/GIF 发送已关闭，已跳过下载")
        if not lines:
            return []
        return [Plain("\n".join(lines))]

    def build_components(
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
        hide_original_when_translated: bool = False,
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
                hide_original_when_translated=hide_original_when_translated,
                link_style=link_style,
            )

        text = self.format_tweet_with_source(
            index,
            username,
            tweet,
            source,
            omit_status_url=omit_status_url,
            hide_original_when_translated=hide_original_when_translated,
            link_style=link_style,
        )
        status_url = (tweet.x_url or tweet.link or "").strip()
        components = [Plain(text)]
        video_notice_added = False
        for media in tweet.media:
            if not media.path:
                continue
            if media.is_video and exclude_videos:
                if not video_notice_added:
                    components.append(
                        Plain(
                            TweetMessageRenderer.video_not_sent_notice(
                                omit_status_url=omit_status_url,
                                status_url=status_url,
                            )
                        )
                    )
                    video_notice_added = True
                continue
            if media.is_video and not self.send_video_attachments:
                if not video_notice_added:
                    components.append(
                        Plain(
                            TweetMessageRenderer.video_not_sent_notice(
                                omit_status_url=omit_status_url,
                                status_url=status_url,
                            )
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
        hide_original_when_translated: bool = False,
        link_style: str = "plain",
    ):
        if media_only:
            return [Video.fromFileSystem(str(media.path))]
        return [
            Plain(
                self.format_video_attachment_text(
                    index,
                    username,
                    tweet,
                    source,
                    media_only=media_only,
                    omit_status_url=omit_status_url,
                    hide_original_when_translated=hide_original_when_translated,
                    link_style=link_style,
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
        hide_original_when_translated: bool = False,
        link_style: str = "plain",
    ):
        # The tweet node already carries the author and source context.
        # Repeating it on every image node creates unwanted captions.
        # Keep the shared builder signature; caption-related arguments are unused.
        return [Image.fromFileSystem(str(media.path))]

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
        hide_original_when_translated: bool = False,
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
            link_style=link_style,
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
                hide_original_when_translated=hide_original_when_translated,
                link_style=link_style,
            )
            items.append(
                {
                    "name": self._source_node_name(username),
                    "uin": uin,
                    "content": content,
                }
            )
            for media in tweet.media:
                if media.path and media.is_image and self.send_image_attachments:
                    items.append(
                        {
                            "name": self._source_node_name(username),
                            "uin": uin,
                            "content": self._build_onebot_image_content(
                                index,
                                username,
                                tweet,
                                media,
                                source=instance,
                                media_only=media_only,
                                omit_status_url=omit_status_url,
                                hide_original_when_translated=hide_original_when_translated,
                                link_style=link_style,
                            ),
                        }
                    )
            if self.send_video_attachments:
                for media in tweet.media:
                    if media.path and media.is_video:
                        items.append(
                            {
                                "name": self._source_node_name(username),
                                "uin": uin,
                                "content": self._build_onebot_video_content(
                                    index,
                                    username,
                                    tweet,
                                    media,
                                    source=instance,
                                    media_only=media_only,
                                    omit_status_url=omit_status_url,
                                    hide_original_when_translated=hide_original_when_translated,
                                    link_style=link_style,
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
        hide_original_when_translated: bool = False,
        link_style: str = "plain",
    ) -> list[dict]:
        if media_only:
            return [self.raw_media(media)]
        return [
            self.raw_text(
                self.format_video_attachment_text(
                    index,
                    username,
                    tweet,
                    source,
                    media_only=media_only,
                    omit_status_url=omit_status_url,
                    hide_original_when_translated=hide_original_when_translated,
                    link_style=link_style,
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
        hide_original_when_translated: bool = False,
        link_style: str = "plain",
    ) -> list[dict]:
        # The tweet node already carries the author and source context.
        # Keep each attachment node media-only to avoid repeated captions.
        # Keep the shared builder signature; caption-related arguments are unused.
        return [self.raw_media(media)]

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
        hide_original_when_translated: bool = False,
        link_style: str = "plain",
    ) -> list[dict]:
        if media_only:
            content = [
                self.raw_text(
                    f"@{TweetMessageRenderer.display_username(username, tweet)}"
                )
            ]
        else:
            content = [
                self.raw_text(
                    self.format_tweet_with_source(
                        index,
                        username,
                        tweet,
                        instance,
                        omit_status_url=omit_status_url,
                        hide_original_when_translated=hide_original_when_translated,
                        link_style=link_style,
                    )
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
                            TweetMessageRenderer.video_not_sent_notice(
                                omit_status_url=omit_status_url,
                                status_url=(tweet.x_url or tweet.link or "").strip(),
                            )
                        )
                    )
                    video_notice_added = True
                continue
            if (
                media.is_image
                and self.send_image_attachments
                and include_images
                or (
                    media.is_video
                    and self.send_video_attachments
                    and not exclude_videos
                    and include_videos
                )
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
        hide_original_when_translated: bool = False,
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
            link_style=link_style,
        )
        if header:
            blocks.append(header)
        blocks.extend(
            (
                self._source_node_name(username)
                if media_only
                else self.format_tweet_with_source(
                    start_index + offset,
                    username,
                    tweet,
                    instance,
                    omit_status_url=omit_status_url,
                    hide_original_when_translated=hide_original_when_translated,
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
        hide_original_when_translated: bool = False,
        link_style: str = "plain",
    ) -> str:
        blocks = [self.format_merged_header(batches, group_label, batch_summary)]
        index = start_index
        for username, instance, tweets in batches:
            for tweet in tweets:
                blocks.append(
                    self._source_node_name(username)
                    if media_only
                    else self.format_tweet_with_source(
                        index,
                        username,
                        tweet,
                        instance,
                        omit_status_url=omit_status_url,
                        hide_original_when_translated=hide_original_when_translated,
                        link_style=link_style,
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
        group_type = "blogger"
        keys = [str(username or "").strip().lower() for username, _, _ in batches]
        if any(key.startswith("q:") for key in keys):
            group_type = "tag"
        elif any(key.startswith("list:") for key in keys):
            group_type = "list"
        return TweetMessageRenderer.format_batch_summary(
            batches, group_label, group_type=group_type
        )

    @staticmethod
    def format_batch_summary(
        batches: list[TweetBatch],
        group_label: str = "",
        action_text: str = "本次检查发现",
        group_type: str = "blogger",
    ) -> str:
        total = sum(len(tweets) for _, _, tweets in batches)
        counts: dict[str, int] = {}
        for username, _, tweets in batches:
            counts[username] = counts.get(username, 0) + len(tweets)
        subscription_count = format_subscription_count(len(counts), group_type)
        if group_label:
            return f"📬 {group_label} · {subscription_count} · {total} 条新推文"
        return f"📬 {subscription_count} · {total} 条新推文"

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
    def display_username(username: str, tweet: TweetItem | None = None) -> str:
        """Prefer real author from tweet link; batch key may be a search query."""
        from_link = ""
        if tweet is not None:
            from_link = (getattr(tweet, "username", None) or "").strip().lstrip("@")
        key = str(username or "").strip()
        # Tag schedule keys: q:...
        if key.lower().startswith("q:"):
            return from_link or key[2:].lstrip("#") or key
        # Manual /推文搜索 passes raw query as username.
        if (
            key.startswith("#")
            or (" " in key)
            or (key and not re.fullmatch(r"[A-Za-z0-9_]{1,15}", key.lstrip("@")))
        ):
            return from_link or key.lstrip("@")
        return from_link or key.lstrip("@")

    @staticmethod
    def _strip_source_links(text: str, source: str) -> str:
        """Remove mirror links generated by the current Nitter instance."""
        raw_source = str(source or "").strip()
        if not raw_source:
            return text
        source_value = raw_source if "://" in raw_source else f"//{raw_source}"
        source_host = (urlparse(source_value).hostname or "").lower().rstrip(".")
        if not source_host:
            return text

        def replace(match: re.Match[str]) -> str:
            value = match.group(0)
            trimmed = value.rstrip("".join(_QQ_OFFICIAL_URL_TRAILING_PUNCTUATION))
            url_host = (urlparse(trimmed).hostname or "").lower().rstrip(".")
            if url_host != source_host:
                return value
            return value[len(trimmed) :]

        cleaned = _QQ_OFFICIAL_URL_RE.sub(replace, str(text or ""))
        cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
        cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
        return cleaned.strip()

    @staticmethod
    def format_tweet(
        index: int,
        username: str,
        tweet: TweetItem,
        source: str = "",
        *,
        omit_status_url: bool = True,
        hide_original_when_translated: bool = False,
        link_style: str = "plain",
    ) -> str:
        status_url = (tweet.x_url or tweet.link or "").strip()
        author = TweetMessageRenderer.display_username(username, tweet)
        author_label = f"@{author}" if author else "@unknown"
        is_qq_official_md = link_style == "qq_official_md"

        # Telegram: keep the author plain and make the status link an explicit action.
        if is_qq_official_md:
            author_line = (
                f"**{TweetMessageRenderer.qq_official_markdown_text(author_label)}**"
            )
        elif link_style == "telegram_md" and status_url:
            author_line = TweetMessageRenderer.telegram_tweet_header(
                author_label, status_url
            )
        else:
            author_line = author_label

        # Compact header: @user · 2024-07-26 22:30 (Asia/Shanghai)
        if tweet.published:
            published = format_tweet_published(str(tweet.published))
            if published:
                if is_qq_official_md:
                    author_line = " · ".join((author_line, published))
                else:
                    author_line = f"{author_line} · {published}"

        if is_qq_official_md and not omit_status_url and status_url:
            author_line = " · ".join(
                (
                    author_line,
                    TweetMessageRenderer.qq_official_markdown_link(
                        "查看原推", status_url
                    ),
                )
            )

        blocks: list[str] = [author_line]

        translation = (tweet.translation or "").strip()
        if translation:
            translation = normalize_external_links(translation).strip()
            translation = TweetMessageRenderer._strip_source_links(translation, source)
            if omit_status_url:
                translation = strip_external_links(translation)

        original_text = normalize_external_links(tweet.text).strip()
        original_text = TweetMessageRenderer._strip_source_links(original_text, source)
        if omit_status_url:
            original_text = strip_external_links(original_text)
        if TweetMessageRenderer._is_blank_tweet_body(original_text):
            original_text = ""

        display_translation = (
            TweetMessageRenderer.qq_official_markdown_text(translation)
            if is_qq_official_md
            else translation
        )
        display_original = (
            TweetMessageRenderer.qq_official_markdown_text(original_text)
            if is_qq_official_md
            else original_text
        )

        show_original = bool(original_text)
        if hide_original_when_translated and translation and show_original:
            show_original = False

        # Body layout (R1, all platforms including Telegram):
        # translation as main text; original as '>' quoted block; no "翻译"/"原文"
        # section titles. Media-only / empty body: header only (+ media summary).
        # Telegram uses its own author header with an explicit status link.
        if translation and show_original:
            blocks.append(display_translation)
            if is_qq_official_md:
                blocks.append(TweetMessageRenderer._quote_markdown_block(original_text))
            else:
                blocks.append(TweetMessageRenderer._quote_plain_block(original_text))
        elif translation:
            blocks.append(display_translation)
        elif show_original:
            blocks.append(display_original)
        # else: media-only / empty — omit body placeholder

        if tweet.ai_warnings:
            warns = "\n".join(
                f"- {TweetMessageRenderer.qq_official_markdown_text(w)}"
                if is_qq_official_md
                else f"- {w}"
                for w in tweet.ai_warnings
                if w
            )
            if warns:
                blocks.append("⚠️\n" + warns)

        # Footer status URL only for non-TG when omit is off (TG has header link).
        if (
            not omit_status_url
            and status_url
            and link_style not in {"telegram_md", "qq_official_md"}
        ):
            blocks.append("🔗\n" + status_url)

        if tweet.media_warnings:
            processed_warns = []
            status_for_warn = "" if omit_status_url else (status_url or "").strip()
            for w in tweet.media_warnings:
                msg = str(w or "").strip()
                if (
                    status_for_warn
                    and msg
                    and "视频/GIF" in msg
                    and status_for_warn not in msg
                    and "http" not in msg
                ):
                    msg = f"{msg} 🔗：{status_for_warn}"
                if msg:
                    processed_warns.append(
                        TweetMessageRenderer.qq_official_markdown_text(msg)
                        if is_qq_official_md
                        else msg
                    )
            if processed_warns:
                warns = "\n".join(f"- {w}" for w in processed_warns)
                blocks.append("⚠️\n" + warns)

        media_summary = TweetMessageRenderer.format_media_summary(tweet)
        if media_summary:
            blocks.append(media_summary)

        return "\n\n".join(blocks)

    @staticmethod
    def video_not_sent_notice(
        *,
        omit_status_url: bool = True,
        status_url: str = "",
    ) -> str:
        base = "视频/GIF 发送已关闭，已跳过下载。"
        url = (status_url or "").strip()
        if omit_status_url or not url:
            return base
        return f"{base} 原文链接：{url}"

    @staticmethod
    def _is_blank_tweet_body(text: str) -> bool:
        value = str(text or "").strip()
        return value in {"", "(无正文)", "（无正文）"}

    @staticmethod
    def _quote_plain_block(text: str) -> str:
        """Prefix each line with '> ' for a lightweight quote look on plain platforms."""
        body = str(text or "")
        if not body:
            return ">"
        return "\n".join("> " + line for line in body.split("\n") if line.strip())

    @staticmethod
    def qq_official_markdown_text(text: str) -> str:
        """Escape user-controlled text while preserving allowed plain URLs.

        QQ runs a LaTeX pass *before* Markdown, with KaTeX's default delimiters
        ``\\[..\\]``, ``\\(..\\)``, ``$$..$$`` and ``$..$``.  Escaping a bracket
        or paren therefore builds a formula delimiter out of thin air and the
        text between the markers is swallowed, so those four characters are
        left bare -- verified on a real client.  Link injection still fails
        because ``[label](url)`` needs a literal ``](`` run, which is broken up
        below.

        Only Markdown syntax is escaped.  HTML tags are left as-is: QQ's
        official Markdown subset does not render HTML, so ``<b>`` and friends
        reach the user as literal text rather than markup.  ``<https://...>``
        is the one exception -- QQ auto-links it -- but that only points a URL
        at itself, so it is not an injection vector.
        """

        value = str(text or "")

        def escape_segment(segment: str, *, at_line_start: bool) -> str:
            escaped = segment.replace("\\", "\\\\")
            for char in ("`", "*", "_", "~"):
                escaped = escaped.replace(char, "\\" + char)
            # Brackets and parens cannot carry a backslash (see docstring), so
            # sever the ``](`` seam instead: a zero-width space renders as
            # nothing but stops the link syntax from being recognised.
            escaped = escaped.replace("](", "]" + _ZERO_WIDTH_SPACE + "(")
            # Leading whitespace is preserved but must not shield the marker:
            # QQ's Markdown treats a four-space indent as list nesting, so an
            # indented ``- foo`` in a tweet body still starts a nested list.
            if at_line_start:
                escaped = re.sub(r"^([ \t]*)([>#])", r"\1\\\2", escaped)
                escaped = re.sub(r"^([ \t]*)([-+])(?=\s)", r"\1\\\2", escaped)
                escaped = re.sub(r"^([ \t]*)(\d+)\.(?=\s)", r"\1\2\\.", escaped)
            escaped = re.sub(r"(?<=\n)([ \t]*)([>#])", r"\1\\\2", escaped)
            escaped = re.sub(r"(?<=\n)([ \t]*)([-+])(?=\s)", r"\1\\\2", escaped)
            escaped = re.sub(r"(?<=\n)([ \t]*)(\d+)\.(?=\s)", r"\1\2\\.", escaped)
            return escaped

        pieces: list[str] = []
        last_end = 0
        for match in _QQ_OFFICIAL_URL_RE.finditer(value):
            pieces.append(
                escape_segment(
                    value[last_end : match.start()],
                    at_line_start=last_end == 0,
                )
            )
            url, trailing = TweetMessageRenderer._split_url_trailing_punctuation(
                match.group(0)
            )
            pieces.append(url.replace("(", "%28").replace(")", "%29"))
            if trailing:
                pieces.append(escape_segment(trailing, at_line_start=False))
            last_end = match.end()
        pieces.append(escape_segment(value[last_end:], at_line_start=last_end == 0))
        return "".join(pieces)

    @staticmethod
    def _split_url_trailing_punctuation(url: str) -> tuple[str, str]:
        """Split sentence punctuation that the greedy URL match swallowed.

        ``见 (https://example.com)`` must not send ``https://example.com%29``:
        the closing paren belongs to the sentence, not the link.  A paren that
        balances one inside the URL (``/wiki/Foo_(bar)``) is kept.
        """

        end = len(url)
        while end > 0:
            char = url[end - 1]
            if char not in _QQ_OFFICIAL_URL_TRAILING_PUNCTUATION:
                break
            if char == ")" and url.count("(", 0, end) >= url.count(")", 0, end):
                break
            end -= 1
        return url[:end], url[end:]

    @staticmethod
    def qq_official_markdown_link(label: str, url: str) -> str:
        safe_url = str(url or "").strip()
        if safe_url and not safe_url.lower().startswith(("http://", "https://")):
            safe_url = "https://" + safe_url.lstrip("/")
        safe_url = safe_url.replace("(", "%28").replace(")", "%29")
        safe_label = TweetMessageRenderer.qq_official_markdown_text(label)
        return f"[{safe_label}]({safe_url})"

    @staticmethod
    def _quote_markdown_block(text: str) -> str:
        body = TweetMessageRenderer.qq_official_markdown_text(text)
        if not body:
            return ">"
        return "\n".join("> " + line for line in body.split("\n") if line.strip())

    @staticmethod
    def telegram_markdown_text(text: str) -> str:
        safe_text = str(text or "")
        for ch in ("\\", "`", "*", "_", "[", "]", "(", ")"):
            safe_text = safe_text.replace(ch, "\\" + ch)
        return safe_text

    @staticmethod
    def telegram_markdown_link(label: str, url: str) -> str:
        safe_label = TweetMessageRenderer.telegram_markdown_text(label)
        safe_url = str(url or "").strip()
        if safe_url and not safe_url.startswith(("http://", "https://")):
            safe_url = "https://" + safe_url.lstrip("/")
        safe_url = safe_url.replace("(", "%28").replace(")", "%29")
        return "[" + safe_label + "](" + safe_url + ")"

    @staticmethod
    def telegram_tweet_header(author_label: str, status_url: str) -> str:
        author_name = str(author_label or "").strip().lstrip("@") or "unknown"
        safe_author_name = TweetMessageRenderer.telegram_markdown_text(author_name)
        status_link = TweetMessageRenderer.telegram_markdown_link(
            "🔗 查看推文", status_url
        )
        return f"@{safe_author_name} · {status_link}"

    @staticmethod
    def format_video_attachment_text(
        index: int,
        username: str,
        tweet: TweetItem,
        source: str = "",
        media_only: bool = False,
        omit_status_url: bool = True,
        hide_original_when_translated: bool = False,
        link_style: str = "plain",
    ) -> str:
        if media_only:
            return TweetMessageRenderer._source_node_name(username)
        text = TweetMessageRenderer.format_tweet(
            index,
            username,
            tweet,
            source=source,
            omit_status_url=omit_status_url,
            hide_original_when_translated=hide_original_when_translated,
            link_style=link_style,
        )
        if text:
            return f"{text}\n\n视频/GIF 附件"
        return f"{TweetMessageRenderer._source_node_name(username)}\n视频/GIF 附件"

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
        hide_original_when_translated: bool = False,
        link_style: str = "plain",
    ) -> str:
        raw_summary = str(batch_summary or "").strip()
        raw_header = str(header_text or "").strip()
        raw_group_label = str(group_label or "").strip()
        is_qq_official_markdown = link_style == "qq_official_md"
        summary = (
            cls.qq_official_markdown_text(raw_summary)
            if is_qq_official_markdown
            else raw_summary
        )
        safe_header = (
            cls.qq_official_markdown_text(raw_header)
            if is_qq_official_markdown
            else raw_header
        )
        safe_group_label = (
            cls.qq_official_markdown_text(raw_group_label)
            if is_qq_official_markdown
            else raw_group_label
        )
        lines = []
        if summary:
            lines.append(summary)
        if safe_header:
            lines.append(safe_header)
        if (
            raw_group_label
            and (raw_summary or raw_header)
            and f"分组\uff1a{raw_group_label}" not in raw_summary
        ):
            lines.append(f"分组\uff1a{safe_group_label}")
        safe_notices = notices
        if is_qq_official_markdown:
            safe_notices = [
                cls.qq_official_markdown_text(str(notice).strip())
                for notice in notices or []
                if str(notice or "").strip()
            ]
        notice_text = "" if media_only else cls.format_notices(safe_notices)
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
        return "\n".join(["⚠️", *[f"- {notice}" for notice in clean_notices]])

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
        return "📎 " + "，".join(parts)

    @staticmethod
    def format_instance_label(instance: str) -> str:
        parsed = urlparse(instance)
        return parsed.netloc or parsed.path or instance
