# -*- coding: utf-8 -*-
"""HTML Nitter backend: blogger HTML fallback + search pools."""

from .pool import HtmlNitterPool, PoolConfig
from .query import (
    normalize_query,
    normalize_watch_query,
    query_kind,
    seen_account_key_for_query,
)
from .service import DEFAULT_HTML_INSTANCES, HtmlBackendConfig, HtmlNitterService

__all__ = [
    "DEFAULT_HTML_INSTANCES",
    "HtmlBackendConfig",
    "HtmlNitterPool",
    "HtmlNitterService",
    "PoolConfig",
    "normalize_query",
    "normalize_watch_query",
    "query_kind",
    "seen_account_key_for_query",
]
