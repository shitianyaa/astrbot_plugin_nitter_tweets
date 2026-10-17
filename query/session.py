"""Shared reservation window adapter; the existing manual store stays intact."""

from __future__ import annotations

import json

try:
    from ..media_support.html_backend.query import normalize_query
    from ..media_support.search_session_buffer import (
        SearchSessionStore,
        SessionSearchBuffer,
    )
except ImportError:
    from media_support.html_backend.query import normalize_query
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

    @staticmethod
    def _llm_key(
        event,
        *,
        kind: str,
        source: str,
        sort: str,
        media_type: str,
    ) -> tuple[str, str]:
        # Neither UMO nor sender is allowed to be empty, as guessing a
        # fallback like "private" could merge different users' read state.
        umo = str(getattr(event, "unified_msg_origin", "") or "").strip()
        getter = getattr(event, "get_sender_id", None)
        sender_id = str(getter() if callable(getter) else "").strip()
        if not umo or not sender_id:
            raise ValueError("LLM session requires exact UMO and sender")
        query_kind = str(kind or "").strip().lower()
        if query_kind not in {"timeline", "search"}:
            raise ValueError("LLM result windows support timeline or search")
        raw = str(source or "").strip()
        if not raw:
            raise ValueError("source cannot be empty")
        normalized = (
            raw.lstrip("@").casefold()
            if query_kind == "timeline"
            else normalize_query(raw).casefold()
        )
        scoped_session = json.dumps(
            [umo, sender_id], ensure_ascii=False, separators=(",", ":")
        )
        scoped_query = json.dumps(
            [query_kind, normalized, str(sort), str(media_type)],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return scoped_session, scoped_query

    def llm_window(
        self,
        event,
        *,
        kind: str,
        source: str,
        sort: str = "latest",
        media_type: str = "",
        refresh: bool = False,
    ) -> SessionSearchBuffer:
        session_id, query_key = self._llm_key(
            event,
            kind=kind,
            source=source,
            sort=sort,
            media_type=media_type,
        )
        if refresh:
            self.reset_window("llm", session_id, query_key)
        return self.window("llm", session_id, query_key)

    def reset_window(self, namespace: str, session_id: str, query_key: str) -> None:
        """Clear one exact window, never in-flight reservations or neighbors."""
        scoped_session = json.dumps(
            [str(namespace), str(session_id)], ensure_ascii=False
        )
        key = self.make_key(scoped_session, str(query_key))
        previous = self._buffers.get(key)
        if previous is not None and previous.reservations:
            raise RuntimeError("cannot refresh while results are reserved")
        self._buffers.pop(key, None)
