from __future__ import annotations

import json
from urllib.request import Request

import pytest

from media_support import client as client_module
from media_support import network
from media_support import service as service_module
from media_support import status_resolve
from media_support.client import NitterClient
from media_support.html_backend.http_session import HttpSession
from media_support.service import MediaService


def _request_header(request: Request, name: str) -> str | None:
    expected = name.casefold()
    for key, value in request.header_items():
        if key.casefold() == expected:
            return value
    return None


class _Response:
    status = 200
    headers: dict[str, str] = {}

    def __init__(self, body: bytes = b"", url: str = "https://example.com/"):
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


def test_safe_urlopen_enforces_builtin_headers(monkeypatch):
    captured: list[Request] = []

    class _Opener:
        def open(self, outgoing: Request, timeout: float):
            captured.append(outgoing)
            return _Response(url=outgoing.full_url)

    monkeypatch.setattr(network, "_safe_opener", lambda **_kwargs: _Opener())

    network.safe_urlopen(
        Request("https://example.com/path", headers={"User-Agent": "custom"}),
        1.0,
        resolve_dns=False,
    )

    assert _request_header(captured[0], "User-Agent") == network.BUILTIN_USER_AGENT
    assert (
        _request_header(captured[0], "Accept-Language")
        == network.BUILTIN_ACCEPT_LANGUAGE
    )


def test_rss_request_uses_builtin_headers(monkeypatch):
    captured: list[Request] = []

    def fake_open(request: Request, _timeout: float):
        captured.append(request)
        raise AssertionError("request captured")

    monkeypatch.setattr(client_module, "compat_urlopen", fake_open)
    client = NitterClient({"user_agent": "ignored-custom-agent"})

    with pytest.raises(AssertionError, match="request captured"):
        client._fetch_page_from_instance("https://example.com", "nasa", "", 1)

    assert _request_header(captured[0], "User-Agent") == network.BUILTIN_USER_AGENT


def test_html_request_uses_builtin_headers():
    captured: list[Request] = []

    class _Opener:
        def open(self, request: Request, timeout: float):
            captured.append(request)
            return _Response(b"ok", request.full_url)

    session = HttpSession(proxy="http://127.0.0.1:8080")
    session.opener = _Opener()

    response = session.request("https://example.com/path")

    assert response.code == 200
    assert _request_header(captured[0], "User-Agent") == network.BUILTIN_USER_AGENT


def test_status_json_request_uses_builtin_headers(monkeypatch):
    captured: list[Request] = []

    def fake_open(request: Request, *, timeout: float):
        captured.append(request)
        return _Response(json.dumps({"ok": True}).encode())

    monkeypatch.setattr(status_resolve, "safe_urlopen", fake_open)

    assert status_resolve._fetch_json("https://example.com/status", timeout=1) == {
        "ok": True
    }
    assert _request_header(captured[0], "User-Agent") == network.BUILTIN_USER_AGENT


def test_xdown_and_media_requests_use_builtin_headers(monkeypatch):
    captured: list[Request] = []

    def fake_open(request: Request, _timeout: float):
        captured.append(request)
        return _Response(json.dumps({"status": "empty"}).encode())

    monkeypatch.setattr(service_module, "compat_urlopen", fake_open)
    service = object.__new__(MediaService)
    service.xdown_url = "https://xdown.app/api/ajaxSearch"
    service.timeout = 1.0

    assert (
        service._resolve_media_candidates(
            type("Tweet", (), {"x_url": "https://x.com/u/status/1"})()
        )
        == []
    )
    media_headers = service._media_request_headers("https://pbs.twimg.com/a.jpg")

    assert _request_header(captured[0], "User-Agent") == network.BUILTIN_USER_AGENT
    assert media_headers["User-Agent"] == network.BUILTIN_USER_AGENT
    assert captured[0].get_header("Origin") == "https://xdown.app"
    assert media_headers["Referer"] == "https://x.com/"
