"""Twitter CDN rejects media downloads that spoof xdown.app as Referer."""

from __future__ import annotations

from media_support.network import BUILTIN_USER_AGENT
from media_support.service import MediaService


def _service() -> MediaService:
    return object.__new__(MediaService)


def test_twimg_video_uses_x_com_referer_not_xdown():
    headers = _service()._media_request_headers(
        "https://video.twimg.com/amplify_video/1/vid/avc1/720x1280/a.mp4?tag=29"
    )
    assert headers["User-Agent"] == BUILTIN_USER_AGENT
    assert headers["Referer"] == "https://x.com/"


def test_pbs_image_uses_x_com_referer():
    headers = _service()._media_request_headers(
        "https://pbs.twimg.com/media/ABC.jpg?name=orig"
    )
    assert headers["Referer"] == "https://x.com/"


def test_xdown_host_keeps_xdown_referer():
    headers = _service()._media_request_headers("https://xdown.app/some/file.mp4")
    assert headers["Referer"] == "https://xdown.app/"
