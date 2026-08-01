"""Search query normalize + kind (locked CF rules)."""

from __future__ import annotations

from typing import Literal

QueryKind = Literal["tag", "phrase"]
MAX_QUERY_LENGTH = 200

# AstrBot ``list`` fields persist strings only. Most query types can be
# inferred from the leading ``#``; this prefix is reserved for the exceptional
# case where the saved type must override that inference (for example a phrase
# whose literal text starts with ``#``). ``auto`` escapes a literal query that
# already starts with the reserved prefix.
WATCH_QUERY_STORAGE_PREFIX = "nitter-query:"


def normalize_query(raw: str) -> str:
    """Strip a query and reject values that cannot have a stable storage key."""
    query = str(raw or "").strip()
    if len(query) > MAX_QUERY_LENGTH or len(query.casefold()) > MAX_QUERY_LENGTH:
        return ""
    return query


def query_kind(query: str) -> QueryKind:
    text = normalize_query(query)
    return "tag" if text.startswith("#") else "phrase"


def normalize_watch_query(
    query: str, type_hint: str | None = None
) -> tuple[str, QueryKind]:
    """Normalize a stored watch query + type for save/runtime.

    - If type_hint is tag/phrase, trust it (with tag # fixup).
    - Else infer from leading #.
    """
    raw_query, stored_type = decode_watch_query(query)
    q = normalize_query(raw_query)
    hinted_type = str(type_hint or "").strip().lower()
    persisted_type = str(stored_type or "").strip().lower()
    raw_type = (
        hinted_type
        if hinted_type in {"tag", "phrase"}
        else persisted_type
        if persisted_type in {"tag", "phrase"}
        else ""
    )
    if raw_type in {"tag", "phrase"}:
        kind: QueryKind = raw_type  # type: ignore[assignment]
    else:
        kind = query_kind(q)
    if kind == "tag":
        if q and not q.startswith("#"):
            q = f"#{q.lstrip('#')}"
        if len(q) > MAX_QUERY_LENGTH:
            return "", kind
    # phrase: never add #
    return q, kind


def encode_watch_query(query: str, kind: str) -> str:
    """Return the canonical string persisted in AstrBot ``list`` config.

    Ordinary ``#tag`` and phrase strings stay human-readable. A type prefix is
    only emitted when inference would change the explicit type. Queries that
    naturally begin with the reserved prefix are escaped with ``auto``.
    """
    q = normalize_query(query)
    if not q:
        return ""
    normalized_kind: QueryKind = (
        "tag" if str(kind).strip().lower() == "tag" else "phrase"
    )
    if normalized_kind == "tag" and q and not q.startswith("#"):
        q = f"#{q.lstrip('#')}"
        if len(q) > MAX_QUERY_LENGTH:
            return ""
    if normalized_kind != query_kind(q):
        return f"{WATCH_QUERY_STORAGE_PREFIX}{normalized_kind}:{q}"
    if q.casefold().startswith(WATCH_QUERY_STORAGE_PREFIX.casefold()):
        return f"{WATCH_QUERY_STORAGE_PREFIX}auto:{q}"
    return q


def decode_watch_query(value: str) -> tuple[str, str | None]:
    """Decode a canonical persisted string into query text and optional type."""
    text = str(value or "").strip()
    prefix = WATCH_QUERY_STORAGE_PREFIX
    if not text.casefold().startswith(prefix.casefold()):
        return text, None
    payload = text[len(prefix) :]
    raw_kind, separator, query = payload.partition(":")
    kind = raw_kind.strip().lower()
    if not separator or kind not in {"tag", "phrase", "auto"}:
        return text, None
    if kind == "auto":
        return query, None
    return query, kind


def seen_account_key_for_query(query: str) -> str:
    """Stable seen account key: q:<casefold normalized query>."""
    q = normalize_query(query)
    return f"q:{q.casefold()}" if q else ""
