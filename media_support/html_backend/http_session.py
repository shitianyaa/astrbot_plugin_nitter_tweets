"""Shared cookie HTTP session (one opener style for all modes)."""

from __future__ import annotations

import hashlib
import http.cookiejar
import ipaddress
import json
import re
import ssl
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import (
    HTTPCookieProcessor,
    ProxyHandler,
    Request,
    build_opener,
)

try:
    from ..network import (
        SafeHTTPHandler,
        SafeHTTPSHandler,
        SafeRedirectHandler,
        validate_http_url,
    )
except ImportError:  # pragma: no cover
    from media_support.network import (
        SafeHTTPHandler,
        SafeHTTPSHandler,
        SafeRedirectHandler,
        validate_http_url,
    )

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
HTML_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
_SAFE_COOKIE_HOST_RE = re.compile(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\Z")
_WINDOWS_RESERVED_BASENAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


def _normalize_cookie_host(host: str) -> str:
    text = str(host or "").strip().lower().rstrip(".")
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    if not text:
        raise ValueError("empty cookie host")
    try:
        return ipaddress.ip_address(text).compressed.lower()
    except ValueError:
        pass
    try:
        return text.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise ValueError("invalid cookie host") from exc


def _cookie_file_name(host: str) -> str:
    """Return a deterministic Windows-safe filename for a normalized host."""

    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if isinstance(address, ipaddress.IPv6Address):
        return f"ipv6-{address.compressed.replace(':', '_')}.json"
    first_label = host.split(".", 1)[0].upper()
    if (
        _SAFE_COOKIE_HOST_RE.fullmatch(host)
        and first_label not in _WINDOWS_RESERVED_BASENAMES
        and len(host) + len(".json") <= 255
    ):
        # Preserve the historical ``<host>.json`` path for ordinary hosts.
        return f"{host}.json"
    digest = hashlib.sha256(host.encode("utf-8")).hexdigest()[:24]
    return f"host-{digest}.json"


def _cookie_domain_matches_host(
    domain: str,
    host: str,
    *,
    host_only: bool,
) -> bool:
    domain_text = str(domain or "").strip().lower().lstrip(".").rstrip(".")
    if not domain_text:
        return False
    try:
        domain_text = _normalize_cookie_host(domain_text)
    except ValueError:
        return False
    if host_only:
        return host == domain_text
    return host == domain_text or host.endswith("." + domain_text)


class _ExactHostCookiePolicy(http.cookiejar.DefaultCookiePolicy):
    """Apply RFC host-only semantics instead of CookieJar's legacy suffix match."""

    def return_ok_domain(self, cookie, request):
        if not cookie.domain_specified:
            try:
                request_domain = _normalize_cookie_host(
                    http.cookiejar.request_host(request)
                )
                cookie_domain = _normalize_cookie_host(cookie.domain)
            except ValueError:
                return False
            if request_domain != cookie_domain:
                return False
        return super().return_ok_domain(cookie, request)


@dataclass(slots=True)
class RawResponse:
    code: int
    url: str
    body: bytes
    elapsed: float
    error: str | None = None

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", "replace")


class HttpSession:
    def __init__(
        self,
        *,
        proxy: str | None = None,
        user_agent: str = DEFAULT_UA,
        timeout: float = 35.0,
        session_dir: Path | None = None,
        log: Callable[[str], None] | None = None,
    ):
        self.proxy = (proxy or "").strip() or None
        self.user_agent = user_agent
        self.timeout = timeout
        self.session_dir = Path(session_dir) if session_dir else None
        self.log = log or (lambda _m: None)
        self.jar = http.cookiejar.CookieJar(policy=_ExactHostCookiePolicy())
        # CookieJar and the challenge/session sequence are shared by the RSS
        # and search pools.  Keep the whole request/read operation serialized;
        # a timestamp-only rate limiter cannot prevent overlapping requests
        # when a response takes longer than the configured interval.
        self.serial_lock = threading.RLock()
        self._request_lock = self.serial_lock  # compatibility for callers/tests
        handlers: list = [
            # SOCKS/HTTP proxies may resolve .onion or private self-hosted
            # names remotely; without a proxy, resolve every hop locally.
            SafeRedirectHandler(resolve_dns=not bool(self.proxy)),
            SafeHTTPHandler(check_peer=not bool(self.proxy)),
            SafeHTTPSHandler(
                context=ssl.create_default_context(),
                check_peer=not bool(self.proxy),
            ),
            HTTPCookieProcessor(self.jar),
        ]
        if self.proxy:
            handlers.insert(0, ProxyHandler({"http": self.proxy, "https": self.proxy}))
        self.opener = build_opener(*handlers)

    def request(
        self,
        url: str,
        *,
        accept: str = HTML_ACCEPT,
        referer: str | None = None,
        timeout: float | None = None,
    ) -> RawResponse:
        try:
            validate_http_url(url, resolve_dns=not bool(self.proxy))
        except Exception as exc:
            return RawResponse(-1, url, b"", 0.0, f"{type(exc).__name__}: {exc}")
        headers = {
            "User-Agent": self.user_agent,
            "Accept": accept,
            "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8",
        }
        if referer:
            headers["Referer"] = referer
        req = Request(url, headers=headers)
        t0 = time.time()
        try:
            with self.serial_lock:
                try:
                    with self.opener.open(
                        req,
                        timeout=timeout or self.timeout,
                    ) as resp:
                        body = resp.read(5_000_000)
                        get_url = getattr(resp, "geturl", None)
                        final_url = get_url() if callable(get_url) else url
                        validate_http_url(
                            final_url,
                            resolve_dns=not bool(self.proxy),
                        )
                        code = int(getattr(resp, "status", None) or resp.getcode())
                        return RawResponse(
                            code,
                            final_url,
                            body,
                            time.time() - t0,
                        )
                except HTTPError as exc:
                    try:
                        body = exc.read(1_000_000) if exc.fp else b""
                    finally:
                        exc.close()
                    return RawResponse(
                        int(exc.code),
                        url,
                        body,
                        time.time() - t0,
                        f"HTTPError {exc.code}",
                    )
        except Exception as exc:
            return RawResponse(
                -1, url, b"", time.time() - t0, f"{type(exc).__name__}: {exc}"
            )

    def set_cookie(
        self,
        name: str,
        value: str,
        domain: str,
        *,
        path: str = "/",
        secure: bool = True,
        host_only: bool = False,
    ) -> None:
        raw_domain = str(domain or "").strip().lower().rstrip(".")
        domain_initial_dot = raw_domain.startswith(".") and not host_only
        normalized_domain = _normalize_cookie_host(raw_domain.lstrip("."))
        cookie_domain = normalized_domain
        if domain_initial_dot:
            cookie_domain = "." + normalized_domain
        cookie = http.cookiejar.Cookie(
            version=0,
            name=name,
            value=value,
            port=None,
            port_specified=False,
            domain=cookie_domain,
            domain_specified=not host_only,
            domain_initial_dot=domain_initial_dot,
            path=path,
            path_specified=True,
            secure=secure,
            expires=None,
            discard=False,
            comment=None,
            comment_url=None,
            rest={},
            rfc2109=False,
        )
        self.jar.set_cookie(cookie)

    def save_cookies(self, host: str) -> None:
        if not self.session_dir:
            return
        self.session_dir.mkdir(parents=True, exist_ok=True)
        try:
            host = _normalize_cookie_host(host)
        except ValueError:
            return
        cookies = {
            c.name: {
                "value": c.value,
                "domain": c.domain,
                "path": c.path,
                "secure": c.secure,
                "host_only": not c.domain_specified,
            }
            for c in self.jar
            if _cookie_domain_matches_host(
                c.domain,
                host,
                host_only=not c.domain_specified,
            )
        }
        path = self.session_dir / _cookie_file_name(host)
        path.write_text(
            json.dumps({"host": host, "cookies": cookies, "ts": time.time()}, indent=2),
            encoding="utf-8",
        )

    def load_cookies(self, host: str) -> bool:
        if not self.session_dir:
            return False
        try:
            host = _normalize_cookie_host(host)
        except ValueError:
            return False
        path = self.session_dir / _cookie_file_name(host)
        if not path.is_file():
            return False
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return False
        stored_host = data.get("host")
        if stored_host:
            try:
                if _normalize_cookie_host(stored_host) != host:
                    return False
            except ValueError:
                return False
        cookies = data.get("cookies") or {}
        if not isinstance(cookies, dict) or not cookies:
            return False
        loaded_names: list[str] = []
        for name, meta in cookies.items():
            if isinstance(meta, str):
                domain, value, cpath = host, meta, "/"
                secure = True
                host_only = True
            elif isinstance(meta, dict):
                domain = str(meta.get("domain") or host)
                value = str(meta.get("value") or "")
                cpath = str(meta.get("path") or "/")
                secure = bool(meta.get("secure", True))
                host_only = bool(meta.get("host_only", False))
            else:
                continue
            # Older Poast session files persisted ``res`` for ``.poast.org``.
            # Narrow it while loading so a legacy file cannot recreate the
            # cross-host cookie scope removed by the current solver.
            if name == "res":
                domain = host
                host_only = True
            if not _cookie_domain_matches_host(
                domain,
                host,
                host_only=host_only,
            ):
                continue
            self.set_cookie(
                str(name),
                value,
                domain,
                path=cpath,
                secure=secure,
                host_only=host_only,
            )
            loaded_names.append(str(name))
        if not loaded_names:
            return False
        self.log(f"session load {host} keys={loaded_names}")
        return True

    @staticmethod
    def host_of(url: str) -> str:
        return (urlparse(url).hostname or "").lower()
