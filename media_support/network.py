"""HTTP helpers shared by RSS, HTML and media fetchers.

Self-hosted Nitter deployments commonly use loopback, Docker service names or
private addresses. The plugin therefore validates URL syntax and protocol,
but leaves network trust to the administrator who configured the instance.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


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
    """Raised when a URL is malformed or uses an unsupported protocol."""


_CONTROL_OR_SPACE_RE = re.compile(r"[\x00-\x20\x7f\\]")


def validate_http_url(url: str) -> str:
    """Validate an HTTP(S) URL and return its stripped original value."""
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
    try:
        host = hostname.rstrip(".").encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise UnsafeUrlError("invalid URL host") from exc
    if not host or _CONTROL_OR_SPACE_RE.search(host):
        raise UnsafeUrlError("invalid URL host")
    effective_port = port if port is not None else (443 if scheme == "https" else 80)
    if effective_port <= 0 or effective_port > 65535:
        raise UnsafeUrlError("invalid URL port")
    return text


def is_safe_http_url(url: str) -> bool:
    """Boolean convenience wrapper used by parsers and config validation."""
    try:
        validate_http_url(url)
    except UnsafeUrlError:
        return False
    return True


class SafeRedirectHandler(HTTPRedirectHandler):
    """Validate every redirect target before urllib follows it."""

    handler_order = 499

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_http_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _safe_opener():
    return build_opener(SafeRedirectHandler())


def safe_urlopen(request: Request | str, timeout: float):
    """Open a syntactically valid HTTP(S) URL with redirect validation."""
    if not isinstance(request, Request):
        request = Request(str(getattr(request, "full_url", request)))
    for key, value in build_request_headers().items():
        request.add_header(key, value)

    target = validate_http_url(request.full_url)
    response = _safe_opener().open(request, timeout=timeout)
    get_url = getattr(response, "geturl", None)
    final_url = get_url() if callable(get_url) else target
    try:
        validate_http_url(final_url)
    except Exception:
        close = getattr(response, "close", None)
        if callable(close):
            close()
        raise
    return response


def compat_urlopen(request, timeout):
    """Compatibility entry point retained for existing monkeypatches."""
    return safe_urlopen(request, timeout)
