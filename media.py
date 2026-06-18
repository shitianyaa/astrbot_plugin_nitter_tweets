from __future__ import annotations

import asyncio
import base64
import json
import re
import time
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlencode, urljoin, urlparse
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


PLUGIN_NAME = "astrbot_plugin_nitter_tweets"
MEDIA_SIZE_LIMIT_ERROR = "media exceeds size limit"


def _plugin_data_dir() -> Path:
    try:
        from astrbot.api.star import StarTools

        return Path(StarTools.get_data_dir(PLUGIN_NAME))
    except Exception:
        try:
            from astrbot.core.utils.astrbot_path import get_astrbot_data_path

            return Path(get_astrbot_data_path()) / "plugin_data" / PLUGIN_NAME
        except Exception:
            return Path("data") / "plugin_data" / PLUGIN_NAME


class XdownMediaParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.cover_url = ""
        self.items: list[tuple[str, str, str]] = []
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
            self.items.append((kind, self._href, text))
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
class XdownMediaCandidate:
    kind: str
    url: str
    label: str = ""
    resolution: int | None = None
    duration_seconds: float | None = None


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
        self.video_resolution_preference = str(
            config_get(config, "video_resolution_preference", "highest") or "highest"
        ).strip().lower()
        self.max_video_duration_seconds = int(
            clamp_float(
                config_get(config, "max_video_duration_minutes", 8.0),
                1.0,
                8.0,
            )
            * 60
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
        self.cache_dir = _plugin_data_dir() / "cache"
        self.legacy_cache_dir = Path(__file__).resolve().parent / "cache"
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
                    if str(exc) == MEDIA_SIZE_LIMIT_ERROR:
                        self._add_media_warning(
                            tweet,
                            "视频/GIF 超过单个媒体大小上限 "
                            f"{self._format_size_mb(self.max_bytes)}，"
                            "已跳过下载并保留原文链接",
                        )
                    else:
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
            debug_log = getattr(logger, "debug", None)
            if debug_log:
                debug_log(
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
        seen_dirs: set[Path] = set()
        for cache_dir in (self.cache_dir, self.legacy_cache_dir):
            try:
                resolved = cache_dir.resolve()
            except OSError:
                resolved = cache_dir
            if resolved in seen_dirs:
                continue
            seen_dirs.add(resolved)
            self._clear_non_staged_cache_dir(cache_dir, result)
        logger.info(
            "[NitterTweets] non-staged media cache clear finished: "
            f"removed={result.removed}, failed={result.failed}, "
            f"skipped_dirs={result.skipped_dirs}"
        )
        return result

    @staticmethod
    def _clear_non_staged_cache_dir(
        cache_dir: Path, result: MediaCacheCleanupResult
    ) -> None:
        if not cache_dir.exists():
            return

        for path in cache_dir.iterdir():
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

    def _resolve_media_candidates(self, tweet: TweetItem) -> list[XdownMediaCandidate]:
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
        result: list[XdownMediaCandidate] = []
        for kind, url, label in parser.items:
            full_url = urljoin(base_url, url)
            # 最终兜底：如果解析不出类型，按 URL 扩展名再试一次
            if not kind:
                kind = XdownMediaParser._detect_kind("", full_url)
            if not kind:
                logger.info(f"[NitterTweets] skipping unclassified media: {full_url}")
                continue
            result.append(
                XdownMediaCandidate(
                    kind=kind,
                    url=full_url,
                    label=label,
                    resolution=self._extract_video_resolution(label, full_url),
                    duration_seconds=self._extract_video_duration(label, full_url),
                )
            )
        return result

    def _resolve_media_urls(self, tweet: TweetItem) -> list[TweetMedia]:
        candidates = self._resolve_media_candidates(tweet)
        return self._normalize_media_candidates(tweet, candidates)

    def _normalize_media_candidates(
        self,
        tweet: TweetItem,
        candidates: list[XdownMediaCandidate],
    ) -> list[TweetMedia]:
        video_candidates = [
            item for item in candidates if item.kind in {"video", "dynamic"}
        ]
        if video_candidates:
            selected = self._select_video_candidate(tweet, video_candidates)
            if selected is None:
                return []
            skipped_images = sum(1 for item in candidates if item.kind == "image")
            if skipped_images:
                logger.info(
                    "[NitterTweets] skipping image media because video/GIF was "
                    f"detected: skipped={skipped_images}, tweet={tweet.x_url}"
                )
            return [
                TweetMedia(
                    selected.kind,
                    selected.url,
                    duration_seconds=selected.duration_seconds,
                )
            ]

        return [
            TweetMedia(
                item.kind,
                item.url,
                duration_seconds=item.duration_seconds,
            )
            for item in candidates
        ]

    def _select_video_candidate(
        self,
        tweet: TweetItem,
        candidates: list[XdownMediaCandidate],
    ) -> XdownMediaCandidate | None:
        if not candidates:
            return None

        allowed_candidates = self._filter_video_duration_candidates(tweet, candidates)
        if not allowed_candidates:
            return None
        candidates = allowed_candidates

        preference = self.video_resolution_preference or "highest"
        known = [item for item in candidates if item.resolution is not None]
        if not known:
            return candidates[0]

        if preference == "lowest":
            return min(known, key=lambda item: item.resolution or 0)
        if preference == "highest":
            return max(known, key=lambda item: item.resolution or 0)

        target = self._parse_resolution_preference(preference)
        if target is None:
            self._add_media_warning(
                tweet,
                f"视频分辨率配置 {preference} 无法识别，已改用最高分辨率",
                log_warning=False,
            )
            return max(known, key=lambda item: item.resolution or 0)

        exact = [item for item in known if item.resolution == target]
        if exact:
            return exact[0]

        not_over_target = [
            item
            for item in known
            if item.resolution is not None and item.resolution <= target
        ]
        if not_over_target:
            selected = max(not_over_target, key=lambda item: item.resolution or 0)
        else:
            selected = min(known, key=lambda item: item.resolution or 0)
        self._add_media_warning(
            tweet,
            f"未找到配置的视频分辨率 {target}p，已选择 {selected.resolution}p",
            log_warning=False,
        )
        return selected

    def _filter_video_duration_candidates(
        self,
        tweet: TweetItem,
        candidates: list[XdownMediaCandidate],
    ) -> list[XdownMediaCandidate]:
        max_seconds = self.max_video_duration_seconds
        allowed = []
        skipped_durations: list[float] = []
        for item in candidates:
            duration = item.duration_seconds
            if duration is None:
                duration = self._probe_remote_video_duration(item.url)
                item.duration_seconds = duration
            if duration is not None and duration > max_seconds:
                skipped_durations.append(duration)
                continue
            allowed.append(item)

        if skipped_durations and not allowed:
            self._add_media_warning(
                tweet,
                "视频/GIF 时长超过配置上限 "
                f"{self._format_duration(max_seconds)}，已跳过下载并保留原文链接",
            )
        elif skipped_durations:
            longest = max(skipped_durations)
            logger.info(
                "[NitterTweets] skipped long video candidates: "
                f"longest={self._format_duration(longest)}, "
                f"limit={self._format_duration(max_seconds)}, tweet={tweet.x_url}"
            )
        return allowed

    @staticmethod
    def _parse_resolution_preference(value: str) -> int | None:
        match = re.search(r"(\d{3,4})\s*p?", str(value or "").lower())
        if not match:
            return None
        return int(match.group(1))

    @classmethod
    def _extract_video_resolution(cls, label: str, url: str) -> int | None:
        text_parts = [label or "", url or ""]
        token_payload = cls._xdown_token_payload(url)
        if token_payload:
            text_parts.extend(
                [
                    str(token_payload.get("filename") or ""),
                    str(token_payload.get("url") or ""),
                ]
            )
        text = " ".join(text_parts)

        p_matches = [int(value) for value in re.findall(r"(?i)(\d{3,4})\s*p\b", text)]
        if p_matches:
            return max(p_matches)

        size_matches = [
            max(int(width), int(height))
            for width, height in re.findall(r"(?i)(\d{3,4})x(\d{3,4})", text)
        ]
        if size_matches:
            return max(size_matches)
        return None

    @classmethod
    def _extract_video_duration(cls, label: str, url: str) -> float | None:
        token_payload = cls._xdown_token_payload(url)
        duration = cls._duration_from_mapping(token_payload)
        if duration is not None:
            return duration

        text = " ".join(
            [
                label or "",
                url or "",
                str(token_payload.get("filename") or ""),
                str(token_payload.get("url") or ""),
            ]
        )
        return cls._duration_from_text(text)

    @classmethod
    def _duration_from_mapping(cls, data: dict) -> float | None:
        for key in (
            "duration",
            "duration_seconds",
            "durationSeconds",
            "length",
            "length_seconds",
        ):
            duration = cls._coerce_duration_seconds(data.get(key))
            if duration is not None:
                return duration
        return None

    @classmethod
    def _duration_from_text(cls, text: str) -> float | None:
        text = str(text or "")
        for match in re.finditer(r"(?<!\d)(\d{1,2}):(\d{2})(?::(\d{2}))?(?!\d)", text):
            parts = [int(value) for value in match.groups(default="0")]
            if match.group(3) is None:
                minutes, seconds = parts[0], parts[1]
                return float(minutes * 60 + seconds)
            hours, minutes, seconds = parts
            return float(hours * 3600 + minutes * 60 + seconds)

        match = re.search(
            r"(?i)(\d+(?:\.\d+)?)\s*(seconds?|secs?|s|minutes?|mins?|m)\b",
            text,
        )
        if not match:
            return None
        value = float(match.group(1))
        unit = match.group(2).lower()
        if unit.startswith("m") and unit != "ms":
            return value * 60
        return value

    @staticmethod
    def _coerce_duration_seconds(value) -> float | None:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            number = float(value)
            return number if number > 0 else None
        text = str(value).strip()
        if not text:
            return None
        try:
            number = float(text)
        except ValueError:
            return MediaService._duration_from_text(text)
        return number if number > 0 else None

    @classmethod
    def _probe_mp4_duration(cls, data: bytes) -> float | None:
        if not data:
            return None
        return cls._find_mp4_duration(data, 0, len(data))

    @classmethod
    def _find_mp4_duration(cls, data: bytes, start: int, end: int) -> float | None:
        offset = start
        container_types = {b"moov", b"trak", b"mdia"}
        while offset + 8 <= end:
            size = int.from_bytes(data[offset : offset + 4], "big")
            box_type = data[offset + 4 : offset + 8]
            header_size = 8
            if size == 1 and offset + 16 <= end:
                size = int.from_bytes(data[offset + 8 : offset + 16], "big")
                header_size = 16
            elif size == 0:
                size = end - offset
            if size < header_size or offset + size > end:
                break

            box_start = offset + header_size
            box_end = offset + size
            if box_type == b"mvhd":
                return cls._parse_mvhd_duration(data[box_start:box_end])
            if box_type in container_types:
                duration = cls._find_mp4_duration(data, box_start, box_end)
                if duration is not None:
                    return duration
            offset += size
        return None

    @staticmethod
    def _parse_mvhd_duration(payload: bytes) -> float | None:
        if len(payload) < 20:
            return None
        version = payload[0]
        if version == 0:
            if len(payload) < 20:
                return None
            timescale = int.from_bytes(payload[12:16], "big")
            duration = int.from_bytes(payload[16:20], "big")
        elif version == 1:
            if len(payload) < 32:
                return None
            timescale = int.from_bytes(payload[20:24], "big")
            duration = int.from_bytes(payload[24:32], "big")
        else:
            return None
        if timescale <= 0 or duration <= 0:
            return None
        return duration / timescale

    def _probe_remote_video_duration(self, url: str) -> float | None:
        request = Request(
            url,
            headers={
                "User-Agent": self.user_agent,
                "Referer": "https://xdown.app/",
                "Range": "bytes=0-1048575",
            },
        )
        try:
            with urlopen(request, timeout=min(self.timeout, 10.0)) as response:
                data = response.read(1_048_576)
        except Exception as exc:
            logger.debug(f"[NitterTweets] failed to probe video duration: {exc}")
            return None
        return self._probe_mp4_duration(data)

    @staticmethod
    def _format_duration(seconds: float | int) -> str:
        total = max(0, int(round(float(seconds))))
        minutes, seconds = divmod(total, 60)
        if minutes:
            return f"{minutes}分{seconds:02d}秒"
        return f"{seconds}秒"

    @staticmethod
    def _format_size_mb(byte_count: int) -> str:
        size = byte_count / 1024 / 1024
        return f"{size:g} MB"

    @staticmethod
    def _xdown_token_payload(url: str) -> dict:
        token = (parse_qs(urlparse(url).query).get("token") or [""])[0]
        if not token:
            return {}
        parts = token.split(".")
        if len(parts) < 2:
            return {}
        payload = parts[1]
        padding = "=" * (-len(payload) % 4)
        try:
            decoded = base64.urlsafe_b64decode((payload + padding).encode("ascii"))
            data = json.loads(decoded.decode("utf-8", errors="replace"))
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

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
                    raise RuntimeError(MEDIA_SIZE_LIMIT_ERROR)

                downloaded = 0
                with temp_path.open("wb") as file:
                    while True:
                        chunk = response.read(1024 * 256)
                        if not chunk:
                            break
                        downloaded += len(chunk)
                        if downloaded > self.max_bytes:
                            raise RuntimeError(MEDIA_SIZE_LIMIT_ERROR)
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
