"""抓取阶段：博主时间线、标签搜索与 List。

`NitterTweetScheduler` 的 mixin：只通过 `self` 协作，不 import 宿主类。
只负责产出 `UserFetchResult`；首次 init、水位裁剪等编排留在 `runner.py`。
"""

from __future__ import annotations

import asyncio

try:
    from ..config import config_get, fetch_proxy_url, parse_config_bool
    from ..media_support.client import NitterClient
    from ..media_support.fxtwitter_client import FxTwitterClient
    from ..shared import (
        TweetItem,
        format_subscription_source,
        redact_instance_urls,
        sanitize_sensitive_text,
    )
    from ..shared.observability import safe_block_log, sanitize_diagnostic
    from .config import ScheduleGroup
    from .models import SchedulerTaskError, SourceStatus, UserFetchResult
except ImportError:
    from config import config_get, fetch_proxy_url, parse_config_bool
    from media_support.client import NitterClient
    from media_support.fxtwitter_client import FxTwitterClient
    from scheduler.config import ScheduleGroup
    from scheduler.models import SchedulerTaskError, SourceStatus, UserFetchResult
    from shared import (
        TweetItem,
        format_subscription_source,
        redact_instance_urls,
        sanitize_sensitive_text,
    )
    from shared.observability import safe_block_log, sanitize_diagnostic


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


FX_FETCH_CONCURRENCY = 3


