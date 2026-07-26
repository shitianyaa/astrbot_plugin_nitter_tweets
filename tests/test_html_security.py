from __future__ import annotations

import asyncio
import http.client
import json
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError
from urllib.request import HTTPHandler, HTTPSHandler, Request

import pytest

from media_support.html_backend.modes import (
    GateKeeper,
    MAX_ANUBIS_CHALLENGE_ID_BYTES,
    MAX_ANUBIS_RANDOM_DATA_BYTES,
    detect_gate,
    solve_anubis_pow,
    solve_poast_pow,
)
from media_support.html_backend.parser import parse_timeline_html
from media_support.network import (
    SafeHTTPHandler,
    SafeHTTPSHandler,
    SafeRedirectHandler,
    UnsafeUrlError,
    _SafeHTTPConnection,
    _SafeHTTPSConnection,
    _request_uses_proxy,
    validate_http_url,
)
from media_support.client import NitterClient, TransientFetchError
from media_support.html_backend.http_session import HttpSession, RawResponse
from command_handlers.manual import ManualCommandMixin


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://10.0.0.1/",
        "http://169.254.169.254/latest/meta-data",
        "http://localhost/",
        "http://user:pass@example.com/",
        "file:///etc/passwd",
    ],
)
def test_validate_http_url_rejects_local_or_non_http_targets(url: str):
    with pytest.raises(UnsafeUrlError):
        validate_http_url(url, resolve_dns=False)


@pytest.mark.parametrize(
    "url",
    [
        "http://2130706433/",
        "http://0x7f000001/",
        "http://0177.0.0.1/",
        "http://127.1/",
    ],
)
def test_validate_http_url_rejects_legacy_ipv4_literals(url: str):
    with pytest.raises(UnsafeUrlError, match="non-canonical IPv4"):
        validate_http_url(url, resolve_dns=False)


@pytest.mark.parametrize(
    "url",
    [
        "http://2130706433/",
        "http://0x7f000001/",
        "http://0177.0.0.1/",
        "http://127.1/",
    ],
)
def test_proxy_session_rejects_legacy_ipv4_before_open(url: str):
    session = HttpSession(proxy="http://127.0.0.1:8080")

    class NeverOpen:
        def open(self, *_args, **_kwargs):
            raise AssertionError("unsafe URL reached the proxy opener")

    session.opener = NeverOpen()

    response = session.request(url)

    assert response.code == -1
    assert "non-canonical IPv4" in str(response.error)


@pytest.mark.parametrize(
    "value",
    [
        "http://127.0.0.1:8080",
        "https://user@example.com",
        "https://example.com:0",
        "ftp://example.com",
    ],
)
def test_manual_mirror_probe_rejects_unsafe_instance_syntax(value: str):
    assert not ManualCommandMixin._looks_like_instance(value)


def test_manual_mirror_probe_accepts_public_form_without_dns_lookup():
    # Configuration/command parsing must still work for test or newly
    # provisioned mirrors whose DNS is temporarily unavailable.  The network
    # opener performs the strict DNS check when the request is made.
    assert ManualCommandMixin._looks_like_instance("https://mirror.example")


