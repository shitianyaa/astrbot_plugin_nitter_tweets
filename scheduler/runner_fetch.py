"""抓取阶段：博主 RSS、HTML 回退与标签搜索。

`NitterTweetScheduler` 的 mixin：只通过 `self` 协作，不 import 宿主类。
只负责产出 `UserFetchResult`；首次 init、水位裁剪等编排留在 `runner.py`。
"""

from __future__ import annotations

import asyncio

from astrbot.api import logger

try:
    from ..config import config_get, parse_config_bool
    from ..shared import TweetItem, format_subscription_source
    from .config import ScheduleGroup
    from .models import SchedulerTaskError, UserFetchResult
except ImportError:
    from config import config_get, parse_config_bool
    from scheduler.config import ScheduleGroup
    from scheduler.models import SchedulerTaskError, UserFetchResult
    from shared import TweetItem, format_subscription_source


class SchedulerFetchMixin:
    """博主与标签的抓取入口。"""

    async def _fetch_group_users(
        self,
        group: ScheduleGroup,
        fetch_limit: int,
        skip_plain_text: bool,
        scan_watermarks: dict[str, list[str]],
    ) -> list[UserFetchResult]:
        accounts = list(group.account_keys)
        # Tag/List groups always serial to protect shared HTML instances.
        if (
            group.is_tag_group
            or group.is_list_group
            or not self._should_use_concurrent_fetch(group)
        ):
            results = []
            for index, username in enumerate(accounts):
                # Add delay between queries (except before the first one)
                if index > 0 and group.send_user_interval > 0:
                    await asyncio.sleep(group.send_user_interval)
                results.append(
                    await self._fetch_group_user(
                        group,
                        index,
                        username,
                        fetch_limit,
                        skip_plain_text,
                        scan_watermarks.get(username),
                        concurrent=False,
                    )
                )
            return results

        semaphore = asyncio.Semaphore(group.fetch_concurrency)

        async def fetch_with_limit(index: int, username: str) -> UserFetchResult:
            async with semaphore:
                return await self._fetch_group_user(
                    group,
                    index,
                    username,
                    fetch_limit,
                    skip_plain_text,
                    scan_watermarks.get(username),
                    concurrent=True,
                )

        tasks = [
            fetch_with_limit(index, username) for index, username in enumerate(accounts)
        ]
        return list(await asyncio.gather(*tasks))

    async def _fetch_group_user(
        self,
        group: ScheduleGroup,
        index: int,
        username: str,
        fetch_limit: int,
        skip_plain_text: bool,
        scan_watermark: list[str] | None,
        *,
        concurrent: bool,
    ) -> UserFetchResult:
        filter_reposts = self._effective_filter_reposts(group)
        if group.is_tag_group:
            return await self._fetch_group_query(
                group,
                index,
                username,
                fetch_limit,
                skip_plain_text=skip_plain_text,
                filter_reposts=filter_reposts,
            )
        if group.is_list_group:
            return await self._fetch_group_list(
                group,
                index,
                username,
                fetch_limit,
                scan_watermark,
                skip_plain_text=skip_plain_text,
                filter_reposts=filter_reposts,
            )
        try:
            scheduler_method = (
                "fetch_tweets_for_scheduler_from_instances"
                if concurrent
                else "fetch_tweets_for_scheduler"
            )
            fetch_for_scheduler = getattr(self.nitter, scheduler_method, None)
            if callable(fetch_for_scheduler):
                if concurrent:
                    instance, scan_result = await fetch_for_scheduler(
                        username,
                        scan_watermark,
                        group.concurrent_fetch_instances,
                        start_index=index,
                        skip_plain_text=skip_plain_text,
                        retry_attempts=getattr(self.nitter, "retry_attempts", 2),
                        filter_reposts=filter_reposts,
                    )
                else:
                    instance, scan_result = await fetch_for_scheduler(
                        username,
                        scan_watermark,
                        skip_plain_text=skip_plain_text,
                        filter_reposts=filter_reposts,
                    )
                raw_anchor_status_ids = getattr(scan_result, "anchor_status_ids", None)
                anchor_status_ids = (
                    list(scan_result.scanned_status_ids)[:20]
                    if raw_anchor_status_ids is None
                    else list(raw_anchor_status_ids)
                )
                tweets = list(scan_result.tweets)
                if not tweets and self._user_html_fallback_enabled():
                    html_result = await self._fetch_user_html_fallback(
                        index,
                        username,
                        fetch_limit,
                        skip_plain_text=skip_plain_text,
                        filter_reposts=filter_reposts,
                    )
                    if html_result is not None:
                        return html_result
                return UserFetchResult(
                    index=index,
                    username=username,
                    instance=instance,
                    tweets=tweets,
                    scanned_status_ids=list(scan_result.scanned_status_ids),
                    anchor_status_ids=anchor_status_ids,
                    latest_status_id=str(scan_result.latest_status_id or ""),
                    scan_complete=bool(scan_result.complete),
                    plain_text_filtered=int(scan_result.plain_text_filtered or 0),
                )

            if concurrent:
                (
                    instance,
                    tweets,
                    plain_text_filtered,
                ) = await self.nitter.fetch_tweets_with_stats_from_instances(
                    username,
                    fetch_limit,
                    group.concurrent_fetch_instances,
                    start_index=index,
                    skip_plain_text=skip_plain_text,
                    retry_attempts=getattr(self.nitter, "retry_attempts", 2),
                    filter_reposts=filter_reposts,
                )
            else:
                (
                    instance,
                    tweets,
                    plain_text_filtered,
                ) = await self.nitter.fetch_tweets_with_stats(
                    username,
                    fetch_limit,
                    skip_plain_text=skip_plain_text,
                    filter_reposts=filter_reposts,
                )
            if not tweets and self._user_html_fallback_enabled():
                html_result = await self._fetch_user_html_fallback(
                    index,
                    username,
                    fetch_limit,
                    skip_plain_text=skip_plain_text,
                    filter_reposts=filter_reposts,
                )
                if html_result is not None:
                    return html_result
        except Exception as exc:
            if self._user_html_fallback_enabled():
                html_result = await self._fetch_user_html_fallback(
                    index,
                    username,
                    fetch_limit,
                    skip_plain_text=skip_plain_text,
                    filter_reposts=filter_reposts,
                )
                if html_result is not None:
                    return html_result
            return UserFetchResult(
                index=index,
                username=username,
                error=SchedulerTaskError.from_exception(exc),
            )
        return UserFetchResult(
            index=index,
            username=username,
            instance=instance,
            tweets=tweets,
            scanned_status_ids=[tweet.status_id for tweet in tweets if tweet.status_id],
            anchor_status_ids=[
                tweet.status_id for tweet in tweets[:20] if tweet.status_id
            ],
            latest_status_id=(tweets[0].status_id if tweets else ""),
            plain_text_filtered=plain_text_filtered,
        )

    def _user_html_fallback_enabled(self) -> bool:
        if self.html_backend is None:
            return False
        return parse_config_bool(
            config_get(self.config, "user_html_fallback", False), False
        )

    def _effective_filter_reposts(self, group: ScheduleGroup) -> bool:
        global_enabled = parse_config_bool(
            config_get(self.config, "filter_reposts_enabled", True),
            True,
        )
        return global_enabled and bool(getattr(group, "filter_reposts_enabled", True))

    async def _fetch_user_html_fallback(
        self,
        index: int,
        username: str,
        fetch_limit: int,
        *,
        skip_plain_text: bool = False,
        filter_reposts: bool = True,
    ) -> UserFetchResult | None:
        if self.html_backend is None:
            return None
        try:
            instance, tweets = await asyncio.to_thread(
                lambda: self.html_backend.fetch_user(
                    username,
                    fetch_limit,
                    filter_reposts=filter_reposts,
                )
            )
        except Exception as exc:
            logger.warning(
                f"[NitterTweets] HTML 用户页回退失败: @{username}, error={exc}"
            )
            return None
        if not tweets:
            return None
        tweets, plain_text_filtered = self._filter_html_tweets_plain_text(
            list(tweets), skip_plain_text=skip_plain_text
        )
        return UserFetchResult(
            index=index,
            username=username,
            instance=instance,
            tweets=tweets,
            scanned_status_ids=[tweet.status_id for tweet in tweets if tweet.status_id],
            anchor_status_ids=[
                tweet.status_id for tweet in tweets[:20] if tweet.status_id
            ],
            latest_status_id=(tweets[0].status_id if tweets else ""),
            scan_complete=True,
            plain_text_filtered=plain_text_filtered,
        )

    @staticmethod
    def _filter_html_tweets_plain_text(
        tweets: list[TweetItem],
        *,
        skip_plain_text: bool,
    ) -> tuple[list[TweetItem], int]:
        """HTML items already carry author media; drop pure-text when filtering."""
        if not skip_plain_text or not tweets:
            return tweets, 0
        kept = [tweet for tweet in tweets if tweet.media]
        return kept, len(tweets) - len(kept)

    async def _fetch_group_query(
        self,
        group: ScheduleGroup,
        index: int,
        account_key: str,
        fetch_limit: int,
        *,
        skip_plain_text: bool = False,
        filter_reposts: bool = True,
    ) -> UserFetchResult:
        query_item = next(
            (item for item in group.queries if item.account_key == account_key),
            None,
        )
        if query_item is None:
            return UserFetchResult(
                index=index,
                username=account_key,
                error=SchedulerTaskError.from_exception(
                    RuntimeError(f"missing watch query for {account_key}")
                ),
            )
        if self.html_backend is None:
            return UserFetchResult(
                index=index,
                username=account_key,
                error=SchedulerTaskError.from_exception(
                    RuntimeError("html_backend unavailable")
                ),
            )
        html_backend = self.html_backend
        source_label = format_subscription_source(account_key, group.group_type)

        self._log_verbose_info(
            f"[NitterTweets] 搜索订阅抓取开始: group={group.group_id}, "
            f"source={source_label}, type={query_item.type}, limit={fetch_limit}"
        )

        try:
            instance, tweets = await asyncio.to_thread(
                lambda: html_backend.search(
                    query_item.query,
                    fetch_limit,
                    kind=query_item.type,
                    filter_reposts=filter_reposts,
                )
            )
            retweet_filtered = max(0, int(getattr(tweets, "retweet_filtered", 0) or 0))
            html_raw_item_count = max(0, int(getattr(tweets, "raw_item_count", 0) or 0))
            tweets = list(tweets)
            self._log_verbose_info(
                f"[NitterTweets] 搜索订阅抓取成功: group={group.group_id}, "
                f"source={source_label}, instance={instance}, "
                f"tweets={len(tweets)}"
            )
        except Exception as exc:
            logger.warning(
                f"[NitterTweets] 搜索订阅抓取失败: group={group.group_id}, "
                f"source={source_label}, error={type(exc).__name__}: {exc}"
            )
            return UserFetchResult(
                index=index,
                username=account_key,
                error=SchedulerTaskError.from_exception(exc),
            )
        tweets, plain_text_filtered = self._filter_html_tweets_plain_text(
            tweets, skip_plain_text=skip_plain_text
        )
        return UserFetchResult(
            index=index,
            username=account_key,
            instance=instance,
            tweets=tweets,
            scanned_status_ids=[tweet.status_id for tweet in tweets if tweet.status_id],
            anchor_status_ids=[
                tweet.status_id for tweet in tweets[:20] if tweet.status_id
            ],
            latest_status_id=(tweets[0].status_id if tweets else ""),
            scan_complete=True,
            plain_text_filtered=plain_text_filtered,
            retweet_filtered=retweet_filtered,
            html_raw_item_count=html_raw_item_count,
        )

    async def _fetch_group_list(
        self,
        group: ScheduleGroup,
        index: int,
        account_key: str,
        fetch_limit: int,
        scan_watermark: list[str] | None,
        *,
        skip_plain_text: bool = False,
        filter_reposts: bool = True,
    ) -> UserFetchResult:
        """Fetch Twitter List timeline (serial, HTML backend)."""
        # account_key format: "list:1234567890"
        if not account_key.startswith("list:"):
            return UserFetchResult(
                index=index,
                username=account_key,
                error=SchedulerTaskError.from_exception(
                    RuntimeError(f"invalid list account_key: {account_key}")
                ),
            )

        list_id = account_key[5:]  # strip "list:" prefix
        source_label = format_subscription_source(account_key, group.group_type)

        if self.html_backend is None:
            return UserFetchResult(
                index=index,
                username=account_key,
                error=SchedulerTaskError.from_exception(
                    RuntimeError("html_backend unavailable")
                ),
            )

        self._log_verbose_info(
            f"[NitterTweets] List 抓取开始: group={group.group_id}, "
            f"source={source_label}, limit={fetch_limit}"
        )

        try:
            instance, tweets = await asyncio.to_thread(
                lambda: self.html_backend.fetch_list(
                    list_id,
                    fetch_limit,
                    filter_reposts=filter_reposts,
                    anchor_ids=scan_watermark,
                )
            )
            retweet_filtered = max(0, int(getattr(tweets, "retweet_filtered", 0) or 0))
            html_raw_item_count = max(0, int(getattr(tweets, "raw_item_count", 0) or 0))
            scan_complete = bool(getattr(tweets, "scan_complete", True))
            raw_anchor_status_ids = getattr(tweets, "anchor_status_ids", None)
            # HtmlSearchResult is populated by the HTML layer; only legacy
            # adapters returning a bare list need this compatibility fallback.
            anchor_status_ids = (
                [tweet.status_id for tweet in tweets[:20] if tweet.status_id]
                if raw_anchor_status_ids is None
                else list(raw_anchor_status_ids)
            )
            tweets = list(tweets)
            self._log_verbose_info(
                f"[NitterTweets] List 抓取成功: group={group.group_id}, "
                f"source={source_label}, instance={instance}, "
                f"tweets={len(tweets)}"
            )
        except Exception as exc:
            logger.warning(
                f"[NitterTweets] List 抓取失败: group={group.group_id}, "
                f"source={source_label}, error={type(exc).__name__}: {exc}"
            )
            return UserFetchResult(
                index=index,
                username=account_key,
                error=SchedulerTaskError.from_exception(exc),
            )

        tweets, plain_text_filtered = self._filter_html_tweets_plain_text(
            tweets, skip_plain_text=skip_plain_text
        )

        return UserFetchResult(
            index=index,
            username=account_key,
            instance=instance,
            tweets=tweets,
            scanned_status_ids=[tweet.status_id for tweet in tweets if tweet.status_id],
            anchor_status_ids=anchor_status_ids,
            latest_status_id=(tweets[0].status_id if tweets else ""),
            scan_complete=scan_complete,
            plain_text_filtered=plain_text_filtered,
            retweet_filtered=retweet_filtered,
            html_raw_item_count=html_raw_item_count,
        )

    @staticmethod
    def _should_use_concurrent_fetch(group: ScheduleGroup) -> bool:
        return (
            bool(group.concurrent_fetch_enabled)
            and bool(group.concurrent_fetch_instances)
            and group.fetch_concurrency > 1
        )
