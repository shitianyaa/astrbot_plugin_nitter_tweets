from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


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


if __name__ == "__main__":
    unittest.main()
