from __future__ import annotations

import sys
import types
import unittest
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


from media_support import MediaService
import media_support.cache as cache_module
from shared import TweetItem, TweetMedia


class MediaCleanupTest(unittest.TestCase):

    def test_send_cleanup_deletes_downloaded_media_after_send(self):
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
            service = MediaService({})

            service.cleanup_after_send([tweet])

            self.assertFalse(path.exists())
            self.assertIsNone(media.path)

    def test_send_cleanup_logs_removed_image_count(self):
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
            service = MediaService({})

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
            service = MediaService({})

            with patch.object(cache_module.logger, "info") as info_log:
                service.cleanup_after_send([tweet])

            logged = "\n".join(str(call.args[0]) for call in info_log.call_args_list)
            self.assertIn("图片 1", logged)
            self.assertIn("视频 0", logged)

    def test_removed_retention_config_is_ignored_after_send(self):
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

            self.assertFalse(path.exists())
            self.assertIsNone(media.path)

    def test_send_cleanup_clears_duplicate_path_references(self):
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
            service = MediaService({})

            service.cleanup_after_send([tweet])

            self.assertFalse(path.exists())
            self.assertIsNone(first.path)
            self.assertIsNone(second.path)

    def test_clear_cache_deletes_files_and_subdirectories(self):
        with TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir) / "cache"
            cache_dir.mkdir()
            image = cache_dir / "image.jpg"
            temp = cache_dir / "video.mp4.tmp"
            nested_dir = cache_dir / "nested"
            nested_dir.mkdir()
            nested_image = nested_dir / "extra.jpg"
            image.write_bytes(b"image")
            temp.write_bytes(b"temp")
            nested_image.write_bytes(b"extra")
            service = MediaService({})
            service.cache_dir = cache_dir
            service.legacy_cache_dir = cache_dir

            result = service.clear_cache()

            self.assertEqual(result.removed, 3)
            self.assertEqual(result.failed, 0)
            self.assertEqual(result.removed_empty_dirs, 1)
            self.assertFalse(image.exists())
            self.assertFalse(temp.exists())
            self.assertFalse(nested_image.exists())
            self.assertFalse(nested_dir.exists())

    def test_clear_cache_also_clears_legacy_cache_files_and_subdirectories(self):
        with TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir) / "cache"
            legacy_cache_dir = Path(temp_dir) / "legacy_cache"
            cache_dir.mkdir()
            legacy_cache_dir.mkdir()
            current_image = cache_dir / "image.jpg"
            legacy_video = legacy_cache_dir / "video.mp4"
            legacy_nested_dir = legacy_cache_dir / "nested"
            legacy_nested_dir.mkdir()
            legacy_nested_video = legacy_nested_dir / "extra.mp4"
            current_image.write_bytes(b"image")
            legacy_video.write_bytes(b"video")
            legacy_nested_video.write_bytes(b"extra")
            service = MediaService({})
            service.cache_dir = cache_dir
            service.legacy_cache_dir = legacy_cache_dir

            result = service.clear_cache()

            self.assertEqual(result.removed, 3)
            self.assertEqual(result.failed, 0)
            self.assertEqual(result.removed_empty_dirs, 1)
            self.assertFalse(current_image.exists())
            self.assertFalse(legacy_video.exists())
            self.assertFalse(legacy_nested_video.exists())
            self.assertFalse(legacy_nested_dir.exists())




