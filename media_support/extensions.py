from __future__ import annotations

from pathlib import Path


MEDIA_TYPE_IMAGE = "image"
MEDIA_TYPE_VIDEO = "video"
MEDIA_TYPE_DYNAMIC = "dynamic"
MEDIA_TYPE_OTHER = "other"

IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".webp", ".bmp", ".svg"})
ANIMATED_IMAGE_SUFFIXES = frozenset({".gif"})
MEDIA_IMAGE_SUFFIXES = IMAGE_SUFFIXES | ANIMATED_IMAGE_SUFFIXES
VIDEO_SUFFIXES = frozenset({".mp4", ".m4v", ".mov", ".webm", ".mkv", ".avi"})


def classify_media_path(path: Path) -> str:
    suffixes = {suffix.lower() for suffix in path.suffixes}
    if suffixes & MEDIA_IMAGE_SUFFIXES:
        return MEDIA_TYPE_IMAGE
    if suffixes & VIDEO_SUFFIXES:
        return MEDIA_TYPE_VIDEO
    return MEDIA_TYPE_OTHER


def suffix_matches(path_or_url: str, suffixes: frozenset[str]) -> bool:
    normalized = str(path_or_url or "").lower().split("?", 1)[0].split("#", 1)[0]
    return any(normalized.endswith(suffix) for suffix in suffixes)
