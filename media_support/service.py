from __future__ import annotations

import asyncio
import json
import ssl
import time
from pathlib import Path
from uuid import uuid4
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import Request

from astrbot.api import logger

try:
    from ..config import DEFAULT_MAX_VIDEO_DURATION_MINUTES, config_get
    from ..shared import (
        TweetItem, TweetMedia, clamp_float, clamp_int,
        generate_file_name,
    )
except ImportError:
    from config import DEFAULT_MAX_VIDEO_DURATION_MINUTES, config_get
    from shared import (
        TweetItem, TweetMedia, clamp_float, clamp_int,
        generate_file_name,
    )

from .cache import MediaCacheMixin
from .extensions import (
    MEDIA_IMAGE_SUFFIXES,
    MEDIA_TYPE_DYNAMIC,
    MEDIA_TYPE_IMAGE,
    MEDIA_TYPE_VIDEO,
)
from . import video_probe
from .network import (
    NetworkClient,
    ResponseTooLargeError,
    safe_error_for_log,
    safe_url_for_log,
)
from .xdown import XdownMediaCandidate, XdownMediaParser


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


class MediaService(MediaCacheMixin):
    def __init__(self, config, network: NetworkClient | None = None):
        self.network = network or NetworkClient(config)
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
                config_get(
                    config,
                    "max_video_duration_minutes",
                    DEFAULT_MAX_VIDEO_DURATION_MINUTES,
                ),
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
        # 普通媒体不长期缓存；发送流程结束后由 cleanup_after_send 删除。
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
        retry_attempts = clamp_int(
            config_get(config, "media_retry_attempts", 3), 1, 10
        )
        retry_delay_seconds = clamp_float(
            config_get(config, "media_retry_delay_seconds", 5.0), 0.0, 60.0
        )
        self.resolve_retry_attempts = retry_attempts
        self.resolve_retry_delay_seconds = retry_delay_seconds
        self.download_retry_attempts = retry_attempts
        self.download_retry_delay_seconds = retry_delay_seconds

    @property
    def enabled(self) -> bool:
        return self.send_image_attachments or self.send_video_attachments

    async def attach_media(self, tweets: list[TweetItem]) -> None:
        if (
            not self.send_image_attachments
            and not self.send_video_attachments
        ) or self.max_per_tweet <= 0:
            return
        for tweet in tweets:
            try:
                tweet.media = await self.resolve_and_download(tweet)
            except Exception as exc:
                error = safe_error_for_log(exc, self.xdown_url)
                self._add_media_warning(
                    tweet, f"媒体解析失败，已保留原文链接：{error}"
                )

    async def resolve_and_download(self, tweet: TweetItem) -> list[TweetMedia]:
        media_urls = [
            TweetMedia(
                media.kind,
                media.url,
                duration_seconds=media.duration_seconds,
            )
            for media in tweet.media
            if media.url
        ]
        if not media_urls:
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
                media.path = await asyncio.to_thread(
                    self._download_with_retries, media
                )
            except Exception as exc:
                if media.is_video:
                    if str(exc) == MEDIA_SIZE_LIMIT_ERROR:
                        self._add_media_warning(
                            tweet,
                            "视频/GIF 超过单个媒体大小上限 "
                            f"{self._format_size_mb(self.max_bytes)}，"
                            "已跳过下载并保留原文链接",
                        )
                        continue
                    else:
                        error = safe_error_for_log(exc, media.url)
                        self._add_media_warning(
                            tweet, f"视频/GIF 下载失败，已保留原文链接：{error}"
                        )
                logger.warning(
                    "[NitterTweets] 媒体下载失败: "
                    f"url={safe_url_for_log(media.url)}, "
                    f"error={safe_error_for_log(exc, media.url)}"
                )
                continue
            downloaded.append(media)
        return downloaded

    def _download_with_retries(self, media: TweetMedia) -> Path:
        attempts = max(1, int(self.download_retry_attempts))
        delay = max(0.0, float(self.download_retry_delay_seconds))
        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                return self._download(media)
            except Exception as exc:
                if str(exc) == MEDIA_SIZE_LIMIT_ERROR or not self._is_retryable_download_error(exc):
                    raise
                last_error = exc
                if attempt >= attempts:
                    break
                logger.warning(
                    "[NitterTweets] 媒体下载失败，准备重试: "
                    f"url={safe_url_for_log(media.url)}, "
                    f"attempt={attempt}/{attempts}, delay={delay:g}s, "
                    f"error={safe_error_for_log(exc, media.url)}"
                )
                if delay > 0:
                    time.sleep(delay)

        if last_error is not None:
            raise last_error
        raise RuntimeError("媒体下载失败")

    @staticmethod
    def _add_media_warning(
        tweet: TweetItem, message: str, log_warning: bool = True
    ) -> None:
        if message not in tweet.media_warnings:
            tweet.media_warnings.append(message)
        log = logger.warning if log_warning else logger.info
        log(f"[NitterTweets] {message}: {tweet.x_url}")

    def _resolve_media_candidates(self, tweet: TweetItem) -> list[XdownMediaCandidate]:
        attempts = max(1, int(self.resolve_retry_attempts))
        delay = max(0.0, float(self.resolve_retry_delay_seconds))
        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                return self._resolve_media_candidates_once(tweet)
            except Exception as exc:
                if not self._is_retryable_resolve_error(exc):
                    raise
                last_error = exc
                if attempt >= attempts:
                    break
                logger.warning(
                    "[NitterTweets] 媒体解析失败，准备重试: "
                    f"tweet={safe_url_for_log(tweet.x_url)}, "
                    f"attempt={attempt}/{attempts}, delay={delay:g}s, "
                    f"error={safe_error_for_log(exc, self.xdown_url)}"
                )
                if delay > 0:
                    time.sleep(delay)

        if last_error is not None:
            raise last_error
        raise RuntimeError("媒体解析失败")

    def _resolve_media_candidates_once(
        self, tweet: TweetItem
    ) -> list[XdownMediaCandidate]:
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
            raw = self.network.read(request, self.timeout, 2_000_000).data
        except HTTPError as exc:
            raise RuntimeError(f"xdown HTTP {exc.code}") from exc
        except URLError as exc:
            reason = getattr(exc, "reason", exc)
            raise RuntimeError(str(reason)) from exc

        payload = json.loads(raw.decode("utf-8", errors="replace"))
        if payload.get("status") != "ok":
            message = str(payload.get("message") or payload.get("error") or "").strip()
            detail = f": {message}" if message else ""
            raise ConnectionError(f"xdown 返回错误状态{detail}")
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
                logger.info(
                    "[NitterTweets] 跳过无法识别类型的媒体: "
                    f"url={safe_url_for_log(full_url)}"
                )
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

    @classmethod
    def _is_retryable_resolve_error(cls, exc: Exception) -> bool:
        cause = exc.__cause__
        if isinstance(cause, HTTPError):
            return cls._is_retryable_http_status(cause.code)
        if isinstance(cause, (URLError, TimeoutError, ssl.SSLError, ConnectionError)):
            return True
        if isinstance(exc, HTTPError):
            return cls._is_retryable_http_status(exc.code)
        if isinstance(exc, (URLError, TimeoutError, ssl.SSLError, ConnectionError)):
            return True
        return isinstance(exc, json.JSONDecodeError)

    def _resolve_media_urls(self, tweet: TweetItem) -> list[TweetMedia]:
        candidates = self._resolve_media_candidates(tweet)
        return self._normalize_media_candidates(tweet, candidates)

    def _normalize_media_candidates(
        self,
        tweet: TweetItem,
        candidates: list[XdownMediaCandidate],
    ) -> list[TweetMedia]:
        video_candidates = [
            item
            for item in candidates
            if item.kind in {MEDIA_TYPE_VIDEO, MEDIA_TYPE_DYNAMIC}
        ]
        if video_candidates:
            selected = self._select_video_candidate(tweet, video_candidates)
            if selected is None:
                return []
            skipped_images = sum(
                1 for item in candidates if item.kind == MEDIA_TYPE_IMAGE
            )
            if skipped_images:
                logger.info(
                    "[NitterTweets] 检测到视频/GIF，跳过同条推文中的图片候选: "
                    f"skipped={skipped_images}, tweet={tweet.x_url}"
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
                "[NitterTweets] 跳过超长视频候选: "
                f"longest={self._format_duration(longest)}, "
                f"limit={self._format_duration(max_seconds)}, tweet={tweet.x_url}"
            )
        return allowed

    @staticmethod
    def _parse_resolution_preference(value: str) -> int | None:
        return video_probe.parse_resolution_preference(value)

    @classmethod
    def _extract_video_resolution(cls, label: str, url: str) -> int | None:
        return video_probe.extract_video_resolution(label, url)

    @classmethod
    def _extract_video_duration(cls, label: str, url: str) -> float | None:
        return video_probe.extract_video_duration(label, url)

    @classmethod
    def _duration_from_mapping(cls, data: dict) -> float | None:
        return video_probe.duration_from_mapping(data)

    @classmethod
    def _duration_from_text(cls, text: str) -> float | None:
        return video_probe.duration_from_text(text)

    @staticmethod
    def _coerce_duration_seconds(value) -> float | None:
        return video_probe.coerce_duration_seconds(value)

    @classmethod
    def _probe_mp4_duration(cls, data: bytes) -> float | None:
        return video_probe.probe_mp4_duration(data)

    @classmethod
    def _find_mp4_duration(cls, data: bytes, start: int, end: int) -> float | None:
        return video_probe.find_mp4_duration(data, start, end)

    @staticmethod
    def _parse_mvhd_duration(payload: bytes) -> float | None:
        return video_probe.parse_mvhd_duration(payload)

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
            data = self.network.read(
                request, min(self.timeout, 10.0), 1_048_576
            ).data
        except Exception as exc:
            logger.debug(
                "[NitterTweets] 探测视频时长失败: "
                f"{safe_error_for_log(exc, url)}"
            )
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
        return video_probe.xdown_token_payload(url)

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
        return suffix in MEDIA_IMAGE_SUFFIXES

    def _download(self, media: TweetMedia) -> Path:
        default_suffix = ".mp4" if media.is_video else ".jpg"
        file_path = self.cache_dir / generate_file_name(media.url, default_suffix)
        if file_path.exists() and file_path.stat().st_size > 0:
            file_path.touch()
            return file_path

        temp_path = file_path.with_name(
            f"{file_path.name}.{uuid4().hex}.tmp"
        )
        request = Request(
            media.url,
            headers={
                "User-Agent": self.user_agent,
                "Referer": "https://xdown.app/",
            },
        )
        try:
            try:
                self.network.download(
                    request,
                    self.timeout,
                    temp_path,
                    self.max_bytes,
                )
            except ResponseTooLargeError as exc:
                raise RuntimeError(MEDIA_SIZE_LIMIT_ERROR) from exc

            if temp_path.stat().st_size <= 0:
                raise RuntimeError("empty media")
            temp_path.replace(file_path)
            return file_path
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise

    @classmethod
    def _is_retryable_download_error(cls, exc: Exception) -> bool:
        if isinstance(exc, HTTPError):
            return cls._is_retryable_http_status(exc.code)
        if isinstance(exc, (URLError, TimeoutError, ssl.SSLError, ConnectionError)):
            return True
        return False

    @staticmethod
    def _is_retryable_http_status(status_code: int) -> bool:
        return status_code in {408, 429, 500, 502, 503, 504, 520, 522, 523, 524}
