from __future__ import annotations

import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import ClassVar
from urllib.error import HTTPError
from urllib.request import Request

import pytest

from command_handlers.manual import ManualCommandMixin
from media_support.client import NitterClient, TransientFetchError
from media_support.html_backend.http_session import HttpSession
from media_support.html_backend.parser import parse_timeline_html
from media_support.network import SafeRedirectHandler, UnsafeUrlError, validate_http_url


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8080/NASA",
        "http://nitter:8080/search?q=test",
        "http://host.docker.internal:8080/NASA",
        "http://169.254.169.254/latest/meta-data",
    ],
)
def test_validate_http_url_allows_self_hosted_and_private_targets(url: str):
    assert validate_http_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "https://user:pass@example.com",
        "https://example.com:0",
        "ftp://example.com/file",
        "file:///etc/passwd",
        "https://example.com/a b",
    ],
)
def test_validate_http_url_rejects_invalid_syntax_or_protocol(url: str):
    with pytest.raises(UnsafeUrlError):
        validate_http_url(url)


@pytest.mark.parametrize(
    "value",
    [
        "http://127.0.0.1:8080",
        "http://nitter:8080",
        "http://host.docker.internal:8080",
    ],
)
def test_manual_instance_probe_accepts_self_hosted_addresses(value: str):
    assert ManualCommandMixin._looks_like_instance(value)


def test_redirect_handler_allows_private_http_target():
    redirected = SafeRedirectHandler().redirect_request(
        Request("https://example.com/start"),
        None,
        302,
        "Found",
        {},
        "http://127.0.0.1:8080/next",
    )
    assert redirected.full_url == "http://127.0.0.1:8080/next"


def test_redirect_handler_rejects_non_http_target():
    with pytest.raises(UnsafeUrlError):
        SafeRedirectHandler().redirect_request(
            Request("https://example.com/start"),
            None,
            302,
            "Found",
            {},
            "file:///etc/passwd",
        )


def test_cookie_persistence_uses_windows_safe_ipv6_filename(tmp_path):
    host = "2001:4860:4860::8888"
    session = HttpSession(session_dir=tmp_path)
    session.set_cookie("auth", "value", host, host_only=True)
    session.save_cookies(host)

    files = list(tmp_path.iterdir())
    assert len(files) == 1
    assert ":" not in files[0].name
    assert files[0].name.startswith("ipv6-")
    restored = HttpSession(session_dir=tmp_path)
    assert restored.load_cookies(host)
    assert [(cookie.name, cookie.domain) for cookie in restored.jar] == [("auth", host)]


def test_cookie_persistence_hashes_very_long_host(tmp_path):
    host = ".".join(["a" * 63, "b" * 63, "c" * 63, "d" * 61])
    session = HttpSession(session_dir=tmp_path)
    session.set_cookie("auth", "value", host, host_only=True)
    session.save_cookies(host)

    files = list(tmp_path.iterdir())
    assert len(files) == 1
    assert files[0].name.startswith("host-")
    assert len(files[0].name) <= 255
    assert HttpSession(session_dir=tmp_path).load_cookies(host)


def test_html_parser_keeps_private_media_but_excludes_quote_and_article_media():
    html = """
    <div class="timeline-item">
      <a href="/u/status/1"></a>
      <div class="tweet-content">body</div>
      <div class="attachments">
        <a class="still-image" href="/pic/orig/media%2Fmain.jpg"></a>
        <a class="still-image" href="http://127.0.0.1:9000/private.jpg"></a>
      </div>
      <div class="quote quote-big">
        <a class="still-image" href="/pic/orig/media%2Fquote.jpg"></a>
      </div>
      <a href="/i/article/123"><img src="/pic/media%2Farticle.jpg" /></a>
    </div>
    """

    media = parse_timeline_html(html, "http://nitter:8080").tweets[0].media

    assert [item.url for item in media] == [
        "http://nitter:8080/pic/orig/media%2Fmain.jpg",
        "http://127.0.0.1:9000/private.jpg",
    ]


