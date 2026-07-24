# -*- coding: utf-8 -*-
"""Search query normalize + kind (locked CF rules)."""

from __future__ import annotations

from typing import Literal

QueryKind = Literal["tag", "phrase"]


def normalize_query(raw: str) -> str:
    """Strip only. Never auto-prefix '#'."""
    return (raw or "").strip()


def query_kind(query: str) -> QueryKind:
    text = normalize_query(query)
    return "tag" if text.startswith("#") else "phrase"


def normalize_watch_query(query: str, type_hint: str | None = None) -> tuple[str, QueryKind]:
    """Normalize a stored watch query + type for save/runtime.

    - If type_hint is tag/phrase, trust it (with tag # fixup).
    - Else infer from leading #.
    """
    q = normalize_query(query)
    raw_type = (type_hint or "").strip().lower()
    if raw_type in {"tag", "phrase"}:
        kind: QueryKind = raw_type  # type: ignore[assignment]
    else:
        kind = query_kind(q)
    if kind == "tag":
        if q and not q.startswith("#"):
            q = f"#{q.lstrip('#')}"
    # phrase: never add #
    return q, kind


def seen_account_key_for_query(query: str) -> str:
    """Stable seen account key: q:<casefold normalized query>."""
    q = normalize_query(query)
    return f"q:{q.casefold()}"
