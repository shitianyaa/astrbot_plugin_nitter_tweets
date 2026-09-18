"""抓取阶段：博主时间线、标签搜索与 List。

`NitterTweetScheduler` 的 mixin：只通过 `self` 协作，不 import 宿主类。
只负责产出 `UserFetchResult`；首次 init、水位裁剪等编排留在 `runner.py`。
"""

from __future__ import annotations

import asyncio

from astrbot.api import logger

try:
    from ..config import config_get, parse_config_bool
    from ..media_support.client import NitterClient
    from ..media_support.fxtwitter_client import FxTwitterClient
    from ..shared import TweetItem, format_subscription_source, sanitize_sensitive_text
    from .config import ScheduleGroup
    from .models import SchedulerTaskError, SourceStatus, UserFetchResult
except ImportError:
    from config import config_get, parse_config_bool
    from media_support.client import NitterClient
    from media_support.fxtwitter_client import FxTwitterClient
    from scheduler.config import ScheduleGroup
    from scheduler.models import SchedulerTaskError, SourceStatus, UserFetchResult
    from shared import TweetItem, format_subscription_source, sanitize_sensitive_text


def _classify_html_fetch(
    tweets: list[TweetItem],
    *,
    scan_complete: bool,
    raw_item_count: int,
    retweet_filtered: int,
    plain_text_filtered: int,
) -> str:
    """Classify the HTML result before the scheduler applies seen/watermarks."""
    if (
        not tweets
        and not raw_item_count
        and not retweet_filtered
        and not plain_text_filtered
    ):
        # Nothing parsed at all: the mirror had no usable page, so an
        # incomplete scan cannot rebuild a baseline from it either.  Report
        # "empty" so the scheduler keeps the old watermark instead of logging
        # a baseline-rebuild failure it could never satisfy.
        return SourceStatus.EMPTY
    if not scan_complete:
        return SourceStatus.INCOMPLETE
    if tweets:
        return SourceStatus.SUCCESS
    # Rows existed but every one was filtered (pure RT / plain text / media
    # policy); the first branch already ruled out an all-zero result.
    return SourceStatus.FILTERED_EMPTY