def test_validate_http_url_rejects_dns_rebinding_to_private_address(monkeypatch):
    def fake_getaddrinfo(*_args, **_kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.2", 80))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(UnsafeUrlError):
        validate_http_url("https://public.example/", resolve_dns=True)


@pytest.mark.parametrize(
    ("handler_type", "base_handler"),
    [(SafeHTTPHandler, HTTPHandler), (SafeHTTPSHandler, HTTPSHandler)],
)
def test_opener_rejects_private_peer_after_dns_check(
    monkeypatch, handler_type, base_handler
):
    """A DNS result can change before urllib connects; inspect the live peer."""

    class FakeSocket:
        def getpeername(self):
            return ("10.0.0.7", 443)

    class FakeResponse:
        fp = type("FakeFP", (), {"raw": type("FakeRaw", (), {"_sock": FakeSocket()})()})()
        closed = False

        def close(self):
            self.closed = True

    response = FakeResponse()

    def fake_do_open(self, *_args, **_kwargs):
        return response

    monkeypatch.setattr(base_handler, "do_open", fake_do_open)
    handler = handler_type(check_peer=True)

    with pytest.raises(UnsafeUrlError, match="connected peer"):
        handler.do_open(object, object())
    assert response.closed is True


def test_opener_skips_origin_peer_check_for_proxy_request(monkeypatch):
    class FakeSocket:
        def getpeername(self):
            return ("127.0.0.1", 3067)

    class FakeResponse:
        fp = type("FakeFP", (), {"raw": type("FakeRaw", (), {"_sock": FakeSocket()})()})()

        def close(self):
            raise AssertionError("proxy response should not be rejected as origin")

    response = FakeResponse()

    def fake_do_open(self, *_args, **_kwargs):
        return response

    monkeypatch.setattr(HTTPHandler, "do_open", fake_do_open)
    handler = SafeHTTPHandler(check_peer=True)
    request = type(
        "ProxyRequest",
        (),
        {
            "host": "127.0.0.1:3067",
            "origin_req_host": "public.example",
            "selector": "http://public.example/",
        },
    )()

    assert handler.do_open(object, request) is response


def test_direct_request_with_explicit_port_is_not_mistaken_for_proxy():
    request = Request("http://example.com:80/path")

    assert _request_uses_proxy(request) is False


@pytest.mark.parametrize(
    ("connection_type", "base_connection_type", "port"),
    [
        (_SafeHTTPConnection, http.client.HTTPConnection, 80),
        (_SafeHTTPSConnection, http.client.HTTPSConnection, 443),
    ],
)
def test_direct_connection_rejects_private_peer_before_sending_request(
    monkeypatch,
    connection_type,
    base_connection_type,
    port,
):
    events: list[str] = []

    class FakeSocket:
        def getpeername(self):
            events.append("peer")
            return ("10.0.0.7", port)

        def close(self):
            events.append("close")

        def sendall(self, _payload):
            events.append("send")

    def fake_connect(connection):
        events.append("connect")
        connection.sock = FakeSocket()

    monkeypatch.setattr(base_connection_type, "connect", fake_connect)
    connection = connection_type("example.com", check_peer=True)

    with pytest.raises(UnsafeUrlError, match="connected peer"):
        connection.request("GET", "/")

    assert events == ["connect", "peer", "close"]


@pytest.mark.parametrize(
    (
        "url",
        "proxy_type",
        "handler_type",
        "base_handler",
        "connection_type",
        "safe_connection_type",
    ),
    [
        (
            "http://public.example/path",
            "http",
            SafeHTTPHandler,
            HTTPHandler,
            http.client.HTTPConnection,
            _SafeHTTPConnection,
        ),
        (
            "https://public.example/path",
            "https",
            SafeHTTPSHandler,
            HTTPSHandler,
            http.client.HTTPSConnection,
            _SafeHTTPSConnection,
        ),
    ],
)
def test_proxy_handler_disables_origin_peer_check(
    monkeypatch,
    url,
    proxy_type,
    handler_type,
    base_handler,
    connection_type,
    safe_connection_type,
):
    captured: dict[str, object] = {}
    response = object()

    def fake_do_open(self, selected_connection, req, **kwargs):
        del self, req
        captured["connection"] = selected_connection
        captured.update(kwargs)
        return response

    monkeypatch.setattr(base_handler, "do_open", fake_do_open)
    request = Request(url)
    request.set_proxy("127.0.0.1:8080", proxy_type)

    assert handler_type(check_peer=True).do_open(connection_type, request) is response
    assert captured["connection"] is safe_connection_type
    assert captured["check_peer"] is False


@pytest.mark.parametrize(
    (
        "url",
        "handler_type",
        "base_handler",
        "connection_type",
        "safe_connection_type",
    ),
    [
        (
            "http://public.example:8080/path",
            SafeHTTPHandler,
            HTTPHandler,
            http.client.HTTPConnection,
            _SafeHTTPConnection,
        ),
        (
            "https://public.example:8443/path",
            SafeHTTPSHandler,
            HTTPSHandler,
            http.client.HTTPSConnection,
            _SafeHTTPSConnection,
        ),
    ],
)
def test_direct_explicit_port_keeps_pre_request_peer_check(
    monkeypatch,
    url,
    handler_type,
    base_handler,
    connection_type,
    safe_connection_type,
):
    captured: dict[str, object] = {}
    response = object()

    def fake_do_open(self, selected_connection, req, **kwargs):
        del self, req
        captured["connection"] = selected_connection
        captured.update(kwargs)
        return response

    monkeypatch.setattr(base_handler, "do_open", fake_do_open)
    request = Request(url)

    assert (
        handler_type(check_peer=True).do_open(
            connection_type,
            request,
        )
        is response
    )
    assert captured == {
        "connection": safe_connection_type,
        "check_peer": True,
    }


def test_redirect_rejects_legacy_ipv4_without_dns_lookup():
    handler = SafeRedirectHandler(resolve_dns=False)

    with pytest.raises(UnsafeUrlError, match="non-canonical IPv4"):
        handler.redirect_request(
            Request("https://public.example/start"),
            None,
            302,
            "Found",
            {},
            "http://2130706433/private",
        )


def test_http_connection_rejects_private_peer_before_request(monkeypatch):
    class FakeSocket:
        closed = False

        def getpeername(self):
            return ("10.0.0.7", 80)

        def close(self):
            self.closed = True

    sock = FakeSocket()

    def fake_connect(connection):
        connection.sock = sock

    monkeypatch.setattr(http.client.HTTPConnection, "connect", fake_connect)
    connection = _SafeHTTPConnection("example.com", check_peer=True)

    with pytest.raises(UnsafeUrlError, match="connected peer"):
        connection.connect()
    assert sock.closed is True


def test_detect_gate_does_not_accept_login_or_maintenance_page():
    assert detect_gate(b"<html><head><title>Login - Nitter</title></head></html>") == "error"
    assert detect_gate(b"<html><body>This site is under maintenance</body></html>") == "error"
    assert detect_gate(b'<div class="timeline-item"><div class="tweet-content">ok</div></div>') == "ok"


def test_anubis_pow_rejects_unreasonable_difficulty():
    with pytest.raises(ValueError):
        solve_anubis_pow("seed", 33, max_iters=1)


def test_anubis_pow_rejects_oversized_random_data():
    with pytest.raises(ValueError, match="random data is too long"):
        solve_anubis_pow(
            "x" * (MAX_ANUBIS_RANDOM_DATA_BYTES + 1),
            0,
            max_iters=1,
        )


@pytest.mark.parametrize(
    ("field", "oversized_value"),
    [
        ("randomData", "x" * (MAX_ANUBIS_RANDOM_DATA_BYTES + 1)),
        ("id", "x" * (MAX_ANUBIS_CHALLENGE_ID_BYTES + 1)),
    ],
)
def test_gatekeeper_rejects_oversized_anubis_fields_before_pow(
    monkeypatch,
    field,
    oversized_value,
):
    challenge = {"randomData": "seed", "id": "challenge-id"}
    challenge[field] = oversized_value
    payload = {"challenge": challenge, "rules": {"difficulty": 0}}
    html = (
        '<script id="anubis_challenge" type="application/json">'
        f"{json.dumps(payload)}"
        "</script>"
    )
    session = HttpSession()

    def unexpected_pow(*_args, **_kwargs):
        raise AssertionError("oversized challenge reached the PoW loop")

    monkeypatch.setattr(
        "media_support.html_backend.modes.solve_anubis_pow",
        unexpected_pow,
    )
    gatekeeper = GateKeeper(session)

    assert not gatekeeper._pass_anubis(
        "https://public.example",
        RawResponse(200, "https://public.example/NASA", html.encode(), 0.0),
    )


def test_poast_pow_rejects_malformed_challenge():
    with pytest.raises(ValueError):
        solve_poast_pow("not-a-challenge", max_iters=1)


def test_poast_cookie_is_scoped_to_the_exact_challenged_host(monkeypatch):
    session = HttpSession()
    passed = RawResponse(
        200,
        "https://mirror.example.com/",
        b'<div class="timeline-item">ok</div>',
        0.0,
    )
    monkeypatch.setattr(
        "media_support.html_backend.modes.solve_poast_pow",
        lambda _challenge: "token",
    )
    monkeypatch.setattr(
        "media_support.html_backend.modes.time_sleep_soft",
        lambda: None,
    )
    monkeypatch.setattr(session, "request", lambda *_args, **_kwargs: passed)
    challenge = "a" * 40
    challenge_response = RawResponse(
        503,
        "https://mirror.example.com/",
        (
            "<html>Verifying your browser with SHA1"
            f"<script>const a0_0x2a54 = ['{challenge}'];</script></html>"
        ).encode(),
        0.0,
    )

    assert GateKeeper(session)._pass_poast(
        "https://mirror.example.com",
        challenge_response,
    )
    cookies = [cookie for cookie in session.jar if cookie.name == "res"]
    assert len(cookies) == 1
    assert cookies[0].domain == "mirror.example.com"
    assert cookies[0].domain_specified is False
    exact_request = Request("https://mirror.example.com/")
    session.jar.add_cookie_header(exact_request)
    assert exact_request.get_header("Cookie") == "res=token"
    subdomain_request = Request("https://sub.mirror.example.com/")
    session.jar.add_cookie_header(subdomain_request)
    assert subdomain_request.get_header("Cookie") is None


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
    assert [(cookie.name, cookie.domain) for cookie in restored.jar] == [
        ("auth", host)
    ]


def test_cookie_persistence_hashes_host_that_exceeds_windows_component_limit(
    tmp_path,
):
    host = ".".join(["a" * 63, "b" * 63, "c" * 63, "d" * 61])
    assert len(host) == 253
    session = HttpSession(session_dir=tmp_path)
    session.set_cookie("auth", "value", host, host_only=True)

    session.save_cookies(host)

    files = list(tmp_path.iterdir())
    assert len(files) == 1
    assert files[0].name.startswith("host-")
    assert len(files[0].name) <= 255
    restored = HttpSession(session_dir=tmp_path)
    assert restored.load_cookies(host)


def test_cookie_persistence_keeps_ordinary_legacy_filename_and_narrows_poast(
    tmp_path,
):
    host = "nitter.poast.org"
    legacy_path = tmp_path / f"{host}.json"
    legacy_path.write_text(
        json.dumps(
            {
                "host": host,
                "cookies": {
                    "res": {
                        "value": "legacy-token",
                        "domain": ".poast.org",
                        "path": "/",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    restored = HttpSession(session_dir=tmp_path)

    assert restored.load_cookies(host)
    cookie = next(iter(restored.jar))
    assert cookie.domain == host
    assert cookie.domain_specified is False
    restored.save_cookies(host)
    assert list(tmp_path.iterdir()) == [legacy_path]
    persisted = json.loads(legacy_path.read_text(encoding="utf-8"))
    assert persisted["cookies"]["res"]["domain"] == host
    assert persisted["cookies"]["res"]["host_only"] is True


def test_html_parser_ignores_quote_article_and_unsafe_media():
    html = """
    <div class="timeline-item">
      <a href="/u/status/1"></a>
      <div class="tweet-content">body</div>
      <div class="attachments"><a class="still-image" href="/pic/orig/media%2Fmain.jpg"></a></div>
      <div class="quote quote-big">
        <div class="quote-media-container"><a class="still-image" href="/pic/orig/media%2Fquote.jpg"></a></div>
      </div>
      <a href="/i/article/123"><img src="/pic/media%2Farticle.jpg" /></a>
      <a class="still-image" href="http://127.0.0.1/private.jpg"></a>
    </div>
    """
    media = parse_timeline_html(html, "https://nitter.example").tweets[0].media
    assert [item.url for item in media] == [
        "https://nitter.example/pic/orig/media%2Fmain.jpg"
    ]


def test_html_parser_keeps_outer_media_around_quote_in_both_orders():
    def parse_media(body: str) -> list[str]:
        html = (
            '<div class="timeline-item"><a href="/u/status/1"></a>'
            '<div class="tweet-content">body</div>'
            f"{body}</div>"
        )
        page = parse_timeline_html(html, "https://nitter.example")
        return [item.url for item in page.tweets[0].media]

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


def test_html_parser_masks_attachments_nested_in_quote_media_container():
    html = (
        '<div class="timeline-item"><a href="/u/status/1"></a>'
        '<div class="tweet-content">body</div>'
        '<div class="attachments">'
        '<a class="still-image" href="/pic/orig/media%2Fouter.jpg"></a>'
        "</div>"
        '<div class="quote quote-big">'
        '<div class="quote-media-container"><div class="attachments">'
        '<a class="still-image" href="/pic/orig/media%2Fquote.jpg"></a>'
        "</div></div></div></div>"
    )

    page = parse_timeline_html(html, "https://nitter.example")

    assert [item.url for item in page.tweets[0].media] == [
        "https://nitter.example/pic/orig/media%2Fouter.jpg"
    ]


def test_html_parser_masks_article_cover_inside_attachments_wrapper():
    html = (
        '<div class="timeline-item"><a href="/u/status/1"></a>'
        '<div class="tweet-content">body</div>'
        '<a href="/i/article/123"><div class="article">'
        '<div class="attachments">'
        '<a class="still-image" href="/pic/orig/media%2Fcover.jpg"></a>'
        "</div></div></a></div>"
    )

    page = parse_timeline_html(html, "https://nitter.example")

    assert page.tweets[0].media == []


def test_html_parser_recovers_outer_media_after_unclosed_quote():
    html = (
        '<div class="timeline-item"><a href="/u/status/1"></a>'
        '<div class="tweet-content">body</div>'
        '<div class="quote">'
        '<a class="still-image" href="/pic/orig/media%2Fquote.jpg"></a>'
        '<div class="attachments">'
        '<a class="still-image" href="/pic/orig/media%2Fouter.jpg"></a>'
        "</div>"
    )
    page = parse_timeline_html(html, "https://nitter.example")
    assert [item.url for item in page.tweets[0].media] == [
        "https://nitter.example/pic/orig/media%2Fouter.jpg"
    ]


def test_rss_host_skip_is_context_local_for_overlapping_tasks():
    client = NitterClient({"instances": ["https://a.example", "https://b.example"]})

    async def worker(instance: str):
        client.begin_run_host_skip()
        try:
            await asyncio.sleep(0)
            client._mark_run_host_skip(instance, TransientFetchError("HTTP 429"))
            await asyncio.sleep(0)
            current = client._active_run_host_skip()
            return current.filter_instances(["https://a.example", "https://b.example"])
        finally:
            client.end_run_host_skip()

    async def run():
        return await asyncio.gather(worker("https://a.example"), worker("https://b.example"))

    assert asyncio.run(run()) == [
        ["https://b.example"],
        ["https://a.example"],
    ]


def test_rss_host_skip_does_not_retry_when_all_hosts_failed_this_run():
    client = NitterClient({"instances": ["https://a.example", "https://b.example"]})
    active = client.begin_run_host_skip()
    active.mark("https://a.example")
    active.mark("https://b.example")
    try:
        assert client._instances_for_run(client.instances) == []
    finally:
        client.end_run_host_skip()


def test_html_http_session_serializes_shared_opener(monkeypatch):
    monkeypatch.setattr(
        "media_support.network._resolved_addresses",
        lambda *_args, **_kwargs: ["93.184.216.34"],
    )

    class Response:
        status = 200
        headers = {}

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
            return "https://public.example/"

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
        list(executor.map(lambda _: session.request("https://public.example/"), range(4)))
    assert opener.maximum == 1


def test_html_http_session_keeps_http_error_body_read_inside_lock():
    tracker_lock = threading.Lock()
    tracker = {"active": 0, "maximum": 0}

    class ErrorBody:
        def read(self, _limit):
            with tracker_lock:
                tracker["active"] += 1
                tracker["maximum"] = max(
                    tracker["maximum"],
                    tracker["active"],
                )
            time.sleep(0.01)
            with tracker_lock:
                tracker["active"] -= 1
            return b"rate limited"

        def close(self):
            return None

    class ErrorOpener:
        def open(self, request, timeout=None):
            del timeout
            raise HTTPError(
                request.full_url,
                429,
                "Too Many Requests",
                {},
                ErrorBody(),
            )

    session = HttpSession(proxy="http://127.0.0.1:8080")
    session.opener = ErrorOpener()
    with ThreadPoolExecutor(max_workers=4) as executor:
        responses = list(
            executor.map(
                lambda _: session.request("https://public.example/"),
                range(4),
            )
        )

    assert [response.code for response in responses] == [429, 429, 429, 429]
    assert tracker["maximum"] == 1
