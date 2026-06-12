from __future__ import annotations

from dataclasses import dataclass, field

try:
    from .utils import normalize_username
except ImportError:
    from utils import normalize_username


KV_KEY_SEEN = "nitter_seen_status_ids"
KV_KEY_SEEN_BY_TARGET = "nitter_seen_status_ids_by_target_v1"
DEFAULT_GROUP_ID = "default"
LEGACY_GLOBAL_GROUP_ID = "global"  # v0.9.x 及更早版本的默认分组 ID
GLOBAL_GROUP_ID = DEFAULT_GROUP_ID
SEEN_LIMIT_PER_USER = 300


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
        grouped = self._grouped_seen_from_value(value)
        target_value = await self.owner.get_kv_data(KV_KEY_SEEN_BY_TARGET, {})
        target_seen = self.normalize_seen_by_target(target_value)
        if target_seen:
            global_seen = grouped.groups.setdefault(GLOBAL_GROUP_ID, {})
            for seen_map in target_seen.values():
                for username, status_ids in seen_map.items():
                    global_seen[username] = self.merge_seen_ids(
                        status_ids,
                        global_seen.get(username, []),
                    )
        return grouped

    def _grouped_seen_from_value(self, value) -> GroupedSeenMap:
        if not isinstance(value, dict):
            return GroupedSeenMap()

        groups_value = value.get("groups")
        if isinstance(groups_value, dict):
            result_groups: dict[str, dict[str, list[str]]] = {}
            for group_id, seen_map in groups_value.items():
                if isinstance(seen_map, dict):
                    # normalize_group_id 会将 "global" 映射为 "default"
                    norm_id = normalize_group_id(group_id)
                    if norm_id in result_groups:
                        # 同一逻辑分组可能来自 "global" 和 "default" 两个 key，合并
                        result_groups[norm_id] = self.merge_seen_map(
                            result_groups[norm_id], self.normalize_seen_map(seen_map)
                        )
                    else:
                        result_groups[norm_id] = self.normalize_seen_map(seen_map)
            return GroupedSeenMap(groups=result_groups)

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

    @classmethod
    def normalize_seen_by_target(cls, value) -> dict[str, dict[str, list[str]]]:
        if not isinstance(value, dict):
            return {}

        result: dict[str, dict[str, list[str]]] = {}
        for target, seen_map in value.items():
            target_key = str(target or "").strip()
            if not target_key or not isinstance(seen_map, dict):
                continue
            normalized_seen = cls.normalize_seen_map(seen_map)
            if normalized_seen:
                result[target_key] = normalized_seen
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

    @staticmethod
    def merge_seen_map(
        base: dict[str, list[str]],
        other: dict[str, list[str]],
    ) -> dict[str, list[str]]:
        """合并两个 seen_map，用于兼容 global → default 映射时的数据合并."""
        result: dict[str, list[str]] = dict(base)
        for username, status_ids in other.items():
            if username in result:
                # 合并去重
                seen_set = set(result[username])
                merged = result[username] + [
                    sid for sid in status_ids if sid not in seen_set
                ]
                result[username] = merged[:SEEN_LIMIT_PER_USER]
            else:
                result[username] = status_ids[:SEEN_LIMIT_PER_USER]
        return result


def normalize_group_id(value: str) -> str:
    group_id = str(value or "").strip().lower()
    # v0.9.x 使用 "global" 作为默认分组 ID，v0.10.0 改为 "default"
    # 兼容映射：老数据中的 "global" 视为 "default"
    if group_id == LEGACY_GLOBAL_GROUP_ID:
        return DEFAULT_GROUP_ID
    return group_id or DEFAULT_GROUP_ID