class SchedulerFetchMixin:
    """博主与标签的抓取入口。"""

    @property
    def fetch_backend(self) -> str:
        return (
            str(
                config_get(getattr(self, "config", {}), "fetch_backend", "mix") or "mix"
            )
            .strip()
            .lower()
        )

    @property
    def html_max_pages(self) -> int:
        owner = getattr(self, "owner", None)
        if owner is not None and hasattr(owner, "html_max_pages"):
            return max(1, int(getattr(owner, "html_max_pages", 3) or 3))
        return max(
            1,
            int(config_get(getattr(self, "config", {}), "html_max_pages", 3) or 3),
        )

    def _get_fxtwitter_client(self) -> FxTwitterClient | None:
        client = getattr(self, "fxtwitter", None)
        if client is not None:
            return client
        client = getattr(getattr(self, "owner", None), "fxtwitter", None)
        if client is not None:
            return client
        client = getattr(getattr(self, "nitter", None), "fxtwitter", None)
        if client is not None:
            return client
        if self.fetch_backend == "fx":
            return FxTwitterClient()
        if isinstance(getattr(self, "nitter", None), NitterClient):
            return FxTwitterClient(timeout=getattr(self.nitter, "timeout", 15.0))
        raw_backend = config_get(getattr(self, "config", {}), "fetch_backend", None)
        if raw_backend and str(raw_backend).strip().lower() in ("mix", "fx"):
            return FxTwitterClient()
        return None

    async def _fetch_group_users(
        self,
        group: ScheduleGroup,
        fetch_limit: int,
        skip_plain_text: bool,
        scan_watermarks: dict[str, list[str]],
    ) -> list[UserFetchResult]:
        accounts = list(group.account_keys)
        if not accounts:
            return []

        # Tag/List groups always serial to protect shared HTML instances.
        if group.is_tag_group or group.is_list_group:
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

        # Blogger groups:
        backend = self.fetch_backend
        fx_client = self._get_fxtwitter_client()
        account_to_original_index = {u: i for i, u in enumerate(accounts)}

        if backend in ("mix", "fx") and fx_client is not None:
            filter_reposts = self._effective_filter_reposts(group)
            concurrency = (
                max(1, group.fetch_concurrency) if group.fetch_concurrency else 3
            )
            semaphore = asyncio.Semaphore(concurrency)

            async def fetch_one_fx(
                index: int, username: str
            ) -> tuple[str, UserFetchResult | None, Exception | None]:
                async with semaphore:
                    try:
                        tweets, _ = await asyncio.to_thread(
                            fx_client.fetch_user_timeline,
                            username,
                            count=fetch_limit,
                            skip_plain_text=skip_plain_text,
                            filter_reposts=filter_reposts,
                            max_pages=self.html_max_pages,
                        )
                        scanned_ids = [t.status_id for t in tweets if t.status_id]
                        anchor_ids = [t.status_id for t in tweets[:20] if t.status_id]
                        return (
                            username,
                            UserFetchResult(
                                index=index,
                                username=username,
                                instance="FxTwitter",
                                tweets=tweets,
                                scanned_status_ids=scanned_ids,
                                anchor_status_ids=anchor_ids,
                                latest_status_id=(
                                    tweets[0].status_id if tweets else ""
                                ),
                                scan_complete=True,
                                plain_text_filtered=0,
                                fetch_status=(
                                    SourceStatus.SUCCESS
                                    if tweets
                                    else SourceStatus.EMPTY
                                ),
                                host_attempts=["FxTwitter=成功"],
                            ),
                            None,
                        )
                    except Exception as exc:
                        return (username, None, exc)

            tasks = [fetch_one_fx(idx, u) for idx, u in enumerate(accounts)]
            fx_results = await asyncio.gather(*tasks)

            fx_batches: list[UserFetchResult] = []
            failed_accounts: list[str] = []
            for username, fetch_res, exc in fx_results:
                if fetch_res is not None:
                    fx_batches.append(fetch_res)
                else:
                    failed_accounts.append(username)

            if not failed_accounts:
                fx_batches.sort(
                    key=lambda r: account_to_original_index.get(r.username, r.index)
                )
                return fx_batches

            if backend == "fx":
                for username, fetch_res, exc in fx_results:
                    if fetch_res is None:
                        fx_batches.append(
                            UserFetchResult(
                                index=account_to_original_index.get(
                                    username, accounts.index(username)
                                ),
                                username=username,
                                instance="FxTwitter",
                                host_attempts=["FxTwitter=失败"],
                                error=SchedulerTaskError.from_exception(
                                    exc or RuntimeError("FxTwitter fetch failed")
                                ),
                            )
                        )
                fx_batches.sort(
                    key=lambda r: account_to_original_index.get(r.username, r.index)
                )
                return fx_batches

            # backend == "mix" and failed_accounts exists
            failed_preview = ", ".join(f"@{u}" for u in failed_accounts[:5])
            if len(failed_accounts) > 5:
                failed_preview += f" 等 {len(failed_accounts)} 位博主"
            logger.warning(
                f"[NitterTweets] FxTwitter 抓取异常平滑回退自建 Nitter: "
                f"group={group.group_id}, 失败博主数={len(failed_accounts)} "
                f"({sanitize_sensitive_text(failed_preview)})"
            )

            # Incremental takeover: only failed_accounts handed to Nitter pipeline
            if len(failed_accounts) > 1 and self._effective_filter_reposts(group):
                nitter_batches = await self._fetch_group_users_merged(
                    group,
                    failed_accounts,
                    fetch_limit,
                    skip_plain_text,
                    scan_watermarks,
                )
                for res in nitter_batches:
                    res.index = account_to_original_index.get(res.username, res.index)
            else:
                nitter_batches = []
                for index, username in enumerate(failed_accounts):
                    if index > 0 and group.send_user_interval > 0:
                        await asyncio.sleep(group.send_user_interval)
                    orig_idx = account_to_original_index.get(username, index)
                    nitter_batches.append(
                        await self._fetch_group_user(
                            group,
                            orig_idx,
                            username,
                            fetch_limit,
                            skip_plain_text,
                            scan_watermarks.get(username),
                            concurrent=False,
                            force_nitter=True,
                        )
                    )
            for res in nitter_batches:
                res.index = account_to_original_index.get(res.username, res.index)
                nitter_attempt = (
                    f"{res.instance or 'Nitter'}=成功"
                    if not res.error
                    else f"{res.instance or 'Nitter'}=失败"
                )
                res.host_attempts = [
                    "FxTwitter=失败",
                    *(res.host_attempts or [nitter_attempt]),
                ]
            all_results = fx_batches + nitter_batches
            all_results.sort(
                key=lambda r: account_to_original_index.get(r.username, r.index)
            )
            return all_results

        # Blogger Nitter path (backend == "nitter" or fallback when fx_client is None)
        if len(accounts) > 1 and self._effective_filter_reposts(group):
            return await self._fetch_group_users_merged(
                group,
                accounts,
                fetch_limit,
                skip_plain_text,
                scan_watermarks,
            )
        if not self._should_use_concurrent_fetch(group):
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
                        force_nitter=True,
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
                    force_nitter=True,
                )

        tasks = [
            fetch_with_limit(index, username) for index, username in enumerate(accounts)
        ]
        return list(await asyncio.gather(*tasks))

    async def _fetch_group_users_merged(
        self,
        group: ScheduleGroup,
        accounts: list[str],
        fetch_limit: int,
        skip_plain_text: bool,
        scan_watermarks: dict[str, list[str]],
    ) -> list[UserFetchResult]:
        """Fetch blogger group via merged RSS, falling back to per-user."""
        filter_reposts = self._effective_filter_reposts(group)
        batches = NitterClient.batch_usernames_by_path_length(accounts)
        results: list[UserFetchResult] = []
        global_index = 0

        for batch_i, batch in enumerate(batches):
            if batch_i > 0 and group.send_user_interval > 0:
                await asyncio.sleep(group.send_user_interval)

            batch_watermarks = {
                username: scan_watermarks.get(username) for username in batch
            }
            source_label = f"@{batch[0]}" if len(batch) == 1 else f"{len(batch)} 位博主"
            self._log_verbose_info(
                f"[NitterTweets] 合并 RSS 抓取开始: group={group.group_id}, "
                f"users={source_label}, batch={batch_i + 1}/{len(batches)}"
            )

            try:
                instance, merged_results = await self.nitter.fetch_merged_for_scheduler(
                    batch,
                    batch_watermarks,
                    skip_plain_text=skip_plain_text,
                    filter_reposts=filter_reposts,
                    media=skip_plain_text and filter_reposts,
                )
            except Exception as exc:
                error_label = sanitize_sensitive_text(str(exc))
                logger.warning(
                    f"[NitterTweets] 合并 RSS 抓取失败，回退逐个请求: "
                    f"group={group.group_id}, batch={batch_i + 1}/{len(batches)}, "
                    f"error={type(exc).__name__}: {error_label}"
                )
                # Fall back to per-user for the entire batch
                for username in batch:
                    if global_index > 0 and group.send_user_interval > 0:
                        await asyncio.sleep(group.send_user_interval)
                    results.append(
                        await self._fetch_group_user(
                            group,
                            global_index,
                            username,
                            fetch_limit,
                            skip_plain_text,
                            scan_watermarks.get(username),
                            concurrent=False,
                            force_nitter=True,
                        )
                    )
                    global_index += 1
                continue

            # Build per-user results from the merged scan; fall back to
            # per-user for any user with no tweets in the merged feed.
            for username in batch:
                scan_result = merged_results.get(username)
                if scan_result and scan_result.tweets:
                    self._log_verbose_info(
                        f"[NitterTweets] 合并 RSS 命中 @{username}: "
                        f"tweets={len(scan_result.tweets)}"
                    )
                    results.append(
                        UserFetchResult(
                            index=global_index,
                            username=username,
                            instance=instance,
                            tweets=list(scan_result.tweets),
                            scanned_status_ids=list(scan_result.scanned_status_ids),
                            anchor_status_ids=list(scan_result.anchor_status_ids),
                            latest_status_id=str(scan_result.latest_status_id or ""),
                            scan_complete=bool(scan_result.complete),
                            plain_text_filtered=int(
                                scan_result.plain_text_filtered or 0
                            ),
                            host_attempts=[f"{instance or 'Nitter'}=成功"],
                        )
                    )
                else:
                    # No tweets for this user in merged feed; try per-user
                    # RSS/HTML to catch anything the merged scan missed.
                    results.append(
                        await self._fetch_group_user(
                            group,
                            global_index,
                            username,
                            fetch_limit,
                            skip_plain_text,
                            scan_watermarks.get(username),
                            concurrent=False,
                            force_nitter=True,
                        )
                    )
                global_index += 1

        return results

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
        force_nitter: bool = False,
    ) -> UserFetchResult:
        filter_reposts = self._effective_filter_reposts(group)
        if group.is_tag_group:
            return await self._fetch_group_tag(
                group,
                index,
                username,
                fetch_limit,
                skip_plain_text=skip_plain_text,
                filter_reposts=filter_reposts,
                scan_watermark=scan_watermark,
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

        backend = self.fetch_backend
        fx_client = self._get_fxtwitter_client()
        fx_failed_attempt: str | None = None
        if (
            not force_nitter
            and not concurrent
            and backend in ("mix", "fx")
            and fx_client is not None
        ):
            try:
                tweets, _ = await asyncio.to_thread(
                    fx_client.fetch_user_timeline,
                    username,
                    count=fetch_limit,
                    skip_plain_text=skip_plain_text,
                    filter_reposts=filter_reposts,
                    max_pages=self.html_max_pages,
                )
                scanned_ids = [t.status_id for t in tweets if t.status_id]
                anchor_ids = [t.status_id for t in tweets[:20] if t.status_id]
                return UserFetchResult(
                    index=index,
                    username=username,
                    instance="FxTwitter",
                    tweets=tweets,
                    scanned_status_ids=scanned_ids,
                    anchor_status_ids=anchor_ids,
                    latest_status_id=(tweets[0].status_id if tweets else ""),
                    scan_complete=True,
                    plain_text_filtered=0,
                    fetch_status=(
                        SourceStatus.SUCCESS if tweets else SourceStatus.EMPTY
                    ),
                    host_attempts=["FxTwitter=成功"],
                )
            except Exception as exc:
                if backend == "fx":
                    logger.warning(
                        f"[NitterTweets] FxTwitter 抓取 @{username} 失败 (fx模式): "
                        f"{type(exc).__name__}: {sanitize_sensitive_text(str(exc))}"
                    )
                    return UserFetchResult(
                        index=index,
                        username=username,
                        instance="FxTwitter",
                        host_attempts=["FxTwitter=失败"],
                        error=SchedulerTaskError.from_exception(exc),
                    )
                logger.warning(
                    f"[NitterTweets] FxTwitter 抓取 @{username} 异常，平滑回退自建 Nitter: "
                    f"{type(exc).__name__}: {sanitize_sensitive_text(str(exc))}"
                )
                fx_failed_attempt = "FxTwitter=失败"

        def _with_fx_fallback(res: UserFetchResult) -> UserFetchResult:
            if fx_failed_attempt:
                nitter_attempt = (
                    f"{res.instance or 'Nitter'}=成功"
                    if not res.error
                    else f"{res.instance or 'Nitter'}=失败"
                )
                res.host_attempts = [
                    fx_failed_attempt,
                    *(res.host_attempts or [nitter_attempt]),
                ]
            return res

        try:
            # /<user>/media/rss shows only the author's own media uploads
            # and excludes ALL retweets.  Only switch to it when both
            # plain-text and repost filtering are active; otherwise keep
            # the regular RSS feed and filter plain text locally so that
            # retweets the user wants to keep are not silently dropped.
            use_media_path = skip_plain_text and filter_reposts
            media_path = f"{username}/media" if use_media_path else ""
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
                        self.nitter.instances,
                        start_index=index,
                        skip_plain_text=skip_plain_text,
                        retry_attempts=getattr(self.nitter, "retry_attempts", 2),
                        filter_reposts=filter_reposts,
                        path_override=media_path,
                    )
                else:
                    instance, scan_result = await fetch_for_scheduler(
                        username,
                        scan_watermark,
                        skip_plain_text=skip_plain_text,
                        filter_reposts=filter_reposts,
                        path_override=media_path,
                    )
                raw_anchor_status_ids = getattr(scan_result, "anchor_status_ids", None)
                anchor_status_ids = (
                    list(scan_result.scanned_status_ids)[:20]
                    if raw_anchor_status_ids is None
                    else list(raw_anchor_status_ids)
                )
                tweets = list(scan_result.tweets)
                if not tweets:
                    html_result = await self._fetch_user_html_after_rss(
                        index,
                        username,
                        fetch_limit,
                        skip_plain_text=skip_plain_text,
                        filter_reposts=filter_reposts,
                    )
                    if html_result is not None:
                        return _with_fx_fallback(html_result)
                return _with_fx_fallback(
                    UserFetchResult(
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
                )

            if concurrent:
                (
                    instance,
                    tweets,
                    plain_text_filtered,
                ) = await self.nitter.fetch_tweets_with_stats_from_instances(
                    username,
                    fetch_limit,
                    self.nitter.instances,
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
            if not tweets:
                html_result = await self._fetch_user_html_after_rss(
                    index,
                    username,
                    fetch_limit,
                    skip_plain_text=skip_plain_text,
                    filter_reposts=filter_reposts,
                )
                if html_result is not None:
                    return _with_fx_fallback(html_result)
        except Exception as exc:
            html_result = await self._fetch_user_html_after_rss(
                index,
                username,
                fetch_limit,
                skip_plain_text=skip_plain_text,
                filter_reposts=filter_reposts,
            )
            if html_result is not None:
                return _with_fx_fallback(html_result)
            return _with_fx_fallback(
                UserFetchResult(
                    index=index,
                    username=username,
                    error=SchedulerTaskError.from_exception(exc),
                )
            )
        return _with_fx_fallback(
            UserFetchResult(
                index=index,
                username=username,
                instance=instance,
                tweets=tweets,
                scanned_status_ids=[
                    tweet.status_id for tweet in tweets if tweet.status_id
                ],
                anchor_status_ids=[
                    tweet.status_id for tweet in tweets[:20] if tweet.status_id
                ],
                latest_status_id=(tweets[0].status_id if tweets else ""),
                plain_text_filtered=plain_text_filtered,
            )
        )

    def _effective_filter_reposts(self, group: ScheduleGroup) -> bool:
        global_enabled = parse_config_bool(
            config_get(self.config, "filter_reposts_enabled", True),
            True,
        )
        return global_enabled and bool(getattr(group, "filter_reposts_enabled", True))

    async def _fetch_user_html_after_rss(
        self,
        index: int,
        username: str,
        fetch_limit: int,
        *,
        skip_plain_text: bool = False,
        filter_reposts: bool = True,
    ) -> UserFetchResult | None:
        try:
            instance, tweets = await asyncio.to_thread(
                lambda: self.nitter.fetch_user_html(
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

    async def _fetch_group_tag(
        self,
        group: ScheduleGroup,
        index: int,
        account_key: str,
        fetch_limit: int,
        *,
        skip_plain_text: bool = False,
        filter_reposts: bool = True,
        scan_watermark: list[str] | None = None,
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
        source_label = format_subscription_source(account_key, group.group_type)

        backend = self.fetch_backend
        fx_client = self._get_fxtwitter_client()
        fx_failed_attempt: str | None = None

        if backend in ("mix", "fx") and fx_client is not None:
            try:
                self._log_verbose_info(
                    f"[NitterTweets] FxTwitter 搜索订阅抓取开始: group={group.group_id}, "
                    f"source={source_label}, type={query_item.type}, limit={fetch_limit}"
                )
                effective_query = query_item.query
                tweets, _ = await asyncio.to_thread(
                    fx_client.search_tweets,
                    effective_query,
                    count=fetch_limit,
                    is_media=skip_plain_text,
                )
                retweet_filtered = 0
                if filter_reposts:
                    orig_len = len(tweets)
                    tweets = [t for t in tweets if not t.is_retweet]
                    retweet_filtered = orig_len - len(tweets)
                tweets, plain_text_filtered = self._filter_html_tweets_plain_text(
                    tweets, skip_plain_text=skip_plain_text
                )
                scanned_ids = [t.status_id for t in tweets if t.status_id]
                anchor_ids = [t.status_id for t in tweets[:20] if t.status_id]
                self._log_verbose_info(
                    f"[NitterTweets] FxTwitter 搜索订阅抓取成功: group={group.group_id}, "
                    f"source={source_label}, instance=FxTwitter, "
                    f"tweets={len(tweets)}"
                )
                return UserFetchResult(
                    index=index,
                    username=account_key,
                    instance="FxTwitter",
                    tweets=tweets,
                    scanned_status_ids=scanned_ids,
                    anchor_status_ids=anchor_ids,
                    latest_status_id=(tweets[0].status_id if tweets else ""),
                    scan_complete=True,
                    plain_text_filtered=plain_text_filtered,
                    retweet_filtered=retweet_filtered,
                    fetch_status=(
                        SourceStatus.SUCCESS if tweets else SourceStatus.EMPTY
                    ),
                    host_attempts=["FxTwitter=成功"],
                )
            except Exception as exc:
                if backend == "fx":
                    logger.warning(
                        f"[NitterTweets] FxTwitter 搜索订阅抓取失败 (fx模式): group={group.group_id}, "
                        f"source={source_label}, error={type(exc).__name__}: {sanitize_sensitive_text(str(exc))}"
                    )
                    return UserFetchResult(
                        index=index,
                        username=account_key,
                        instance="FxTwitter",
                        host_attempts=["FxTwitter=失败"],
                        error=SchedulerTaskError.from_exception(exc),
                    )
                logger.warning(
                    f"[NitterTweets] FxTwitter 标签搜索抓取异常，平滑回退自建 Nitter HTML: "
                    f"group={group.group_id}, source={source_label}, "
                    f"error={type(exc).__name__}: {sanitize_sensitive_text(str(exc))}"
                )
                fx_failed_attempt = "FxTwitter=失败"

        res = await self._fetch_group_tag_html(
            group,
            index,
            account_key,
            query_item,
            source_label,
            fetch_limit,
            skip_plain_text=skip_plain_text,
            filter_reposts=filter_reposts,
            scan_watermark=scan_watermark,
        )
        if fx_failed_attempt:
            nitter_attempt = (
                f"{res.instance or 'Nitter'}=成功"
                if not res.error
                else f"{res.instance or 'Nitter'}=失败"
            )
            res.host_attempts = [
                fx_failed_attempt,
                *(res.host_attempts or [nitter_attempt]),
            ]
        return res

    async def _fetch_group_query(
        self,
        group: ScheduleGroup,
        index: int,
        account_key: str,
        fetch_limit: int,
        *,
        skip_plain_text: bool = False,
        filter_reposts: bool = True,
        scan_watermark: list[str] | None = None,
    ) -> UserFetchResult:
        return await self._fetch_group_tag(
            group,
            index,
            account_key,
            fetch_limit,
            skip_plain_text=skip_plain_text,
            filter_reposts=filter_reposts,
            scan_watermark=scan_watermark,
        )

    async def _fetch_group_tag_html(
        self,
        group: ScheduleGroup,
        index: int,
        account_key: str,
        query_item,
        source_label: str,
        fetch_limit: int,
        *,
        skip_plain_text: bool = False,
        filter_reposts: bool = True,
        scan_watermark: list[str] | None = None,
    ) -> UserFetchResult:
        self._log_verbose_info(
            f"[NitterTweets] 搜索订阅抓取开始: group={group.group_id}, "
            f"source={source_label}, type={query_item.type}, limit={fetch_limit}"
        )

        try:
            # When filter_plain_text is on, append filter:media for server-side
            # filtering so Nitter returns only media-carrying tweets.
            effective_query = query_item.query
            if skip_plain_text and "filter:media" not in effective_query:
                effective_query = f"{effective_query} filter:media"
            search_kwargs = {
                "kind": query_item.type,
                "filter_reposts": filter_reposts,
                # Background tag scanning must always use f=tweets (time order)
                # for correct incremental seen/watermark logic; never f=top.
                "sort": "latest",
            }
            if scan_watermark is not None:
                search_kwargs["anchor_ids"] = scan_watermark
            instance, tweets = await asyncio.to_thread(
                lambda: self.nitter.search(
                    effective_query,
                    fetch_limit,
                    **search_kwargs,
                )
            )
            retweet_filtered = max(0, int(getattr(tweets, "retweet_filtered", 0) or 0))
            html_raw_item_count = max(0, int(getattr(tweets, "raw_item_count", 0) or 0))
            scan_complete = bool(getattr(tweets, "scan_complete", True))
            raw_anchor_status_ids = getattr(tweets, "anchor_status_ids", None)
            anchor_status_ids = (
                [tweet.status_id for tweet in tweets[:20] if tweet.status_id]
                if raw_anchor_status_ids is None
                else list(raw_anchor_status_ids)
            )
            host_attempts = list(getattr(tweets, "host_attempts", []) or [])
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
            anchor_status_ids=anchor_status_ids,
            latest_status_id=(tweets[0].status_id if tweets else ""),
            scan_complete=scan_complete,
            plain_text_filtered=plain_text_filtered,
            retweet_filtered=retweet_filtered,
            html_raw_item_count=html_raw_item_count,
            fetch_status=_classify_html_fetch(
                tweets,
                scan_complete=scan_complete,
                raw_item_count=html_raw_item_count,
                retweet_filtered=retweet_filtered,
                plain_text_filtered=plain_text_filtered,
            ),
            host_attempts=host_attempts,
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
        """Fetch Twitter List timeline: RSS first, HTML fallback."""
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

        self._log_verbose_info(
            f"[NitterTweets] List 抓取开始: group={group.group_id}, "
            f"source={source_label}, limit={fetch_limit}"
        )

        # --- RSS path (primary) ---
        rss_error: Exception | None = None
        try:
            instance, scan_result = await self.nitter.fetch_list_for_scheduler(
                list_id,
                scan_watermark,
                skip_plain_text=skip_plain_text,
                filter_reposts=filter_reposts,
            )
            tweets = list(scan_result.tweets)
            if tweets or scan_result.complete:
                self._log_verbose_info(
                    f"[NitterTweets] List RSS 抓取成功: group={group.group_id}, "
                    f"source={source_label}, instance={instance}, "
                    f"tweets={len(tweets)}"
                )
                return UserFetchResult(
                    index=index,
                    username=account_key,
                    instance=instance,
                    tweets=tweets,
                    scanned_status_ids=list(scan_result.scanned_status_ids),
                    anchor_status_ids=list(scan_result.anchor_status_ids),
                    latest_status_id=str(scan_result.latest_status_id or ""),
                    scan_complete=bool(scan_result.complete),
                    plain_text_filtered=int(scan_result.plain_text_filtered or 0),
                )
        except Exception as exc:
            rss_error = exc
            error_label = sanitize_sensitive_text(str(exc))
            logger.warning(
                f"[NitterTweets] List RSS 抓取失败，尝试 HTML 后备: "
                f"group={group.group_id}, source={source_label}, "
                f"error={type(exc).__name__}: {error_label}"
            )

        # --- HTML path (fallback) ---
        try:
            instance, tweets = await asyncio.to_thread(
                lambda: self.nitter.fetch_list(
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
            anchor_status_ids = (
                [tweet.status_id for tweet in tweets[:20] if tweet.status_id]
                if raw_anchor_status_ids is None
                else list(raw_anchor_status_ids)
            )
            host_attempts = list(getattr(tweets, "host_attempts", []) or [])
            tweets = list(tweets)
            self._log_verbose_info(
                f"[NitterTweets] List HTML 后备抓取成功: group={group.group_id}, "
                f"source={source_label}, instance={instance}, "
                f"tweets={len(tweets)}"
            )
        except Exception as exc:
            logger.warning(
                f"[NitterTweets] List 抓取失败: group={group.group_id}, "
                f"source={source_label}, error={type(exc).__name__}: {exc}"
            )
            if rss_error is not None:
                return UserFetchResult(
                    index=index,
                    username=account_key,
                    error=SchedulerTaskError.from_exception(rss_error),
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
            fetch_status=_classify_html_fetch(
                tweets,
                scan_complete=scan_complete,
                raw_item_count=html_raw_item_count,
                retweet_filtered=retweet_filtered,
                plain_text_filtered=plain_text_filtered,
            ),
            host_attempts=host_attempts,
        )

    def _should_use_concurrent_fetch(self, group: ScheduleGroup) -> bool:
        return (
            bool(group.concurrent_fetch_enabled)
            and bool(getattr(self.nitter, "instances", []))
            and group.fetch_concurrency > 1
        )
