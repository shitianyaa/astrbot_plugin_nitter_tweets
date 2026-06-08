from __future__ import annotations

from dataclasses import dataclass, field

try:
    from .utils import normalize_username
except ImportError:
    from utils import normalize_username


KV_KEY_SEEN = "nitter_seen_status_ids"
GLOBAL_GROUP_ID = "global"
SEEN_LIMIT_PER_USER = 100


@dataclass(slots=True)
class GroupedSeenMap:
    groups: dict[str, dict[str, list[str]]] = field(default_factory=dict)


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
        return await self.get_group_seen_map(GLOBAL_GROUP_ID)

    async def put_seen_map(self, seen_map: dict[str, list[str]]) -> None:
        await self.put_group_seen_map(GLOBAL_GROUP_ID, seen_map)

    async def get_group_seen_map(self, group_id: str) -> dict[str, list[str]]:
        grouped = await self.get_grouped_seen_map()
        return dict(grouped.groups.get(normalize_group_id(group_id), {}))

    async def put_group_seen_map(
        self, group_id: str, seen_map: dict[str, list[str]]
    ) -> None:
        grouped = await self.get_grouped_seen_map()
        grouped.groups[normalize_group_id(group_id)] = self.normalize_seen_map(seen_map)
        await self.put_grouped_seen_map(grouped)

    async def get_grouped_seen_map(self) -> GroupedSeenMap:
        value = await self.owner.get_kv_data(self.key, {})
        if not isinstance(value, dict):
            return GroupedSeenMap()

        groups_value = value.get("groups")
        if isinstance(groups_value, dict):
            return GroupedSeenMap(
                groups={
                    normalize_group_id(group_id): self.normalize_seen_map(seen_map)
                    for group_id, seen_map in groups_value.items()
                    if isinstance(seen_map, dict)
                }
            )

        return GroupedSeenMap(groups={GLOBAL_GROUP_ID: self.normalize_seen_map(value)})

    async def put_grouped_seen_map(self, grouped: GroupedSeenMap) -> None:
        await self.owner.put_kv_data(
            self.key,
            {
                "version": 2,
                "groups": {
                    normalize_group_id(group_id): self.normalize_seen_map(seen_map)
                    for group_id, seen_map in grouped.groups.items()
                },
            },
        )

    @staticmethod
    def normalize_seen_map(value: dict) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        for key, ids in value.items():
            username = normalize_username(str(key))
            if not username or not isinstance(ids, list):
                continue
            result[username] = [str(item) for item in ids if item]
        return result

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


def normalize_group_id(value: str) -> str:
    group_id = str(value or "").strip().lower()
    return group_id or GLOBAL_GROUP_ID
