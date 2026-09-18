from __future__ import annotations

import asyncio
import logging
import re
import time

from astrbot.api.all import At, MessageChain, Plain, logger
from astrbot.api.event import AstrMessageEvent
from astrbot.core.star.filter.command import GreedyStr

try:
    from ..ai import format_ai_tweet_summary
    from ..config import (
        config_get,
        resolve_hide_original_when_translated,
        resolve_manual_send_interval,
    )
    from ..media_support.client import NitterClient
    from ..media_support.fxtwitter_client import FxTwitterClient
    from ..media_support.html_backend.query import MAX_QUERY_LENGTH
    from ..media_support.network import UnsafeUrlError, validate_http_url
    from ..media_support.search_session_buffer import (
        MAX_FETCH_CAP,
        MAX_PAGES_PER_FILL,
        SearchSessionStore,
    )
    from ..rendering.tweets import format_twitter_trends
    from ..shared import normalize_username, safe_call, sanitize_sensitive_text
    from ..shared.observability import safe_task_log
except ImportError:
    from ai import format_ai_tweet_summary
    from config import (
        config_get,
        resolve_hide_original_when_translated,
        resolve_manual_send_interval,
    )
    from media_support.client import NitterClient
    from media_support.fxtwitter_client import FxTwitterClient
    from media_support.html_backend.query import MAX_QUERY_LENGTH
    from media_support.network import UnsafeUrlError, validate_http_url
    from media_support.search_session_buffer import (
        MAX_FETCH_CAP,
        MAX_PAGES_PER_FILL,
        SearchSessionStore,
    )
    from rendering.tweets import format_twitter_trends
    from shared import normalize_username, safe_call, sanitize_sensitive_text
    from shared.observability import safe_task_log


