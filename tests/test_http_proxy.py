"""Fetch proxy configuration and local wire-level regression tests."""

import socket
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from urllib.error import URLError

import pytest

from config import fetch_proxy_url
from media_support import service as media_module
from media_support.fxtwitter_client import FxTwitterClient
from media_support.network import (
    HttpProxyConfigError,
    _proxy_authority,
    safe_urlopen,
)
from media_support.nitter import NitterService
from media_support.status_link import StatusLink
from media_support.status_resolve import StatusResolveError, resolve_status_tweet
from shared import TweetItem, TweetMedia

PROXY_URL = "http://proxy.example:3128"


@pytest.mark.parametrize(
    ("scope", "selected"),
    [
        ("off", set()),
        ("all", {"api", "nitter", "media"}),
        ("api", {"api"}),
        ("nitter", {"nitter"}),
    ],
)
def test_fetch_proxy_scope_connects_clients(monkeypatch, tmp_path, scope, selected):
    config = {"basic": {"http_proxy_scope": scope, "http_proxy_url": PROXY_URL}}
    monkeypatch.setattr(media_module, "_plugin_data_dir", lambda: tmp_path)
    nitter = NitterService(config)
    media = media_module.MediaService(config)
    expected = {
        family: PROXY_URL if family in selected else None
        for family in ("api", "nitter", "media")
    }

    assert nitter.proxy_url == nitter.html.session.proxy == expected["nitter"]
    assert nitter.fxtwitter.proxy_url == media.api_proxy_url == expected["api"]
    assert media.media_proxy_url == expected["media"]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("http://proxy.local", "proxy.local:80"),
        (" http://proxy.local:8080/ ", "proxy.local:8080"),
        ("http://[::1]", "[::1]:80"),
        ("https://proxy.local", None),
        ("socks5://proxy.local:1080", None),
        ("http://name:password@proxy.local", None),
        ("http://proxy.local/path", None),
        ("http://proxy.local?query", None),
        ("http://proxy.local#fragment", None),
        ("http://[::1]extra", None),
        ("http://proxy.local:", None),
        ("http://proxy.local:0", None),
        ("", None),
    ],
)
def test_proxy_url_requires_http_authority(value, expected):
    assert _proxy_authority(value) == expected


def test_missing_setting_retains_ambient_proxy_and_invalid_scope_fails():
    assert fetch_proxy_url({}, "api") is None
    assert fetch_proxy_url({"basic": {"http_proxy_scope": "typo"}}, "api") == ""
    config = {"basic": {"http_proxy_scope": "nitter"}}
    nitter = NitterService(config)
    response = nitter.html.session.request("http://127.0.0.1:1/")
    assert response.code == -1
    assert "HTTP 代理配置无效" in response.error
    with pytest.raises(HttpProxyConfigError) as error:
        safe_urlopen("http://127.0.0.1:1/", 1, proxy_url="http://u:secret@proxy")
    assert "secret" not in str(error.value)


def test_media_enrichment_uses_api_proxy_in_api_only_mode(monkeypatch, tmp_path):
    monkeypatch.setattr(media_module, "_plugin_data_dir", lambda: tmp_path)
    media = media_module.MediaService(
        {"basic": {"http_proxy_scope": "api", "http_proxy_url": PROXY_URL}}
    )
    tweet = TweetItem(text="", link="https://x.com/u/status/1", published="")
    calls = []

    def resolve(link, *, timeout, media_quality, proxy_url):
        calls.append((link.status_id, proxy_url))
        return tweet

    monkeypatch.setattr(media_module, "resolve_status_tweet", resolve)
    assert media._resolve_candidates_from_status(tweet) == []
    assert calls == [("1", PROXY_URL)]
    assert media.media_proxy_url is None


@contextmanager
def _serve(handler):
    with ThreadingHTTPServer(("127.0.0.1", 0), handler) as server:
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}"
        finally:
            server.shutdown()
            worker.join()


class _LocalHandler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def reply(self, body: bytes, *, status: int = 200, **headers):
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        for key, value in headers.items():
            self.send_header(key.replace("_", "-"), value)
        self.end_headers()
        self.wfile.write(body)


