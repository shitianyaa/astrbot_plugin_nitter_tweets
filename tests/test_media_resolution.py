from __future__ import annotations

import asyncio
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError


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


import media_support.network as network_module
import media_support.service as service_module
from media_support import MEDIA_SIZE_LIMIT_ERROR, MediaService, XdownMediaCandidate
from shared import TweetItem, TweetMedia


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
        60.0,
    )


class MediaResolutionTest(unittest.TestCase):
    def test_grouped_video_duration_config_controls_service_limit(self):
        service = MediaService(
            {
                "max_video_duration_minutes": 8.0,
                "media": {"max_video_duration_minutes": 3.0},
            }
        )

        self.assertEqual(service.max_video_duration_seconds, 180)

    def test_media_service_respects_media_urlopen_compat_patch(self):
        service = MediaService({})
        calls = []

        class _FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self, limit=-1):
                del limit
                return b'{"status":"ok","data":""}'

        def fake_urlopen(request, timeout):
            calls.append((request.full_url, timeout))
            return _FakeResponse()

        original_urlopen = network_module.stdlib_urlopen
        network_module.stdlib_urlopen = fake_urlopen
        try:
            candidates = service._resolve_media_candidates(_tweet())
        finally:
            network_module.stdlib_urlopen = original_urlopen

        self.assertEqual(candidates, [])
        self.assertEqual(calls[0][0], service.xdown_url)

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

    def test_long_video_is_skipped_before_download(self):
        service = MediaService({"max_video_duration_minutes": 3})
        tweet = _tweet()

        media = service._normalize_media_candidates(
            tweet,
            [
                XdownMediaCandidate(
                    "video",
                    "https://example.test/long.mp4",
                    "Download 1280p MP4 04:30",
                    1280,
                    270.0,
                ),
            ],
        )

        self.assertEqual(media, [])
        self.assertIn("3分00秒", tweet.media_warnings[0])

    def test_long_highest_video_falls_back_to_allowed_resolution(self):
        service = MediaService({"video_resolution_preference": "highest"})

        media = service._normalize_media_candidates(
            _tweet(),
            [
                XdownMediaCandidate(
                    "video",
                    "https://example.test/1280p.mp4",
                    "Download 1280p MP4",
                    1280,
                    600.0,
                ),
                XdownMediaCandidate(
                    "video",
                    "https://example.test/852p.mp4",
                    "Download 852p MP4",
                    852,
                    120.0,
                ),
            ],
        )

        self.assertEqual(len(media), 1)
        self.assertIn("852p", media[0].url)
        self.assertEqual(media[0].duration_seconds, 120.0)

    def test_extracts_duration_from_token_payload(self):
        token = (
            "header."
            "eyJkdXJhdGlvbl9zZWNvbmRzIjo5MH0"
            ".signature"
        )

        duration = MediaService._extract_video_duration(
            "",
            f"https://xdown.app/download?token={token}",
        )

        self.assertEqual(duration, 90.0)

    def test_extracts_duration_from_label(self):
        duration = MediaService._extract_video_duration(
            "Download 1280p MP4 02:15",
            "https://example.test/video.mp4",
        )

        self.assertEqual(duration, 135.0)

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

    def test_video_size_limit_warning_is_user_facing(self):
        service = MediaService(
            {"send_video_attachments": True, "media_max_size_mb": 3}
        )
        tweet = _tweet()

        def resolve_media_urls(_tweet):
            return [TweetMedia("video", "https://example.test/large.mp4")]

        def fail_size_limit(_media):
            raise RuntimeError(MEDIA_SIZE_LIMIT_ERROR)

        service._resolve_media_urls = resolve_media_urls
        service._download = fail_size_limit

        media = asyncio.run(service.resolve_and_download(tweet))

        self.assertEqual(media, [])
        self.assertEqual(len(tweet.media_warnings), 1)
        self.assertIn("视频/GIF 超过单个媒体大小上限 3 MB", tweet.media_warnings[0])
        self.assertIn("已跳过下载并保留原文链接", tweet.media_warnings[0])
        self.assertNotIn(MEDIA_SIZE_LIMIT_ERROR, tweet.media_warnings[0])

    def test_video_size_limit_does_not_log_generic_download_failure(self):
        service = MediaService(
            {"send_video_attachments": True, "media_max_size_mb": 3}
        )
        tweet = _tweet()
        warnings = []

        def resolve_media_urls(_tweet):
            return [TweetMedia("video", "https://example.test/large.mp4")]

        def fail_size_limit(_media):
            raise RuntimeError(MEDIA_SIZE_LIMIT_ERROR)

        service._resolve_media_urls = resolve_media_urls
        service._download = fail_size_limit

        with patch.object(service_module.logger, "warning", side_effect=warnings.append):
            asyncio.run(service.resolve_and_download(tweet))

        self.assertEqual(len(warnings), 1)
        self.assertIn("视频/GIF 超过单个媒体大小上限 3 MB", warnings[0])
        self.assertNotIn("Failed to download media", warnings[0])

    def test_extracts_resolution_from_twimg_size(self):
        resolution = MediaService._extract_video_resolution(
            "",
            "https://video.twimg.com/amplify_video/1/vid/avc1/480x852/test.mp4",
        )

        self.assertEqual(resolution, 852)

    def test_media_download_retries_transient_errors(self):
        service = MediaService({"send_image_attachments": True})
        service.download_retry_delay_seconds = 0
        tweet = _tweet()
        calls = []

        def resolve_media_urls(_tweet):
            return [TweetMedia("image", "https://example.test/image.jpg")]

        def flaky_download(_media):
            calls.append(_media.url)
            if len(calls) < 3:
                raise URLError("temporary network failure")
            return Path("image.jpg")

        service._resolve_media_urls = resolve_media_urls
        service._download = flaky_download

        media = asyncio.run(service.resolve_and_download(tweet))

        self.assertEqual(len(media), 1)
        self.assertEqual(media[0].path, Path("image.jpg"))
        self.assertEqual(len(calls), 3)

    def test_media_download_does_not_retry_non_transient_http_errors(self):
        service = MediaService({"send_image_attachments": True})
        service.download_retry_delay_seconds = 0
        tweet = _tweet()
        calls = []

        def resolve_media_urls(_tweet):
            return [TweetMedia("image", "https://example.test/image.jpg")]

        def fail_not_found(_media):
            calls.append(_media.url)
            raise HTTPError(_media.url, 404, "Not Found", {}, None)

        service._resolve_media_urls = resolve_media_urls
        service._download = fail_not_found

        media = asyncio.run(service.resolve_and_download(tweet))

        self.assertEqual(media, [])
        self.assertEqual(len(calls), 1)

    def test_attach_media_uses_existing_media_urls_without_resolving_again(self):
        service = MediaService({"send_image_attachments": True})
        tweet = _tweet()
        tweet.media = [TweetMedia("image", "https://example.test/history.jpg")]

        def fail_resolve(_tweet):
            raise AssertionError("should not resolve media again")

        service._resolve_media_urls = fail_resolve
        service._download = lambda media: Path("history.jpg")

        asyncio.run(service.attach_media([tweet]))

        self.assertEqual(len(tweet.media), 1)
        self.assertEqual(tweet.media[0].url, "https://example.test/history.jpg")
        self.assertEqual(tweet.media[0].path, Path("history.jpg"))


if __name__ == "__main__":
    unittest.main()
