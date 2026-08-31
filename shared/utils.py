from __future__ import annotations

import datetime as dt
import hashlib
import html
import re
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:
    CN_TZ = ZoneInfo("Asia/Shanghai")
except ZoneInfoNotFoundError:  # pragma: no cover
    CN_TZ = dt.timezone(dt.timedelta(hours=8), name="Asia/Shanghai")

_DISPLAY_TIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
_NITTER_TITLE_RE = re.compile(
    r"^([A-Za-z]{3} \d{1,2}, \d{4})"
    r"(?:\s*[·•]\s*(\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM)?))?"
    r"(?:\s*(UTC|GMT|Z))?$",
    re.IGNORECASE,
)

# ──────────────────────────────────────────────────────────────────────
# 数据模型
# ──────────────────────────────────────────────────────────────────────


@dataclass(slots=True)
class TweetMedia:
    kind: str
    url: str
    path: Path | None = None
    duration_seconds: float | None = None

    @property
    def is_image(self) -> bool:
        return self.kind == "image"

    @property
    def is_video(self) -> bool:
        return self.kind in {"video", "dynamic"}


@dataclass(slots=True)
class TweetItem:
    text: str
    link: str
    published: str
    media: list[TweetMedia] = field(default_factory=list)
    media_warnings: list[str] = field(default_factory=list)
    ai_warnings: list[str] = field(default_factory=list)
    translation: str = ""
    is_retweet: bool = False

    @property
    def status_id(self) -> str:
        if match := re.search(r"/status(?:es)?/(\d+)", self.link):
            return match.group(1)
        return ""

    @property
    def username(self) -> str:
        path_parts = [part for part in urlparse(self.link).path.split("/") if part]
        if len(path_parts) >= 2 and path_parts[1] in {"status", "statuses"}:
            return path_parts[0].lstrip("@")
        return ""

    @property
    def x_url(self) -> str:
        if self.username and self.status_id:
            return f"https://x.com/{self.username}/status/{self.status_id}"
        return self.link


# No public Nitter instances are shipped.  Users must configure a self-hosted
# instance explicitly; an empty list lets startup diagnostics explain that
# deployment is incomplete instead of silently calling a retired mirror.
DEFAULT_INSTANCES: list[str] = []

# Public mirrors are no longer a supported deployment dependency.  Keep this
# list only to prevent stale configs from silently calling retired services.
RETIRED_PUBLIC_INSTANCES = frozenset(
    {
        "https://nitter.net",
        "https://nitter.tiekoetter.com",
        "https://nitter.poast.org",
        "https://nitter.kareem.one",
        "https://nitter.catsarch.com",
    }
)


def format_tweet_published(raw: str) -> str:
    """Normalize any tweet timestamp to Asia/Shanghai ``YYYY-MM-DD HH:MM:SS``.

    Covers RSS pubDate, Twitter ``created_at``, Fx/Vx strings, and common
    Nitter ``tweet-date`` title values (List/search HTML). Unparseable input
    is returned unchanged.

    Display-form guard: strings already matching ``YYYY-MM-DD HH:MM:SS`` are
    treated as **final Asia/Shanghai wall time** and are not shifted again.
    Callers must not write bare UTC wall clocks in that shape; emit Twitter/
    RFC/ISO forms (with offset) or this function's own output only.

    Date-only Nitter titles (e.g. ``Jul 23, 2026``) are interpreted as
    **UTC midnight**, then converted to Shanghai (typically ``08:00:00``).
    """
    text = str(raw or "").strip()
    if not text:
        return ""
    if _DISPLAY_TIME_RE.fullmatch(text):
        # Already normalized (or trusted local display). Do not assume UTC.
        return text

    parsed = _parse_tweet_datetime(text)
    if parsed is None:
        return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(CN_TZ).strftime("%Y-%m-%d %H:%M:%S")


