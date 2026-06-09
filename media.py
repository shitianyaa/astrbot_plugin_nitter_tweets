from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urljoin, urlparse
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

from astrbot.api import logger

try:
    from .config_compat import config_get
    from .utils import (
        TweetItem, TweetMedia, clean_text, clamp_float, clamp_int,
        generate_file_name, load_instances, normalize_external_links,
    )
except ImportError:
    from config_compat import config_get
    from utils import (
        TweetItem, TweetMedia, clean_text, clamp_float, clamp_int,
        generate_file_name, load_instances, normalize_external_links,
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


@dataclass(slots=True)
class MediaCacheCleanupResult:
    removed: int = 0
    failed: int = 0
    skipped_dirs: int = 0


class MediaService:
    def __init__(self, config):
        image_config = config_get(config, "send_image_attachments", None)
        if image_config is None:
            image_config = bool(config_get(config, "download_media", True)) and bool(
                config_get(config, "download_images", True)
            )
        self.send_image_attachments = bool(
            image_config
        )
        self.send_video_attachments = bool(
            config_get(config, "send_video_attachments", False)
        )
        self.max_per_tweet = clamp_int(
            config_get(config, "max_media_per_tweet", 4), 0, 12
        )
        self.timeout = clamp_float(
            config_get(config, "media_timeout", 25.0), 5.0, 120.0
        )
        self.max_bytes = clamp_float(
            config_get(config, "media_max_size_mb", 25.0), 1.0, 200.0
        )
        self.max_bytes = int(self.max_bytes * 1024 * 1024)
        self.cache_retention_days = clamp_float(
            config_get(config, "media_cache_retention_days", 3.0), 0.0, 3650.0
        )
        self.cache_cleanup_interval = 3600.0
        self._last_cache_cleanup = 0.0
        self.xdown_url = str(
            config_get(config, "xdown_api_url", "https://xdown.app/api/ajaxSearch")
        )
        self.user_agent = str(
            config_get(
                config,
                "media_user_agent",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
            )
        )
        self.cache_dir = Path(__file__).resolve().parent / "cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    @property
    def enabled(self) -> bool:
        return self.send_image_attachments or self.send_video_attachments

    async def attach_media(self, tweets: list[TweetItem]) -> None:
        await asyncio.to_thread(self.cleanup_cache)
        if (
            not self.send_image_attachments
            and not self.send_video_attachments
        ) or self.max_per_tweet <= 0:
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
        video_disabled_warned = False
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
            if media.is_image and not self.send_image_attachments:
                continue
            if media.is_video and not self.send_video_attachments:
                if not video_disabled_warned:
                    self._add_media_warning(
                        tweet,
                        "视频/GIF 附件发送功能仍在优化，当前按配置不发送，已保留原文链接",
                        log_warning=False,
                    )
                    video_disabled_warned = True
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
    def _add_media_warning(
        tweet: TweetItem, message: str, log_warning: bool = True
    ) -> None:
        if message not in tweet.media_warnings:
            tweet.media_warnings.append(message)
        log = logger.warning if log_warning else logger.info
        log(f"[NitterTweets] {message}: {tweet.x_url}")

    def cleanup_after_send(self, tweets: list[TweetItem]) -> None:
        if self.cache_retention_days > 0:
            return

        removed = 0
        failed = 0
        seen_paths: set[Path] = set()
        for tweet in tweets:
            for media in tweet.media:
                path = media.path
                if path is None:
                    continue
                if self._is_staged_path(path):
                    continue
                if path in seen_paths:
                    media.path = None
                    continue
                seen_paths.add(path)
                try:
                    path.unlink(missing_ok=True)
                    removed += 1
                    media.path = None
                except OSError as exc:
                    failed += 1
                    logger.warning(
                        f"[NitterTweets] failed to delete media file {path}: {exc}"
                    )

        if failed:
            logger.warning(
                "[NitterTweets] media cleanup after send finished: "
                f"removed={removed}, failed={failed}"
            )
        elif removed:
            logger.debug(
                "[NitterTweets] media cleanup after send finished: "
                f"removed={removed}, failed={failed}"
            )

    async def move_tweets_media_to_staged(
        self,
        group_id: str,
        username: str,
        tweets: list[TweetItem],
        interval_seconds: float = 0.0,
    ) -> None:
        await asyncio.to_thread(
            self._move_tweets_media_to_staged, group_id, username, tweets
        )
        if interval_seconds <= 0:
            return
        staged_count = sum(1 for tweet in tweets for media in tweet.media if media.path)
        if staged_count > 0:
            await asyncio.sleep(interval_seconds * staged_count)

    def _move_tweets_media_to_staged(
        self,
        group_id: str,
        username: str,
        tweets: list[TweetItem],
    ) -> None:
        for tweet in tweets:
            status_id = tweet.status_id or "unknown"
            staged_dir = self.staged_cache_dir / str(group_id) / status_id
            staged_dir.mkdir(parents=True, exist_ok=True)
            for media_index, media in enumerate(tweet.media):
                if media.path is None:
                    continue
                source_path = media.path
                if self._is_staged_path(source_path):
                    continue
                suffix = source_path.suffix or (".mp4" if media.is_video else ".jpg")
                staged_name = (
                    f"{media_index:02d}_"
                    f"{generate_file_name(media.url, suffix)}"
                )
                target_path = staged_dir / staged_name
                if target_path.exists() and target_path.stat().st_size > 0:
                    source_path.unlink(missing_ok=True)
                    media.path = target_path
                    continue
                try:
                    source_path.replace(target_path)
                    media.path = target_path
                except OSError as exc:
                    logger.warning(
                        "[NitterTweets] failed to move media into staged cache: "
                        f"user={username}, status={status_id}, path={source_path}, "
                        f"error={exc}"
                    )

    def cleanup_staged_media_for_tweets(self, tweets: list[TweetItem]) -> None:
        removed = 0
        failed = 0
        seen_paths: set[Path] = set()
        touched_dirs: set[Path] = set()
        for tweet in tweets:
            for media in tweet.media:
                path = media.path
                if path is None or not self._is_staged_path(path):
                    continue
                if path in seen_paths:
                    media.path = None
                    continue
                seen_paths.add(path)
                touched_dirs.add(path.parent)
                try:
                    path.unlink(missing_ok=True)
                    removed += 1
                    media.path = None
                except OSError as exc:
                    failed += 1
                    logger.warning(
                        f"[NitterTweets] failed to delete staged media file {path}: {exc}"
                    )
        for directory in sorted(touched_dirs, key=lambda item: len(item.parts), reverse=True):
            self._remove_empty_staged_dirs(directory)
        if removed or failed:
            logger.info(
                "[NitterTweets] staged media cleanup finished: "
                f"removed={removed}, failed={failed}"
            )

    def cleanup_expired_staged_media(
        self,
        retention_hours: float,
        protected_paths: set[str] | None = None,
    ) -> MediaCacheCleanupResult:
        result = MediaCacheCleanupResult()
        staged_root = self.staged_cache_dir
        if not staged_root.exists():
            return result

        cutoff = time.time() - retention_hours * 60 * 60
        protected = {
            str(Path(path).resolve())
            for path in protected_paths or set()
            if str(path).strip()
        }
        touched_dirs: set[Path] = set()
        for path in staged_root.rglob("*"):
            if path.is_dir():
                continue
            if not path.is_file():
                continue
            try:
                if str(path.resolve()) in protected:
                    continue
                if path.stat().st_mtime >= cutoff:
                    continue
                path.unlink()
                result.removed += 1
                touched_dirs.add(path.parent)
            except OSError as exc:
                result.failed += 1
                logger.warning(
                    f"[NitterTweets] failed to clean expired staged media {path}: {exc}"
                )
        for directory in sorted(touched_dirs, key=lambda item: len(item.parts), reverse=True):
            self._remove_empty_staged_dirs(directory)
        if result.removed or result.failed:
            logger.info(
                "[NitterTweets] expired staged media cleanup finished: "
                f"removed={result.removed}, failed={result.failed}, "
                f"retention_hours={retention_hours:g}"
            )
        return result

    def clear_non_staged_cache(self) -> MediaCacheCleanupResult:
        result = MediaCacheCleanupResult()
        if not self.cache_dir.exists():
            return result

        for path in self.cache_dir.iterdir():
            if path.is_dir():
                result.skipped_dirs += 1
                continue
            if not path.is_file():
                continue
            try:
                path.unlink(missing_ok=True)
                result.removed += 1
            except OSError as exc:
                result.failed += 1
                logger.warning(
                    f"[NitterTweets] failed to clear media cache file {path}: {exc}"
                )

        logger.info(
            "[NitterTweets] non-staged media cache clear finished: "
            f"removed={result.removed}, failed={result.failed}, "
            f"skipped_dirs={result.skipped_dirs}"
        )
        return result

    @property
    def staged_cache_dir(self) -> Path:
        return self.cache_dir / "staged"

    def _is_staged_path(self, path: Path) -> bool:
        try:
            path.resolve().relative_to(self.staged_cache_dir.resolve())
            return True
        except ValueError:
            return False

    def _remove_empty_staged_dirs(self, directory: Path) -> None:
        staged_root = self.staged_cache_dir.resolve()
        current = directory
        while True:
            try:
                resolved = current.resolve()
                if resolved == staged_root or staged_root not in resolved.parents:
                    return
                current.rmdir()
            except OSError:
                return
            current = current.parent

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
        cover_url = urljoin(base_url, parser.cover_url) if parser.cover_url else ""
        has_video_candidate = any(
            kind in {"video", "dynamic"} for kind, _ in parser.items
        )
        result: list[TweetMedia] = []
        for kind, url in parser.items:
            full_url = urljoin(base_url, url)
            # 最终兜底：如果解析不出类型，按 URL 扩展名再试一次
            if not kind:
                kind = XdownMediaParser._detect_kind("", full_url)
            if not kind:
                logger.info(f"[NitterTweets] skipping unclassified media: {full_url}")
                continue
            if (
                kind == "image"
                and has_video_candidate
                and cover_url
                and self._same_media_url(full_url, cover_url)
            ):
                logger.info(
                    "[NitterTweets] skipping video/GIF cover image: "
                    f"{full_url}"
                )
                continue
            result.append(TweetMedia(kind, full_url))
        return result

    @staticmethod
    def _same_media_url(left: str, right: str) -> bool:
        left = (left or "").strip()
        right = (right or "").strip()
        if not left or not right:
            return False
        if left.rstrip("/") == right.rstrip("/"):
            return True

        left_parsed = urlparse(left)
        right_parsed = urlparse(right)
        if left_parsed.netloc and right_parsed.netloc:
            if left_parsed.netloc.lower() != right_parsed.netloc.lower():
                return False

        left_path = left_parsed.path.rstrip("/")
        right_path = right_parsed.path.rstrip("/")
        if left_path != right_path:
            return False

        suffix = Path(left_path).suffix.lower()
        return suffix in {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".svg"}

    def _download(self, media: TweetMedia) -> Path:
        default_suffix = ".mp4" if media.is_video else ".jpg"
        file_path = self.cache_dir / generate_file_name(media.url, default_suffix)
        if file_path.exists() and file_path.stat().st_size > 0:
            file_path.touch()
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

    def cleanup_cache(self, force: bool = False) -> None:
        if self.cache_retention_days <= 0:
            return

        now = time.time()
        if not force and now - self._last_cache_cleanup < self.cache_cleanup_interval:
            return
        self._last_cache_cleanup = now

        cutoff = now - self.cache_retention_days * 24 * 60 * 60
        removed = 0
        failed = 0
        for path in self.cache_dir.iterdir():
            if not path.is_file():
                continue
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
                    removed += 1
            except OSError as exc:
                failed += 1
                logger.warning(f"[NitterTweets] failed to clean cache file {path}: {exc}")

        if removed or failed:
            logger.info(
                "[NitterTweets] media cache cleanup finished: "
                f"removed={removed}, failed={failed}, retention_days={self.cache_retention_days:g}"
            )


# ──────────────────────────────────────────────────────────────────────
# Nitter RSS 客户端
# ──────────────────────────────────────────────────────────────────────

class NitterClient:
    def __init__(self, config):
        self.instances = load_instances(config_get(config, "instances"))
        self.timeout = clamp_float(
            config_get(config, "request_timeout", 12.0), 3.0, 60.0
        )
        self.user_agent = config_get(
            config,
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
        raise RuntimeError(self._format_fetch_errors(errors))

    async def fetch_tweets_from_instance(
        self, instance: str, username: str, limit: int,
    ) -> tuple[str, list[TweetItem]]:
        normalized = load_instances([instance])[0]
        tweets = await asyncio.to_thread(
            self._fetch_from_instance, normalized, username, limit,
        )
        if not tweets:
            raise RuntimeError(f"{normalized}: empty feed")
        return normalized, tweets

    def _format_fetch_errors(self, errors: list[str]) -> str:
        if not errors:
            return "no Nitter instance configured"

        shown_errors = errors[-3:]
        hidden_count = len(errors) - len(shown_errors)
        total_count = len(self.instances)
        summary = (
            f"tried {len(errors)}/{total_count} Nitter instances; no usable feed"
        )
        if hidden_count > 0:
            summary += (
                f"; showing last {len(shown_errors)} errors "
                f"({hidden_count} earlier omitted)"
            )
        else:
            summary += "; errors"
        return f"{summary}: {'; '.join(shown_errors)}"

    def _fetch_from_instance(
        self, instance: str, username: str, limit: int,
    ) -> list[TweetItem]:
        if limit <= 0:
            return []

        tweets: list[TweetItem] = []
        seen: set[str] = set()
        seen_cursors: set[str] = set()
        cursor = ""

        while len(tweets) < limit:
            try:
                page_tweets, next_cursor = self._fetch_page_from_instance(
                    instance, username, cursor, limit,
                )
            except Exception:
                if not tweets:
                    raise
                logger.warning(
                    "[NitterTweets] paged RSS fetch failed after partial results: "
                    f"instance={instance}, username={username}, fetched={len(tweets)}"
                )
                break

            if not page_tweets:
                break

            added = 0
            for tweet in page_tweets:
                key = self._tweet_identity(tweet)
                if key in seen:
                    continue
                seen.add(key)
                tweets.append(tweet)
                added += 1
                if len(tweets) >= limit:
                    break

            if len(tweets) >= limit:
                break
            if not next_cursor or next_cursor in seen_cursors:
                break
            seen_cursors.add(next_cursor)
            cursor = next_cursor
            if added == 0:
                break

        return tweets

    def _fetch_page_from_instance(
        self, instance: str, username: str, cursor: str, limit: int,
    ) -> tuple[list[TweetItem], str]:
        rss_url = self._rss_url(instance, username, cursor)
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
                next_cursor = self._header_value(response.headers, "Min-Id")
        except HTTPError as exc:
            raise RuntimeError(f"HTTP {exc.code}") from exc
        except URLError as exc:
            raise RuntimeError(str(getattr(exc, "reason", exc))) from exc
        return self._parse_rss(data, instance, limit), next_cursor

    @staticmethod
    def _rss_url(instance: str, username: str, cursor: str = "") -> str:
        rss_url = f"{instance.rstrip('/')}/{quote(username)}/rss"
        if cursor:
            rss_url = f"{rss_url}?{urlencode({'cursor': cursor})}"
        return rss_url

    @staticmethod
    def _header_value(headers, name: str) -> str:
        value = headers.get(name) if hasattr(headers, "get") else ""
        if value:
            return str(value).strip()
        for key in getattr(headers, "keys", lambda: [])():
            if str(key).lower() == name.lower():
                return str(headers[key]).strip()
        return ""

    @staticmethod
    def _tweet_identity(tweet: TweetItem) -> str:
        return tweet.status_id or tweet.link or f"{tweet.published}:{tweet.text}"

    def _parse_rss(self, data: bytes, instance: str, limit: int) -> list[TweetItem]:
        root = ET.fromstring(data)
        channel = root.find("channel") if root.tag.lower().endswith("rss") else root
        if channel is None:
            return []
        tweets: list[TweetItem] = []
        for item in channel.findall("item"):
            title = self._node_text(item, "title")
            description = self._node_text(item, "description")
            text = normalize_external_links(clean_text(description or title))
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
