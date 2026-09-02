"""token 解 twimg 直链 + 下载换源兜底测试。

xdown 返回的 snapcdn 代理 URL 的 token JWT payload 内含原始 twimg 直链；
_resolve_media_candidates 应以 twimg 直链作主 URL、snapcdn 代理作 fallback_url。
下载主 URL 失败时 _download_with_retries 切到 fallback 重试一次。
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from urllib.error import URLError

from media_support import service as service_module
from media_support.service import MediaService
from shared import TweetItem


class _Response:
    status = 200
    headers: dict[str, str] = {}

    def __init__(self, body: bytes = b"", url: str = "https://xdown.app/"):
        self.body = body
        self.url = url
        self.read_done = False

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def read(self, _size: int = -1) -> bytes:
        if self.read_done:
            return b""
        self.read_done = True
        return self.body

    def geturl(self) -> str:
        return self.url

    def getcode(self) -> int:
        return self.status


def _make_token(direct_url: str, filename: str = "XDown.app_x_720p.mp4") -> str:
    payload = {"url": direct_url, "filename": filename}
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"hdr.{body}.sig"


def _service() -> MediaService:
    service = object.__new__(MediaService)
    service.xdown_url = "https://xdown.app/api/ajaxSearch"
    service.timeout = 25.0
    return service


def test_resolve_uses_twimg_direct_url_with_snapcdn_fallback(monkeypatch):
    twimg = "https://video.twimg.com/amplify_video/1/vid/avc1/720x1280/x.mp4?tag=29"
    token = _make_token(twimg)
    snapcdn = f"https://dl.snapcdn.app/get?token={token}"
    html = f"<a class='tw-button-dl' href='{snapcdn}'>下载 MP4 (720p)</a>"
    body = json.dumps({"status": "ok", "data": html}).encode()

    monkeypatch.setattr(
        service_module, "compat_urlopen", lambda _r, _t: _Response(body)
    )

    tweet = TweetItem(text="", link="https://x.com/u/status/1", published="")
    candidates = _service()._resolve_media_candidates(tweet)

    assert len(candidates) == 1
    cand = candidates[0]
    assert cand.url == twimg
    assert cand.fallback_url == snapcdn
    assert cand.resolution == 720


def test_resolve_keeps_snapcdn_when_token_has_no_url(monkeypatch):
    # token payload 无 url 字段：主 URL 保持 snapcdn 代理，fallback 留空。
    payload = {"filename": "XDown.app_x_720p.mp4"}
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    token = f"hdr.{body}.sig"
    snapcdn = f"https://dl.snapcdn.app/get?token={token}"
    html = f"<a class='tw-button-dl' href='{snapcdn}'>下载 MP4 (720p)</a>"
    body_bytes = json.dumps({"status": "ok", "data": html}).encode()

    monkeypatch.setattr(
        service_module, "compat_urlopen", lambda _r, _t: _Response(body_bytes)
    )

    tweet = TweetItem(text="", link="https://x.com/u/status/1", published="")
    candidates = _service()._resolve_media_candidates(tweet)

    assert len(candidates) == 1
    assert candidates[0].url == snapcdn
    assert candidates[0].fallback_url == ""


def test_download_with_retries_switches_to_fallback_on_failure(monkeypatch):
    service = object.__new__(MediaService)
    service.download_retry_attempts = 2
    service.download_retry_delay_seconds = 0.0
    service._is_retryable_download_error = lambda _exc: True  # type: ignore[method-assign]

    calls: list[str] = []

    def fake_download(media):
        calls.append(media.url)
        if media.url == "https://twimg/x.mp4":
            raise URLError("twimg unreachable")
        media.path = Path("fake.mp4")
        return media.path

    monkeypatch.setattr(service, "_download", fake_download)

    from shared import TweetMedia  # noqa: PLC0415

    media = TweetMedia(
        "video",
        "https://twimg/x.mp4",
        fallback_url="https://snapcdn/get?token=x",
    )
    result = service._download_with_retries(media)

    assert result == Path("fake.mp4")
    assert calls == ["https://twimg/x.mp4", "https://snapcdn/get?token=x"]
    assert media.url == "https://snapcdn/get?token=x"
    assert media.fallback_url == ""