def _parse_tweet_datetime(text: str) -> dt.datetime | None:
    try:
        parsed = parsedate_to_datetime(text)
        if isinstance(parsed, dt.datetime):
            return parsed
    except (TypeError, ValueError, IndexError, OverflowError):
        pass

    iso = text
    if iso.endswith("Z") and "T" in iso:
        iso = iso[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(iso)
        if isinstance(parsed, dt.datetime):
            return parsed
    except ValueError:
        pass

    # Nitter: "Jul 23, 2026" or "Jul 28, 2026 · 5:15 AM UTC".
    # Times without offset (and date-only) are treated as UTC, then converted
    # by format_tweet_published to Asia/Shanghai.
    m = _NITTER_TITLE_RE.match(text.replace("  ", " ").strip())
    if m:
        date_part = m.group(1)
        time_part = (m.group(2) or "").strip()
        if time_part:
            for fmt in (
                "%b %d, %Y %I:%M %p",
                "%b %d, %Y %I:%M:%S %p",
                "%b %d, %Y %H:%M",
                "%b %d, %Y %H:%M:%S",
            ):
                try:
                    naive = dt.datetime.strptime(  # noqa: DTZ007
                        f"{date_part} {time_part}", fmt
                    )
                    return naive.replace(tzinfo=dt.timezone.utc)
                except ValueError:
                    continue
        try:
            # Date-only → UTC midnight (see format_tweet_published docstring).
            naive = dt.datetime.strptime(date_part, "%b %d, %Y")  # noqa: DTZ007
            return naive.replace(tzinfo=dt.timezone.utc)
        except ValueError:
            pass
    return None


def format_subscription_count(count: int, group_type: str = "blogger") -> str:
    """Return the user-facing quantity phrase for a subscription group."""
    kind = str(group_type or "blogger").strip().lower()
    if kind == "tag":
        noun = "个搜索订阅"
    elif kind == "list":
        noun = "个 List"
    else:
        noun = "位博主"
    return f"{int(count)} {noun}"


def format_subscription_source(source: str, group_type: str = "blogger") -> str:
    """Render a stored account/query/List key without internal prefixes."""
    raw = str(source or "").strip()
    if raw.startswith("@"):
        raw = raw[1:].strip()
    lowered = raw.lower()
    kind = str(group_type or "blogger").strip().lower()
    if lowered.startswith("q:"):
        kind = "tag"
        raw = raw[2:].strip()
    elif lowered.startswith("list:"):
        kind = "list"
        raw = raw[5:].strip()

    if not raw:
        return "-"
    if kind == "tag":
        return f"搜索「{raw}」"
    if kind == "list":
        return f"List {raw}"
    return f"@{raw}"


URL_LIKE_RE = re.compile(
    r"(?i)(?<![@\w])(?:https?://)?(?:[a-z0-9-]+\.)+[a-z]{2,}"
    r"(?:/[^\s<>()]*)?"
)
PIPED_WATCH_RE = re.compile(
    r"(?i)\b(?:https?://)?(?:www\.)?piped\.video/watch\?v=([A-Za-z0-9_-]+)"
    r"(?:[^\s<>()]*)?"
)
PIPED_SHORT_RE = re.compile(
    r"(?i)\b(?:https?://)?(?:www\.)?piped\.video/([A-Za-z0-9_-]+)"
    r"(?:[^\s<>()]*)?"
)
TRAILING_URL_PUNCT = ".,;:!?)）】』」\"'"


def clamp_int(value, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = minimum
    return max(minimum, min(maximum, number))


def clamp_float(value, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = minimum
    return max(minimum, min(maximum, number))


def clean_text(raw: str) -> str:
    text = re.sub(r"(?i)<br\s*/?>", "\n", raw)
    text = re.sub(r"(?s)<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def normalize_external_links(text: str) -> str:
    text = PIPED_WATCH_RE.sub(r"https://youtu.be/\1", text or "")
    text = PIPED_SHORT_RE.sub(r"https://youtu.be/\1", text)
    return text


def extract_external_links(text: str) -> list[str]:
    links: list[str] = []
    seen: set[str] = set()
    for match in URL_LIKE_RE.finditer(normalize_external_links(text or "")):
        link = match.group(0).rstrip(TRAILING_URL_PUNCT)
        if not link.startswith(("http://", "https://")):
            link = f"https://{link}"
        if link not in seen:
            links.append(link)
            seen.add(link)
    return links


def strip_external_links(text: str) -> str:
    stripped = URL_LIKE_RE.sub("", normalize_external_links(text or ""))
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in stripped.splitlines()]
    cleaned: list[str] = []
    for line in lines:
        if line or (cleaned and cleaned[-1]):
            cleaned.append(line)
    while cleaned and not cleaned[-1]:
        cleaned.pop()
    return "\n".join(cleaned).strip()


def file_uri(path: Path) -> str:
    if not path.is_absolute():
        path = path.resolve()
    posix_path = path.as_posix()
    if posix_path.startswith("/"):
        return f"file:///{posix_path.lstrip('/')}"
    return path.as_uri()


def generate_file_name(url: str, default_suffix: str = "") -> str:
    parsed = urlparse(url)
    suffix = Path(parsed.path).suffix
    if not suffix:
        query = parse_qs(parsed.query)
        media_format = (query.get("format") or [""])[0].strip(".")
        suffix = f".{media_format}" if media_format else default_suffix
    digest = hashlib.md5(url.encode("utf-8")).hexdigest()[:16]
    return f"{digest}{suffix or default_suffix}"


def load_instances(value) -> list[str]:
    if isinstance(value, str):
        raw_items = re.split(r"[\n,]+", value)
    elif isinstance(value, list):
        raw_items = [str(item) for item in value]
    else:
        raw_items = DEFAULT_INSTANCES

    instances: list[str] = []
    for item in raw_items:
        item = item.strip().rstrip("/")
        if not item:
            continue
        if not item.startswith(("http://", "https://")):
            item = f"https://{item}"
        if item not in instances:
            instances.append(item)
    return instances or DEFAULT_INSTANCES


def filter_retired_instances(value) -> tuple[list[str], list[str]]:
    """Return configured instances minus retired public mirrors."""

    configured = load_instances(value)
    active: list[str] = []
    removed: list[str] = []
    retired_hosts = {
        (urlparse(item).hostname or "").rstrip(".").casefold()
        for item in RETIRED_PUBLIC_INSTANCES
    }
    for instance in configured:
        normalized = instance.rstrip("/")
        host = (urlparse(normalized).hostname or "").rstrip(".").casefold()
        if host in retired_hosts:
            removed.append(normalized)
        elif normalized not in active:
            active.append(normalized)
    return active, removed


def normalize_username(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if value.startswith(("http://", "https://")):
        path = urlparse(value).path.strip("/")
        value = path.split("/", 1)[0] if path else ""
    value = value.lstrip("@").strip()
    if not re.fullmatch(r"[A-Za-z0-9_]{1,15}", value):
        return ""
    return value


def normalize_seen_account_key(value: str) -> str:
    """Normalize username, tag-query, and Twitter List seen/scan keys."""
    value = (value or "").strip()
    if not value:
        return ""
    if value[:2].casefold() == "q:":
        body = value[2:].strip()
        folded = body.casefold()
        if not body or len(body) > 200 or len(folded) > 200:
            return ""
        return "q:" + folded
    if value[:5].casefold() == "list:":
        list_id = value[5:].strip()
        if not list_id.isdigit() or len(list_id) > 20 or int(list_id) <= 0:
            return ""
        return "list:" + list_id
    return normalize_username(value)


def safe_call(obj, method_name: str):
    method = getattr(obj, method_name, None)
    if not callable(method):
        return None
    try:
        return method()
    except Exception:
        return None


def node_uin(event):
    for method_name in ("get_self_id", "get_sender_id"):
        value = safe_call(event, method_name)
        if value:
            try:
                return int(value)
            except (TypeError, ValueError):
                return value
    return 10000