def test_proxy_route_survives_no_proxy_redirect_and_connect_rejection(monkeypatch):
    direct_hits = []
    proxy_hits = []
    create_connection = socket.create_connection

    def connect_only_to_loopback(address, *args, **kwargs):
        assert address[0] == "127.0.0.1"
        return create_connection(address, *args, **kwargs)

    class Origin(_LocalHandler):
        def do_GET(self):
            direct_hits.append(self.path)
            self.reply(b"direct")

    class Proxy(_LocalHandler):
        def do_GET(self):
            proxy_hits.append(self.path)
            if self.path.endswith("/redirect"):
                self.reply(b"", status=302, Location=f"{origin}/page")
            elif self.path.endswith("/rss"):
                self.reply(b"<rss><channel /></rss>")
            else:
                self.reply(b"proxy")

        def do_CONNECT(self):
            proxy_hits.append(f"CONNECT {self.path}")
            self.reply(b"", status=407)

    monkeypatch.setenv("no_proxy", "127.0.0.1")
    monkeypatch.setattr(socket, "create_connection", connect_only_to_loopback)
    with _serve(Origin) as origin, _serve(Proxy) as proxy:
        nitter = NitterService(
            {"basic": {"http_proxy_scope": "nitter", "http_proxy_url": proxy}}
        )
        with safe_urlopen(f"{origin}/direct", 3) as response:
            assert response.read() == b"direct"
        assert nitter.html.session.request(f"{origin}/redirect").body == b"proxy"
        nitter._fetch_page_from_instance(origin, "nasa", "", 1)
        with pytest.raises(URLError, match="407"):
            safe_urlopen(origin.replace("http:", "https:"), 3, proxy_url=proxy)
        with pytest.raises(StatusResolveError):
            resolve_status_tweet(
                StatusLink("u", "1", "https://x.com/u/status/1"),
                timeout=3,
                proxy_url=proxy,
            )

    assert direct_hits == ["/direct"]
    assert proxy_hits == [
        f"{origin}/redirect",
        f"{origin}/page",
        f"{origin}/nasa/rss",
        f"CONNECT {origin.removeprefix('http://')}",
        "CONNECT api.fxtwitter.com:443",
        "CONNECT api.vxtwitter.com:443",
        "CONNECT cdn.syndication.twimg.com:443",
    ]


def test_all_scope_proxies_api_xdown_range_and_download(monkeypatch, tmp_path):
    requests = []

    class Proxy(_LocalHandler):
        def do_GET(self):
            requests.append(("GET", self.path, self.headers.get("Range")))
            if self.headers.get("Range"):
                self.reply(b"x", status=206, Content_Range="bytes 0-0/3")
            elif self.path.endswith("/fx"):
                self.reply(b'{"code": 200}')
            else:
                self.reply(b"img")

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            requests.append(("POST", self.path, self.headers.get("Content-Type")))
            self.reply(b'{"status": "empty"}')

    monkeypatch.setenv("no_proxy", "*")
    monkeypatch.setattr(media_module, "_plugin_data_dir", lambda: tmp_path)
    origin = "http://127.0.0.1:1"
    with _serve(Proxy) as proxy:
        config = {"basic": {"http_proxy_scope": "all", "http_proxy_url": proxy}}
        fx = FxTwitterClient(proxy_url=fetch_proxy_url(config, "api"))
        media = media_module.MediaService(config)
        media.xdown_url = f"{origin}/xdown"
        tweet = TweetItem(text="", link="https://x.com/u/status/1", published="")
        media_url = f"{origin}/pic/img.jpg"

        assert fx._fetch_json(f"{origin}/fx") == {"code": 200}
        assert media._resolve_candidates_from_xdown(tweet) == []
        assert (
            media._probe_remote_media(media_url, need_duration=False)["size_bytes"] == 3
        )
        assert (
            media._download(TweetMedia(kind="image", url=media_url)).read_bytes()
            == b"img"
        )

    assert requests == [
        ("GET", f"{origin}/fx", None),
        ("POST", f"{origin}/xdown", "application/x-www-form-urlencoded"),
        ("GET", media_url, "bytes=0-0"),
        ("GET", media_url, None),
    ]
