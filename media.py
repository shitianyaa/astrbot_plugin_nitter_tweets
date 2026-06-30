from __future__ import annotations

from urllib.request import urlopen

from astrbot.api import logger

try:
    from .media_support import (
        MEDIA_SIZE_LIMIT_ERROR,
        MediaCacheCleanupResult,
        MediaService,
        NitterClient,
        XdownMediaCandidate,
        XdownMediaParser,
    )
except ImportError:
    from media_support import (
        MEDIA_SIZE_LIMIT_ERROR,
        MediaCacheCleanupResult,
        MediaService,
        NitterClient,
        XdownMediaCandidate,
        XdownMediaParser,
    )

__all__ = [
    "MEDIA_SIZE_LIMIT_ERROR",
    "MediaCacheCleanupResult",
    "MediaService",
    "NitterClient",
    "XdownMediaCandidate",
    "XdownMediaParser",
    "logger",
    "urlopen",
]
