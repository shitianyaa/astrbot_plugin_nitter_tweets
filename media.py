from __future__ import annotations

import asyncio
import json
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urljoin
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

from astrbot.api import logger

try:
    from .utils import (
        TweetItem, TweetMedia, clean_text, clamp_float, clamp_int,
        generate_file_name, load_instances,
    )
except ImportError:
    from utils import (
        TweetItem, TweetMedia, clean_text, clamp_float, clamp_int,
        generate_file_name, load_instances,
    )


class XdownMediaParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.cover_url = ""
        self.items: list[tuple[str, str]] = []
        self._href = ""
        self._classes: set[str] = set()
        self._text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs):
        attrs_dict = dict(attrs)
        if tag == "img" and not self.cover_url:
            self.cover_url = str(attrs_dict.get("src") or "")
            return

        if tag != "a":
            return
        classes = set(str(attrs_dict.get("class") or "").split())
        if classes.intersection({"tw-button-dl", "abutton"}):
            self._href = str(attrs_dict.get("href") or "")
            self._classes = classes
            self._text_parts = []

    def handle_data(self, data: str):
        if self._href:
            self._text_parts.append(data)

    def handle_endtag(self, tag: str):
        if tag != "a" or not self._href:
            return
        text = "".join(self._text_parts).strip()
        kind = self._detect_kind(text, self._href)
        if kind:
            self.items.append((kind, self._href))
        self._href = ""
        self._classes = set()
        self._text_parts = []

    @staticmethod
    def _detect_kind(text: str, url: str = "") -> str:
        lowered = text.lower()
        if "mp4" in lowered or "video" in lowered:
            return "video"
        if "gif" in lowered:
            return "dynamic"
        if "图片" in text or "image" in lowered or "photo" in lowered:
            return "image"

        # 按 URL 扩展名兜底判断
        url_lower = url.lower().split("?")[0].split("#")[0]
        if url_lower.endswith((".mp4", ".m4v", ".mov", ".webm")):
            return "video"
        if url_lower.endswith(".gif"):
            return "dynamic"
        if url_lower.endswith((
            ".jpg", ".jpeg", ".png", ".webp", ".bmp", ".svg"
        )):
            return "image"
        return ""


