"""媒体下载日志不得写入完整私有 URL（twimg 签名、xdown/snapcdn token）。"""

from __future__ import annotations

from media_support.service import _safe_text, _safe_url

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
