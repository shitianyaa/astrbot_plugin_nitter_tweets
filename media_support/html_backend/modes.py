"""Auth modes: plain / anubis / poast_sha1 / auto.

Only the gate differs; page fetch + parse stay shared.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from urllib.parse import urlencode

from .http_session import HTML_ACCEPT, HttpSession, RawResponse

# Built-in host → mode. Defaults shipped to users are net (RSS) + tiekoetter
# (HTML/search). Other keys remain so manually configured hosts still work.
BUILTIN_MODES: dict[str, str] = {
    "nitter.tiekoetter.com": "anubis",  # default search instance
    "nitter.net": "plain",  # RSS-oriented; HTML/search usually empty
    "nitter.poast.org": "poast_sha1",  # optional manual; not a shipped default
    "nitter.kareem.one": "auto",  # often CF now; auto/detect, not default
    "nitter.catsarch.com": "anubis",  # optional manual; search often closed
}

MAX_ANUBIS_DIFFICULTY = 32
MAX_ANUBIS_ITERATIONS = 2_000_000
MAX_ANUBIS_RANDOM_DATA_BYTES = 256
MAX_ANUBIS_CHALLENGE_ID_BYTES = 256
MAX_POAST_ITERATIONS = 5_000_000


def resolve_mode(host: str, override: str | None = None) -> str:
    override_text = str(override or "").strip().lower()
    if override_text and override_text != "auto":
        return override_text
    host = str(host or "").strip().lower().rstrip(".")
    if host in BUILTIN_MODES:
        return BUILTIN_MODES[host]
    for key, mode in BUILTIN_MODES.items():
        if host.endswith("." + key):
            return mode
    return "auto"


def detect_gate(body: bytes) -> str:
    """Return anubis | poast_sha1 | cf | ok | error | empty | other.

    Order matters: explicit Anubis/Poast challenge structures require solving,
    while real content wins over generic CDN footers and challenge wording.
    """
    if not body:
        return "empty"
    low = body.lower()

    # 1) Explicit challenge structures must not be bypassed by placeholder
    # timeline nodes included in a challenge/interstitial response.
    if (
        b'id="anubis_challenge"' in low
        or b"id='anubis_challenge'" in low
        or (
            b"making sure you're not a bot" in low
            and (b"anubis" in low or b"application/json" in low)
        )
    ):
        return "anubis"
    if (
        b"verifying your browser" in low
        and (b"s1" in low or b"sha1" in low or b"a0_0x2a54" in low or b"res=" in low)
    ) or (b"js-sha1" in low and b"res=" in low):
        return "poast_sha1"

    # 2) Real content wins over generic CDN markers and ordinary tweet text.
    if (
        b"timeline-item" in low
        or b"<rss" in low
        or b"tweet-body" in low
        or b"tweet-content" in low
    ):
        return "ok"

    # 3) Hard Cloudflare interstitial only when no real content exists.
    if (
        b"just a moment" in low
        or b"cf-turnstile" in low
        or b"cdn-cgi/challenge-platform/h/" in low
        or (
            b"challenge-platform" in low
            and b"nitter" not in low[:4000]
            and b"site-name" not in low
        )
    ):
        return "cf"

    title_match = re.search(rb"<title[^>]*>(.*?)</title>", low, re.DOTALL)
    title = title_match.group(1) if title_match else b""
    error_markers = (
        b'class="error-panel',
        b"class='error-panel",
        b'id="error-page',
        b"this site is under maintenance",
        b"temporarily unavailable",
        b"service unavailable",
        b"access denied",
        b"authentication required",
        b"unauthorized",
        b"maintenance mode",
        b"page not found",
        b"you must be logged in",
        b"please log in",
        b"sign in to continue",
    )
    title_error = any(
        marker in title
        for marker in (
            b"login",
            b"log in",
            b"sign in",
            b"maintenance",
            b"error",
            b"not found",
            b"unavailable",
        )
    )
    body_error = any(marker in low for marker in error_markers)
    if title_error or body_error:
        return "error"
    if b"nitter" in low:
        return "ok"
    return "other"


def _json_id(html: str, element_id: str):
    m = re.search(
        rf'<script id="{re.escape(element_id)}" type="application/json">(.*?)</script>',
        html,
        re.DOTALL,
    )
    return json.loads(m.group(1)) if m else None


def _bounded_anubis_text(value: object, *, field: str, max_bytes: int) -> str:
    """Validate remote Anubis fields before they enter the PoW hot loop."""

    if not isinstance(value, str) or not value:
        raise ValueError(f"invalid anubis {field}")
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError(f"invalid anubis {field}") from exc
    if len(encoded) > max_bytes:
        raise ValueError(f"anubis {field} is too long")
    return value


def solve_anubis_pow(
    random_data: str,
    difficulty: int,
    max_iters: int = MAX_ANUBIS_ITERATIONS,
) -> tuple[str, int]:
    random_data = _bounded_anubis_text(
        random_data,
        field="random data",
        max_bytes=MAX_ANUBIS_RANDOM_DATA_BYTES,
    )
    try:
        difficulty = int(difficulty)
        requested_iters = int(max_iters)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid anubis pow parameters") from exc
    if difficulty < 0 or difficulty > MAX_ANUBIS_DIFFICULTY:
        raise ValueError(f"anubis difficulty out of range (0..{MAX_ANUBIS_DIFFICULTY})")
    budget = min(MAX_ANUBIS_ITERATIONS, requested_iters)
    if budget <= 0:
        raise ValueError("anubis pow iteration budget must be positive")
    zb = difficulty // 2
    odd = difficulty % 2 != 0
    n = 0
    while n < budget:
        d = hashlib.sha256(f"{random_data}{n}".encode()).digest()
        if all(d[i] == 0 for i in range(zb)) and (not odd or (d[zb] >> 4) == 0):
            return d.hex(), n
        n += 1
    raise RuntimeError(
        f"anubis pow not found within {budget} iters (difficulty={difficulty})"
    )


def solve_poast_pow(challenge: str, max_iters: int = MAX_POAST_ITERATIONS) -> str:
    if not re.fullmatch(r"[0-9A-Fa-f]{40}", str(challenge or "")):
        raise ValueError("invalid poast pow challenge")
    try:
        budget = min(MAX_POAST_ITERATIONS, int(max_iters))
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid poast pow iteration budget") from exc
    if budget <= 0:
        raise ValueError("poast pow iteration budget must be positive")
    n1 = int(challenge[0], 16)
    if n1 + 1 >= 20:
        raise RuntimeError("poast pow challenge index is out of range")
    for i in range(budget):
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
        if gate == "error":
            self.log(f"gate {host}: login/maintenance/error page")
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
            return resp.code == 200 and gate in {"ok", "empty"}

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
        try:
            payload = _json_id(html, "anubis_challenge")
        except (TypeError, ValueError, json.JSONDecodeError):
            payload = None
        if not isinstance(payload, dict):
            self.log("anubis: no challenge json")
            return False
        ch = payload.get("challenge")
        rules = payload.get("rules") or {}
        if not isinstance(ch, dict) or not isinstance(rules, dict):
            self.log("anubis: invalid challenge json")
            return False
        try:
            diff = int(rules.get("difficulty", ch.get("difficulty", 1)))
            random_data = _bounded_anubis_text(
                ch["randomData"],
                field="random data",
                max_bytes=MAX_ANUBIS_RANDOM_DATA_BYTES,
            )
            challenge_id = _bounded_anubis_text(
                ch["id"],
                field="challenge id",
                max_bytes=MAX_ANUBIS_CHALLENGE_ID_BYTES,
            )
            hx, nonce = solve_anubis_pow(random_data, diff)
        except (KeyError, TypeError, ValueError, RuntimeError) as exc:
            self.log(f"anubis: invalid/too-hard challenge ({type(exc).__name__})")
            return False
        try:
            base_prefix = _json_id(html, "anubis_base_prefix") or ""
        except (TypeError, ValueError, json.JSONDecodeError):
            base_prefix = ""
        if not isinstance(base_prefix, str) or len(base_prefix) > 200:
            self.log("anubis: invalid base prefix")
            return False
        params = {
            "id": challenge_id,
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
        try:
            token = solve_poast_pow(challenge)
        except (TypeError, ValueError, RuntimeError) as exc:
            self.log(f"poast: invalid/too-hard challenge ({type(exc).__name__})")
            return False
        host = self.session.host_of(base)
        self.session.set_cookie("res", token, host, host_only=True)
        self.log(f"poast: solved token_len={len(token)}")
        time_sleep_soft()
        passed = self.session.request(f"{base}/")
        if detect_gate(passed.body) == "poast_sha1":
            passed = self.session.request(f"{base}/NASA")
        return detect_gate(passed.body) != "poast_sha1" and passed.code == 200


def time_sleep_soft() -> None:
    import time

    time.sleep(1.0)
