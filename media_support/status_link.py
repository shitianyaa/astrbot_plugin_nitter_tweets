"""Extract and normalize public X/Twitter status URLs from message text."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

_ALLOWED_HOSTS = frozenset(
    {
        "x.com",
        "www.x.com",
        "twitter.com",
        "www.twitter.com",
        "mobile.twitter.com",
        "fxtwitter.com",
        "fixupx.com",
        "twittpr.com",
    }
)
_HOST_PATTERN = "|".join(re.escape(host) for host in sorted(_ALLOWED_HOSTS))

# AstrBot's regex filter looks for a candidate; parse_status_link validates it.
STATUS_LINK_REGEX = (
    r"""(?i)(?:https?://|(?<![^\s(\[{<"'=:]))"""
    rf"(?:{_HOST_PATTERN})/\S*?status(?:es)?/\d+"
)
_STATUS_FIND_RE = re.compile(STATUS_LINK_REGEX + r"\S*")

_USER_RE = re.compile(r"^[A-Za-z0-9_]{1,30}$")
_STATUS_PATH_RE = re.compile(
    r"/(?P<user>[A-Za-z0-9_]+)/(?:status|statuses)/(?P<id>\d+)(?:/|$)",
    re.IGNORECASE,
)
_TRAILING_PUNCT_RE = re.compile(r"[)\],.;!?'\"<>]+$")


@dataclass(frozen=True, slots=True)
class StatusLink:
    username: str
    status_id: str
    canonical_url: str


def _strip_trailing_punct(value: str) -> str:
    text = str(value or "").strip()
    # Peel common wrappers repeatedly: (url) / url.
    for _ in range(3):
        updated = _TRAILING_PUNCT_RE.sub("", text)
        if updated == text:
            break
        text = updated
    return text


def extract_status_links(text: str) -> list[StatusLink]:
    """Return unique status links in appearance order."""
    raw = str(text or "")
    if not raw.strip():
        return []

    found: list[StatusLink] = []
    seen: set[str] = set()
    for match in _STATUS_FIND_RE.finditer(raw):
        candidate = _strip_trailing_punct(match.group(0))
        parsed = parse_status_link(candidate)
        if parsed is None:
            continue
        if parsed.status_id in seen:
            continue
        seen.add(parsed.status_id)
        found.append(parsed)
    return found


def parse_status_link(value: str) -> StatusLink | None:
    """Parse one URL-like string into a StatusLink, or None if invalid."""
    raw = _strip_trailing_punct(str(value or "").strip())
    if not raw:
        return None
    if "://" not in raw:
        raw = "https://" + raw.lstrip("/")

    try:
        parts = urlparse(raw)
    except (TypeError, ValueError):
        return None

    host = (parts.hostname or "").lower().rstrip(".")
    if host not in _ALLOWED_HOSTS:
        return None
    if parts.scheme not in {"http", "https"}:
        return None

    path_match = _STATUS_PATH_RE.search(parts.path or "")
    if not path_match:
        return None

    user = path_match.group("user")
    status_id = path_match.group("id")
    if not _USER_RE.fullmatch(user):
        return None
    if not status_id.isdigit():
        return None

    canonical = f"https://x.com/{user}/status/{status_id}"
    return StatusLink(username=user, status_id=status_id, canonical_url=canonical)
