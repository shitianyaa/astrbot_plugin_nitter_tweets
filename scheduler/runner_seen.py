"""seen 索引与扫描水位的读写封装。

`NitterTweetScheduler` 的 mixin：只通过 `self` 协作，不 import 宿主类。
seen 的**写入时机**仍由 `runner.py` 的编排决定，这里只提供存取原语。
"""

from __future__ import annotations

try:
    from ..shared import TweetItem
    from ..shared.group_ids import GLOBAL_GROUP_ID
except ImportError:
    from shared import TweetItem
    from shared.group_ids import GLOBAL_GROUP_ID


class SchedulerSeenMixin:
    """seen map / scan watermark 存取。"""

    async def _store_incremental_seen_ids(
        self,
        group_id: str,
        username: str,
        status_ids: list[str],
        seen_map: dict[str, list[str]],
    ) -> None:
        ids = [str(item) for item in status_ids if item]
        if not ids:
            return
        current = seen_map.get(username, [])
        if not isinstance(current, list):
            current = []
        seen_map[username] = self._merge_seen_ids(ids, current)
        await self.storage.add_seen_ids(group_id, username, ids)

    async def _get_seen_map(
        self, group_id: str = GLOBAL_GROUP_ID
    ) -> dict[str, list[str]]:
        return await self.storage.get_group_seen_map(group_id)

    async def _get_scan_watermarks(
        self,
        group_id: str,
        seen_map: dict[str, list[str]],
    ) -> dict[str, list[str]]:
        getter = getattr(self.storage, "get_group_scan_watermarks", None)
        if callable(getter):
            stored_watermarks = await getter(group_id)
            # Older databases and lightweight test adapters may contain seen
            # IDs but no dedicated anchor row yet. Infer only the missing
            # entries; an explicit empty anchor window means the source was
            # initialized with no historical status ID and must be preserved.
            for username, status_ids in seen_map.items():
                if username in stored_watermarks:
                    continue
                if not isinstance(status_ids, list):
                    continue
                if status_ids:
                    stored_watermarks[username] = list(status_ids[:20])
            return stored_watermarks

        # Keep older storage fakes and external adapters usable while they add
        # the dedicated scan-anchor API.
        return {
            username: list(status_ids[:20])
            for username, status_ids in seen_map.items()
            if isinstance(status_ids, list) and status_ids
        }

    async def _set_scan_watermark(
        self,
        group_id: str,
        username: str,
        status_ids: list[str] | str | None,
    ) -> None:
        setter = getattr(self.storage, "set_scan_watermark", None)
        if callable(setter):
            await setter(group_id, username, status_ids)

    async def _put_seen_map(
        self, group_id: str, seen_map: dict[str, list[str]]
    ) -> None:
        await self.storage.put_group_seen_map(group_id, seen_map)

    async def _put_seen_map_and_scan_watermark(
        self,
        group_id: str,
        username: str,
        seen_map: dict[str, list[str]],
        status_ids: list[str] | str | None,
    ) -> None:
        writer = getattr(
            self.storage,
            "put_group_seen_map_and_scan_watermark",
            None,
        )
        if callable(writer):
            await writer(group_id, username, seen_map, status_ids)
            return

        # Keep lightweight/legacy storage adapters usable until they expose
        # the SQLite transaction-backed operation.
        await self._set_scan_watermark(group_id, username, status_ids)
        await self._put_seen_map(group_id, seen_map)

    def _merge_seen_ids(self, new_ids: list[str], old_ids: list[str]) -> list[str]:
        return self.storage.merge_seen_ids(new_ids, old_ids)

    @classmethod
    def _select_new_tweets_after_scan_watermark(
        cls,
        tweets: list[TweetItem],
        seen_ids: list[str],
        watermark_ids: list[str] | None,
    ) -> tuple[list[TweetItem], list[str]]:
        del watermark_ids
        seen_set = {str(item) for item in seen_ids}
        new_tweets: list[TweetItem] = []

        for tweet in tweets:
            status_id = str(tweet.status_id or "")
            if not status_id or status_id in seen_set:
                continue
            new_tweets.append(tweet)

        return new_tweets, []

    @classmethod
    def _max_numeric_status_id(cls, seen_ids: list[str]) -> int | None:
        numeric_ids = [
            status_number
            for status_id in seen_ids
            if (status_number := cls._parse_numeric_status_id(str(status_id)))
            is not None
        ]
        if not numeric_ids:
            return None
        return max(numeric_ids)

    @staticmethod
    def _parse_numeric_status_id(status_id: str) -> int | None:
        value = str(status_id or "").strip()
        if not value or not value.isdigit():
            return None
        return int(value)
