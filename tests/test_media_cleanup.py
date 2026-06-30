from __future__ import annotations

import sys
import types
import unittest
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


if "astrbot.api" not in sys.modules:
    astrbot_module = types.ModuleType("astrbot")
    astrbot_api_module = types.ModuleType("astrbot.api")

    class _Logger:
        def info(self, *args, **kwargs):
            pass

        def warning(self, *args, **kwargs):
            pass

        def error(self, *args, **kwargs):
            pass

    astrbot_api_module.logger = _Logger()
    sys.modules["astrbot"] = astrbot_module
    sys.modules["astrbot.api"] = astrbot_api_module


from media import MediaService
import media_support.cache as cache_module
from utils import TweetItem, TweetMedia


class MediaCleanupTest(unittest.TestCase):
    def test_zero_retention_deletes_downloaded_media_after_send(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "image.jpg"
            path.write_bytes(b"image")
            media = TweetMedia("image", "https://example.test/image.jpg", path)
            tweet = TweetItem(
                text="tweet",
                link="https://x.com/example/status/1",
                published="",
                media=[media],
            )
            service = MediaService({"media_cache_retention_days": 0})

            service.cleanup_after_send([tweet])

            self.assertFalse(path.exists())
            self.assertIsNone(media.path)

    def test_zero_retention_cleanup_after_send_logs_removed_image_count(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "image.jpg"
            path.write_bytes(b"image")
            media = TweetMedia("image", "https://example.test/image.jpg", path)
            tweet = TweetItem(
                text="tweet",
                link="https://x.com/example/status/1",
                published="",
                media=[media],
            )
            service = MediaService({"media_cache_retention_days": 0})

            with patch.object(cache_module.logger, "info") as info_log:
                service.cleanup_after_send([tweet])

            logged = "\n".join(str(call.args[0]) for call in info_log.call_args_list)
            self.assertIn("发送后媒体清理完成", logged)
            self.assertIn("图片 1", logged)

    def test_cleanup_after_send_prefers_media_metadata_over_suffix(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "image-named-like-video.mp4"
            path.write_bytes(b"image")
            media = TweetMedia("image", "https://example.test/image.jpg", path)
            tweet = TweetItem(
                text="tweet",
                link="https://x.com/example/status/1",
                published="",
                media=[media],
            )
            service = MediaService({"media_cache_retention_days": 0})

            with patch.object(cache_module.logger, "info") as info_log:
                service.cleanup_after_send([tweet])

            logged = "\n".join(str(call.args[0]) for call in info_log.call_args_list)
            self.assertIn("图片 1", logged)
            self.assertIn("视频 0", logged)

    def test_positive_retention_keeps_downloaded_media_after_send(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "image.jpg"
            path.write_bytes(b"image")
            media = TweetMedia("image", "https://example.test/image.jpg", path)
            tweet = TweetItem(
                text="tweet",
                link="https://x.com/example/status/1",
                published="",
                media=[media],
            )
            service = MediaService({"media_cache_retention_days": 3})

            service.cleanup_after_send([tweet])

            self.assertTrue(path.exists())
            self.assertEqual(media.path, path)

    def test_zero_retention_clears_duplicate_path_references(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "image.jpg"
            path.write_bytes(b"image")
            first = TweetMedia("image", "https://example.test/1.jpg", path)
            second = TweetMedia("image", "https://example.test/2.jpg", path)
            tweet = TweetItem(
                text="tweet",
                link="https://x.com/example/status/1",
                published="",
                media=[first, second],
            )
            service = MediaService({"media_cache_retention_days": 0})

            service.cleanup_after_send([tweet])

            self.assertFalse(path.exists())
            self.assertIsNone(first.path)
            self.assertIsNone(second.path)

    def test_clear_non_staged_cache_deletes_only_cache_root_files(self):
        with TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir) / "cache"
            cache_dir.mkdir()
            image = cache_dir / "image.jpg"
            temp = cache_dir / "video.mp4.tmp"
            staged_dir = cache_dir / "staged"
            staged_dir.mkdir()
            staged_image = staged_dir / "queued.jpg"
            image.write_bytes(b"image")
            temp.write_bytes(b"temp")
            staged_image.write_bytes(b"queued")
            service = MediaService({})
            service.cache_dir = cache_dir
            service.legacy_cache_dir = cache_dir

            result = service.clear_non_staged_cache()

            self.assertEqual(result.removed, 2)
            self.assertEqual(result.failed, 0)
            self.assertEqual(result.skipped_dirs, 1)
            self.assertFalse(image.exists())
            self.assertFalse(temp.exists())
            self.assertTrue(staged_image.exists())

    def test_clear_non_staged_cache_also_clears_legacy_cache_root_files(self):
        with TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir) / "cache"
            legacy_cache_dir = Path(temp_dir) / "legacy_cache"
            cache_dir.mkdir()
            legacy_cache_dir.mkdir()
            current_image = cache_dir / "image.jpg"
            legacy_video = legacy_cache_dir / "video.mp4"
            legacy_staged_dir = legacy_cache_dir / "staged"
            legacy_staged_dir.mkdir()
            legacy_staged_video = legacy_staged_dir / "queued.mp4"
            current_image.write_bytes(b"image")
            legacy_video.write_bytes(b"video")
            legacy_staged_video.write_bytes(b"queued")
            service = MediaService({})
            service.cache_dir = cache_dir
            service.legacy_cache_dir = legacy_cache_dir

            result = service.clear_non_staged_cache()

            self.assertEqual(result.removed, 2)
            self.assertEqual(result.failed, 0)
            self.assertEqual(result.skipped_dirs, 1)
            self.assertFalse(current_image.exists())
            self.assertFalse(legacy_video.exists())
            self.assertTrue(legacy_staged_video.exists())

    def test_move_media_to_staged_then_cleanup_staged_media(self):
        with TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir) / "cache"
            cache_dir.mkdir()
            image = cache_dir / "image.jpg"
            image.write_bytes(b"image")
            media = TweetMedia("image", "https://example.test/image.jpg", image)
            tweet = TweetItem(
                text="tweet",
                link="https://x.com/example/status/123",
                published="",
                media=[media],
            )
            service = MediaService({})
            service.cache_dir = cache_dir
            service.legacy_cache_dir = cache_dir

            service._move_tweets_media_to_staged("global", "example", [tweet])
            staged_path = media.path
            clear_result = service.clear_non_staged_cache()

            self.assertEqual(clear_result.removed, 0)
            self.assertIsNotNone(staged_path)
            self.assertFalse(image.exists())
            self.assertTrue(staged_path.exists())
            self.assertIn("staged", staged_path.parts)

            service.cleanup_staged_media_for_tweets([tweet])

            self.assertFalse(staged_path.exists())
            self.assertIsNone(media.path)

    def test_zero_retention_cleanup_after_send_keeps_staged_media(self):
        with TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir) / "cache"
            staged_dir = cache_dir / "staged" / "global" / "123"
            staged_dir.mkdir(parents=True)
            staged_path = staged_dir / "00_image.jpg"
            staged_path.write_bytes(b"image")
            media = TweetMedia("image", "https://example.test/image.jpg", staged_path)
            tweet = TweetItem(
                text="tweet",
                link="https://x.com/example/status/123",
                published="",
                media=[media],
            )
            service = MediaService({"media_cache_retention_days": 0})
            service.cache_dir = cache_dir
            service.legacy_cache_dir = cache_dir

            service.cleanup_after_send([tweet])

            self.assertTrue(staged_path.exists())
            self.assertEqual(media.path, staged_path)

    def test_expired_staged_cleanup_keeps_protected_paths(self):
        with TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir) / "cache"
            staged_dir = cache_dir / "staged" / "global" / "123"
            staged_dir.mkdir(parents=True)
            protected = staged_dir / "00_keep.jpg"
            expired = staged_dir / "01_delete.jpg"
            protected.write_bytes(b"keep")
            expired.write_bytes(b"delete")
            old_time = 1
            os.utime(protected, (old_time, old_time))
            os.utime(expired, (old_time, old_time))
            service = MediaService({})
            service.cache_dir = cache_dir
            service.legacy_cache_dir = cache_dir

            result = service.cleanup_expired_staged_media(
                retention_hours=1,
                protected_paths={str(protected)},
            )

            self.assertEqual(result.removed, 1)
            self.assertTrue(protected.exists())
            self.assertFalse(expired.exists())

    def test_expired_staged_cleanup_logs_media_type_and_empty_dir_counts(self):
        with TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir) / "cache"
            image_dir = cache_dir / "staged" / "images" / "nested"
            video_dir = cache_dir / "staged" / "videos" / "nested"
            other_dir = cache_dir / "staged" / "other" / "nested"
            for directory in (image_dir, video_dir, other_dir):
                directory.mkdir(parents=True)

            image = image_dir / "expired.jpg"
            video = video_dir / "expired.mp4"
            other = other_dir / "expired.bin"
            for path in (image, video, other):
                path.write_bytes(b"data")
                os.utime(path, (1, 1))

            service = MediaService({})
            service.cache_dir = cache_dir
            service.legacy_cache_dir = cache_dir

            with patch.object(cache_module.logger, "info") as info_log:
                result = service.cleanup_expired_staged_media(retention_hours=1)

            logged = "\n".join(str(call.args[0]) for call in info_log.call_args_list)
            self.assertIn("过期暂存媒体清理完成", logged)
            self.assertIn("图片 1", logged)
            self.assertIn("视频 1", logged)
            self.assertIn("其他 1", logged)
            self.assertRegex(logged, r"空目录 [1-9]\d* 个")
            self.assertEqual(result.removed, 3)
            self.assertGreater(result.removed_empty_dirs, 0)
            self.assertFalse(image.exists())
            self.assertFalse(video.exists())
            self.assertFalse(other.exists())

    def test_expired_cache_cleanup_logs_media_type_counts(self):
        with TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir) / "cache"
            cache_dir.mkdir()
            image = cache_dir / "old.jpg"
            video = cache_dir / "old.mp4"
            other = cache_dir / "old.bin"
            fresh = cache_dir / "fresh.jpg"
            for path in (image, video, other, fresh):
                path.write_bytes(b"data")
            old_time = 1
            for path in (image, video, other):
                os.utime(path, (old_time, old_time))
            service = MediaService({"media_cache_retention_days": 1})
            service.cache_dir = cache_dir
            service.legacy_cache_dir = cache_dir

            with patch.object(cache_module.logger, "info") as info_log:
                service.cleanup_cache(force=True)

            logged = "\n".join(str(call.args[0]) for call in info_log.call_args_list)
            self.assertIn("媒体缓存清理完成", logged)
            self.assertIn("图片 1", logged)
            self.assertIn("视频 1", logged)
            self.assertIn("其他 1", logged)
            self.assertFalse(image.exists())
            self.assertFalse(video.exists())
            self.assertFalse(other.exists())
            self.assertTrue(fresh.exists())


if __name__ == "__main__":
    unittest.main()
