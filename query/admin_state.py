"""Read-only, administrator-scoped subscription information for LLM tools."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .formatting import safe_label


def admin_state(plugin, event, *, scope: str = "all", page: int = 1) -> dict[str, Any]:
    """Deny by default: no subscription/config access before admin verification."""
    if not callable(getattr(event, "is_admin", None)) or not event.is_admin():
        return {"status": "forbidden", "kind": "state", "entries": []}
    if scope not in {"all", "subscriptions", "instances"}:
        return {"status": "invalid", "kind": "state", "error": "invalid scope"}
    if type(page) is not int or not 1 <= page <= 100_000:
        return {"status": "invalid", "kind": "state", "error": "invalid page"}
    umo = str(getattr(event, "unified_msg_origin", "") or "").strip()
    sender = getattr(event, "get_sender_id", None)
    sender_id = str(sender() if callable(sender) else "").strip()
    private_fn = getattr(event, "is_private_chat", None)
    if not umo or not sender_id or not callable(private_fn):
        return {
            "status": "forbidden",
            "kind": "state",
            "entries": [],
            "error": "unverifiable conversation",
        }
    is_private = private_fn()
    if type(is_private) is not bool:
        return {
            "status": "forbidden",
            "kind": "state",
            "entries": [],
            "error": "unverifiable conversation",
        }

    try:
        from ..scheduler.config import SchedulerConfigReader
    except ImportError:
        from scheduler.config import SchedulerConfigReader

    # Parsing can heal legacy Tag query shapes. Always parse a deep copy so
    # a read-only status tool cannot accidentally persist those repairs.
    config_copy = deepcopy(dict(plugin.config))
    reader = SchedulerConfigReader(config_copy, plugin.context)
    groups = reader.schedule_groups(log_invalid_targets=False)
    allowed = (
        groups if is_private else [group for group in groups if umo in group.targets]
    )
    if not is_private and not allowed:
        return {
            "status": "empty",
            "kind": "state",
            "entries": [],
            "error": "当前会话无可确认订阅",
        }

    entries: list[dict[str, Any]] = []
    if scope != "instances":
        for group in allowed:
            if group.is_tag_group:
                sources = [item.query for item in group.queries]
            elif group.is_list_group:
                sources = [f"list:{item}" for item in group.list_ids]
            else:
                sources = [f"@{item}" for item in group.users]
            # Each page contains bounded source chunks, so even a very large
            # single group can be inspected completely across pages.
            sources = [safe_label(source, max_chars=160) for source in sources]
            sources = [source for source in sources if source]
            for start in range(0, max(1, len(sources)), 10):
                entries.append(
                    {
                        "group": safe_label(group.name, max_chars=120),
                        "type": group.group_type,
                        "enabled": bool(group.enabled),
                        "sources": sources[start : start + 10],
                        "source_count": len(sources),
                        "offset": start,
                    }
                )

    page_size = 5
    start = (page - 1) * page_size
    result: dict[str, Any] = {
        "status": "success",
        "kind": "state",
        "scope": scope,
        "page": page,
        "total_entries": len(entries),
        "has_more": start + page_size < len(entries),
        "entries": entries[start : start + page_size],
        "truncated": False,
    }
    if scope in {"all", "instances"}:
        # No instance addresses, ports, credentials or invented probe status.
        result["instances"] = {
            "count": len(getattr(plugin.nitter, "instances", []) or []),
            "health": "未知/未探测",
        }
    return result
