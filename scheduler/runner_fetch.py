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
    from ..query import FetchStatus, QueryService, SearchQuery, TimelineQuery
    from ..query.models import FetchOutcome
    from ..shared import (
        TweetItem,
        format_subscription_source,
        redact_instance_urls,
        sanitize_sensitive_text,
    )
    from .config import ScheduleGroup
    from .models import SchedulerTaskError, SourceStatus, UserFetchResult
except ImportError:
    from config import config_get, parse_config_bool
    from media_support.client import NitterClient
    from media_support.fxtwitter_client import FxTwitterClient
    from query import FetchStatus, QueryService, SearchQuery, TimelineQuery
    from query.models import FetchOutcome
    from scheduler.config import ScheduleGroup
    from scheduler.models import SchedulerTaskError, SourceStatus, UserFetchResult
    from shared import (
        TweetItem,
        format_subscription_source,
        redact_instance_urls,
        sanitize_sensitive_text,
    )


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


class _SchedulerNitterAdapter:
    """Keep the scheduler's RSS warning and run-scoped host-skip ownership.

    The scheduler already manages its run-scoped Nitter host-skip context.
    QueryService's optional per-query begin/end must not start a second
    context for any scan; other Nitter fetch methods are delegated unchanged.
    """

    def __init__(
        self,
        nitter,
        on_rss_error=None,
        *,
        start_index: int | None = None,
        on_merged_error=None,
    ):
        self._nitter = nitter
        self._on_rss_error = on_rss_error
        self._start_index = start_index
        self._on_merged_error = on_merged_error
        self.list_rss_used = False

    def __getattr__(self, name):
        if name in {"begin_run_host_skip", "end_run_host_skip"}:
            return None
        return getattr(self._nitter, name)

    async def fetch_tweets_for_scheduler(self, username, anchor_ids, **kwargs):
        if self._start_index is not None:
            return await self._nitter.fetch_tweets_for_scheduler_from_instances(
                username,
                anchor_ids,
                self._nitter.instances,
                start_index=self._start_index,
                retry_attempts=getattr(self._nitter, "retry_attempts", 2),
                **kwargs,
            )
        return await self._nitter.fetch_tweets_for_scheduler(
            username, anchor_ids, **kwargs
        )

    async def fetch_list_for_scheduler(self, *args, **kwargs):
        try:
            result = await self._nitter.fetch_list_for_scheduler(*args, **kwargs)
            scan = result[1]
            self.list_rss_used = bool(scan.tweets or scan.complete)
            return result
        except Exception as exc:
            if self._on_rss_error is not None:
                self._on_rss_error(exc)
            raise

    async def fetch_merged_for_scheduler(self, *args, **kwargs):
        try:
            return await self._nitter.fetch_merged_for_scheduler(*args, **kwargs)
        except Exception as exc:
            if self._on_merged_error is not None:
                self._on_merged_error(exc)
            raise


class _SchedulerFxAdapter:
    """Keep the original FX exception available for scheduler error summaries.

    QueryService only exposes safe error categories to ordinary callers.
    """

    def __init__(self, client, *, search_media: bool | None = None):
        self._client = client
        self._search_media = search_media
        self.failure: Exception | None = None

    def fetch_user_timeline(self, *args, **kwargs):
        try:
            return self._client.fetch_user_timeline(*args, **kwargs)
        except Exception as exc:
            self.failure = exc
            raise

    def search_tweets(self, *args, **kwargs):
        if self._search_media is not None:
            # Preserve Tag's legacy Fx request and its local filter ordering.
            kwargs.pop("feed", None)
            kwargs["is_media"] = self._search_media
        try:
            return self._client.search_tweets(*args, **kwargs)
        except Exception as exc:
            self.failure = exc
            raise


