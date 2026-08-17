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
        parse_config_bool,
        resolve_hide_original_when_translated,
        resolve_manual_send_interval,
    )
    from ..media_support.html_backend.query import MAX_QUERY_LENGTH
    from ..media_support.network import UnsafeUrlError, validate_http_url
    from ..media_support.search_session_buffer import (
        MAX_FETCH_CAP,
        MAX_PAGES_PER_FILL,
        SearchSessionStore,
    )
    from ..shared import normalize_username, safe_call
    from ..shared.observability import safe_task_log
except ImportError:
    from ai import format_ai_tweet_summary
    from config import (
        parse_config_bool,
        resolve_hide_original_when_translated,
        resolve_manual_send_interval,
    )
    from media_support.html_backend.query import MAX_QUERY_LENGTH
    from media_support.network import UnsafeUrlError, validate_http_url
    from media_support.search_session_buffer import (
        MAX_FETCH_CAP,
        MAX_PAGES_PER_FILL,
        SearchSessionStore,
    )
    from shared import normalize_username, safe_call
    from shared.observability import safe_task_log


class ManualCommandMixin:
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
    ):
        """获取指定公开 X/Twitter 用户的最近推文。"""
        event.stop_event()

        username = normalize_username(username)
        if not username:
            await event.send(
                event.plain_result("用法：/推文 用户名 [数量]\n例如：/推文 nasa 5")
            )
            return

        cooldown_left = self._cooldown_left(event)
        if cooldown_left > 0:
            await event.send(
                event.plain_result(f"请求太快啦，{cooldown_left:.0f} 秒后再试。")
            )
            return

        limit_text = self._strip_self_at_argument(event, limit)
        if limit_text:
            parsed_limit, limit_error = self._parse_command_limit(limit_text)
            if limit_error:
                await event.send(event.plain_result(limit_error))
                return
            requested_limit = parsed_limit
        else:
            requested_limit = self.default_limit
        limit = requested_limit
        self._mark_cooldown(event)
        await event.send(
            event.plain_result(f"正在获取 @{username} 最近最多 {limit} 条推文...")
        )

        started = time.perf_counter()
        if hasattr(self.nitter, "begin_run_host_skip"):
            self.nitter.begin_run_host_skip()
        try:
            try:
                instance, tweets = await self.nitter.fetch_tweets(
                    username, limit, filter_reposts=False
                )
            except Exception as exc:
                logger.warning(f"[NitterTweets] 手动获取 @{username} 推文失败: {exc}")
                instance, tweets = await self._fetch_user_with_html_fallback(
                    username, limit, rss_error=exc
                )
                if not tweets:
                    self._log_manual_no_send_task(
                        "推文查询失败",
                        operation="user_timeline",
                        source=f"@{username}",
                        instance=instance,
                        started=started,
                        status="抓取失败",
                        error_detail=f"RSS 与 HTML 回退均不可用: {exc}",
                        warning=True,
                    )
                    await event.send(
                        event.plain_result(
                            f"获取 @{username} 推文失败：Nitter RSS 与 HTML 回退均不可用。"
                        )
                    )
                    return
            else:
                if not tweets:
                    instance, tweets = await self._fetch_user_with_html_fallback(
                        username, limit, rss_error=None
                    )
                    if not tweets:
                        self._log_manual_no_send_task(
                            "推文查询完成",
                            operation="user_timeline",
                            source=f"@{username}",
                            instance=instance,
                            started=started,
                            status="无公开推文",
                        )
                        await event.send(
                            event.plain_result(f"没有找到 @{username} 的公开推文。")
                        )
                        return

        finally:
            if hasattr(self.nitter, "end_run_host_skip"):
                self.nitter.end_run_host_skip()
        sent_count = await self._send_tweets_response(event, username, instance, tweets)
        self._log_manual_send_task(
            "推文查询完成",
            operation="user_timeline",
            source=f"@{username}",
            instance=instance,
            tweet_count=len(tweets),
            sent_count=sent_count,
            started=started,
        )

    async def _cmd_tweet_search_impl(self, event: AstrMessageEvent, args=GreedyStr):
        """HTML 搜索公开推文：标签请带 #，短语直接写。"""
        event.stop_event()

        query, limit, error = self._parse_search_args(event, args)
        if error:
            await event.send(event.plain_result(error))
            return

        cooldown_left = self._cooldown_left(event, scope="search")
        if cooldown_left > 0:
            await event.send(
                event.plain_result(f"请求太快啦，{cooldown_left:.0f} 秒后再试。")
            )
            return

        search_started = time.perf_counter()
        html_backend = getattr(self, "html_backend", None)
        if html_backend is None:
            self._log_manual_no_send_task(
                "推文搜索失败",
                operation="tweet_search",
                source=query,
                started=search_started,
                status="搜索后端未初始化",
                warning=True,
            )
            await event.send(event.plain_result("搜索后端未初始化。"))
            return
        if not getattr(html_backend.config, "search_enabled", True):
            self._log_manual_no_send_task(
                "推文搜索跳过",
                operation="tweet_search",
                source=query,
                started=search_started,
                status="搜索已关闭",
            )
            await event.send(event.plain_result("搜索已关闭（search_enabled=false）。"))
            return

        session_id = self._search_session_id(event)
        store = self._get_search_session_store()
        query_key = self._search_query_key(query)
        buf = store.get_or_create(session_id, query_key)

        sent_progress = [0]

        def record_sent_progress(count: int) -> None:
            # The send coroutine may abort after one or more messages were
            # accepted. Preserve that prefix when finalizing the reservation.
            sent_progress[0] = max(sent_progress[0], int(count))

        def abort_reservation(token: str) -> None:
            if sent_progress[0] > 0:
                buf.finalize(token, sent_progress[0])
            else:
                buf.rollback(token)

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
                sent_count = await self._send_tweets_response(
                    event,
                    query,
                    instance,
                    tweets,
                    on_sent_progress=record_sent_progress,
                )
            except BaseException:
                abort_reservation(reservation_token)
                raise
            buf.finalize(reservation_token, sent_count)
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
        try:
            instance, fetched = await asyncio.to_thread(
                html_backend.search,
                query,
                fetch_limit,
                max_pages=pages,
            )
        except TypeError:
            try:
                instance, fetched = await asyncio.to_thread(
                    html_backend.search, query, fetch_limit
                )
            except Exception as exc:
                logger.warning(f"[NitterTweets] 搜索失败 query={query!r}: {exc}")
                self._log_manual_no_send_task(
                    "推文搜索失败",
                    operation="tweet_search",
                    source=query,
                    started=search_started,
                    status="抓取失败",
                    error_detail=str(exc),
                    warning=True,
                )
                await event.send(
                    event.plain_result("搜索失败，请稍后重试或检查搜索镜像配置")
                )
                return
        except Exception as exc:
            logger.warning(f"[NitterTweets] 搜索失败 query={query!r}: {exc}")
            self._log_manual_no_send_task(
                "推文搜索失败",
                operation="tweet_search",
                source=query,
                started=search_started,
                status="抓取失败",
                error_detail=str(exc),
                warning=True,
            )
            await event.send(
                event.plain_result("搜索失败，请稍后重试或检查搜索镜像配置")
            )
            return

        added = buf.add_tweets(list(fetched or []), instance=instance or "")
        logger.info(
            f"[NitterTweets] search buffer session={session_id!r} query={query!r} "
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
        except BaseException:
            abort_reservation(reservation_token)
            raise
        buf.finalize(reservation_token, sent_count)
        self._log_manual_send_task(
            "推文搜索完成",
            operation="tweet_search",
            source=query,
            instance=buf.instance or instance or "",
            tweet_count=len(tweets),
            sent_count=sent_count,
            started=search_started,
        )

    async def _fetch_user_with_html_fallback(
        self, username: str, limit: int, rss_error=None
    ):
        html_backend = getattr(self, "html_backend", None)
        if html_backend is None:
            return "", []
        try:
            from ..config import config_get
        except ImportError:  # pragma: no cover
            from config import config_get

        if not parse_config_bool(
            config_get(self.config, "user_html_fallback", False), False
        ):
            return "", []
        try:
            instance, tweets = await asyncio.to_thread(
                html_backend.fetch_user, username, limit
            )
            if tweets:
                logger.info(
                    f"[NitterTweets] HTML 回退成功 @{username} via {instance}"
                    + (f" after RSS error={rss_error}" if rss_error else "")
                )
            return instance, list(tweets or [])
        except Exception as exc:
            logger.warning(f"[NitterTweets] HTML 回退失败 @{username}: {exc}")
            return "", []

    def _parse_search_args(self, event: AstrMessageEvent, args=GreedyStr):
        text = ""
        if args is not None and str(args).strip():
            text = str(args).strip()
        else:
            text = (event.get_message_str() or "").strip()
            # strip command token
            for prefix in ("/推文搜索", "推文搜索", "/tweetsearch", "tweetsearch"):
                if text.startswith(prefix):
                    text = text[len(prefix) :].strip()
                    break
        if not text:
            return (
                "",
                0,
                (
                    "用法：/推文搜索 <query> [数量]\n"
                    "标签请带 #，例如：#圣娅\n"
                    "普通词/短语直接写：python programming"
                ),
            )
        parts = text.rsplit(None, 1)
        limit = int(getattr(self, "search_default_limit", self.default_limit))
        query = text
        if len(parts) == 2 and parts[1].isdigit():
            query = parts[0].strip()
            limit = int(parts[1])
        max_limit = int(getattr(self, "search_max_limit", 10))
        if limit < 1:
            return "", 0, "数量至少为 1。"
        limit = min(limit, max_limit)
        if not query:
            return "", 0, "查询内容不能为空。"
        if len(query) > MAX_QUERY_LENGTH:
            return "", 0, f"查询内容过长（最多 {MAX_QUERY_LENGTH} 字符）。"
        return query, limit, ""

    async def _cmd_mirror_probe_impl(self, event: AstrMessageEvent, args=GreedyStr):
        """用临时 Nitter 镜像站测试获取推文。"""
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
            instance, tweets = await self.nitter.fetch_tweets_from_instance(
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
                    "Nitter 镜像站暂时不可用或该用户无公开 RSS。"
                )
            )
            return

        if not tweets:
            await event.send(event.plain_result(f"没有找到 @{username} 的公开推文。"))
            return

        await self._send_tweets_response(event, username, instance, tweets)

    async def _send_tweets_response(
        self,
        event: AstrMessageEvent,
        username: str,
        instance: str,
        tweets,
        on_sent_progress=None,
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
                )
                # Preserve compatibility with older overrides that returned
                # None/True without invoking the new progress callback.
                if sent is not False:
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
    ) -> list[str]:
        translation_report = await self.translator.attach_translations(tweets, umo)
        await self.media.attach_media(tweets)
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
        ):
            record_sent(len(tweets))
            return True
        remaining = list(tweets[sent_count:])
        if not remaining:
            return True
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
            "用法：/镜像测试 [用户名] [数量] 镜像站URL\n"
            "镜像站必须填写完整 http:// 或 https:// 地址\n"
            "例如：/镜像测试 https://nitter.net\n"
            "也可以：/镜像测试 nasa 3 https://nitter.net"
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
                ("请提供完整 Nitter 镜像站地址，例如：/镜像测试 https://nitter.net"),
            )

        instance_text = tokens[instance_index]
        try:
            instance_text = validate_http_url(instance_text, resolve_dns=False).rstrip(
                "/"
            )
        except UnsafeUrlError:
            return (
                "",
                0,
                "",
                "镜像站地址不安全或格式无效，请使用公开的 http:// 或 https:// 地址",
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
                        ("数量只能填写一次，例如：/镜像测试 3 https://nitter.net"),
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
                    ("用户名只能填写一次，例如：/镜像测试 nasa https://nitter.net"),
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
            validate_http_url(value, resolve_dns=False)
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

    def _search_query_key(self, query: str) -> str:
        q = str(query or "").strip()
        try:
            from ..media_support.html_backend.query import normalize_query
        except ImportError:  # pragma: no cover
            try:
                from media_support.html_backend.query import normalize_query
            except ImportError:
                return q.casefold()
        try:
            return normalize_query(q).casefold()
        except Exception:
            return q.casefold()

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
