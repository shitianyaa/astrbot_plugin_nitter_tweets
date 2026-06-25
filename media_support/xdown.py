from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser

from .extensions import (
    ANIMATED_IMAGE_SUFFIXES,
    IMAGE_SUFFIXES,
    VIDEO_SUFFIXES,
    suffix_matches,
)


class XdownMediaParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.cover_url = ""
        self.items: list[tuple[str, str, str]] = []
        self._href = ""
        self._classes: set[str] = set()
        self._text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs):
        attrs_dict = dict(attrs)
        if tag == "img" and not self.cover_url:
            self.cover_url = str(attrs_dict.get("src") or "")
            return

        if tag != "a":
            return
        classes = set(str(attrs_dict.get("class") or "").split())
        if classes.intersection({"tw-button-dl", "abutton"}):
            self._href = str(attrs_dict.get("href") or "")
            self._classes = classes
            self._text_parts = []

    def handle_data(self, data: str):
        if self._href:
            self._text_parts.append(data)

    def handle_endtag(self, tag: str):
        if tag != "a" or not self._href:
            return
        text = "".join(self._text_parts).strip()
        kind = self._detect_kind(text, self._href)
        if kind:
            self.items.append((kind, self._href, text))
        self._href = ""
        self._classes = set()
        self._text_parts = []

    @staticmethod
    def _detect_kind(text: str, url: str = "") -> str:
        lowered = text.lower()
        if "mp4" in lowered or "video" in lowered:
            return "video"
        if "gif" in lowered:
            return "dynamic"
        if "图片" in text or "image" in lowered or "photo" in lowered:
            return "image"

        # 按 URL 扩展名兜底判断
        if suffix_matches(url, VIDEO_SUFFIXES):
            return "video"
        if suffix_matches(url, ANIMATED_IMAGE_SUFFIXES):
            return "dynamic"
        if suffix_matches(url, IMAGE_SUFFIXES):
            return "image"
        return ""


@dataclass(slots=True)
class XdownMediaCandidate:
    kind: str
    url: str
    label: str = ""
    resolution: int | None = None
    duration_seconds: float | None = None
