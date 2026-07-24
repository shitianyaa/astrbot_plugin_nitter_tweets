# -*- coding: utf-8 -*-
"""Auth modes: plain / anubis / poast_sha1 / auto.

Only the gate differs; page fetch + parse stay shared.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Callable
from urllib.parse import urlencode

from .http_session import HTML_ACCEPT, HttpSession, RawResponse

# Built-in host → mode (locked plan defaults)
BUILTIN_MODES: dict[str, str] = {
    "nitter.tiekoetter.com": "anubis",
    "nitter.poast.org": "poast_sha1",
    "nitter.kareem.one": "plain",
    "nitter.catsarch.com": "anubis",
    "nitter.net": "plain",  # HTML usually empty; still plain if tried
}


def resolve_mode(host: str, override: str | None = None) -> str:
    if override and override != "auto":
        return override
    host = host.lower()
    if host in BUILTIN_MODES:
        return BUILTIN_MODES[host]
    for key, mode in BUILTIN_MODES.items():
        if key in host:
            return mode
    return "auto"


def detect_gate(body: bytes) -> str:
    """Return anubis | poast_sha1 | cf | ok | empty | other."""
    if not body:
        return "empty"
    low = body.lower()
    if b"anubis_challenge" in low or b"making sure you're not a bot" in low:
        return "anubis"
    if b"verifying your browser" in low and (b"s1" in low or b"sha1" in low):
        return "poast_sha1"
    if b"just a moment" in low or b"challenge-platform" in low or b"cf-turnstile" in low:
        return "cf"
    if b"timeline-item" in low or b"<rss" in low or b"nitter" in low:
        return "ok"
    return "other"


def _json_id(html: str, element_id: str):
    m = re.search(
        rf'<script id="{re.escape(element_id)}" type="application/json">(.*?)</script>',
        html,
        re.S,
    )
    return json.loads(m.group(1)) if m else None


def solve_anubis_pow(
    random_data: str, difficulty: int, max_iters: int = 2_000_000
) -> tuple[str, int]:
    zb = difficulty // 2
    odd = difficulty % 2 != 0
    n = 0
    while n < max_iters:
        d = hashlib.sha256(f"{random_data}{n}".encode()).digest()
        if all(d[i] == 0 for i in range(zb)) and (not odd or (d[zb] >> 4) == 0):
            return d.hex(), n
        n += 1
    raise RuntimeError(
        f"anubis pow not found within {max_iters} iters (difficulty={difficulty})"
    )


def solve_poast_pow(challenge: str, max_iters: int = 5_000_000) -> str:
    n1 = int(challenge[0], 16)
    for i in range(max_iters):
        digest = hashlib.sha1(f"{challenge}{i}".encode()).digest()
        if n1 + 1 < len(digest) and digest[n1] == 0xB0 and digest[n1 + 1] == 0x0B:
            return f"{challenge}{i}"
    raise RuntimeError("poast pow not found")


def extract_poast_challenge(html: str) -> str | None:
    m = re.search(r"const\s+a0_0x2a54\s*=\s*\[([^\]]+)\]", html)
    if m:
        parts = re.findall(r"'([^']*)'", m.group(1))
        for p in parts:
            if re.fullmatch(r"[0-9A-Fa-f]{40}", p):
                return p
    m2 = re.search(r"'([0-9A-Fa-f]{40})'", html)
    return m2.group(1) if m2 else None


class GateKeeper:
    """Pass host-specific gates using a shared HttpSession."""

    def __init__(
        self,
        session: HttpSession,
        *,
        log: Callable[[str], None] | None = None,
    ):
        self.session = session
        self.log = log or (lambda _m: None)
        self._mode_cache: dict[str, str] = {}

    def mode_for(self, base: str) -> str:
        host = self.session.host_of(base)
        if host in self._mode_cache:
            return self._mode_cache[host]
        mode = resolve_mode(host)
        self._mode_cache[host] = mode
        return mode

    def ensure(self, base: str, seed_path: str = "/NASA") -> bool:
        base = base.rstrip("/")
        host = self.session.host_of(base)
        self.session.load_cookies(host)
        mode = self.mode_for(base)
        url = f"{base}{seed_path}"
        resp = self.session.request(url)
        gate = detect_gate(resp.body)
        # QuietHtmlLog drops repeated gate-ok; still emit once for diagnostics.
        self.log(f"gate {host} mode={mode} http={resp.code} detect={gate}")

        if gate == "ok" and resp.code == 200:
            self._mode_cache[host] = "plain" if mode == "auto" else mode
            self.session.save_cookies(host)
            return True
        if gate == "cf":
            self.log(f"gate {host}: cloudflare unsupported")
            return False
        if gate == "empty" and resp.code == 200:
            # nitter.net style empty — not auth, just empty capability
            return True

        if mode == "auto":
            if gate == "anubis":
                mode = "anubis"
            elif gate == "poast_sha1":
                mode = "poast_sha1"
            elif gate == "ok":
                mode = "plain"
            else:
                mode = "plain"
            self._mode_cache[host] = mode

        if mode == "plain":
            # maybe soft rate limit page
            return resp.code == 200 and gate in {"ok", "other", "empty"}

        if mode == "anubis" or gate == "anubis":
            ok = self._pass_anubis(base, resp)
            if ok:
                self._mode_cache[host] = "anubis"
                self.session.save_cookies(host)
            return ok

        if mode == "poast_sha1" or gate == "poast_sha1":
            ok = self._pass_poast(base, resp)
            if ok:
                self._mode_cache[host] = "poast_sha1"
                self.session.save_cookies(host)
            return ok

        return False

    def _pass_anubis(self, base: str, challenge_resp: RawResponse) -> bool:
        if detect_gate(challenge_resp.body) != "anubis":
            # already past?
            probe = self.session.request(f"{base}/NASA")
            return detect_gate(probe.body) == "ok" and probe.code == 200
        html = challenge_resp.text
        payload = _json_id(html, "anubis_challenge")
        if not payload:
            self.log("anubis: no challenge json")
            return False
        ch = payload["challenge"]
        rules = payload["rules"]
        diff = int(rules.get("difficulty", ch.get("difficulty", 1)))
        hx, nonce = solve_anubis_pow(ch["randomData"], diff)
        base_prefix = _json_id(html, "anubis_base_prefix") or ""
        params = {
            "id": ch["id"],
            "response": hx,
            "nonce": str(nonce),
            "redir": challenge_resp.url or f"{base}/NASA",
            "elapsedTime": "10",
        }
        pass_url = (
            f"{base}{base_prefix}/.within.website/x/cmd/anubis/api/pass-challenge?"
            f"{urlencode(params)}"
        )
        self.log(f"anubis: solved difficulty={diff} nonce={nonce}")
        passed = self.session.request(
            pass_url, accept=HTML_ACCEPT, referer=challenge_resp.url
        )
        return detect_gate(passed.body) != "anubis" and passed.code in {200, 302}

    def _pass_poast(self, base: str, challenge_resp: RawResponse) -> bool:
        body = challenge_resp.body
        if detect_gate(body) != "poast_sha1":
            probe = self.session.request(f"{base}/")
            body = probe.body
            if detect_gate(body) != "poast_sha1":
                return detect_gate(body) == "ok"
        html = body.decode("utf-8", "replace")
        challenge = extract_poast_challenge(html)
        if not challenge:
            self.log("poast: no challenge hex")
            return False
        token = solve_poast_pow(challenge)
        host = self.session.host_of(base)
        self.session.set_cookie("res", token, host)
        self.session.set_cookie("res", token, "." + host.split(".", 1)[-1] if host.count(".") else host)
        # also nitter.poast.org explicit
        self.session.set_cookie("res", token, "nitter.poast.org")
        self.session.set_cookie("res", token, ".poast.org")
        self.log(f"poast: solved token_len={len(token)}")
        time_sleep_soft()
        passed = self.session.request(f"{base}/")
        if detect_gate(passed.body) == "poast_sha1":
            passed = self.session.request(f"{base}/NASA")
        return detect_gate(passed.body) != "poast_sha1" and passed.code == 200


def time_sleep_soft() -> None:
    import time

    time.sleep(1.0)
