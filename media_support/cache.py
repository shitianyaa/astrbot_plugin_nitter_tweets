from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from astrbot.api import logger

from .extensions import MEDIA_TYPE_IMAGE, MEDIA_TYPE_VIDEO, classify_media_path

try:
    from ..shared import TweetItem, TweetMedia
except ImportError:
    from shared import TweetItem, TweetMedia


@dataclass(slots=True)
class MediaCacheCleanupResult:
    removed: int = 0
    failed: int = 0
    skipped_dirs: int = 0
    removed_images: int = 0
    removed_videos: int = 0
    removed_other: int = 0
    removed_empty_dirs: int = 0


class MediaCacheMixin:
    def cleanup_after_send(self, tweets: list[TweetItem]) -> None:
        result = MediaCacheCleanupResult()
        seen_paths: set[Path] = set()
        for tweet in tweets:
            for media in tweet.media:
                path = media.path
                if path is None:
                    continue
                if path in seen_paths:
                    media.path = None
                    continue
                seen_paths.add(path)
                try:
                    path.unlink(missing_ok=True)
                    self._record_removed_media_file(result, path, media)
                    media.path = None
                except OSError as exc:
                    result.failed += 1
                    logger.warning(
                        f"[NitterTweets] 删除媒体文件失败: path={path}, error={exc}"
                    )

        if result.removed or result.failed:
            log_func = logger.warning if result.failed else logger.info
            log_func(
                "[NitterTweets] 发送后媒体清理完成: "
                f"共删除 {result.removed} 个媒体文件"
                f"（图片 {result.removed_images}，视频 {result.removed_videos}，"
                f"其他 {result.removed_other}），失败 {result.failed} 个"
            )

    def clear_cache(self) -> MediaCacheCleanupResult:
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
            self._clear_cache_dir(cache_dir, result)
        logger.info(
            "[NitterTweets] 媒体缓存清理完成: "
            f"removed={result.removed}, images={result.removed_images}, "
            f"videos={result.removed_videos}, other={result.removed_other}, "
            f"failed={result.failed}, empty_dirs={result.removed_empty_dirs}"
        )
        return result

    # Backward-compatible alias for older call sites.
    def clear_non_staged_cache(self) -> MediaCacheCleanupResult:
        return self.clear_cache()

    @staticmethod
    def _clear_cache_dir(
        cache_dir: Path, result: MediaCacheCleanupResult
    ) -> None:
        if not cache_dir.exists():
            return

        # Walk deepest-first so empty parent dirs can be removed after files.
        for path in sorted(cache_dir.rglob("*"), reverse=True):
            try:
                if path.is_file():
                    path.unlink(missing_ok=True)
                    MediaCacheMixin._record_removed_media_file(result, path)
                elif path.is_dir():
                    path.rmdir()
                    result.removed_empty_dirs += 1
            except OSError as exc:
                if path.is_dir():
                    result.skipped_dirs += 1
                else:
                    result.failed += 1
                logger.warning(
                    f"[NitterTweets] 清理媒体缓存失败: path={path}, error={exc}"
                )

    @staticmethod
    def _record_removed_media_file(
        result: MediaCacheCleanupResult,
        path: Path,
        media: TweetMedia | None = None,
    ) -> None:
        result.removed += 1
        if isinstance(media, TweetMedia):
            if media.is_image:
                result.removed_images += 1
                return
            if media.is_video:
                result.removed_videos += 1
                return

        media_type = classify_media_path(path)
        if media_type == MEDIA_TYPE_IMAGE:
            result.removed_images += 1
        elif media_type == MEDIA_TYPE_VIDEO:
            result.removed_videos += 1
        else:
            result.removed_other += 1
