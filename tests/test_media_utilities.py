"""Focused contracts for media request headers, cache names, and log safety."""

from __future__ import annotations

from media_support.network import BUILTIN_USER_AGENT
from media_support.service import MediaService, _safe_text, _safe_url
from shared.utils import generate_file_name


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


# 真实事故样本：nitter /video/ 代理 URL 把 twimg 直链（含 ?tag=29）百分号编码
# 塞在 path 里；naive 的 Path().suffix 曾把 ".mp4%3Ftag%3D29" 整个当成扩展名，
# NapCat 收到 file:// 路径做 URI 解码后文件名对不上磁盘文件 → ENOENT 1200。
NITTER_PROXY_VIDEO = (
    "http://nitter:8080/video/C26BBB8DC1653/"
    "https%3A%2F%2Fvideo.twimg.com%2Famplify_video%2F2094778591859146752"
    "%2Fvid%2Favc1%2F704x1280%2F573FQmGXgTmD3FuT.mp4%3Ftag%3D29"
)


def test_proxy_video_url_keeps_clean_mp4_name():
    name = generate_file_name(NITTER_PROXY_VIDEO, ".mp4")
    # md5 前缀由完整 URL 决定；后缀必须是干净的 .mp4
    assert name == "d574b203470fc4db.mp4"
    assert "?" not in name and "%" not in name and "=" not in name


def test_plain_url_extension_kept():
    name = generate_file_name("https://video.twimg.com/a/b.mp4?tag=29", ".mp4")
    assert name.endswith(".mp4") and "?" not in name


def test_query_format_without_path_extension():
    name = generate_file_name("https://example.com/dl?id=1&format=gif", ".jpg")
    assert name.endswith(".gif")


def test_dirty_query_format_falls_back_to_default():
    name = generate_file_name(
        "https://example.com/dl?id=1&format=mp4%3Ftag%3D29", ".mp4"
    )
    assert name.endswith(".mp4") and "?" not in name and "%" not in name


def test_no_extension_falls_back_to_default():
    name = generate_file_name("https://example.com/m", ".jpg")
    assert name.endswith(".jpg")


SIGNED_TWIMG = (
    "https://video.twimg.com/amplify_video/2094/vid/avc1/720x1280/x.mp4"
    "?tag=29&g2a_sig=AbCdEf123456"
)
SNAPCDN = "https://snapcdn.app/download?token=eyJhbGciOiJIUzI1NiJ9.abcdef.ghijkl&f=mp4"


def test_query_and_signature_are_masked():
    out = _safe_url(SIGNED_TWIMG)
    assert "g2a_sig=AbCdEf123456" not in out
    assert "tag=29" not in out
    # host+path 保留，才有排查价值
    assert out.startswith("https://video.twimg.com/amplify_video/2094/")


def test_token_bearing_proxy_url_is_masked():
    out = _safe_url(SNAPCDN)
    assert "eyJhbGciOiJIUzI1NiJ9" not in out
    assert out.startswith("https://snapcdn.app/download?")


def test_empty_url_renders_placeholder():
    assert _safe_url("") == "-"
    assert _safe_url(None) == "-"


def test_exception_text_with_url_is_masked():
    exc = Exception(f"HTTP Error 403: Forbidden for url {SIGNED_TWIMG}")
    out = _safe_text(exc)
    assert "g2a_sig=AbCdEf123456" not in out
    assert "403" in out


def test_plain_error_text_survives():
    assert "connection reset" in _safe_text(Exception("connection reset"))