def test_html_parser_keeps_outer_media_around_quote_in_both_orders():
    def parse_media(body: str) -> list[str]:
        html = (
            '<div class="timeline-item"><a href="/u/status/1"></a>'
            '<div class="tweet-content">body</div>'
            f"{body}</div>"
        )
        return [
            item.url
            for item in parse_timeline_html(html, "https://nitter.example")
            .tweets[0]
            .media
        ]

    outer = (
        '<div class="attachments">'
        '<a class="still-image" href="/pic/orig/media%2Fouter.jpg"></a>'
        "</div>"
    )
    quote = (
        '<div class="quote">'
        '<a class="still-image" href="/pic/orig/media%2Fquote.jpg"></a>'
        "</div>"
    )
    expected = ["https://nitter.example/pic/orig/media%2Fouter.jpg"]
    assert parse_media(outer + quote) == expected
    assert parse_media(quote + outer) == expected


def test_rss_host_skip_is_context_local_for_overlapping_tasks():
    client = NitterClient({"instances": ["https://a.example", "https://b.example"]})

    async def worker(instance: str):
        client.begin_run_host_skip()
        try:
            await asyncio.sleep(0)
            client._mark_run_host_skip(instance, TransientFetchError("HTTP 429"))
            await asyncio.sleep(0)
            current = client._active_run_host_skip()
            return current.filter_instances(client.instances)
        finally:
            client.end_run_host_skip()

    async def run():
        return await asyncio.gather(
            worker("https://a.example"), worker("https://b.example")
        )

    assert asyncio.run(run()) == [["https://b.example"], ["https://a.example"]]


def test_rss_host_skip_does_not_retry_when_all_hosts_failed_this_run():
    client = NitterClient({"instances": ["https://a.example", "https://b.example"]})
    active = client.begin_run_host_skip()
    active.mark("https://a.example")
    active.mark("https://b.example")
    try:
        assert client._instances_for_run(client.instances) == []
    finally:
        client.end_run_host_skip()


def test_html_http_session_serializes_shared_opener():
    class Response:
        status = 200
        headers: ClassVar[dict] = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit):
            time.sleep(0.01)
            return b"<html>ok</html>"

        def getcode(self):
            return 200

        def geturl(self):
            return "http://nitter:8080/"

    class Opener:
        def __init__(self):
            self.lock = threading.Lock()
            self.active = 0
            self.maximum = 0

        def open(self, _request, timeout=None):
            del timeout
            with self.lock:
                self.active += 1
                self.maximum = max(self.maximum, self.active)
            time.sleep(0.01)
            with self.lock:
                self.active -= 1
            return Response()

    session = HttpSession()
    opener = Opener()
    session.opener = opener
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(lambda _: session.request("http://nitter:8080/"), range(4)))
    assert opener.maximum == 1


def test_html_http_session_keeps_http_error_body_read_inside_lock():
    tracker_lock = threading.Lock()
    tracker = {"active": 0, "maximum": 0}

    class ErrorBody:
        def read(self, _limit):
            with tracker_lock:
                tracker["active"] += 1
                tracker["maximum"] = max(tracker["maximum"], tracker["active"])
            time.sleep(0.01)
            with tracker_lock:
                tracker["active"] -= 1
            return b"rate limited"

        def close(self):
            return None

    class ErrorOpener:
        def open(self, request, timeout=None):
            del timeout
            raise HTTPError(request.full_url, 429, "Too Many Requests", {}, ErrorBody())

    session = HttpSession(proxy="http://127.0.0.1:8080")
    session.opener = ErrorOpener()
    with ThreadPoolExecutor(max_workers=4) as executor:
        responses = list(
            executor.map(lambda _: session.request("http://nitter:8080/"), range(4))
        )

    assert [response.code for response in responses] == [429, 429, 429, 429]
    assert tracker["maximum"] == 1