class SchedulerFetchMixin:
    """博主与标签的抓取入口。"""

    def _nitter_query_service(
        self, *, start_index: int | None = None, on_merged_error=None
    ) -> QueryService:
        # Background orchestration chooses the backend itself (including
        # mixed-mode batch fallbacks). A scan adapter must never auto-fall
        # back via the ordinary 5/10-item timeline query.
        return QueryService(
            _SchedulerNitterAdapter(
                self.nitter,
                start_index=start_index,
                on_merged_error=on_merged_error,
            ),
            fetch_backend="nitter",
        )

    async def _fx_timeline_outcome(
        self,
        client: FxTwitterClient,
        username: str,
        fetch_limit: int,
        *,
        skip_plain_text: bool,
        filter_reposts: bool,
    ) -> tuple[FetchOutcome, Exception | None]:
        adapter = _SchedulerFxAdapter(client)
        outcome = await QueryService(
            self.nitter, adapter, fetch_backend="fx"
        ).fetch_timeline(
            TimelineQuery(
                username,
                limit=fetch_limit,
                skip_plain_text=skip_plain_text,
                filter_reposts=filter_reposts,
                max_pages=self.html_max_pages,
            )
        )
        return outcome, adapter.failure

    @staticmethod
    def _query_to_user_result(
        outcome: FetchOutcome,
        index: int,
        account_key: str,
        *,
        html_stats: bool = False,
    ) -> UserFetchResult:
        if outcome.status == FetchStatus.ERROR:
            return UserFetchResult(
                index=index,
                username=account_key,
                instance=outcome.instance,
                error=SchedulerTaskError(
                    message=outcome.error_kind or "查询失败",
                    kind=outcome.error_kind,
                ),
                host_attempts=list(outcome.host_attempts),
            )
        return UserFetchResult(
            index=index,
            username=account_key,
            instance=outcome.instance,
            tweets=list(outcome.tweets),
            scanned_status_ids=list(outcome.scanned_status_ids),
            anchor_status_ids=list(outcome.anchor_status_ids),
            latest_status_id=outcome.latest_status_id,
            scan_complete=outcome.scan_complete,
            plain_text_filtered=outcome.plain_text_filtered,
            retweet_filtered=outcome.retweet_filtered if html_stats else 0,
            html_raw_item_count=outcome.raw_item_count if html_stats else 0,
            fetch_status=(
                str(outcome.status) if html_stats or outcome.backend == "fx" else ""
            ),
            host_attempts=list(outcome.host_attempts),
        )

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
                    outcome, failure = await self._fx_timeline_outcome(
                        fx_client,
                        username,
                        fetch_limit,
                        skip_plain_text=skip_plain_text,
                        filter_reposts=filter_reposts,
                    )
                    if outcome.status == FetchStatus.ERROR:
                        return (
                            username,
                            None,
                            failure or RuntimeError(outcome.error_kind),
                        )
                    return (
                        username,
                        self._query_to_user_result(outcome, index, username),
                        None,
                    )

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
                nitter_attempt = "Nitter=成功" if not res.error else "Nitter=失败"
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

            merged_errors: list[Exception] = []
            try:
                merged_results = await self._nitter_query_service(
                    on_merged_error=merged_errors.append
                ).scan_merged(
                    batch,
                    batch_watermarks,
                    skip_plain_text=skip_plain_text,
                    filter_reposts=filter_reposts,
                )
                failed = next(
                    (
                        result
                        for result in merged_results.values()
                        if result.status == FetchStatus.ERROR
                    ),
                    None,
                )
                if failed is not None:
                    raise (
                        merged_errors[-1]
                        if merged_errors
                        else RuntimeError(failed.error_kind or "merged scan failed")
                    )
            except Exception as exc:
                error_label = sanitize_sensitive_text(redact_instance_urls(str(exc)))
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
                        self._query_to_user_result(scan_result, global_index, username)
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
            outcome, failure = await self._fx_timeline_outcome(
                fx_client,
                username,
                fetch_limit,
                skip_plain_text=skip_plain_text,
                filter_reposts=filter_reposts,
            )
            if outcome.status != FetchStatus.ERROR:
                return self._query_to_user_result(outcome, index, username)
            failure = failure or RuntimeError(outcome.error_kind)
            detail = sanitize_sensitive_text(redact_instance_urls(str(failure)))
            if backend == "fx":
                logger.warning(
                    f"[NitterTweets] FxTwitter 抓取 @{username} 失败 (fx模式): "
                    f"{type(failure).__name__}: {detail}"
                )
                return UserFetchResult(
                    index=index,
                    username=username,
                    instance="FxTwitter",
                    host_attempts=["FxTwitter=失败"],
                    error=SchedulerTaskError.from_exception(failure),
                )
            logger.warning(
                f"[NitterTweets] FxTwitter 抓取 @{username} 异常，平滑回退自建 Nitter: "
                f"{type(failure).__name__}: {detail}"
            )
            fx_failed_attempt = "FxTwitter=失败"

        def _with_fx_fallback(res: UserFetchResult) -> UserFetchResult:
            if fx_failed_attempt:
                nitter_attempt = "Nitter=成功" if not res.error else "Nitter=失败"
                res.host_attempts = [
                    fx_failed_attempt,
                    *(res.host_attempts or [nitter_attempt]),
                ]
            return res

        # The scan uses the same query adapter in both serial and rotated
        # concurrent modes; the adapter preserves per-instance start_index
        # and retry_attempts. Seen/watermark handling remains in the runner.
        scheduler_method = (
            "fetch_tweets_for_scheduler_from_instances"
            if concurrent
            else "fetch_tweets_for_scheduler"
        )
        if callable(getattr(self.nitter, scheduler_method, None)):
            outcome = await self._nitter_query_service(
                start_index=index if concurrent else None
            ).scan_timeline(
                username,
                scan_watermark,
                skip_plain_text=skip_plain_text,
                filter_reposts=filter_reposts,
            )
            if outcome.status == FetchStatus.ERROR or not outcome.tweets:
                html_result = await self._fetch_user_html_after_rss(
                    index,
                    username,
                    fetch_limit,
                    skip_plain_text=skip_plain_text,
                    filter_reposts=filter_reposts,
                )
                if html_result is not None:
                    return _with_fx_fallback(html_result)
            result = self._query_to_user_result(outcome, index, username)
            # A plain successful RSS fetch did not previously add a synthetic
            # host trace. FX fallback gets its trace from _with_fx_fallback.
            result.host_attempts.clear()
            return _with_fx_fallback(result)

        try:
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
                f"[NitterTweets] HTML 用户页回退失败: @{username}, "
                f"error={sanitize_sensitive_text(redact_instance_urls(str(exc)))}"
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
        # A search subscription can contain arbitrary text or credentials.
        # Keep its raw key only for matching seen/watermarks, never logs.
        source_label = "搜索订阅（内容已隐藏）"

        backend = self.fetch_backend
        fx_client = self._get_fxtwitter_client()
        fx_failed_attempt: str | None = None

        if backend in ("mix", "fx") and fx_client is not None:
            self._log_verbose_info(
                f"[NitterTweets] FxTwitter 搜索订阅抓取开始: group={group.group_id}, "
                f"source={source_label}, type={query_item.type}, limit={fetch_limit}"
            )
            fx_adapter = _SchedulerFxAdapter(fx_client, search_media=skip_plain_text)
            outcome = await QueryService(
                self.nitter, fx_adapter, fetch_backend="fx"
            ).search(SearchQuery(query_item.query, limit=fetch_limit))
            if outcome.status != FetchStatus.ERROR:
                tweets = list(outcome.tweets)
                retweet_filtered = 0
                if filter_reposts:
                    original_count = len(tweets)
                    tweets = [tweet for tweet in tweets if not tweet.is_retweet]
                    retweet_filtered = original_count - len(tweets)
                tweets, plain_text_filtered = self._filter_html_tweets_plain_text(
                    tweets, skip_plain_text=skip_plain_text
                )
                self._log_verbose_info(
                    f"[NitterTweets] FxTwitter 搜索订阅抓取成功: group={group.group_id}, "
                    f"source={source_label}, instance=FxTwitter, "
                    f"tweets={len(tweets)}"
                )
                result = self._query_to_user_result(outcome, index, account_key)
                result.tweets = tweets
                result.scanned_status_ids = [
                    tweet.status_id for tweet in tweets if tweet.status_id
                ]
                result.anchor_status_ids = [
                    tweet.status_id for tweet in tweets[:20] if tweet.status_id
                ]
                result.latest_status_id = tweets[0].status_id if tweets else ""
                result.retweet_filtered = retweet_filtered
                result.plain_text_filtered = plain_text_filtered
                result.fetch_status = (
                    SourceStatus.SUCCESS if tweets else SourceStatus.EMPTY
                )
                return result

            failure = fx_adapter.failure or RuntimeError(outcome.error_kind)
            detail = sanitize_sensitive_text(redact_instance_urls(str(failure)))
            if backend == "fx":
                logger.warning(
                    f"[NitterTweets] FxTwitter 搜索订阅抓取失败 (fx模式): group={group.group_id}, "
                    f"source={source_label}, error={type(failure).__name__}: {detail}"
                )
                return UserFetchResult(
                    index=index,
                    username=account_key,
                    instance="FxTwitter",
                    host_attempts=["FxTwitter=失败"],
                    error=SchedulerTaskError.from_exception(failure),
                )
            logger.warning(
                "[NitterTweets] FxTwitter 标签搜索抓取异常，平滑回退自建 Nitter HTML: "
                f"group={group.group_id}, source={source_label}, "
                f"error={type(failure).__name__}: {detail}"
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
            nitter_attempt = "Nitter=成功" if not res.error else "Nitter=失败"
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
        outcome = await self._nitter_query_service().scan_search(
            query_item.query,
            fetch_limit,
            kind=query_item.type,
            anchor_ids=scan_watermark,
            skip_plain_text=skip_plain_text,
            filter_reposts=filter_reposts,
        )
        if outcome.status == FetchStatus.ERROR:
            logger.warning(
                f"[NitterTweets] 搜索订阅抓取失败: group={group.group_id}, "
                f"source={source_label}, error={outcome.error_kind}"
            )
        else:
            self._log_verbose_info(
                f"[NitterTweets] 搜索订阅抓取成功: group={group.group_id}, "
                f"source={source_label}, tweets={len(outcome.tweets)}"
            )
        return self._query_to_user_result(outcome, index, account_key, html_stats=True)

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
        """Fetch a Public List with its existing RSS-first/HTML-fallback scan."""
        if not account_key.startswith("list:"):
            return UserFetchResult(
                index=index,
                username=account_key,
                error=SchedulerTaskError.from_exception(
                    RuntimeError(f"invalid list account_key: {account_key}")
                ),
            )

        list_id = account_key[5:]
        source_label = format_subscription_source(account_key, group.group_type)
        self._log_verbose_info(
            f"[NitterTweets] List 抓取开始: group={group.group_id}, "
            f"source={source_label}, limit={fetch_limit}"
        )

        def log_rss_error(exc: Exception) -> None:
            detail = sanitize_sensitive_text(redact_instance_urls(str(exc)))
            logger.warning(
                f"[NitterTweets] List RSS 抓取失败，尝试 HTML 后备: "
                f"group={group.group_id}, source={source_label}, "
                f"error={type(exc).__name__}: {detail}"
            )

        adapter = _SchedulerNitterAdapter(self.nitter, log_rss_error)
        outcome = await QueryService(adapter, fetch_backend="nitter").scan_list(
            list_id,
            scan_watermark,
            limit=fetch_limit,
            skip_plain_text=skip_plain_text,
            filter_reposts=filter_reposts,
        )
        if outcome.status == FetchStatus.ERROR:
            logger.warning(
                f"[NitterTweets] List 抓取失败: group={group.group_id}, "
                f"source={source_label}, error={outcome.error_kind}"
            )
        else:
            self._log_verbose_info(
                f"[NitterTweets] List 抓取成功: group={group.group_id}, "
                f"source={source_label}, tweets={len(outcome.tweets)}"
            )
        result = self._query_to_user_result(
            outcome, index, account_key, html_stats=not adapter.list_rss_used
        )
        if adapter.list_rss_used:
            # Legacy RSS scans did not populate HTML parser counters or
            # an invented per-instance host attempt.
            result.host_attempts.clear()
        return result

    def _should_use_concurrent_fetch(self, group: ScheduleGroup) -> bool:
        return (
            bool(group.concurrent_fetch_enabled)
            and bool(getattr(self.nitter, "instances", []))
            and group.fetch_concurrency > 1
        )
