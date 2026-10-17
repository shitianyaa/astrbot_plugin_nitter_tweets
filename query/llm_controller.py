"""LLM-only query orchestration: event budgets, isolated pages and delivery.

Manual commands and the scheduler do not use these result windows or budgets.
This module never invokes the plugin translator or changes seen/history.
"""

from __future__ import annotations

import asyncio
import json
from copy import copy
from typing import Any

try:
    from ..shared import normalize_username
except ImportError:
    from shared import normalize_username

from .admin_state import admin_state
from .budget import BudgetLimitExceeded, QueryBudget
from .formatting import (
    response_json,
    trends_to_data,
    tweet_to_data,
)
from .models import FetchStatus, SearchQuery, TimelineQuery, TrendQuery
from .service import QueryService
from .session import ResultSessionStore

_FETCH_TIMEOUT_SECONDS = 90
_MEDIA_TIMEOUT_SECONDS = 90

# Every warning emitted by _deliver_media belongs here. Previewing their
# union before any platform side effects bounds the final JSON text cost.
_MEDIA_PREVIEW_WARNINGS = (
    "本轮直接发送上限为 5 条，剩余仅返回数据",
    "媒体准备超时，未发出原帖",
    "媒体准备失败，未发出原帖",
    "平台发送超时，送达状态不确定，未自动重发",
    "发送失败，未自动重复发送",
    "平台未确认发送成功，未自动重发",
    "结果过长，部分文本已截断",
)


