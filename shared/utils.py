from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qs, urlparse


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


DEFAULT_INSTANCES = [
    "https://nitter.net",
]

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