def _failed_fetch_attempt(stage: str, error: Exception) -> str:
    reason = sanitize_diagnostic(redact_instance_urls(str(error)))
    status = (
        "跳过"
        if reason.startswith("本轮所有 Nitter 实例均不可用") and "已跳过" in reason
        else "失败"
    )
    return f"{stage}={status}: {reason}"


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
        config = getattr(self, "config", None)
        proxy_url = fetch_proxy_url(config, "api")
        if self.fetch_backend == "fx":
            return FxTwitterClient(proxy_url=proxy_url)
        if isinstance(getattr(self, "nitter", None), NitterClient):
            return FxTwitterClient(
                timeout=getattr(self.nitter, "timeout", 15.0), proxy_url=proxy_url
            )
        raw_backend = config_get(config, "fetch_backend", None)
        if raw_backend and str(raw_backend).strip().lower() in ("mix", "fx"):
            return FxTwitterClient(proxy_url=proxy_url)
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
                    )
                )
            return results

        # Blogger groups:
        backend = self.fetch_backend
        fx_client = self._get_fxtwitter_client()
        account_to_original_index = {u: i for i, u in enumerate(accounts)}

        if backend in ("mix", "fx") and fx_client is not None:
            filter_reposts = self._effective_filter_reposts(group)
            semaphore = asyncio.Semaphore(FX_FETCH_CONCURRENCY)

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
            fx_failures: dict[str, str] = {}
            for username, fetch_res, exc in fx_results:
                if fetch_res is not None:
                    fx_batches.append(fetch_res)
                else:
                    failed_accounts.append(username)
                    fx_failures[username] = _failed_fetch_attempt(
                        "FxTwitter", exc or RuntimeError("FxTwitter fetch failed")
                    )

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
                                host_attempts=[fx_failures[username]],
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
            use_merged = len(failed_accounts) > 1 and self._effective_filter_reposts(
                group
            )
            fallback_path = "合并 RSS" if use_merged else "单账号 RSS"
            safe_block_log(
                "debug",
                f"[NitterTweets] FxTwitter 抓取异常平滑回退自建 Nitter: "
                f"group={group.group_id}, 失败博主数={len(failed_accounts)} "
                f"({sanitize_sensitive_text(failed_preview)}), 回退路径={fallback_path}",
            )

            # Incremental takeover: only failed_accounts handed to Nitter pipeline
            if use_merged:
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
                            force_nitter=True,
                        )
                    )
            for res in nitter_batches:
                res.index = account_to_original_index.get(res.username, res.index)
                nitter_attempt = "Nitter=成功" if not res.error else "Nitter=失败"
                res.host_attempts = [
                    fx_failures[res.username],
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
        results = []
        for index, username in enumerate(accounts):
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
                    force_nitter=True,
                )
            )
        return results

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
        safe_block_log(
            "debug",
            f"[NitterTweets] 合并 RSS 批量抓取: group={group.group_id}, "
            f"博主数={len(accounts)}, 批次数={len(batches)}",
        )

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

            merged_failure = ""
            try:
                instance, merged_results = await self.nitter.fetch_merged_for_scheduler(
                    batch,
                    batch_watermarks,
                    skip_plain_text=skip_plain_text,
                    filter_reposts=filter_reposts,
                    media=skip_plain_text and filter_reposts,
                )
            except Exception as exc:
                error_label = sanitize_sensitive_text(redact_instance_urls(str(exc)))
                safe_block_log(
                    "debug",
                    f"[NitterTweets] 合并 RSS 抓取失败，回退逐个请求: "
                    f"group={group.group_id}, batch={batch_i + 1}/{len(batches)}, "
                    f"error={type(exc).__name__}: {error_label}",
                )
                instance, merged_results = "", {}
                merged_failure = _failed_fetch_attempt("合并RSS", exc)

            # A nonempty result can still end before this user's watermark.
            for username in batch:
                index = len(results)
                scan_result = merged_results.get(username)
                if (
                    scan_result
                    and scan_result.complete
                    and scan_result.scanned_status_ids
                ):
                    self._log_verbose_info(
                        f"[NitterTweets] 合并 RSS 命中 @{username}: "
                        f"tweets={len(scan_result.tweets)}"
                    )
                    results.append(
                        UserFetchResult(
                            index=index,
                            username=username,
                            instance=instance,
                            tweets=list(scan_result.tweets),
                            scanned_status_ids=list(scan_result.scanned_status_ids),
                            anchor_status_ids=list(scan_result.anchor_status_ids),
                            latest_status_id=str(scan_result.latest_status_id or ""),
                            scan_complete=True,
                            plain_text_filtered=int(
                                scan_result.plain_text_filtered or 0
                            ),
                            host_attempts=["合并RSS=成功"],
                        )
                    )
                    continue

                watermark = batch_watermarks[username]
                if merged_failure:
                    if index > 0 and group.send_user_interval > 0:
                        await asyncio.sleep(group.send_user_interval)
                    merged_attempt = merged_failure
                else:
                    if scan_result and scan_result.reached_watermark:
                        fallback_reason = "该账号推文需补查"
                    else:
                        fallback_reason = (
                            "未命中该账号水位"
                            if watermark is not None
                            else "无该账号推文"
                        )
                    safe_block_log(
                        "debug",
                        f"[NitterTweets] 合并 RSS {fallback_reason}，补查单账号 RSS/HTML: "
                        f"group={group.group_id}, user=@{username}, "
                        f"batch={batch_i + 1}/{len(batches)}",
                    )
                    merged_attempt = (
                        "合并RSS=无该账号结果"
                        if watermark is None
                        else f"合并RSS={fallback_reason}"
                    )
                user_result = await self._fetch_group_user(
                    group,
                    index,
                    username,
                    fetch_limit,
                    skip_plain_text,
                    watermark,
                    force_nitter=True,
                    require_html_watermark=True,
                )
                user_result.host_attempts.insert(0, merged_attempt)
                results.append(user_result)

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
        force_nitter: bool = False,
        require_html_watermark: bool = False,
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
        if not force_nitter and backend in ("mix", "fx") and fx_client is not None:
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
                    safe_block_log(
                        "debug",
                        f"[NitterTweets] FxTwitter 抓取 @{username} 失败 (fx模式): "
                        f"{type(exc).__name__}: {sanitize_sensitive_text(str(exc))}",
                    )
                    return UserFetchResult(
                        index=index,
                        username=username,
                        instance="FxTwitter",
                        host_attempts=[_failed_fetch_attempt("FxTwitter", exc)],
                        error=SchedulerTaskError.from_exception(exc),
                    )
                safe_block_log(
                    "debug",
                    f"[NitterTweets] FxTwitter 抓取 @{username} 异常，平滑回退自建 Nitter: "
                    f"{type(exc).__name__}: {sanitize_sensitive_text(str(exc))}",
                )
                fx_failed_attempt = _failed_fetch_attempt("FxTwitter", exc)

        nitter_attempts: list[str] = []

        def _with_fx_fallback(res: UserFetchResult) -> UserFetchResult:
            res.host_attempts = list(nitter_attempts) or ["单账号RSS=成功"]
            if fx_failed_attempt:
                res.host_attempts = [
                    fx_failed_attempt,
                    *res.host_attempts,
                ]
            return res

        html_watermark = scan_watermark if require_html_watermark else None
        try:
            # /<user>/media/rss shows only the author's own media uploads
            # and excludes ALL retweets.  Only switch to it when both
            # plain-text and repost filtering are active; otherwise keep
            # the regular RSS feed and filter plain text locally so that
            # retweets the user wants to keep are not silently dropped.
            use_media_path = skip_plain_text and filter_reposts
            media_path = f"{username}/media" if use_media_path else ""
            fetch_for_scheduler = getattr(
                self.nitter, "fetch_tweets_for_scheduler", None
            )
            if callable(fetch_for_scheduler):
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
                    nitter_attempts.append("单账号RSS=无推文")
                    html_result = await self._fetch_user_html_after_rss(
                        index,
                        username,
                        fetch_limit,
                        skip_plain_text=skip_plain_text,
                        filter_reposts=filter_reposts,
                        attempts=nitter_attempts,
                        required_watermark=html_watermark,
                    )
                    if html_result is not None and (
                        html_result.scan_complete
                        or not (scan_result.complete and scan_result.scanned_status_ids)
                    ):
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
                        retweet_filtered=scan_result.reposts_filtered,
                        fetch_status=(
                            SourceStatus.FILTERED_EMPTY
                            if scan_result.complete
                            and not tweets
                            and scan_result.reposts_filtered
                            else None
                        ),
                    )
                )

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
                nitter_attempts.append("单账号RSS=无推文")
                html_result = await self._fetch_user_html_after_rss(
                    index,
                    username,
                    fetch_limit,
                    skip_plain_text=skip_plain_text,
                    filter_reposts=filter_reposts,
                    attempts=nitter_attempts,
                    required_watermark=html_watermark,
                )
                if html_result is not None:
                    return _with_fx_fallback(html_result)
        except Exception as exc:
            nitter_attempts.append(_failed_fetch_attempt("单账号RSS", exc))
            html_result = await self._fetch_user_html_after_rss(
                index,
                username,
                fetch_limit,
                skip_plain_text=skip_plain_text,
                filter_reposts=filter_reposts,
                attempts=nitter_attempts,
                required_watermark=html_watermark,
            )
            if html_result is not None:
                return _with_fx_fallback(html_result)
            return _with_fx_fallback(
                UserFetchResult(
                    index=index,
                    username=username,
                    error=SchedulerTaskError(
                        # 最终摘要有长度上限，优先保留最后一次后备失败。
                        message="; ".join(reversed(nitter_attempts)),
                        kind=type(exc).__name__,
                    ),
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
        attempts: list[str],
        required_watermark: list[str] | None = None,
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
            attempts.append(_failed_fetch_attempt("HTML", exc))
            safe_block_log(
                "debug",
                f"[NitterTweets] HTML 用户页回退失败: @{username}, "
                f"error={sanitize_sensitive_text(redact_instance_urls(str(exc)))}",
            )
            return None
        if not tweets:
            attempts.append("HTML=无推文")
            return None
        scanned_tweets = list(tweets)
        tweets, plain_text_filtered = self._filter_html_tweets_plain_text(
            scanned_tweets, skip_plain_text=skip_plain_text
        )
        boundary_tweets = scanned_tweets if required_watermark is not None else tweets
        scanned_status_ids = [
            tweet.status_id for tweet in boundary_tweets if tweet.status_id
        ]
        scan_complete = required_watermark is None or not set(
            required_watermark
        ).isdisjoint(scanned_status_ids)
        attempts.append("HTML=成功" if scan_complete else "HTML=未命中该账号水位")
        return UserFetchResult(
            index=index,
            username=username,
            instance=instance,
            tweets=tweets,
            scanned_status_ids=scanned_status_ids,
            anchor_status_ids=scanned_status_ids[:20],
            latest_status_id=(tweets[0].status_id if tweets else ""),
            scan_complete=scan_complete,
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
                    safe_block_log(
                        "debug",
                        f"[NitterTweets] FxTwitter 搜索订阅抓取失败 (fx模式): group={group.group_id}, "
                        f"source={source_label}, error={type(exc).__name__}: {sanitize_sensitive_text(str(exc))}",
                    )
                    return UserFetchResult(
                        index=index,
                        username=account_key,
                        instance="FxTwitter",
                        host_attempts=[_failed_fetch_attempt("FxTwitter", exc)],
                        error=SchedulerTaskError.from_exception(exc),
                    )
                safe_block_log(
                    "debug",
                    f"[NitterTweets] FxTwitter 标签搜索抓取异常，平滑回退自建 Nitter HTML: "
                    f"group={group.group_id}, source={source_label}, "
                    f"error={type(exc).__name__}: {sanitize_sensitive_text(str(exc))}",
                )
                fx_failed_attempt = _failed_fetch_attempt("FxTwitter", exc)

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
            host_attempts = [
                *list(getattr(tweets, "host_attempts", []) or []),
                "HTML=成功",
            ]
            tweets = list(tweets)
            self._log_verbose_info(
                f"[NitterTweets] 搜索订阅抓取成功: group={group.group_id}, "
                f"source={source_label}, "
                f"tweets={len(tweets)}"
            )
        except Exception as exc:
            safe_block_log(
                "debug",
                f"[NitterTweets] 搜索订阅抓取失败: group={group.group_id}, "
                f"source={source_label}, "
                f"error={sanitize_sensitive_text(redact_instance_urls(str(exc)))}",
            )
            return UserFetchResult(
                index=index,
                username=account_key,
                host_attempts=[_failed_fetch_attempt("HTML", exc)],
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
        rss_attempt = "ListRSS=扫描未完整"
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
                    f"source={source_label}, "
                    f"tweets={len(tweets)}"
                )
                return UserFetchResult(
                    index=index,
                    username=account_key,
                    instance=instance,
                    host_attempts=["ListRSS=成功"],
                    tweets=tweets,
                    scanned_status_ids=list(scan_result.scanned_status_ids),
                    anchor_status_ids=list(scan_result.anchor_status_ids),
                    latest_status_id=str(scan_result.latest_status_id or ""),
                    scan_complete=bool(scan_result.complete),
                    plain_text_filtered=int(scan_result.plain_text_filtered or 0),
                    retweet_filtered=scan_result.reposts_filtered,
                    fetch_status=(
                        SourceStatus.FILTERED_EMPTY
                        if scan_result.complete
                        and not tweets
                        and (
                            scan_result.reposts_filtered
                            or scan_result.plain_text_filtered
                        )
                        else None
                    ),
                )
        except Exception as exc:
            rss_attempt = _failed_fetch_attempt("ListRSS", exc)
            error_label = sanitize_sensitive_text(redact_instance_urls(str(exc)))
            safe_block_log(
                "debug",
                f"[NitterTweets] List RSS 抓取失败，尝试 HTML 后备: "
                f"group={group.group_id}, source={source_label}, "
                f"error={type(exc).__name__}: {error_label}",
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
            host_attempts = [
                rss_attempt,
                *list(getattr(tweets, "host_attempts", []) or []),
                "HTML=成功",
            ]
            tweets = list(tweets)
            self._log_verbose_info(
                f"[NitterTweets] List HTML 后备抓取成功: group={group.group_id}, "
                f"source={source_label}, "
                f"tweets={len(tweets)}"
            )
        except Exception as exc:
            safe_block_log(
                "debug",
                f"[NitterTweets] List 抓取失败: group={group.group_id}, "
                f"source={source_label}, "
                f"error={sanitize_sensitive_text(redact_instance_urls(str(exc)))}",
            )
            host_attempts = [rss_attempt, _failed_fetch_attempt("HTML", exc)]
            return UserFetchResult(
                index=index,
                username=account_key,
                host_attempts=host_attempts,
                error=SchedulerTaskError(
                    message="; ".join(reversed(host_attempts)),
                    kind=type(exc).__name__,
                ),
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
