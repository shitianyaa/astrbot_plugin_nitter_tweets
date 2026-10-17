"""Shared reservation window adapter; the existing manual store stays intact."""

from __future__ import annotations

import json

try:
    from ..media_support.search_session_buffer import (
        SearchSessionStore,
        SessionSearchBuffer,
    )
except ImportError:
    from media_support.search_session_buffer import (
        SearchSessionStore,
        SessionSearchBuffer,
    )


class ResultSessionStore(SearchSessionStore):
    """Namespace windows without changing manual SearchSessionStore behavior.

    P-03 supplies LLM's complete UMO/sender/source key; this primitive only
    guarantees that two namespaces cannot consume each other's reservations.
    """

    def window(
        self, namespace: str, session_id: str, query_key: str
    ) -> SessionSearchBuffer:
        if not namespace or not session_id or not query_key:
            raise ValueError("namespace, session_id and query_key are required")
        session_scope = json.dumps(
            [str(namespace), str(session_id)], ensure_ascii=False
        )
        return self.get_or_create(session_scope, str(query_key))
