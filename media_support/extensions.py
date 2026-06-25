from __future__ import annotations

from pathlib import Path


IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".webp", ".bmp", ".svg"})
ANIMATED_IMAGE_SUFFIXES = frozenset({".gif"})
MEDIA_IMAGE_SUFFIXES = IMAGE_SUFFIXES | ANIMATED_IMAGE_SUFFIXES
VIDEO_SUFFIXES = frozenset({".mp4", ".m4v", ".mov", ".webm", ".mkv", ".avi"})


def classify_media_path(path: Path) -> str:
    suffixes = {suffix.lower() for suffix in path.suffixes}
    if suffixes & MEDIA_IMAGE_SUFFIXES:
        return "image"
    if suffixes & VIDEO_SUFFIXES:
        return "video"
    return "other"


def suffix_matches(path_or_url: str, suffixes: frozenset[str]) -> bool:
    normalized = str(path_or_url or "").lower().split("?", 1)[0].split("#", 1)[0]
    return any(normalized.endswith(suffix) for suffix in suffixes)
