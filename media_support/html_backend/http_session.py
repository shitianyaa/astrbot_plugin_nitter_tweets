# -*- coding: utf-8 -*-
"""Shared cookie HTTP session (one opener style for all modes)."""

from __future__ import annotations

import http.cookiejar
import json
import ssl
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import (
    HTTPCookieProcessor,
    HTTPSHandler,
    ProxyHandler,
    Request,
    build_opener,
)

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
HTML_ACCEPT = (
    "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
)


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
        self.jar = http.cookiejar.CookieJar()
        handlers: list = [
            HTTPSHandler(context=ssl.create_default_context()),
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
            with self.opener.open(req, timeout=timeout or self.timeout) as resp:
                body = resp.read(5_000_000)
                code = int(getattr(resp, "status", None) or resp.getcode())
                return RawResponse(code, resp.geturl(), body, time.time() - t0)
        except HTTPError as exc:
            body = exc.read(1_000_000) if exc.fp else b""
            return RawResponse(
                int(exc.code),
                url,
                body,
                time.time() - t0,
                f"HTTPError {exc.code}",
            )
        except Exception as exc:  # noqa: BLE001
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
    ) -> None:
        cookie = http.cookiejar.Cookie(
            version=0,
            name=name,
            value=value,
            port=None,
            port_specified=False,
            domain=domain,
            domain_specified=True,
            domain_initial_dot=domain.startswith("."),
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
        host = host.lower()
        cookies = {
            c.name: {"value": c.value, "domain": c.domain, "path": c.path}
            for c in self.jar
            if host in (c.domain or "").lstrip(".").lower()
            or (c.domain or "").lstrip(".").lower() in host
        }
        if not cookies:
            cookies = {
                c.name: {"value": c.value, "domain": c.domain, "path": c.path}
                for c in self.jar
            }
        path = self.session_dir / f"{host}.json"
        path.write_text(
            json.dumps({"host": host, "cookies": cookies, "ts": time.time()}, indent=2),
            encoding="utf-8",
        )

    def load_cookies(self, host: str) -> bool:
        if not self.session_dir:
            return False
        path = self.session_dir / f"{host}.json"
        if not path.is_file():
            return False
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return False
        cookies = data.get("cookies") or {}
        if not cookies:
            return False
        for name, meta in cookies.items():
            if isinstance(meta, str):
                domain, value, cpath = host, meta, "/"
            else:
                domain = meta.get("domain") or host
                value = meta.get("value") or ""
                cpath = meta.get("path") or "/"
            self.set_cookie(name, value, domain, path=cpath)
        self.log(f"session load {host} keys={list(cookies)}")
        return True

    @staticmethod
    def host_of(url: str) -> str:
        return (urlparse(url).hostname or "").lower()