class MediaService:
    def __init__(self, config):
        self.enabled = bool(config.get("download_media", True))
        self.include_images = bool(config.get("download_images", True))
        self.include_videos = bool(config.get("download_videos", True))
        self.max_per_tweet = clamp_int(config.get("max_media_per_tweet", 4), 0, 12)
        self.timeout = clamp_float(config.get("media_timeout", 25.0), 5.0, 120.0)
        self.max_bytes = clamp_float(config.get("media_max_size_mb", 25.0), 1.0, 200.0)
        self.max_bytes = int(self.max_bytes * 1024 * 1024)
        self.xdown_url = str(
            config.get("xdown_api_url", "https://xdown.app/api/ajaxSearch")
        )
        self.user_agent = str(
            config.get(
                "media_user_agent",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
            )
        )
        self.cache_dir = Path(__file__).resolve().parent / "cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    async def attach_media(self, tweets: list[TweetItem]) -> None:
        if not self.enabled or self.max_per_tweet <= 0:
            return
        for tweet in tweets:
            try:
                tweet.media = await self.resolve_and_download(tweet)
            except Exception as exc:
                self._add_media_warning(tweet, f"媒体解析失败，已保留原文链接：{exc}")

    async def resolve_and_download(self, tweet: TweetItem) -> list[TweetMedia]:
        media_urls = await asyncio.to_thread(self._resolve_media_urls, tweet)
        if not media_urls:
            return []

        downloaded: list[TweetMedia] = []
        seen: set[str] = set()
        for index, media in enumerate(media_urls):
            if media.url in seen:
                continue
            seen.add(media.url)
            if len(downloaded) >= self.max_per_tweet:
                if any(item.is_video for item in media_urls[index:]):
                    self._add_media_warning(
                        tweet,
                        f"视频/GIF 超过单条媒体上限 {self.max_per_tweet}，已保留原文链接",
                    )
                break
            if media.is_image and not self.include_images:
                continue
            if media.is_video and not self.include_videos:
                self._add_media_warning(
                    tweet, "视频/GIF 已按配置跳过，已保留原文链接"
                )
                continue
            try:
                media.path = await asyncio.to_thread(self._download, media)
            except Exception as exc:
                if media.is_video:
                    self._add_media_warning(
                        tweet, f"视频/GIF 下载失败，已保留原文链接：{exc}"
                    )
                logger.warning(f"Failed to download media {media.url}: {exc}")
                continue
            downloaded.append(media)
        return downloaded

    @staticmethod
    def _add_media_warning(tweet: TweetItem, message: str) -> None:
        if message not in tweet.media_warnings:
            tweet.media_warnings.append(message)
        logger.warning(f"[NitterTweets] {message}: {tweet.x_url}")

    def _resolve_media_urls(self, tweet: TweetItem) -> list[TweetMedia]:
        data = urlencode({"q": tweet.x_url, "lang": "zh-cn"}).encode("utf-8")
        request = Request(
            self.xdown_url,
            data=data,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "application/json, text/plain, */*",
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": "https://xdown.app",
                "Referer": "https://xdown.app/",
            },
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read(2_000_000)
        except HTTPError as exc:
            raise RuntimeError(f"xdown HTTP {exc.code}") from exc
        except URLError as exc:
            reason = getattr(exc, "reason", exc)
            raise RuntimeError(str(reason)) from exc

        payload = json.loads(raw.decode("utf-8", errors="replace"))
        if payload.get("status") != "ok":
            return []
        html = payload.get("data") or ""
        parser = XdownMediaParser()
        parser.feed(str(html))

        base_url = "https://xdown.app"
        result: list[TweetMedia] = []
        for kind, url in parser.items:
            full_url = urljoin(base_url, url)
            # 最终兜底：如果解析不出类型，按 URL 扩展名再试一次
            if not kind:
                kind = XdownMediaParser._detect_kind("", full_url)
            if not kind:
                logger.info(f"[NitterTweets] skipping unclassified media: {full_url}")
                continue
            result.append(TweetMedia(kind, full_url))
        return result

    def _download(self, media: TweetMedia) -> Path:
        default_suffix = ".mp4" if media.is_video else ".jpg"
        file_path = self.cache_dir / generate_file_name(media.url, default_suffix)
        if file_path.exists() and file_path.stat().st_size > 0:
            return file_path

        temp_path = file_path.with_suffix(file_path.suffix + ".tmp")
        request = Request(
            media.url,
            headers={
                "User-Agent": self.user_agent,
                "Referer": "https://xdown.app/",
            },
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                content_length = response.headers.get("Content-Length")
                if content_length and int(content_length) > self.max_bytes:
                    raise RuntimeError("media exceeds size limit")

                downloaded = 0
                with temp_path.open("wb") as file:
                    while True:
                        chunk = response.read(1024 * 256)
                        if not chunk:
                            break
                        downloaded += len(chunk)
                        if downloaded > self.max_bytes:
                            raise RuntimeError("media exceeds size limit")
                        file.write(chunk)

            if temp_path.stat().st_size <= 0:
                raise RuntimeError("empty media")
            temp_path.replace(file_path)
            return file_path
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise


# ──────────────────────────────────────────────────────────────────────
# Nitter RSS 客户端
# ──────────────────────────────────────────────────────────────────────

class NitterClient:
    def __init__(self, config):
        self.instances = load_instances(config.get("instances"))
        self.timeout = clamp_float(config.get("request_timeout", 12.0), 3.0, 60.0)
        self.user_agent = config.get(
            "user_agent", "Mozilla/5.0 (compatible; AstrBotNitterTweets/0.3)",
        )

    async def fetch_tweets(self, username: str, limit: int) -> tuple[str, list[TweetItem]]:
        errors: list[str] = []
        for instance in self.instances:
            try:
                tweets = await asyncio.to_thread(
                    self._fetch_from_instance, instance, username, limit,
                )
            except Exception as exc:
                errors.append(f"{instance}: {exc}")
                continue
            if tweets:
                return instance, tweets
            errors.append(f"{instance}: empty feed")
        raise RuntimeError("; ".join(errors[-3:]) or "no instance available")

    def _fetch_from_instance(self, instance: str, username: str, limit: int) -> list[TweetItem]:
        rss_url = f"{instance.rstrip('/')}/{quote(username)}/rss"
        request = Request(
            rss_url,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "application/rss+xml, application/xml, text/xml;q=0.9, */*;q=0.8",
            },
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                data = response.read(2_000_000)
        except HTTPError as exc:
            raise RuntimeError(f"HTTP {exc.code}") from exc
        except URLError as exc:
            raise RuntimeError(str(getattr(exc, "reason", exc))) from exc
        return self._parse_rss(data, instance, limit)

    def _parse_rss(self, data: bytes, instance: str, limit: int) -> list[TweetItem]:
        root = ET.fromstring(data)
        channel = root.find("channel") if root.tag.lower().endswith("rss") else root
        if channel is None:
            return []
        tweets: list[TweetItem] = []
        for item in channel.findall("item"):
            title = self._node_text(item, "title")
            description = self._node_text(item, "description")
            text = clean_text(description or title)
            link = self._normalize_link(self._node_text(item, "link"), instance)
            published = self._format_pub_date(self._node_text(item, "pubDate"))
            if not text and not link:
                continue
            tweets.append(TweetItem(text=text or "(无正文)", link=link, published=published))
            if len(tweets) >= limit:
                break
        return tweets

    @staticmethod
    def _node_text(node: ET.Element, name: str) -> str:
        child = node.find(name)
        return (child.text or "").strip() if child is not None else ""

    @staticmethod
    def _format_pub_date(raw: str) -> str:
        if not raw:
            return ""
        try:
            parsed = parsedate_to_datetime(raw)
        except (TypeError, ValueError):
            return raw
        return parsed.strftime("%Y-%m-%d %H:%M:%S %Z").strip()

    @staticmethod
    def _normalize_link(link: str, instance: str) -> str:
        if not link:
            return ""
        if link.startswith("/"):
            return f"{instance.rstrip('/')}{link}"
        return link
