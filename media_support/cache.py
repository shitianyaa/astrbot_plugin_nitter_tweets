from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import ClassVar

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
    skipped_active: int = 0


class MediaCacheMixin:
    _protected_cache_dirs = frozenset({"staged"})
    _lease_lock = Lock()
    _active_leases: ClassVar[dict[Path, int]] = {}

    @classmethod
    def register_media_path(cls, path: Path | str) -> None:
        """Hold a lease while a prepared media file may still be sent."""
        key = cls._lease_key(path)
        with cls._lease_lock:
            cls._increment_lease_locked(key)

    @classmethod
    def lease_existing_media_path(cls, path: Path | str) -> Path | None:
        """Lease a ready cache file without racing a concurrent cleanup."""
        value = Path(path)
        key = cls._lease_key(value)
        with cls._lease_lock:
            try:
                if not value.is_file() or value.stat().st_size <= 0:
                    return None
                value.touch()
            except OSError:
                return None
            cls._increment_lease_locked(key)
        return value

    @classmethod
    def commit_media_path(
        cls,
        temp_path: Path | str,
        file_path: Path | str,
    ) -> Path:
        """Install a completed temp file and transfer its lease atomically."""
        temp = Path(temp_path)
        target = Path(file_path)
        temp_key = cls._lease_key(temp)
        target_key = cls._lease_key(target)
        with cls._lease_lock:
            try:
                target_ready = target.is_file() and target.stat().st_size > 0
            except OSError:
                target_ready = False
            if target_ready:
                temp.unlink(missing_ok=True)
                target.touch()
            else:
                temp.replace(target)
            cls._decrement_lease_locked(temp_key)
            cls._increment_lease_locked(target_key)
        return target

    @classmethod
    def discard_media_path(cls, path: Path | str) -> None:
        """Drop an internal lease and best-effort delete its temporary file."""
        value = Path(path)
        key = cls._lease_key(value)
        error: OSError | ValueError | None = None
        with cls._lease_lock:
            cls._decrement_lease_locked(key)
            try:
                value.unlink(missing_ok=True)
            except (OSError, ValueError) as exc:
                error = exc
        if error is not None:
            logger.warning(
                f"[NitterTweets] 删除临时媒体文件失败: path={value}, error={error}"
            )

    @classmethod
    def _increment_lease_locked(cls, key: Path) -> None:
        cls._active_leases[key] = cls._active_leases.get(key, 0) + 1

    @classmethod
    def _decrement_lease_locked(cls, key: Path) -> int:
        count = cls._active_leases.get(key, 0)
        if count <= 1:
            cls._active_leases.pop(key, None)
            return 0
        remaining = count - 1
        cls._active_leases[key] = remaining
        return remaining

    @classmethod
    def _lease_key(cls, path: Path | str) -> Path:
        value = Path(path)
        try:
            return value.resolve()
        except (OSError, RuntimeError):
            return value.absolute()

    @classmethod
    def _release_media_path(
        cls,
        path: Path | str,
        media: TweetMedia,
        result: MediaCacheCleanupResult,
    ) -> bool:
        try:
            value = Path(path)
            key = cls._lease_key(value)
        except (TypeError, ValueError, OSError) as exc:
            result.failed += 1
            logger.warning(
                f"[NitterTweets] 无效媒体缓存路径: path={path!r}, error={exc}"
            )
            return True

        removed = False
        error: OSError | None = None
        with cls._lease_lock:
            count = cls._active_leases.get(key, 0)
            if count:
                remaining = cls._decrement_lease_locked(key)
                if remaining:
                    result.skipped_active += 1
                    return True
            try:
                if value.exists():
                    value.unlink()
                    removed = True
            except OSError as exc:
                error = exc

        if removed:
            cls._record_removed_media_file(result, value, media)
        if error is not None:
            result.failed += 1
            logger.warning(
                f"[NitterTweets] 删除媒体文件失败: path={value}, error={error}"
            )
            # The current sender has released its lease. Keeping the path on
            # the media object lets a later cleanup retry instead of leaking a
            # permanently active lease that clear_cache must always skip.
            return False
        return True

    def cleanup_after_send(self, tweets: list[TweetItem]) -> None:
        result = MediaCacheCleanupResult()
        pending: list[tuple[TweetMedia, Path | str]] = []
        for tweet in tweets:
            for media in tweet.media:
                path = media.path
                if path is None:
                    continue
                pending.append((media, path))

        for media, path in pending:
            if self._release_media_path(path, media, result):
                media.path = None

        if result.removed or result.failed or result.skipped_active:
            log_func = logger.warning if result.failed else logger.info
            log_func(
                "[NitterTweets] 发送后媒体清理完成: "
                f"共删除 {result.removed} 个媒体文件"
                f"（图片 {result.removed_images}，视频 {result.removed_videos}，"
                f"其他 {result.removed_other}），失败 {result.failed} 个，"
                f"活跃跳过 {result.skipped_active} 个"
            )

    def clear_cache(self) -> MediaCacheCleanupResult:
        result = MediaCacheCleanupResult()
        seen_dirs: set[Path] = set()
        for cache_dir in (self.cache_dir, self.legacy_cache_dir):
            cache_dir = Path(cache_dir)
            try:
                resolved = cache_dir.resolve()
            except (OSError, RuntimeError):
                resolved = cache_dir
            if resolved in seen_dirs:
                continue
            seen_dirs.add(resolved)
            self._clear_cache_dir(cache_dir, result)
        logger.info(
            "[NitterTweets] 媒体缓存清理完成: "
            f"removed={result.removed}, images={result.removed_images}, "
            f"videos={result.removed_videos}, other={result.removed_other}, "
            f"failed={result.failed}, active={result.skipped_active}, "
            f"empty_dirs={result.removed_empty_dirs}"
        )
        return result

    @classmethod
    def _clear_cache_dir(cls, cache_dir: Path, result: MediaCacheCleanupResult) -> None:
        cache_dir = Path(cache_dir)
        if not cache_dir.exists():
            return

        # Walk deepest-first so empty parent dirs can be removed after files.
        for path in sorted(cache_dir.rglob("*"), reverse=True):
            try:
                relative = path.relative_to(cache_dir)
                if (
                    relative.parts
                    and relative.parts[0].casefold() in cls._protected_cache_dirs
                ):
                    if len(relative.parts) == 1 and path.is_dir():
                        result.skipped_dirs += 1
                    continue
                if path.is_file():
                    key = cls._lease_key(path)
                    with cls._lease_lock:
                        active = cls._active_leases.get(key, 0)
                        if active:
                            result.skipped_active += 1
                            continue
                        path.unlink(missing_ok=True)
                    cls._record_removed_media_file(result, path)
                elif path.is_dir():
                    path.rmdir()
                    result.removed_empty_dirs += 1
            except (OSError, ValueError) as exc:
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
        path: Path | str,
        media: TweetMedia | None = None,
    ) -> None:
        path = Path(path)
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
