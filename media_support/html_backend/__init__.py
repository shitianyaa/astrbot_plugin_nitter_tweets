# -*- coding: utf-8 -*-
"""HTML Nitter search backend and legacy compatibility facade."""

from .pool import HtmlNitterPool, PoolConfig
from .query import (
    MAX_QUERY_LENGTH,
    decode_watch_query,
    encode_watch_query,
    normalize_query,
    normalize_watch_query,
    query_kind,
    seen_account_key_for_query,
)
from .logging_util import QuietHtmlLog
from .service import (
    DEFAULT_HTML_INSTANCES,
    DEFAULT_SEARCH_INSTANCES,
    DEFAULT_TIEKOETTER,
    HtmlBackendConfig,
    HtmlNitterService,
)

__all__ = [
    "DEFAULT_HTML_INSTANCES",
    "DEFAULT_SEARCH_INSTANCES",
    "DEFAULT_TIEKOETTER",
    "HtmlBackendConfig",
    "HtmlNitterPool",
    "HtmlNitterService",
    "PoolConfig",
    "QuietHtmlLog",
    "MAX_QUERY_LENGTH",
    "decode_watch_query",
    "encode_watch_query",
    "normalize_query",
    "normalize_watch_query",
    "query_kind",
    "seen_account_key_for_query",
]
