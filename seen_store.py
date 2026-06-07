from __future__ import annotations

try:
    from .utils import normalize_username
except ImportError:
    from utils import normalize_username


KV_KEY_SEEN = "nitter_seen_status_ids"
SEEN_LIMIT_PER_USER = 100


class SeenStore:
    def __init__(
        self,
        owner,
        key: str = KV_KEY_SEEN,
        limit_per_user: int = SEEN_LIMIT_PER_USER,
    ):
        self.owner = owner
        self.key = key
        self.limit_per_user = limit_per_user

    async def get_seen_map(self) -> dict[str, list[str]]:
        value = await self.owner.get_kv_data(self.key, {})
        if not isinstance(value, dict):
            return {}

        result: dict[str, list[str]] = {}
        for key, ids in value.items():
            username = normalize_username(str(key))
            if not username or not isinstance(ids, list):
                continue
            result[username] = [str(item) for item in ids if item]
        return result

    async def put_seen_map(self, seen_map: dict[str, list[str]]) -> None:
        await self.owner.put_kv_data(self.key, seen_map)

    def initial_seen_ids(self, ids: list[str]) -> list[str]:
        return [str(item) for item in ids if item][: self.limit_per_user]

    def merge_seen_ids(self, new_ids: list[str], old_ids: list[str]) -> list[str]:
        merged: list[str] = []
        seen: set[str] = set()
        for status_id in [*new_ids, *[str(item) for item in old_ids]]:
            if not status_id or status_id in seen:
                continue
            seen.add(status_id)
            merged.append(status_id)
            if len(merged) >= self.limit_per_user:
                break
        return merged
