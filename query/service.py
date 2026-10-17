"""Pure query facade: no AstrBot event, translation, sending or seen writes."""

from __future__ import annotations

from .backends import QueryBackends
from .models import FetchOutcome, SearchQuery, TimelineQuery, TrendQuery


class QueryService:
    def __init__(self, nitter, fxtwitter=None, *, fetch_backend: str = "mix"):
        self.backends = QueryBackends(nitter, fxtwitter, fetch_backend=fetch_backend)

    async def fetch_timeline(self, request: TimelineQuery) -> FetchOutcome:
        return await self.backends.fetch_timeline(request)

    async def search(self, request: SearchQuery) -> FetchOutcome:
        return await self.backends.search(request)

    async def trends(self, request: TrendQuery) -> FetchOutcome:
        return await self.backends.trends(request)

    async def scan_timeline(
        self,
        username: str,
        anchor_ids: list[str] | None,
        *,
        skip_plain_text: bool = False,
        filter_reposts: bool = True,
    ) -> FetchOutcome:
        return await self.backends.scan_timeline(
            username,
            anchor_ids,
            skip_plain_text=skip_plain_text,
            filter_reposts=filter_reposts,
        )

    async def scan_search(
        self,
        query: str,
        limit: int,
        *,
        anchor_ids: list[str] | None = None,
        kind: str = "tag",
        skip_plain_text: bool = False,
        filter_reposts: bool = True,
    ) -> FetchOutcome:
        return await self.backends.scan_search(
            query,
            limit,
            anchor_ids=anchor_ids,
            kind=kind,
            skip_plain_text=skip_plain_text,
            filter_reposts=filter_reposts,
        )

    async def scan_list(
        self,
        list_id: str,
        anchor_ids: list[str] | None,
        *,
        limit: int = 20,
        skip_plain_text: bool = False,
        filter_reposts: bool = True,
    ) -> FetchOutcome:
        return await self.backends.scan_list(
            list_id,
            anchor_ids,
            limit=limit,
            skip_plain_text=skip_plain_text,
            filter_reposts=filter_reposts,
        )

    async def scan_merged(
        self,
        usernames: list[str],
        watermarks: dict[str, list[str] | None],
        *,
        skip_plain_text: bool = False,
        filter_reposts: bool = True,
    ) -> dict[str, FetchOutcome]:
        return await self.backends.scan_merged(
            usernames,
            watermarks,
            skip_plain_text=skip_plain_text,
            filter_reposts=filter_reposts,
        )