class LLMQueryController:
    def __init__(self, plugin):
        self.plugin = plugin
        self.sessions = ResultSessionStore()

    def _service(self) -> QueryService:
        return QueryService(
            self.plugin.nitter,
            self.plugin.fxtwitter,
            fetch_backend=self.plugin.fetch_backend,
        )

    @staticmethod
    def validate_common(
        *,
        limit: int,
        media_type: str = "",
        page_mode: str = "auto",
        delivery: str = "data",
    ) -> None:
        if type(limit) is not int or not 1 <= limit <= 10:
            raise ValueError("limit must be an integer between 1 and 10")
        if media_type not in {"", "image", "video"} or type(media_type) is not str:
            raise ValueError("media_type must be image, video or empty")
        if type(page_mode) is not str or page_mode not in {"auto", "refresh"}:
            raise ValueError("page_mode must be auto or refresh")
        if type(delivery) is not str or delivery not in {"data", "media"}:
            raise ValueError("delivery must be data or media")

    def _claim_network(self, event, budget: QueryBudget, scope: str) -> None:
        # This is synchronous under a reentrant lock, so two concurrent tool
        # calls cannot both bypass the first request's cooldown check.
        with budget._lock:
            if budget.network_used >= budget.max_network:
                raise BudgetLimitExceeded(
                    "network", budget.max_network - budget.network_used
                )
            if budget.network_used == 0:
                left = self.plugin._cooldown_left(event, scope=scope)
                if left > 0:
                    raise QueryCooldown(left)
            budget.start_network()
            if budget.network_used == 1:
                self.plugin._mark_cooldown(event, scope=scope)

    async def timeline(
        self,
        event,
        *,
        username: str,
        limit: int = 5,
        media_type: str = "",
        page_mode: str = "auto",
        delivery: str = "data",
    ) -> str:
        self.validate_common(
            limit=limit,
            media_type=media_type,
            page_mode=page_mode,
            delivery=delivery,
        )
        if type(username) is not str:
            raise ValueError("username must be a public X username")
        normalized = normalize_username(username)
        if not normalized:
            raise ValueError("username must be a public X username")
        return await self._tweet_query(
            event,
            kind="timeline",
            source=normalized,
            limit=limit,
            media_type=media_type,
            page_mode=page_mode,
            delivery=delivery,
            sort="latest",
        )

    async def search(
        self,
        event,
        *,
        query: str,
        limit: int = 5,
        sort: str = "latest",
        media_type: str = "",
        page_mode: str = "auto",
        delivery: str = "data",
    ) -> str:
        self.validate_common(
            limit=limit,
            media_type=media_type,
            page_mode=page_mode,
            delivery=delivery,
        )
        if type(query) is not str or not query.strip() or len(query.strip()) > 200:
            raise ValueError("query must be nonempty and at most 200 characters")
        if type(sort) is not str or sort not in {"latest", "top"}:
            raise ValueError("sort must be latest or top")
        if media_type and len(query.strip() + " filter:media") > 200:
            raise ValueError("media filter exceeds the 200 character query limit")
        return await self._tweet_query(
            event,
            kind="search",
            source=query.strip(),
            limit=limit,
            media_type=media_type,
            page_mode=page_mode,
            delivery=delivery,
            sort=sort,
        )

    async def _tweet_query(
        self,
        event,
        *,
        kind: str,
        source: str,
        limit: int,
        media_type: str,
        page_mode: str,
        delivery: str,
        sort: str,
    ) -> str:
        budget = QueryBudget.for_event(event)
        data_ticket = budget.reserve_data(limit)
        text_ticket = None
        token = None
        window = None
        delivered: dict[str, Any] = {
            "requested": delivery == "media",
            "attempted": 0,
            "confirmed_sent": 0,
            "failed": 0,
            "uncertain": 0,
            "preparation_failed": 0,
        }
        try:
            window = self.sessions.llm_window(
                event,
                kind=kind,
                source=source,
                sort=sort,
                media_type=media_type,
                refresh=page_mode == "refresh",
            )
            cached = len(window) > 0
            continuation = window.cursor if not cached else ""
            exhausted = bool(window.known_ids) and not cached and not continuation
            outcome = None

            if not cached and not exhausted:
                self._claim_network(
                    event, budget, "search" if kind == "search" else "tweet"
                )
                fetch_limit = min(40, max(15, limit * 3))
                if kind == "search":
                    outcome = await asyncio.wait_for(
                        self._service().search(
                            SearchQuery(
                                source,
                                limit=fetch_limit,
                                sort=sort,
                                is_media=bool(media_type),
                                media_type=media_type,
                                max_pages=3,
                                cursor=continuation or None,
                            )
                        ),
                        timeout=_FETCH_TIMEOUT_SECONDS,
                    )
                else:
                    outcome = await asyncio.wait_for(
                        self._service().fetch_timeline(
                            TimelineQuery(
                                source,
                                limit=fetch_limit,
                                media_filter=media_type,
                                max_pages=3,
                                cursor=continuation or None,
                                filter_reposts=bool(
                                    getattr(self.plugin, "filter_reposts_enabled", True)
                                ),
                            )
                        ),
                        timeout=_FETCH_TIMEOUT_SECONDS,
                    )
                if outcome.status == FetchStatus.ERROR:
                    return self._finalize_empty(budget, data_ticket, kind, outcome)

                added = window.add_tweets(
                    outcome.tweets,
                    instance=("FxTwitter" if outcome.backend == "fx" else "Nitter"),
                )
                next_cursor = outcome.cursor if outcome.backend == "fx" else None
                # A cursor is only useful if it advances to a genuinely new
                # page. A repeated cursor or duplicate-only page must end.
                window.cursor = (
                    next_cursor
                    if added and next_cursor and next_cursor != continuation
                    else ""
                )

            token, tweets = window.reserve(limit)
            warnings: list[str] = []
            if outcome is not None and outcome.status in (
                FetchStatus.INCOMPLETE,
                FetchStatus.PARTIAL,
            ):
                warnings.append("抓取扫描不完整，结论仅供参考")
            if outcome is not None and outcome.plain_text_filtered > 0 and media_type:
                warnings.append("媒体类型只能依据当前可用元数据判断")
            if not tweets and window.known_ids and not window.cursor:
                warnings.append("当前查询没有更多未读推文；可用 refresh 刷新")

            base_status = (
                "partial"
                if outcome is not None
                and outcome.status in (FetchStatus.INCOMPLETE, FetchStatus.PARTIAL)
                else "success"
                if tweets
                else "empty"
            )
            base: dict[str, Any] = {
                "status": base_status,
                "kind": kind,
                "items": [tweet_to_data(tweet) for tweet in tweets],
                "returned_count": len(tweets),
                "has_more": bool(len(window)) or bool(window.cursor),
                "from_cache": cached or exhausted,
                "delivery": delivered,
                "warnings": warnings,
                "truncated": False,
            }
            if any(row["text_truncated"] for row in base["items"]):
                warnings.append("单条推文正文超长，已截断到 900 字")

            # Budget must be secured before sending *anything*. Build a
            # conservative full-envelope upper bound (including all possible
            # fixed delivery warnings); it may trim rows/leaf text safely.
            # The actual delivery response can only be shorter.
            preview = dict(base)
            if delivery == "media" and tweets:
                preview["status"] = "partial"
                preview["has_more"] = False  # False is longer than True in JSON.
                preview["from_cache"] = False
                preview["warnings"] = [*warnings, *_MEDIA_PREVIEW_WARNINGS]
                preview["delivery"] = {
                    "requested": True,
                    "attempted": 5,
                    "confirmed_sent": 5,
                    "failed": 5,
                    "uncertain": 5,
                    "preparation_failed": 5,
                }
            preview_data = json.loads(response_json(preview))
            visible_items = preview_data.get("items", [])
            visible_tweets = tweets[: len(visible_items)]
            is_truncated = bool(preview_data.get("truncated", False))
            if is_truncated and "结果过长，部分文本已截断" not in warnings:
                warnings.append("结果过长，部分文本已截断")

            # Text and tweet data reservations are independent. A tool with
            # insufficient text quota must never send messages on the side.
            text_ticket = budget.reserve_text(
                len(json.dumps(preview_data, ensure_ascii=False, separators=(",", ":")))
            )
            if delivery == "media" and visible_tweets:
                await self._deliver_media(
                    event, visible_tweets, source, kind, budget, delivered, warnings
                )

            media_partial = (
                delivery == "media"
                and bool(visible_tweets)
                and (
                    delivered["failed"] > 0
                    or delivered["uncertain"] > 0
                    or delivered["preparation_failed"] > 0
                    or delivered["attempted"] < len(visible_tweets)
                )
            )
            response = {
                **base,
                "status": (
                    "partial"
                    if base_status == "partial"
                    or media_partial
                    or (tweets and not visible_items)
                    else base_status
                ),
                "items": visible_items,
                "returned_count": len(visible_items),
                "has_more": (
                    bool(len(window))
                    or bool(window.cursor)
                    or len(visible_items) < len(tweets)
                ),
                "delivery": delivered,
                "warnings": warnings,
                "truncated": is_truncated,
            }
            encoded = response_json(response)
            final = json.loads(encoded)
            shown = len(final.get("items", []))
            if shown < len(visible_items):
                final["has_more"] = True
                final["truncated"] = True
                if shown == 0:
                    final["status"] = "partial"
                encoded = response_json(final)
                shown = len(json.loads(encoded).get("items", []))

            if len(encoded) > text_ticket.amount:
                # Defensive safety net for future warning fields: preserve
                # confirmed delivery counts rather than throwing post-send.
                compact = {
                    "status": "partial",
                    "kind": kind,
                    "items": [],
                    "returned_count": 0,
                    "has_more": True,
                    "delivery": delivered,
                    "warnings": ["结果超出长度限制，正文未能返回"],
                    "truncated": True,
                }
                encoded = response_json(compact)
                shown = 0
                if len(encoded) > text_ticket.amount:
                    raise RuntimeError("delivery result exceeded text reservation")

            # A row is read when actually returned to the model, or when its
            # delivery was attempted and replay could duplicate a platform
            # message. All other reserved rows return to the front.
            consumed = max(shown, delivered["attempted"])
            window.finalize(token, consumed)
            token = None
            data_ticket.commit(shown)
            text_ticket.commit(len(encoded))
            return encoded
        except BaseException:
            if token is not None and window is not None:
                window.finalize(
                    token,
                    delivered["confirmed_sent"],
                    failed_count=delivered["failed"] + delivered["uncertain"],
                )
            data_ticket.rollback()
            if text_ticket is not None:
                text_ticket.rollback()
            raise

    @staticmethod
    def _finalize_empty(
        budget: QueryBudget,
        data_ticket,
        kind: str,
        outcome,
    ) -> str:
        result = response_json(
            {
                "status": "error",
                "kind": kind,
                "items": [],
                "returned_count": 0,
                "error_kind": outcome.error_kind or "UnavailableProvider",
                "warnings": [],
            }
        )
        ticket = budget.reserve_text(len(result))
        data_ticket.commit(0)
        ticket.commit()
        return result

    async def _deliver_media(
        self,
        event,
        tweets,
        source: str,
        kind: str,
        budget: QueryBudget,
        progress: dict[str, Any],
        warnings: list[str],
    ) -> None:
        sender = self.plugin.sender
        media_service = self.plugin.media
        if budget.remaining()["send"] == 0:
            warnings.append("本轮直接发送上限为 5 条，剩余仅返回数据")
            return
        if budget.progress_notice():
            try:
                await event.send(event.plain_result("正在发送所请求的公开推文..."))
            except Exception:
                pass

        for tweet in tweets:
            if budget.remaining()["send"] == 0:
                warnings.append("本轮直接发送上限为 5 条，剩余仅返回数据")
                break
            delivery_copy = copy(tweet)
            delivery_copy.media = [copy(item) for item in tweet.media]
            delivery_copy.media_candidates = list(tweet.media_candidates)
            try:
                # Media preparation is not a platform send. A timeout here
                # must not be recorded as an uncertain delivery or consume
                # the send allowance.
                if getattr(media_service, "enabled", False):
                    try:
                        results = await asyncio.wait_for(
                            media_service.attach_media_with_results(
                                [delivery_copy], force_all_media=False
                            ),
                            timeout=_MEDIA_TIMEOUT_SECONDS,
                        )
                    except asyncio.CancelledError:
                        raise
                    except TimeoutError:
                        progress["preparation_failed"] += 1
                        warnings.append("媒体准备超时，未发出原帖")
                        break
                    except Exception:
                        progress["preparation_failed"] += 1
                        warnings.append("媒体准备失败，未发出原帖")
                        break
                    if results and any(
                        getattr(item, "status", "") == "transient_failure"
                        for item in results
                    ):
                        progress["preparation_failed"] += 1
                        warnings.append("媒体准备失败，未发出原帖")
                        break

                try:
                    budget.start_send()
                except BudgetLimitExceeded:
                    warnings.append("本轮直接发送上限为 5 条，剩余仅返回数据")
                    break
                progress["attempted"] += 1
                try:
                    sent = await asyncio.wait_for(
                        sender.send(
                            event,
                            source if kind == "timeline" else "搜索结果",
                            "FxTwitter/Nitter",
                            [delivery_copy],
                            force_media=False,
                            media_only=False,
                            omit_status_url=False,
                        ),
                        timeout=_MEDIA_TIMEOUT_SECONDS,
                    )
                except asyncio.CancelledError:
                    # The platform call may have succeeded before cancellation.
                    progress["uncertain"] += 1
                    raise
                except TimeoutError:
                    progress["uncertain"] += 1
                    warnings.append("平台发送超时，送达状态不确定，未自动重发")
                    break
                except Exception:
                    progress["failed"] += 1
                    warnings.append("发送失败，未自动重复发送")
                    break
                if sent:
                    progress["confirmed_sent"] += 1
                else:
                    progress["failed"] += 1
                    warnings.append("平台未确认发送成功，未自动重发")
                    break
            finally:
                try:
                    await asyncio.wait_for(
                        asyncio.to_thread(
                            media_service.cleanup_after_send, [delivery_copy]
                        ),
                        timeout=12,
                    )
                except Exception:
                    pass

    async def trends(self, event) -> str:
        budget = QueryBudget.for_event(event)
        self._claim_network(event, budget, "trends")
        result = await asyncio.wait_for(
            self._service().trends(TrendQuery()), timeout=_FETCH_TIMEOUT_SECONDS
        )
        rows = trends_to_data(result.trends)
        response = response_json(
            {
                "status": (
                    "error"
                    if result.status == FetchStatus.ERROR
                    else "success"
                    if rows
                    else "empty"
                ),
                "kind": "trends",
                "items": rows,
                "returned_count": len(rows),
                "error_kind": result.error_kind or None,
                "warnings": [],
            }
        )
        budget.reserve_text(len(response)).commit()
        return response

    async def state(self, event, *, scope: str = "all", page: int = 1) -> str:
        result = admin_state(self.plugin, event, scope=scope, page=page)
        response = response_json(result)
        QueryBudget.for_event(event).reserve_text(len(response)).commit()
        return response


class QueryCooldown(Exception):
    def __init__(self, seconds: float):
        self.seconds = max(0, float(seconds))
        super().__init__("query cooldown")