class ManualCommandMixin:
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
    def search_sort(self) -> str:
        val = (
            str(
                config_get(getattr(self, "config", {}), "search_sort", "latest")
                or "latest"
            )
            .strip()
            .lower()
        )
        return "top" if val == "top" else "latest"

    @property
    def fxtwitter_client(self) -> FxTwitterClient:
        client = getattr(self, "fxtwitter", None)
        if client is None:
            nitter = getattr(self, "nitter", None)
            client = getattr(nitter, "fxtwitter", None)
        if client is None:
            client = FxTwitterClient()
            self.fxtwitter = client
        return client

    def _get_fxtwitter_client(self) -> FxTwitterClient | None:
        client = getattr(self, "fxtwitter", None)
        if client is not None:
            return client
        nitter = getattr(self, "nitter", None)
        client = getattr(nitter, "fxtwitter", None)
        if client is not None:
            return client
        if self.fetch_backend == "fx":
            return self.fxtwitter_client
        if isinstance(nitter, NitterClient):
            return self.fxtwitter_client
        raw_backend = config_get(getattr(self, "config", {}), "fetch_backend", None)
        if raw_backend and str(raw_backend).strip().lower() in ("mix", "fx"):
            return self.fxtwitter_client
        return None

    @staticmethod
    def _log_manual_send_task(
        title: str,
        *,
        operation: str,
        source: str,
        instance: str,
        tweet_count: int,
        sent_count: int,
        started: float,
    ) -> None:
        total = max(0, int(tweet_count))
        sent = max(0, min(total, int(sent_count)))
        fully_sent = total > 0 and sent == total
        status = "成功" if fully_sent else "部分完成" if sent else "发送失败"
        safe_task_log(
            logging.INFO if fully_sent else logging.WARNING,
            title,
            operation=operation,
            source=source,
            trigger="manual_command",
            instance=instance,
            tweet_count=total,
            sent_count=sent,
            target_success_ratio=f"{int(fully_sent)}/1",
            result_status=status,
            elapsed_ms=(time.perf_counter() - started) * 1000,
        )

    @staticmethod
    def _log_manual_no_send_task(
        title: str,
        *,
        operation: str,
        source: str,
        started: float,
        status: str,
        instance: str = "",
        error_detail: str = "",
        warning: bool = False,
    ) -> None:
        safe_task_log(
            logging.WARNING if warning else logging.INFO,
            title,
            operation=operation,
            source=source,
            trigger="manual_command",
            instance=instance,
            tweet_count=0,
            sent_count=0,
            result_status=status,
            error_detail=error_detail,
            elapsed_ms=(time.perf_counter() - started) * 1000,
        )

    async def _cmd_tweets_impl(
        self,
        event: AstrMessageEvent,
        username: str = "",
        limit: str = "",
        *,
        media_type_arg: str = "",
        is_media_only: bool = False,
    ):
        """获取指定公开 X/Twitter 用户的最近推文或相册媒体推文。"""
        event.stop_event()

        username = normalize_username(username)
        if not username:
            cmd = "/推图" if is_media_only else "/推文"
            hint = (
                f"用法：{cmd} 用户名 [数量] [视频/图片]"
                if is_media_only
                else f"用法：{cmd} 用户名 [数量]"
            )
            await event.send(event.plain_result(f"{hint}\n例如：{cmd} nasa 5"))
            return

        cooldown_left = self._cooldown_left(event)
        if cooldown_left > 0:
            await event.send(
                event.plain_result(f"请求太快啦，{cooldown_left:.0f} 秒后再试。")
            )
            return

        # 解析数量与媒体类型参数（支持 /推图 用户名 5 视频 或 /推图 用户名 视频）
        raw_limit = self._strip_self_at_argument(event, limit)
        raw_type = self._strip_self_at_argument(event, media_type_arg)
        media_filter = ""

        def _parse_filter_tag(val: str) -> str:
            v = str(val or "").strip().lower()
            if v in ("视频", "video", "v", "videos", "gif"):
                return "video"
            if v in ("图片", "图", "image", "photo", "img", "images", "photos"):
                return "image"
            return ""

        if is_media_only:
            # 检查 raw_limit 是否其实是媒体类型（如 /推图 user 视频）
            detected_type = _parse_filter_tag(raw_limit)
            if detected_type:
                media_filter = detected_type
                raw_limit = ""
            elif raw_type:
                media_filter = _parse_filter_tag(raw_type)

        if raw_limit:
            parsed_limit, limit_error = self._parse_command_limit(raw_limit)
            if limit_error:
                await event.send(event.plain_result(limit_error))
                return
            requested_limit = parsed_limit
        else:
            requested_limit = self.default_limit
        limit = requested_limit
        self._mark_cooldown(event)

        is_video_mode = is_media_only and media_filter == "video"
        if is_video_mode:
            desc = "视频推文"
        elif is_media_only:
            desc = "相册图片推文" if media_filter == "image" else "相册媒体推文"
        else:
            desc = "推文"

        await event.send(
            event.plain_result(f"正在获取 @{username} 最近最多 {limit} 条{desc}...")
        )

        started = time.perf_counter()
        backend = self.fetch_backend
        instance = ""
        tweets = []
        fx_error: Exception | None = None
        op_name = "user_media" if is_media_only else "user_timeline"

        fx = self._get_fxtwitter_client()
        effective_filter_reposts = bool(
            getattr(
                self,
                "filter_reposts_enabled",
                config_get(getattr(self, "config", {}), "filter_reposts_enabled", True),
            )
        )
        effective_max_pages = int(
            getattr(
                self,
                "html_max_pages",
                config_get(getattr(self, "config", {}), "html_max_pages", 3),
            )
            or 3
        )

        if backend in ("mix", "fx") and fx is not None:
            try:
                fetch_kw = {
                    "count": int(limit),
                    "skip_plain_text": is_media_only,
                    "filter_reposts": effective_filter_reposts,
                    "max_pages": effective_max_pages,
                }
                if media_filter:
                    fetch_kw["media_filter"] = media_filter
                fx_tweets, _ = await asyncio.to_thread(
                    fx.fetch_user_timeline,
                    username,
                    **fetch_kw,
                )
                instance = "FxTwitter"
                tweets = fx_tweets
            except Exception as exc:
                fx_error = exc
                if backend == "fx":
                    logger.warning(
                        f"[NitterTweets] FxTwitter 手动获取 @{username} 推文失败 (fx模式): {sanitize_sensitive_text(str(exc))}"
                    )
                    self._log_manual_no_send_task(
                        "推文查询失败",
                        operation=op_name,
                        source=f"@{username}",
                        instance="FxTwitter",
                        started=started,
                        status="抓取失败",
                        error_detail=sanitize_sensitive_text(str(exc)),
                        warning=True,
                    )
                    await event.send(
                        event.plain_result(f"获取 @{username} 推文失败，请稍后重试。")
                    )
                    return
                logger.warning(
                    f"[NitterTweets] FxTwitter 手动获取 @{username} 异常，平滑回退自建 Nitter: {sanitize_sensitive_text(str(exc))}"
                )

        if backend == "nitter" or (
            backend == "mix" and (fx is None or fx_error is not None)
        ):
            if hasattr(self.nitter, "begin_run_host_skip"):
                self.nitter.begin_run_host_skip()
            try:
                try:
                    fetch_kwargs = {"filter_reposts": effective_filter_reposts}
                    if is_media_only:
                        fetch_kwargs["skip_plain_text"] = True
                    nitter_inst, tweets = await self.nitter.fetch_user(
                        username, limit, **fetch_kwargs
                    )
                    instance = f"Nitter ({nitter_inst})" if nitter_inst else "Nitter"
                except TypeError:
                    nitter_inst, tweets = await self.nitter.fetch_user(
                        username, limit, filter_reposts=effective_filter_reposts
                    )
                    instance = f"Nitter ({nitter_inst})" if nitter_inst else "Nitter"
                    if is_media_only and tweets:
                        tweets = [t for t in tweets if bool(t.media)]
                if is_video_mode and tweets:
                    tweets = [t for t in tweets if any(m.is_video for m in t.media)]
                elif media_filter == "image" and tweets:
                    tweets = [t for t in tweets if any(m.is_image for m in t.media)]
            except Exception as exc:
                logger.warning(
                    f"[NitterTweets] 手动获取 @{sanitize_sensitive_text(username)} 推文失败: {sanitize_sensitive_text(str(exc))}"
                )
                self._log_manual_no_send_task(
                    "推文查询失败",
                    operation=op_name,
                    source=f"@{username}",
                    instance=instance or "Nitter",
                    started=started,
                    status="抓取失败",
                    error_detail=sanitize_sensitive_text(str(exc)),
                    warning=True,
                )
                await event.send(
                    event.plain_result(
                        f"获取 @{username} 推文失败，请检查自建 Nitter 实例。"
                    )
                )
                return
            finally:
                if hasattr(self.nitter, "end_run_host_skip"):
                    self.nitter.end_run_host_skip()

        if not tweets:
            self._log_manual_no_send_task(
                "推文查询完成",
                operation=op_name,
                source=f"@{username}",
                instance=instance,
                started=started,
                status="无公开推文",
            )
            empty_msg = (
                f"没有找到 @{username} 的{desc}。"
                if is_media_only
                else f"没有找到 @{username} 的公开推文。"
            )
            await event.send(event.plain_result(empty_msg))
            return

        kwargs = {}
        if is_video_mode:
            kwargs["force_media"] = True
        try:
            sent_count = await self._send_tweets_response(
                event, username, instance, tweets, **kwargs
            )
        except TypeError:
            sent_count = await self._send_tweets_response(
                event, username, instance, tweets
            )
        self._log_manual_send_task(
            "推文查询完成",
            operation=op_name,
            source=f"@{username}",
            instance=instance,
            tweet_count=len(tweets),
            sent_count=sent_count,
            started=started,
        )

    async def _cmd_tweet_search_impl(
        self,
        event: AstrMessageEvent,
        args=GreedyStr,
        *,
        is_media_search: bool = False,
    ):
        """HTML 搜索公开推文：标签请带 #，短语直接写。

        ``is_media_search=True`` 时自动追加 ``filter:media`` 并本地兜底过滤。
        """
        event.stop_event()

        extra_prefixes = ("推文搜图", "tweetpic", "搜推图") if is_media_search else ()
        query, limit, sort, error = self._parse_search_args(
            event, args, extra_prefixes=extra_prefixes
        )
        if error:
            await event.send(event.plain_result(error))
            return

        # Append filter:media for media-only search (server-side, best effort).
        effective_query = query
        if is_media_search and "filter:media" not in effective_query:
            effective_query = f"{effective_query} filter:media"
            if len(effective_query) > MAX_QUERY_LENGTH:
                await event.send(
                    event.plain_result(
                        f"查询内容过长（加上搜图过滤后最多 {MAX_QUERY_LENGTH} 字符）。"
                    )
                )
                return

        cooldown_left = self._cooldown_left(event, scope="search")
        if cooldown_left > 0:
            await event.send(
                event.plain_result(f"请求太快啦，{cooldown_left:.0f} 秒后再试。")
            )
            return

        search_started = time.perf_counter()

        session_id = self._search_session_id(event)
        store = self._get_search_session_store()
        effective_sort = sort or getattr(self, "search_sort", "latest")
        query_sort = effective_sort if (sort or effective_sort != "latest") else ""
        query_key = self._search_query_key(effective_query, query_sort)
        buf = store.get_or_create(session_id, query_key)

        sent_progress = [0]

        def record_sent_progress(count: int) -> None:
            # The send coroutine may abort after one or more messages were
            # accepted. Preserve that prefix when finalizing the reservation.
            sent_progress[0] = max(sent_progress[0], int(count))

        def abort_reservation(token: str, failed_count: int = 1) -> None:
            if sent_progress[0] > 0:
                buf.finalize(token, sent_progress[0])
            else:
                buf.rollback(token, failed_count=failed_count)

        # Pure buffer hit: no network — skip cooldown burn for short fun use.
        if len(buf) >= limit:
            reservation_token, tweets = buf.reserve(limit)
            instance = buf.instance or "buffer"
            try:
                await event.send(
                    event.plain_result(
                        f"从本会话缓存发送「{query}」{len(tweets)} 条"
                        f"（缓存剩余 {len(buf)}）。"
                    )
                )
            except BaseException:
                abort_reservation(reservation_token, failed_count=0)
                raise

            try:
                sent_count = await self._send_tweets_response(
                    event,
                    query,
                    instance,
                    tweets,
                    on_sent_progress=record_sent_progress,
                )
            except asyncio.CancelledError:
                abort_reservation(reservation_token, failed_count=0)
                raise
            except BaseException:
                abort_reservation(reservation_token, failed_count=1)
                raise
            buf.finalize(
                reservation_token,
                sent_count,
                failed_count=1 if sent_count < len(tweets) else 0,
            )
            self._log_manual_send_task(
                "推文搜索完成",
                operation="tweet_search",
                source=query,
                instance=f"{instance} (会话缓存)",
                tweet_count=len(tweets),
                sent_count=sent_count,
                started=search_started,
            )
            return

        self._mark_cooldown(event, scope="search")
        need = limit - len(buf)
        had_known = bool(getattr(buf, "known_ids", None))
        await event.send(
            event.plain_result(
                f"正在搜索「{query}」，需要 {limit} 条"
                + (f"（缓存已有 {len(buf)}，再取 {need}）" if len(buf) else "")
                + "..."
            )
        )
        # When session already consumed first page ids, pull a wider window so
        # later pages can still contribute (pool restarts cursor each call).
        pages = MAX_PAGES_PER_FILL
        if had_known and len(buf) == 0:
            pages = max(pages, 5)
        fetch_limit = min(
            MAX_FETCH_CAP * 2 if had_known else MAX_FETCH_CAP,
            max(limit * pages, limit + need, 15 if had_known else limit),
        )

        backend = self.fetch_backend
        instance = ""
        fetched = []
        fx_error: Exception | None = None

        fx = self._get_fxtwitter_client()
        if backend in ("mix", "fx") and fx is not None:
            try:
                fx_tweets, _ = await asyncio.to_thread(
                    fx.search_tweets,
                    query,
                    count=fetch_limit,
                    is_media=is_media_search,
                    feed=("top" if effective_sort == "top" else "latest"),
                )
                instance = "FxTwitter"
                fetched = fx_tweets
            except Exception as exc:
                fx_error = exc
                if backend == "fx":
                    logger.warning(
                        f"[NitterTweets] FxTwitter 搜索失败 (fx模式) query={query!r}: {sanitize_sensitive_text(str(exc))}"
                    )
                    self._log_manual_no_send_task(
                        "推文搜索失败",
                        operation="tweet_search",
                        source=query,
                        instance="FxTwitter",
                        started=search_started,
                        status="抓取失败",
                        error_detail=sanitize_sensitive_text(str(exc)),
                        warning=True,
                    )
                    await event.send(event.plain_result("搜索失败，请稍后重试"))
                    return
                logger.warning(
                    f"[NitterTweets] FxTwitter 搜索「{sanitize_sensitive_text(query)}」异常，平滑回退自建 Nitter: {sanitize_sensitive_text(str(exc))}"
                )

        if backend == "nitter" or (
            backend == "mix" and (fx is None or fx_error is not None)
        ):
            try:
                nitter_inst, fetched = await asyncio.to_thread(
                    self.nitter.search,
                    effective_query,
                    fetch_limit,
                    max_pages=pages,
                    sort=effective_sort or None,
                )
                instance = f"Nitter ({nitter_inst})" if nitter_inst else "Nitter"
            except TypeError:
                try:
                    nitter_inst, fetched = await asyncio.to_thread(
                        self.nitter.search,
                        effective_query,
                        fetch_limit,
                        sort=effective_sort or None,
                    )
                    instance = f"Nitter ({nitter_inst})" if nitter_inst else "Nitter"
                except Exception as exc:
                    logger.warning(
                        f"[NitterTweets] 搜索失败 query={sanitize_sensitive_text(query)!r}: {sanitize_sensitive_text(str(exc))}"
                    )
                    self._log_manual_no_send_task(
                        "推文搜索失败",
                        operation="tweet_search",
                        source=query,
                        instance=instance or "Nitter",
                        started=search_started,
                        status="抓取失败",
                        error_detail=sanitize_sensitive_text(str(exc)),
                        warning=True,
                    )
                    await event.send(
                        event.plain_result("搜索失败，请稍后重试或检查自建 Nitter 实例")
                    )
                    return
            except Exception as exc:
                logger.warning(
                    f"[NitterTweets] 搜索失败 query={sanitize_sensitive_text(query)!r}: {sanitize_sensitive_text(str(exc))}"
                )
                self._log_manual_no_send_task(
                    "推文搜索失败",
                    operation="tweet_search",
                    source=query,
                    instance=instance or "Nitter",
                    started=search_started,
                    status="抓取失败",
                    error_detail=sanitize_sensitive_text(str(exc)),
                    warning=True,
                )
                await event.send(
                    event.plain_result("搜索失败，请稍后重试或检查自建 Nitter 实例")
                )
                return

        fetched_list = list(fetched or [])
        # Local fallback: drop pure-text tweets for media-only search.
        if is_media_search:
            fetched_list = [t for t in fetched_list if t.media]
        added = buf.add_tweets(fetched_list, instance=instance or "")
        logger.info(
            f"[NitterTweets] search buffer session={session_id!r} query={effective_query!r} "
            f"fetched={len(fetched or [])} added={added} pool={len(buf)}"
        )

        reservation_token, tweets = buf.reserve(limit)
        if not tweets:
            buf.rollback(reservation_token)
            self._log_manual_no_send_task(
                "推文搜索完成",
                operation="tweet_search",
                source=query,
                instance=buf.instance or instance or "",
                started=search_started,
                status="无新增结果",
            )
            if had_known or (fetched and added == 0):
                await event.send(
                    event.plain_result(
                        f"「{query}」在本会话近期已展示过相近结果，"
                        f"暂无更多未见推文。可换关键词，或约 10 分钟后再试。"
                    )
                )
            else:
                await event.send(
                    event.plain_result(f"没有找到与「{query}」相关的公开推文。")
                )
            return
        try:
            sent_count = await self._send_tweets_response(
                event,
                query,
                buf.instance or instance or "",
                tweets,
                on_sent_progress=record_sent_progress,
            )
        except asyncio.CancelledError:
            abort_reservation(reservation_token, failed_count=0)
            raise
        except BaseException:
            abort_reservation(reservation_token, failed_count=1)
            raise
        buf.finalize(
            reservation_token,
            sent_count,
            failed_count=1 if sent_count < len(tweets) else 0,
        )
        self._log_manual_send_task(
            "推文搜索完成",
            operation="tweet_search",
            source=query,
            instance=buf.instance or instance or "",
            tweet_count=len(tweets),
            sent_count=sent_count,
            started=search_started,
        )

    def _parse_search_args(
        self,
        event: AstrMessageEvent,
        args=GreedyStr,
        *,
        extra_prefixes: tuple[str, ...] = (),
    ):
        text = ""
        if args is not None and str(args).strip():
            text = str(args).strip()
        else:
            text = (event.get_message_str() or "").strip()
            # strip command token
            prefixes = (
                "/推文搜索",
                "推文搜索",
                "/tweetsearch",
                "tweetsearch",
                *(f"/{p}" for p in extra_prefixes),
                *extra_prefixes,
            )
            for prefix in prefixes:
                if text.startswith(prefix):
                    text = text[len(prefix) :].strip()
                    break

        # --- CLI flag extraction (whitelist, token-boundary safe) ---
        # If any known flag is present, extract all known flags and use the
        # remaining text verbatim as the query — no heuristic sort/limit
        # guessing.  Unknown dash-prefixed tokens (e.g. -valorant,
        # -filter:retweets, -min_faves:100) stay in the query untouched.
        _USAGE_HINT = (
            "用法：/推文搜索 <query> [-数量] [-top] [-last]\n"
            "标签请带 #，例如：#圣娅\n"
            "普通词/短语直接写：python programming\n"
            "排序：-top（热门）-last（最新）；数量：-5 或 -n 5 或末尾数字\n"
            "示例：/推文搜索 deepseek娘 -3 -top"
        )

        limit_re = re.compile(r"(?<!\S)(?:-n|--limit)\s+(\d+)(?!\S)", re.IGNORECASE)
        bare_limit_re = re.compile(r"(?<!\S)-(\d+)(?!\S)")
        sort_re = re.compile(
            r"(?<!\S)(?:-top|--top|-热门|--热门|-last|--last|-最新|--最新)(?!\S)",
            re.IGNORECASE,
        )

        has_flag = bool(
            limit_re.search(text) or bare_limit_re.search(text) or sort_re.search(text)
        )

        if has_flag:
            # Branch A: explicit CLI flags detected.
            # Extract limit (last match wins), then sort, then the rest = query.
            limit = int(getattr(self, "search_default_limit", self.default_limit))
            # Collect limit matches from both -n/--limit and bare -<num>;
            # last position wins so "-3 -n 5" → 5 and "-n 5 -3" → 3.
            limit_tokens: list[tuple[int, int]] = []
            for m in limit_re.finditer(text):
                limit_tokens.append((m.start(), int(m.group(1))))
            for m in bare_limit_re.finditer(text):
                limit_tokens.append((m.start(), int(m.group(1))))
            if limit_tokens:
                limit_tokens.sort(key=lambda t: t[0])
                limit = limit_tokens[-1][1]
                text = limit_re.sub("", text)
                text = bare_limit_re.sub("", text)

            # Sort: last flag wins — -last/--last/-最新 → "latest", else "top".
            sort = ""
            sort_matches = list(sort_re.finditer(text))
            if sort_matches:
                token = sort_matches[-1].group(0).lstrip("-").lower()
                sort = "latest" if token in ("last", "最新") else "top"
            text = sort_re.sub("", text)
            query = re.sub(r"\s+", " ", text).strip()

            if not query:
                return "", 0, "", _USAGE_HINT
            max_limit = int(getattr(self, "search_max_limit", 10))
            if limit < 1:
                return "", 0, "", "数量至少为 1。"
            limit = min(limit, max_limit)
            if len(query) > MAX_QUERY_LENGTH:
                return "", 0, "", f"查询内容过长（最多 {MAX_QUERY_LENGTH} 字符）。"
            return query, limit, sort, ""

        # Branch B: no known flags — backward-compatible heuristic parsing.
        # Extract optional sort keyword. Only match "top" / "热门" as a
        # trailing standalone word (after optional limit extraction) to avoid
        # breaking queries like "top gear" or "toproad".
        sort = ""

        def _strip_trailing_sort(s: str) -> str:
            m = re.search(r"\s+(?:top|热门)\s*$", s, re.IGNORECASE)
            if m:
                return s[: m.start()].strip()
            return s

        # Pass 1: check original text for trailing sort keyword (e.g. "纳西妲 热门").
        stripped = _strip_trailing_sort(text)
        if stripped != text:
            text = stripped
            sort = "top"

        if not text:
            return "", 0, "", _USAGE_HINT
        parts = text.rsplit(None, 1)
        limit = int(getattr(self, "search_default_limit", self.default_limit))
        query = text
        if len(parts) == 2 and parts[1].isdigit():
            query = parts[0].strip()
            limit = int(parts[1])

        # Pass 2: after limit extraction, check again (e.g. "纳西妲 top 5" →
        # limit=5, query="纳西妲 top" → strip trailing "top").
        if not sort:
            stripped = _strip_trailing_sort(query)
            if stripped != query:
                query = stripped
                sort = "top"

        max_limit = int(getattr(self, "search_max_limit", 10))
        if limit < 1:
            return "", 0, "", "数量至少为 1。"
        limit = min(limit, max_limit)
        if not query:
            return "", 0, "", "查询内容不能为空。"
        if len(query) > MAX_QUERY_LENGTH:
            return "", 0, "", f"查询内容过长（最多 {MAX_QUERY_LENGTH} 字符）。"
        return query, limit, sort, ""

    async def _cmd_mirror_probe_impl(self, event: AstrMessageEvent, args=GreedyStr):
        """用临时自建 Nitter 实例测试用户时间线。"""
        event.stop_event()

        parsed = self._parse_mirror_probe_args(event, args)
        if parsed[3]:
            await event.send(event.plain_result(parsed[3]))
            return
        username, limit, instance_text, _ = parsed

        cooldown_left = self._cooldown_left(event)
        if cooldown_left > 0:
            await event.send(
                event.plain_result(f"请求太快啦，{cooldown_left:.0f} 秒后再试。")
            )
            return

        self._mark_cooldown(event)
        await event.send(
            event.plain_result(
                f"正在测试 {instance_text}：获取 @{username} 最近最多 {limit} 条推文..."
            )
        )

        try:
            instance, tweets = await self.nitter.fetch_user_from_instance(
                instance_text, username, limit, filter_reposts=False
            )
        except Exception as exc:
            logger.warning(
                f"[NitterTweets] 测试 Nitter 实例失败: instance={instance_text}, "
                f"username={username}, error={exc}"
            )
            await event.send(
                event.plain_result(
                    f"通过 {instance_text} 获取 @{username} 推文失败："
                    "自建 Nitter 实例不可用，或该用户没有公开推文。"
                )
            )
            return

        if not tweets:
            await event.send(event.plain_result(f"没有找到 @{username} 的公开推文。"))
            return

        await self._send_tweets_response(event, username, instance, tweets)

    async def _cmd_tweet_trends_impl(self, event: AstrMessageEvent):
        """查看 Twitter/X 实时趋势热搜榜。"""
        event.stop_event()

        cooldown_left = self._cooldown_left(event, scope="trends")
        if cooldown_left > 0:
            await event.send(
                event.plain_result(f"请求太快啦，{cooldown_left:.0f} 秒后再试。")
            )
            return

        self._mark_cooldown(event, scope="trends")
        started = time.perf_counter()

        client = self.fxtwitter_client

        try:
            trends = await asyncio.to_thread(client.fetch_trends)
        except Exception as exc:
            logger.warning(
                f"[NitterTweets] 手动获取推特热搜失败: {sanitize_sensitive_text(str(exc))}"
            )
            self._log_manual_no_send_task(
                "推特热搜查询",
                operation="trends",
                source="trends",
                instance="FxTwitter",
                started=started,
                status="抓取失败",
                error_detail=sanitize_sensitive_text(str(exc)),
                warning=True,
            )
            await event.send(
                event.plain_result("获取 Twitter/X 实时趋势热搜失败，请稍后重试。")
            )
            return

        if not trends:
            self._log_manual_no_send_task(
                "推特热搜查询",
                operation="trends",
                source="trends",
                instance="FxTwitter",
                started=started,
                status="无数据",
                warning=True,
            )
            await event.send(
                event.plain_result("获取 Twitter/X 实时趋势热搜暂无数据，请稍后再试。")
            )
            return

        formatted_text = format_twitter_trends(trends)
        sent = 0
        try:
            await event.send(event.plain_result(formatted_text))
            sent = len(trends)
        except Exception as exc:
            logger.warning(
                f"[NitterTweets] 发送推特热搜失败: {sanitize_sensitive_text(str(exc))}"
            )
        finally:
            self._log_manual_send_task(
                "推特热搜查询",
                operation="trends",
                source="trends",
                instance="FxTwitter",
                tweet_count=len(trends),
                sent_count=sent,
                started=started,
            )

    async def _send_tweets_response(
        self,
        event: AstrMessageEvent,
        username: str,
        instance: str,
        tweets,
        on_sent_progress=None,
        force_media: bool = False,
    ) -> int:
        hide_original = resolve_hide_original_when_translated(self.config)
        if self.sender.should_merge_for_event(event, len(tweets)):
            notices = []
            sent_count = 0

            def record_sent(count: int) -> None:
                nonlocal sent_count
                try:
                    confirmed = max(0, min(len(tweets), int(count)))
                except (TypeError, ValueError, OverflowError):
                    return
                if confirmed <= sent_count:
                    return
                sent_count = confirmed
                if callable(on_sent_progress):
                    try:
                        on_sent_progress(sent_count)
                    except Exception as exc:
                        logger.warning(f"[NitterTweets] 手动发送进度记录失败: {exc}")

            try:
                for tweet_index, tweet in enumerate(tweets, 1):
                    notices.extend(
                        await self._prepare_manual_tweets(
                            [tweet],
                            event.unified_msg_origin,
                            username=username,
                            progress_index=tweet_index,
                            progress_total=len(tweets),
                            force_all_media=force_media,
                        )
                    )
                sent = await self._send_manual_tweets_with_fallback(
                    event,
                    username,
                    instance,
                    tweets,
                    notices=self._dedupe_texts(notices),
                    hide_original_when_translated=hide_original,
                    on_sent_progress=record_sent,
                    force_media=force_media,
                )
                # Preserve compatibility with older overrides that returned
                # None/True without invoking the new progress callback.
                if sent is not False and sent_count == 0:
                    record_sent(len(tweets))
                return sent_count
            finally:
                await self._cleanup_manual_media(tweets)

        # Sequential path: interval applies to all platforms before adapter send.
        send_interval = resolve_manual_send_interval(self.config)
        sent_notices: set[str] = set()
        total = len(tweets)
        sent_count = 0
        for index, tweet in enumerate(tweets, 1):
            if index > 1 and send_interval > 0:
                await asyncio.sleep(send_interval)
            try:
                notices = await self._prepare_manual_tweets(
                    [tweet],
                    event.unified_msg_origin,
                    username=username,
                    progress_index=index,
                    progress_total=total,
                    force_all_media=force_media,
                )
                notices = [notice for notice in notices if notice not in sent_notices]
                sent_notices.update(notices)
                sent = await self._send_manual_tweets_with_fallback(
                    event,
                    username,
                    instance,
                    [tweet],
                    notices=notices,
                    tweet_start_index=1,
                    hide_original_when_translated=hide_original,
                    force_media=force_media,
                )
                # Keep compatibility with pre-reservation overrides that
                # returned None after a successful send.
                if sent is False:
                    break
                sent_count += 1
                if callable(on_sent_progress):
                    on_sent_progress(sent_count)
            except Exception as exc:
                logger.warning(
                    f"[NitterTweets] 手动推文准备/发送失败: username={username}, "
                    f"index={index}, error={exc}"
                )
                break
            finally:
                await self._cleanup_manual_media([tweet])
        return sent_count

    async def _cleanup_manual_media(self, tweets) -> None:
        """Keep cleanup failures from changing an already confirmed send."""
        try:
            await asyncio.to_thread(self.media.cleanup_after_send, tweets)
        except Exception as exc:
            logger.warning(f"[NitterTweets] 手动推文媒体清理失败: {exc}")

    async def _prepare_manual_tweets(
        self,
        tweets,
        umo: str | None,
        username: str = "",
        progress_index: int = 0,
        progress_total: int = 0,
        force_all_media: bool = False,
    ) -> list[str]:
        translation_report = await self.translator.attach_translations(tweets, umo)
        await self.media.attach_media_with_results(
            tweets, force_all_media=force_all_media
        )
        if username:
            self._log_ai_process_results(
                username,
                tweets,
                translation_report,
                progress_index,
                progress_total,
            )
        return []

    def _log_ai_process_results(
        self,
        username: str,
        tweets,
        translation_report=None,
        progress_index: int = 0,
        progress_total: int = 0,
    ) -> None:
        # Skip per-tweet AI log when translation is off — the
        # "translation=off" line adds no value and clutters the log
        # for every tweet in the batch.
        if not getattr(self.translator, "enabled", True):
            return
        total = progress_total or len(tweets)
        start = progress_index or 1
        for offset, tweet in enumerate(tweets):
            logger.info(
                format_ai_tweet_summary(
                    username,
                    tweet,
                    translation_report,
                    start + offset,
                    total,
                )
            )

    async def _send_manual_tweets_with_fallback(
        self,
        event: AstrMessageEvent,
        username: str,
        instance: str,
        tweets,
        notices: list[str] | None = None,
        header_text: str = "",
        tweet_start_index: int = 1,
        hide_original_when_translated: bool = False,
        on_sent_progress=None,
        force_media: bool = False,
    ) -> bool:
        notices = notices or []
        sent_count = 0

        def record_sent(count: int) -> None:
            nonlocal sent_count
            try:
                confirmed = max(0, min(len(tweets), int(count)))
            except (TypeError, ValueError, OverflowError):
                return
            if confirmed <= sent_count:
                return
            sent_count = confirmed
            if callable(on_sent_progress):
                on_sent_progress(sent_count)

        if await self.sender.send(
            event,
            username,
            instance,
            tweets,
            notices=notices,
            header_text=header_text,
            tweet_start_index=tweet_start_index,
            hide_original_when_translated=hide_original_when_translated,
            on_sent_progress=record_sent,
            force_media=force_media,
        ):
            record_sent(len(tweets))
            return True
        remaining = list(tweets[sent_count:])
        if not remaining:
            return True

        if getattr(self.sender, "last_send_rejected", False) and not getattr(
            self.sender, "forward_reject_plain_fallback_enabled", False
        ):
            notice = (
                "⚠️ 部分推文触发平台风控，已自动略过。"
                if sent_count > 0
                else "⚠️ 内容触发平台风控，已自动略过。"
            )
            try:
                if hasattr(event, "plain_result"):
                    await event.send(event.plain_result(notice))
                else:
                    await event.send(MessageChain([Plain(notice)]))
            except Exception as exc:
                logger.warning(
                    f"[NitterTweets] 发送风控略过提示失败: {sanitize_sensitive_text(str(exc))}"
                )
            return sent_count > 0

        remaining_start_index = tweet_start_index + sent_count
        remaining_notices = notices if sent_count == 0 else []
        remaining_header = header_text if sent_count == 0 else ""
        fallback_text = self.sender.renderer.format_plain(
            username,
            instance,
            remaining,
            start_index=remaining_start_index,
            notices=remaining_notices,
            header_text=remaining_header,
            hide_original_when_translated=hide_original_when_translated,
        )
        try:
            await event.send(MessageChain([Plain(fallback_text)]))
            record_sent(len(tweets))
            return True
        except Exception as exc:
            logger.warning(f"[NitterTweets] 发送手动推文降级消息失败: {exc}")
            try:
                await event.send(
                    MessageChain(
                        [
                            Plain(
                                f"已获取 @{username} 的推文，但发送失败。"
                                "请查看插件日志或稍后重试。"
                            )
                        ]
                    )
                )
            except Exception as notice_exc:
                logger.warning(f"[NitterTweets] 发送手动推文失败提示失败: {notice_exc}")
            return False

    @staticmethod
    def _dedupe_texts(values: list[str]) -> list[str]:
        result = []
        seen = set()
        for value in values:
            if value in seen:
                continue
            seen.add(value)
            result.append(value)
        return result

    def _parse_mirror_probe_args(
        self,
        event: AstrMessageEvent,
        args: str,
    ) -> tuple[str, int, str, str]:
        tokens = self._command_tokens(event, args)
        usage = (
            "用法：/镜像测试 [用户名] [数量] 实例URL\n"
            "实例必须填写完整 http:// 或 https:// 地址\n"
            "例如：/镜像测试 http://nitter:8080\n"
            "也可以：/镜像测试 nasa 3 http://nitter:8080"
        )
        if not tokens:
            return "", 0, "", usage

        instance_index = -1
        for index, token in enumerate(tokens):
            if self._looks_like_instance(token):
                instance_index = index
        if instance_index < 0:
            return (
                "",
                0,
                "",
                ("请提供完整 Nitter 实例地址，例如：/镜像测试 http://nitter:8080"),
            )

        instance_text = tokens[instance_index]
        try:
            instance_text = validate_http_url(instance_text).rstrip("/")
        except UnsafeUrlError:
            return (
                "",
                0,
                "",
                "实例地址格式无效，请使用完整的 http:// 或 https:// 地址",
            )
        extras = tokens[:instance_index] + tokens[instance_index + 1 :]
        if len(extras) > 2:
            return "", 0, "", usage

        username = "nasa"
        requested_limit = self.default_limit
        seen_username = False
        seen_limit = False
        for token in extras:
            if self._looks_like_limit(token):
                if seen_limit:
                    return (
                        "",
                        0,
                        "",
                        ("数量只能填写一次，例如：/镜像测试 3 http://nitter:8080"),
                    )
                parsed_limit, limit_error = self._parse_command_limit(token)
                if limit_error:
                    return "", 0, "", limit_error
                requested_limit = parsed_limit
                seen_limit = True
                continue

            normalized = normalize_username(token)
            if not normalized:
                return "", 0, "", usage
            if seen_username:
                return (
                    "",
                    0,
                    "",
                    ("用户名只能填写一次，例如：/镜像测试 nasa http://nitter:8080"),
                )
            username = normalized
            seen_username = True

        return username, requested_limit, instance_text, ""

    @staticmethod
    def _parse_positive_limit(value, fallback: int) -> int:
        try:
            number = int(value)
        except (TypeError, ValueError):
            return fallback
        return number if number > 0 else fallback

    @staticmethod
    def _parse_command_limit(value: str) -> tuple[int, str]:
        try:
            number = int(str(value).strip())
        except (TypeError, ValueError):
            return 0, "数量需要是整数，例如：/推文 nasa 5"
        if number <= 0:
            return 0, "数量需要大于 0，例如：/推文 nasa 5"
        return number, ""

    @staticmethod
    def _looks_like_limit(value: str) -> bool:
        return bool(re.fullmatch(r"[+-]?\d+", str(value or "").strip()))

    def _command_tokens(self, event: AstrMessageEvent, args: str) -> list[str]:
        return [
            token
            for token in str(args or "").split()
            if not self._is_self_at_argument(event, token)
        ]

    def _strip_self_at_argument(self, event: AstrMessageEvent, value: str) -> str:
        value = str(value or "").strip()
        return "" if self._is_self_at_argument(event, value) else value

    def _is_self_at_argument(self, event: AstrMessageEvent, value: str) -> bool:
        value = str(value or "").strip()
        if not value.startswith("@"):
            return False

        self_id = str(safe_call(event, "get_self_id") or "").strip()
        if not self_id:
            return False

        for component in safe_call(event, "get_messages") or []:
            if not isinstance(component, At):
                continue
            at_id = str(getattr(component, "qq", "") or "").strip()
            at_name = str(getattr(component, "name", "") or "").strip()
            if self_id not in {at_id, at_name}:
                continue
            if value in {f"@{at_id}", f"@{at_name}"}:
                return True
        return False

    @staticmethod
    def _looks_like_instance(value: str) -> bool:
        value = str(value or "").strip()
        if not value or value.startswith("@") or " " in value:
            return False
        try:
            validate_http_url(value)
        except UnsafeUrlError:
            return False
        return True

    def _search_session_id(self, event: AstrMessageEvent) -> str:
        """Session id for search buffer: prefer UMO, else group/private + sender."""
        umo = str(getattr(event, "unified_msg_origin", "") or "").strip()
        if umo:
            return umo
        sender = safe_call(event, "get_sender_id") or "unknown"
        group = safe_call(event, "get_group_id") or "private"
        return f"{group}:{sender}"

    def _search_query_key(self, query: str, sort: str = "") -> str:
        q = str(query or "").strip()
        try:
            from ..media_support.html_backend.query import normalize_query
        except ImportError:  # pragma: no cover
            try:
                from media_support.html_backend.query import normalize_query
            except ImportError:
                base = q.casefold()
            else:
                base = normalize_query(q).casefold()
        else:
            base = normalize_query(q).casefold()
        # Include sort in the key so explicit latest/top searches don't share
        # a cache with the no-flag path (which falls back to config search_sort).
        suffix = f"\0{sort}" if sort else ""
        return f"{base}{suffix}"

    def _get_search_session_store(self):
        store = getattr(self, "_search_session_store", None)
        if store is None:
            store = SearchSessionStore()
            self._search_session_store = store
        return store

    def _cooldown_key(self, event: AstrMessageEvent, scope: str = "tweet") -> str:
        sender = safe_call(event, "get_sender_id") or "unknown"
        group = safe_call(event, "get_group_id") or "private"
        return f"{scope}:{group}:{sender}"

    def _cooldown_seconds_for(self, scope: str = "tweet") -> float:
        if scope == "search":
            return float(getattr(self, "search_cooldown_seconds", 30.0) or 0.0)
        return float(getattr(self, "cooldown_seconds", 0.0) or 0.0)

    def _cooldown_left(self, event: AstrMessageEvent, scope: str = "tweet") -> float:
        seconds = self._cooldown_seconds_for(scope)
        if seconds <= 0:
            return 0
        last = self._cooldowns.get(self._cooldown_key(event, scope), 0)
        return max(0.0, seconds - (time.time() - last))

    def _mark_cooldown(self, event: AstrMessageEvent, scope: str = "tweet") -> None:
        self._cooldowns[self._cooldown_key(event, scope)] = time.time()
