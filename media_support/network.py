"""HTTP helpers shared by RSS, HTML and media fetchers.

The plugin consumes URLs returned by remote mirrors.  Keep the policy in one
place so a newly added downloader cannot accidentally re-introduce an SSRF
sink.  We intentionally allow arbitrary *public* HTTP(S) hosts rather than a
small CDN allow-list; self-hosted Nitter mirrors commonly use their own media
domains.
"""

from __future__ import annotations

import http.client
import ipaddress
import re
import socket
from urllib.parse import urlsplit
from urllib.request import (
    HTTPHandler,
    HTTPRedirectHandler,
    HTTPSHandler,
    Request,
    build_opener,
)


BUILTIN_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
BUILTIN_ACCEPT_LANGUAGE = "en-US,en;q=0.9,zh-CN;q=0.8"


def build_request_headers(
    *,
    accept: str | None = None,
    referer: str | None = None,
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build a fresh header mapping with the plugin's fixed browser identity."""
    headers = dict(extra or {})
    headers["User-Agent"] = BUILTIN_USER_AGENT
    headers["Accept-Language"] = BUILTIN_ACCEPT_LANGUAGE
    if accept:
        headers["Accept"] = accept
    if referer:
        headers["Referer"] = referer
    return headers


class UnsafeUrlError(ValueError):
    """Raised when a remote URL is not safe for server-side fetching."""


_CONTROL_OR_SPACE_RE = re.compile(r"[\x00-\x20\x7f\\]")
_PRIVATE_HOST_SUFFIXES = (
    ".localhost",
    ".localdomain",
    ".local",
    ".internal",
    ".lan",
    ".home",
    ".home.arpa",
    ".corp",
)
_PRIVATE_HOSTNAMES = {
    "localhost",
    "localhost.localdomain",
    "ip6-localhost",
    "ip6-loopback",
}


def _is_public_address(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return True
    # ``is_global`` excludes loopback, RFC1918, link-local, multicast,
    # unspecified and other special-use ranges in the stdlib ipaddress table.
    return bool(address.is_global)


def _is_legacy_ipv4_literal(host: str) -> bool:
    """Detect inet_aton forms that bypass strict ipaddress parsing."""
    if not host or ":" in host:
        return False
    try:
        socket.inet_aton(host)
    except OSError:
        return False
    try:
        ipaddress.IPv4Address(host)
    except ipaddress.AddressValueError:
        return True
    return False


def _resolved_addresses(host: str, port: int) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise UnsafeUrlError(f"unable to resolve host: {host}") from exc
    addresses: list[str] = []
    for info in infos:
        sockaddr = info[4]
        if not sockaddr:
            continue
        value = str(sockaddr[0])
        if value not in addresses:
            addresses.append(value)
    if not addresses:
        raise UnsafeUrlError(f"host has no address: {host}")
    return addresses


def validate_http_url(
    url: str,
    *,
    resolve_dns: bool = True,
) -> str:
    """Validate an HTTP(S) URL and return the original normalized string.

    ``resolve_dns=False`` is useful while parsing HTML, where resolving every
    image URL would add latency.  The actual opener always performs the strict
    resolution check before connecting and repeats it for every redirect.
    """

    text = str(url or "").strip()
    if not text:
        raise UnsafeUrlError("empty URL")
    if _CONTROL_OR_SPACE_RE.search(text):
        raise UnsafeUrlError("URL contains whitespace or backslash")
    try:
        parsed = urlsplit(text)
        scheme = parsed.scheme.lower()
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise UnsafeUrlError("malformed URL") from exc
    if scheme not in {"http", "https"}:
        raise UnsafeUrlError("only http/https URLs are allowed")
    if not hostname:
        raise UnsafeUrlError("URL has no host")
    if parsed.username is not None or parsed.password is not None:
        raise UnsafeUrlError("URL userinfo is not allowed")
    host = hostname.rstrip(".").lower()
    try:
        # Normalize IDN labels before the literal/private-host checks and DNS
        # lookup.  Keep the original URL untouched for callers and logging.
        host = host.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise UnsafeUrlError("invalid URL host") from exc
    # Reject names which are conventionally only resolvable on a local
    # network even when DNS resolution is intentionally deferred by a parser
    # or configuration screen.  The fetch path still resolves every public
    # hostname immediately before opening the socket.
    if host in _PRIVATE_HOSTNAMES or host.endswith(_PRIVATE_HOST_SUFFIXES):
        raise UnsafeUrlError("local URL host is not allowed")
    if not host or _CONTROL_OR_SPACE_RE.search(host):
        raise UnsafeUrlError("invalid URL host")
    if _is_legacy_ipv4_literal(host):
        raise UnsafeUrlError("non-canonical IPv4 URL host is not allowed")
    # A missing port means the scheme default.  Explicit port zero is not a
    # useful public endpoint and is frequently used in SSRF probes.
    effective_port = port
    if effective_port is None:
        effective_port = 443 if scheme == "https" else 80
    if effective_port <= 0 or effective_port > 65535:
        raise UnsafeUrlError("invalid URL port")
    if not _is_public_address(host):
        raise UnsafeUrlError("private or special-use URL host is not allowed")
    if resolve_dns and not _is_ip_literal(host):
        addresses = _resolved_addresses(host, effective_port)
        if any(not _is_public_address(address) for address in addresses):
            raise UnsafeUrlError(
                "URL host resolves to a private or special-use address"
            )
    return text


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def is_safe_http_url(url: str, *, resolve_dns: bool = False) -> bool:
    """Boolean convenience wrapper used by parsers and config validation."""

    try:
        validate_http_url(url, resolve_dns=resolve_dns)
    except UnsafeUrlError:
        return False
    return True


class SafeRedirectHandler(HTTPRedirectHandler):
    """Reject unsafe redirect targets before urllib opens the next hop."""

    # urllib ships a default redirect handler with order=500.  Give this
    # policy handler precedence so the default handler cannot open a redirect
    # before validation runs.
    handler_order = 499

    def __init__(self, *, resolve_dns: bool = True):
        super().__init__()
        self.resolve_dns = bool(resolve_dns)

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_http_url(newurl, resolve_dns=self.resolve_dns)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _response_peer_address(response) -> str | None:
    """Return the connected peer address exposed by an urllib response.

    ``HTTPHandler.do_open`` closes its connection object's socket reference
    before returning, but the live socket remains reachable through
    ``response.fp.raw._sock`` (and through an SSL wrapper for HTTPS).  Walk a
    small, cycle-safe object graph so this also works across Python versions
    and the common buffered-reader/socket wrappers.
    """

    pending = [getattr(response, "fp", None)]
    visited: set[int] = set()
    while pending:
        current = pending.pop()
        if current is None or id(current) in visited:
            continue
        visited.add(id(current))

        getpeername = getattr(current, "getpeername", None)
        if callable(getpeername):
            try:
                peer = getpeername()
            except OSError:
                peer = None
            if isinstance(peer, tuple) and peer:
                return str(peer[0])
            if isinstance(peer, str) and peer:
                return peer

        for attribute in ("raw", "_sock", "sock", "_sslobj"):
            nested = getattr(current, attribute, None)
            if nested is not None and id(nested) not in visited:
                pending.append(nested)
    return None


def _validate_connected_peer(response) -> None:
    """Reject a response whose actual socket peer is not publicly routable."""

    peer = _response_peer_address(response)
    if not peer or not _is_ip_literal(peer) or not _is_public_address(peer):
        close = getattr(response, "close", None)
        if callable(close):
            close()
        raise UnsafeUrlError("connected peer is private, special-use, or unavailable")


def _validate_socket_peer(sock) -> None:
    """Validate a connected socket before HTTP request bytes are sent."""
    try:
        peer = sock.getpeername() if sock is not None else None
    except OSError:
        peer = None
    address = str(peer[0]) if isinstance(peer, tuple) and peer else ""
    if not address or not _is_ip_literal(address) or not _is_public_address(address):
        close = getattr(sock, "close", None)
        if callable(close):
            close()
        raise UnsafeUrlError("connected peer is private, special-use, or unavailable")


def _request_uses_proxy(req) -> bool:
    """Detect whether urllib rewrote this request to a proxy endpoint."""

    if getattr(req, "_tunnel_host", None):
        return True
    has_proxy = getattr(req, "has_proxy", None)
    if callable(has_proxy) and has_proxy():
        return True
    selector = str(getattr(req, "selector", "") or "").lower()
    return selector.startswith(("http://", "https://"))


class _SafeHTTPConnection(http.client.HTTPConnection):
    def __init__(self, *args, check_peer: bool = True, **kwargs):
        self._check_peer = bool(check_peer)
        super().__init__(*args, **kwargs)

    def connect(self):
        super().connect()
        if self._check_peer and not getattr(self, "_tunnel_host", None):
            _validate_socket_peer(self.sock)


class _SafeHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, *args, check_peer: bool = True, **kwargs):
        self._check_peer = bool(check_peer)
        super().__init__(*args, **kwargs)

    def connect(self):
        super().connect()
        if self._check_peer and not getattr(self, "_tunnel_host", None):
            _validate_socket_peer(self.sock)


class _PeerCheckingHandler:
    """Mixin that validates direct peers before urllib sends request bytes."""

    def __init__(self, *args, check_peer: bool = True, **kwargs):
        self.check_peer = bool(check_peer)
        super().__init__(*args, **kwargs)

    def do_open(self, http_class, req, **http_conn_args):
        proxied = _request_uses_proxy(req)
        check_peer = self.check_peer and not proxied
        checked_before_request = False
        if http_class is http.client.HTTPConnection:
            http_class = _SafeHTTPConnection
            http_conn_args["check_peer"] = check_peer
            checked_before_request = check_peer
        elif http_class is http.client.HTTPSConnection:
            http_class = _SafeHTTPSConnection
            http_conn_args["check_peer"] = check_peer
            checked_before_request = check_peer
        response = super().do_open(http_class, req, **http_conn_args)
        # A proxy socket identifies the proxy, not the origin.  URL and
        # redirect validation still run, but local peer classification would
        # either reject a legitimate private proxy or create a false sense of
        # validating the remote origin.
        # The stdlib handlers use the exact connection classes above, so the
        # normal path has already checked the live socket before ``request()``
        # can write HTTP bytes.  Retain the response inspection only as a
        # fallback for a custom handler/connection class that could not be
        # wrapped; re-checking a normal response can falsely fail after a
        # server closes its socket immediately after sending the response.
        if check_peer and not checked_before_request:
            _validate_connected_peer(response)
        return response


class SafeHTTPHandler(_PeerCheckingHandler, HTTPHandler):
    """HTTP opener handler with pre-request SSRF peer validation."""


class SafeHTTPSHandler(_PeerCheckingHandler, HTTPSHandler):
    """HTTPS opener handler with pre-request SSRF peer validation."""


def _safe_opener(*, resolve_dns: bool = True):
    return build_opener(
        SafeHTTPHandler(check_peer=True),
        SafeHTTPSHandler(check_peer=True),
        SafeRedirectHandler(resolve_dns=resolve_dns),
    )


def safe_urlopen(
    request: Request | str,
    timeout: float,
    *,
    resolve_dns: bool = True,
):
    """Open a public HTTP(S) URL with per-hop redirect validation."""

    if isinstance(request, Request):
        request.add_header("User-Agent", BUILTIN_USER_AGENT)
        request.add_header("Accept-Language", BUILTIN_ACCEPT_LANGUAGE)
    else:
        request = Request(str(getattr(request, "full_url", request)))
        for key, value in build_request_headers().items():
            request.add_header(key, value)

    target = (
        request.full_url
        if isinstance(request, Request)
        else str(getattr(request, "full_url", request))
    )
    validate_http_url(target, resolve_dns=resolve_dns)
    response = _safe_opener(resolve_dns=resolve_dns).open(request, timeout=timeout)
    # ``SafeRedirectHandler`` covers normal urllib redirects; checking the
    # final URL also protects custom handlers and test doubles.
    get_url = getattr(response, "geturl", None)
    final_url = get_url() if callable(get_url) else target
    try:
        validate_http_url(final_url, resolve_dns=resolve_dns)
    except Exception:
        close = getattr(response, "close", None)
        if callable(close):
            close()
        raise
    return response


def compat_urlopen(request, timeout):
    """Compatibility entry point retained for existing monkeypatches."""

    return safe_urlopen(request, timeout)
