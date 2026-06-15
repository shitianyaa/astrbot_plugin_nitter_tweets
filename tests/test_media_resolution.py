from __future__ import annotations

import sys
import types
import unittest


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


from media import MediaService, XdownMediaCandidate
from utils import TweetItem


def _tweet() -> TweetItem:
    return TweetItem(
        text="tweet",
        link="https://x.com/JuanEgg18/status/2064692617242448015",
        published="",
    )


def _video(resolution: int) -> XdownMediaCandidate:
    return XdownMediaCandidate(
        "video",
        f"https://example.test/video_{resolution}p.mp4",
        f"Download {resolution}p MP4",
        resolution,
    )


class MediaResolutionTest(unittest.TestCase):
    def test_default_highest_keeps_one_video_and_ignores_images(self):
        service = MediaService({})
        tweet = _tweet()

        media = service._normalize_media_candidates(
            tweet,
            [
                _video(1280),
                _video(852),
                _video(568),
                XdownMediaCandidate("image", "https://example.test/cover.jpg"),
            ],
        )

        self.assertEqual(len(media), 1)
        self.assertTrue(media[0].is_video)
        self.assertIn("1280p", media[0].url)

    def test_configured_resolution_keeps_exact_match(self):
        service = MediaService({"video_resolution_preference": "852p"})

        media = service._normalize_media_candidates(
            _tweet(),
            [_video(1280), _video(852), _video(568)],
        )

        self.assertEqual(len(media), 1)
        self.assertIn("852p", media[0].url)

    def test_missing_resolution_uses_nearest_not_over_target(self):
        service = MediaService({"video_resolution_preference": "720p"})
        tweet = _tweet()

        media = service._normalize_media_candidates(
            tweet,
            [_video(1280), _video(852), _video(568)],
        )

        self.assertEqual(len(media), 1)
        self.assertIn("568p", media[0].url)
        self.assertIn("720p", tweet.media_warnings[0])
        self.assertIn("568p", tweet.media_warnings[0])

    def test_lowest_keeps_lowest_resolution(self):
        service = MediaService({"video_resolution_preference": "lowest"})

        media = service._normalize_media_candidates(
            _tweet(),
            [_video(1280), _video(852), _video(568)],
        )

        self.assertEqual(len(media), 1)
        self.assertIn("568p", media[0].url)

    def test_image_only_candidates_are_unchanged(self):
        service = MediaService({})

        media = service._normalize_media_candidates(
            _tweet(),
            [
                XdownMediaCandidate("image", "https://example.test/1.jpg"),
                XdownMediaCandidate("image", "https://example.test/2.jpg"),
            ],
        )

        self.assertEqual([item.url for item in media], [
            "https://example.test/1.jpg",
            "https://example.test/2.jpg",
        ])

    def test_video_disabled_does_not_leave_cover_image_to_download(self):
        service = MediaService(
            {"send_image_attachments": True, "send_video_attachments": False}
        )
        tweet = _tweet()

        media = service._normalize_media_candidates(
            tweet,
            [
                _video(1280),
                XdownMediaCandidate("image", "https://example.test/cover.jpg"),
            ],
        )

        self.assertEqual(len(media), 1)
        self.assertTrue(media[0].is_video)

    def test_extracts_resolution_from_twimg_size(self):
        resolution = MediaService._extract_video_resolution(
            "",
            "https://video.twimg.com/amplify_video/1/vid/avc1/480x852/test.mp4",
        )

        self.assertEqual(resolution, 852)


if __name__ == "__main__":
    unittest.main()
