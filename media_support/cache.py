from __future__ import annotations

from dataclasses import dataclass

import asyncio
import time
from pathlib import Path

from astrbot.api import logger

from .extensions import classify_media_path

try:
    from ..utils import TweetItem, TweetMedia, generate_file_name
except ImportError:
    from utils import TweetItem, TweetMedia, generate_file_name


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
        if self.cache_retention_days > 0:
            return

        result = MediaCacheCleanupResult()
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
                        "[NitterTweets] 移动媒体到暂存缓存失败: "
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
                        f"[NitterTweets] 删除暂存媒体文件失败: path={path}, error={exc}"
                    )
        removed_empty_dirs = 0
        for directory in sorted(touched_dirs, key=lambda item: len(item.parts), reverse=True):
            removed_empty_dirs += self._remove_empty_staged_dirs(directory)
        if removed or failed:
            logger.info(
                "[NitterTweets] 暂存媒体清理完成: "
                f"removed={removed}, failed={failed}, "
                f"empty_dirs={removed_empty_dirs}"
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
                self._record_removed_media_file(result, path)
                touched_dirs.add(path.parent)
            except OSError as exc:
                result.failed += 1
                logger.warning(
                    f"[NitterTweets] 清理过期暂存媒体失败: path={path}, error={exc}"
                )
        for directory in sorted(touched_dirs, key=lambda item: len(item.parts), reverse=True):
            result.removed_empty_dirs += self._remove_empty_staged_dirs(directory)
        if result.removed or result.failed:
            logger.info(
                "[NitterTweets] 过期暂存媒体清理完成: "
                f"共删除 {result.removed} 个媒体文件"
                f"（图片 {result.removed_images}，视频 {result.removed_videos}，"
                f"其他 {result.removed_other}），"
                f"空目录 {result.removed_empty_dirs} 个，失败 {result.failed} 个，"
                f"保留时间 {retention_hours:g} 小时"
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
            "[NitterTweets] 非暂存媒体缓存清理完成: "
            f"removed={result.removed}, images={result.removed_images}, "
            f"videos={result.removed_videos}, other={result.removed_other}, "
            f"failed={result.failed}, "
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
                MediaCacheMixin._record_removed_media_file(result, path)
            except OSError as exc:
                result.failed += 1
                logger.warning(
                    f"[NitterTweets] 清理媒体缓存文件失败: path={path}, error={exc}"
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

    def _remove_empty_staged_dirs(self, directory: Path) -> int:
        staged_root = self.staged_cache_dir.resolve()
        current = directory
        removed = 0
        while True:
            try:
                resolved = current.resolve()
                if resolved == staged_root or staged_root not in resolved.parents:
                    return removed
                current.rmdir()
                removed += 1
            except OSError:
                return removed
            current = current.parent


    def cleanup_cache(self, force: bool = False) -> None:
        if self.cache_retention_days <= 0:
            return

        now = time.time()
        if not force and now - self._last_cache_cleanup < self.cache_cleanup_interval:
            return
        self._last_cache_cleanup = now

        cutoff = now - self.cache_retention_days * 24 * 60 * 60
        result = MediaCacheCleanupResult()
        for path in self.cache_dir.iterdir():
            if not path.is_file():
                continue
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
                    self._record_removed_media_file(result, path)
            except OSError as exc:
                result.failed += 1
                logger.warning(f"[NitterTweets] 清理缓存文件失败: path={path}, error={exc}")

        if result.removed or result.failed:
            logger.info(
                "[NitterTweets] 媒体缓存清理完成: "
                f"共删除 {result.removed} 个过期媒体文件"
                f"（图片 {result.removed_images}，视频 {result.removed_videos}，"
                f"其他 {result.removed_other}），失败 {result.failed} 个，"
                f"保留时间 {self.cache_retention_days:g} 天"
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
        if media_type == "image":
            result.removed_images += 1
        elif media_type == "video":
            result.removed_videos += 1
        else:
            result.removed_other += 1


# ──────────────────────────────────────────────────────────────────────
# Nitter RSS 客户端
# ──────────────────────────────────────────────────────────────────────
