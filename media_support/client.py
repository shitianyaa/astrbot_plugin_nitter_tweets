from __future__ import annotations

import asyncio
import re
import ssl
import time
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request
from xml.etree import ElementTree as ET

from astrbot.api import logger

try:
    from ..config import config_get
    from ..shared import (
        TweetItem, clean_text, clamp_float, load_instances, normalize_external_links,
    )
except ImportError:
    from config import config_get
    from shared import (
        TweetItem, clean_text, clamp_float, load_instances, normalize_external_links,
    )

from .network import compat_urlopen


class TransientFetchError(RuntimeError):
    pass


class EmptyFeedError(RuntimeError):
    """A valid RSS response contained no items at all."""


# 作者上传的媒体标记：Nitter RSS 的 <description> 是 HTML，作者上传的图片走
# /pic/media（链接预览卡片图走 /pic/card_img，不算作者媒体）；视频/GIF 可能包成
# <video> 标签，也可能只暴露 Nitter 的 video_thumb 封面图。引用推文里的媒体也不算
# 当前作者上传的媒体。
# Twitter Article（长文）的封面图虽走 /pic/media，但包在 <a href="/i/article/...">
# 里，属于文章卡片而非作者上传的媒体附件，不算作者媒体。
_MEDIA_SRC_RE = re.compile(
    r"(?i)/pic/(?:media|[a-z0-9_]+_video_thumb)(?:/|%2f)"
)
_ARTICLE_LINK_RE = re.compile(r"(?i)/i/article/")
# ElementTree blocks external entities by default but still permits DTD-defined
# entities; reject both declarations before parsing so the plugin needs no new
# runtime dependency just to process untrusted RSS responses.
_UNSAFE_XML_DECLARATION_RE = re.compile(
    br"<!\s*(?:DOCTYPE|ENTITY)\b", re.IGNORECASE
)
_HTML_VOID_TAGS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)


class _AuthorMediaDetector(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.has_author_media = False
        self._ignored_stack: list[tuple[str, bool]] = []

    @property
    def _inside_ignored_container(self) -> bool:
        return bool(self._ignored_stack and self._ignored_stack[-1][1])

    def handle_starttag(self, tag: str, attrs):
        tag = tag.lower()
        ignored = (
            self._inside_ignored_container
            or tag == "blockquote"
            or self._is_ignored_container(attrs)
            or self._is_article_link(tag, attrs)
        )
        if not ignored:
            self._detect_media(tag, attrs)
        if tag in _HTML_VOID_TAGS:
            return
        self._ignored_stack.append((tag, ignored))

    def handle_startendtag(self, tag: str, attrs):
        tag = tag.lower()
        if (
            self._inside_ignored_container
            or tag == "blockquote"
            or self._is_ignored_container(attrs)
            or self._is_article_link(tag, attrs)
        ):
            return
        self._detect_media(tag, attrs)

    def handle_endtag(self, tag: str):
        tag = tag.lower()
        if tag in _HTML_VOID_TAGS:
            return
        for index in range(len(self._ignored_stack) - 1, -1, -1):
            if self._ignored_stack[index][0] == tag:
                del self._ignored_stack[index:]
                return

    def _detect_media(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag == "video":
            self.has_author_media = True
            return
        if tag != "img":
            return
        src = self._first_attr_value(attrs, "src")
        if _MEDIA_SRC_RE.search(src):
            self.has_author_media = True

    @staticmethod
    def _is_ignored_container(attrs) -> bool:
        class_text = " ".join(
            _AuthorMediaDetector._attr_values(attrs, "class")
        )
        classes = {
            item.lower()
            for item in class_text.replace("_", "-").split()
        }
        return any("quote" in item for item in classes)

    @staticmethod
    def _is_article_link(tag: str, attrs) -> bool:
        if tag.lower() != "a":
            return False
        href = _AuthorMediaDetector._first_attr_value(attrs, "href")
        return bool(_ARTICLE_LINK_RE.search(href))

    @staticmethod
    def _first_attr_value(attrs, name: str) -> str:
        return next(iter(_AuthorMediaDetector._attr_values(attrs, name)), "")

    @staticmethod
    def _attr_values(attrs, name: str) -> list[str]:
        normalized_name = name.lower()
        return [
            str(value or "")
            for attr_name, value in attrs
            if str(attr_name or "").lower() == normalized_name
        ]


def _has_author_media(description: str) -> bool:
    if not description:
        return False
    detector = _AuthorMediaDetector()
    detector.feed(description)
    detector.close()
    return detector.has_author_media


@dataclass(slots=True)
class InstanceFetchResult:
    tweets: list[TweetItem]
    saw_items: bool = False
    plain_text_filtered: int = 0


@dataclass(slots=True)
class SchedulerFetchResult:
    tweets: list[TweetItem]
    scanned_status_ids: list[str]
    anchor_status_ids: list[str] = field(default_factory=list)
    latest_status_id: str = ""
    plain_text_filtered: int = 0
    reposts_filtered: int = 0
    complete: bool = False
    reached_watermark: bool = False


@dataclass(slots=True)
class RssPageResult:
    tweets: list[TweetItem]
    next_cursor: str = ""
    scanned_status_ids: list[str] = field(default_factory=list)
    raw_item_count: int = 0
    plain_text_filtered: int = 0


@dataclass(slots=True)
class FetchAttemptBudget:
    """Optional per-instance retry budget shared by all paginated RSS pages.

    When ``remaining`` is ``None``, each page gets its own normal retry count.
    When it is an integer, every page attempt consumes from the same budget so
    one slow/broken instance cannot spend more than the configured total.
    """

    remaining: int | None = None

    @property
    def exhausted(self) -> bool:
        return self.remaining is not None and self.remaining <= 0

    def attempts_for_page(self, default_attempts: int) -> int:
        if self.remaining is None:
            return default_attempts
        return max(1, self.remaining)

    def consume(self) -> bool:
        if self.remaining is None:
            return True
        if self.remaining <= 0:
            return False
        self.remaining -= 1
        return True


class NitterClient:
    SCHEDULER_SCAN_LIMIT = 300
    RSS_RESPONSE_LIMIT = 2_000_000

    def __init__(self, config):
        self.instances = load_instances(config_get(config, "instances"))
        self.timeout = clamp_float(
            config_get(config, "request_timeout", 12.0), 3.0, 60.0
        )
        self.user_agent = config_get(
            config,
            "user_agent", "Mozilla/5.0 (compatible; AstrBotNitterTweets/0.3)",
        )
        self.retry_attempts = 2
        self.retry_delay_seconds = 5.0
        self.filter_reposts_enabled = bool(
            config_get(config, "filter_reposts_enabled", True)
        )
        self.brief_log_enabled = bool(config_get(config, "brief_log_enabled", True))

    async def fetch_tweets(
        self,
        username: str,
        limit: int,
        skip_plain_text: bool = False,
    ) -> tuple[str, list[TweetItem]]:
        instance, tweets, _ = await self.fetch_tweets_with_stats(
            username, limit, skip_plain_text=skip_plain_text
        )
        return instance, tweets

    async def fetch_tweets_with_stats(
        self,
        username: str,
        limit: int,
        skip_plain_text: bool = False,
    ) -> tuple[str, list[TweetItem], int]:
        return await self._fetch_tweets_with_stats_from_instances(
            username,
            limit,
            self.instances,
            skip_plain_text=skip_plain_text,
            retry_attempts=self.retry_attempts,
        )

    async def fetch_tweets_with_stats_from_instances(
        self,
        username: str,
        limit: int,
        instances: list[str],
        start_index: int = 0,
        skip_plain_text: bool = False,
        retry_attempts: int = 3,
    ) -> tuple[str, list[TweetItem], int]:
        """Fetch using a dedicated instance pool rotated by ``start_index``.

        ``retry_attempts`` is the total attempt budget for each instance in this
        dedicated pool, shared across first-page and pagination requests. This
        differs from ``fetch_tweets_with_stats()``, where the default instance
        list gives each RSS page its own retry allowance.
        """

        ordered_instances = self._rotate_instances(instances, start_index)
        if not ordered_instances:
            raise RuntimeError("未配置并发专用 Nitter 实例")
        return await self._fetch_tweets_with_stats_from_instances(
            username,
            limit,
            ordered_instances,
            skip_plain_text=skip_plain_text,
            retry_attempts=retry_attempts,
            total_retry_attempts_per_instance=True,
        )

    async def fetch_tweets_for_scheduler(
        self,
        username: str,
        anchor_ids: list[str] | None,
        skip_plain_text: bool = False,
    ) -> tuple[str, SchedulerFetchResult]:
        return await self._fetch_tweets_for_scheduler_from_instances(
            username,
            anchor_ids,
            self.instances,
            skip_plain_text=skip_plain_text,
            retry_attempts=self.retry_attempts,
        )

    async def fetch_tweets_for_scheduler_from_instances(
        self,
        username: str,
        anchor_ids: list[str] | None,
        instances: list[str],
        start_index: int = 0,
        skip_plain_text: bool = False,
        retry_attempts: int = 3,
    ) -> tuple[str, SchedulerFetchResult]:
        """Fetch a complete scheduler scan from a dedicated instance pool.

        Scheduler pagination can legitimately span many successful pages, so
        ``retry_attempts`` applies to each page. The separate 300-item scan
        limit bounds the total work without making healthy scans stop after
        only a few pages.
        """

        ordered_instances = self._rotate_instances(instances, start_index)
        if not ordered_instances:
            raise RuntimeError("未配置并发专用 Nitter 实例")
        return await self._fetch_tweets_for_scheduler_from_instances(
            username,
            anchor_ids,
            ordered_instances,
            skip_plain_text=skip_plain_text,
            retry_attempts=retry_attempts,
            total_retry_attempts_per_instance=False,
        )

    async def _fetch_tweets_for_scheduler_from_instances(
        self,
        username: str,
        anchor_ids: list[str] | None,
        instances: list[str],
        skip_plain_text: bool = False,
        retry_attempts: int | None = None,
        total_retry_attempts_per_instance: bool = False,
    ) -> tuple[str, SchedulerFetchResult]:
        errors: list[str] = []
        empty_instances: list[str] = []
        for index, instance in enumerate(instances):
            try:
                result = await asyncio.to_thread(
                    self._fetch_for_scheduler_from_instance,
                    instance,
                    username,
                    anchor_ids,
                    skip_plain_text,
                    retry_attempts,
                    total_retry_attempts_per_instance,
                )
            except EmptyFeedError as exc:
                empty_instances.append(instance)
                errors.append(f"{instance}: {exc}")
                self._log_instance_fetch_failure(
                    index, instance, username, exc, instances
                )
                continue
            except Exception as exc:
                errors.append(f"{instance}: {exc}")
                self._log_instance_fetch_failure(
                    index, instance, username, exc, instances
                )
                continue
            self._log_instance_fetch_success(index, instance, username, result)
            return instance, result
        # If every configured instance returned a valid but empty RSS feed,
        # treat it as an initialized empty source. This lets a later first
        # tweet be delivered instead of being mistaken for historical data.
        if empty_instances and len(empty_instances) == len(instances):
            instance = empty_instances[0]
            result = SchedulerFetchResult(
                tweets=[],
                scanned_status_ids=[],
                complete=True,
            )
            self._log_instance_fetch_success(0, instance, username, result)
            return instance, result
        raise RuntimeError(self._format_fetch_errors(errors, total_count=len(instances)))

    async def _fetch_tweets_with_stats_from_instances(
        self,
        username: str,
        limit: int,
        instances: list[str],
        skip_plain_text: bool = False,
        retry_attempts: int | None = None,
        total_retry_attempts_per_instance: bool = False,
    ) -> tuple[str, list[TweetItem], int]:
        """Try instances in order until one returns RSS items or tweets.

        ``total_retry_attempts_per_instance=False`` means ``retry_attempts`` is
        applied per page fetch, preserving the historic serial behavior.
        ``True`` means ``retry_attempts`` is a per-instance total budget across
        all pagination requests; this is used for concurrent dedicated pools so
        pagination does not multiply the intended retry cost.
        """

        errors: list[str] = []
        for index, instance in enumerate(instances):
            try:
                result = await asyncio.to_thread(
                    self._fetch_from_instance,
                    instance,
                    username,
                    limit,
                    skip_plain_text,
                    retry_attempts,
                    total_retry_attempts_per_instance,
                )
            except Exception as exc:
                errors.append(f"{instance}: {exc}")
                self._log_instance_fetch_failure(
                    index, instance, username, exc, instances
                )
                continue
            if result.tweets or result.saw_items:
                self._log_instance_fetch_success(index, instance, username, result)
                return instance, result.tweets, result.plain_text_filtered
            errors.append(f"{instance}: empty feed")
            self._log_instance_fetch_failure(
                index, instance, username, "empty feed", instances
            )
        raise RuntimeError(self._format_fetch_errors(errors, total_count=len(instances)))

    def _log_instance_fetch_failure(
        self,
        index: int,
        instance: str,
        username: str,
        error,
        instances: list[str] | None = None,
    ) -> None:
        instances = instances or self.instances
        total = len(instances)
        if total <= 1:
            return

        if index + 1 < total:
            logger.warning(
                "[NitterTweets] RSS 实例失败，尝试下一个实例: "
                f"instance={instance}, next_instance={instances[index + 1]}, "
                f"username={username}, error={error}"
            )
            return

        logger.warning(
            "[NitterTweets] RSS 实例失败，已无更多实例可尝试: "
            f"instance={instance}, username={username}, error={error}"
        )

    def _log_instance_fetch_success(
        self, index: int, instance: str, username: str, result: InstanceFetchResult,
    ) -> None:
        if index <= 0:
            return

        logger.info(
            "[NitterTweets] RSS 实例成功，已完成实例切换: "
            f"instance={instance}, username={username}, tweets={len(result.tweets)}"
        )

    async def fetch_tweets_from_instance(
        self,
        instance: str,
        username: str,
        limit: int,
        skip_plain_text: bool = False,
    ) -> tuple[str, list[TweetItem]]:
        normalized = load_instances([instance])[0]
        result = await asyncio.to_thread(
            self._fetch_from_instance,
            normalized, username, limit, skip_plain_text,
        )
        if not result.tweets and not result.saw_items:
            raise RuntimeError(f"{normalized}: empty feed")
        return normalized, result.tweets

    def _format_fetch_errors(
        self, errors: list[str], total_count: int | None = None
    ) -> str:
        if not errors:
            return "未配置 Nitter 实例"

        shown_errors = errors[-3:]
        hidden_count = len(errors) - len(shown_errors)
        total_count = total_count if total_count is not None else len(self.instances)
        summary = f"已尝试 {len(errors)}/{total_count} 个 Nitter 实例，未获得可用 RSS"
        if hidden_count > 0:
            summary += (
                f"；仅显示最后 {len(shown_errors)} 个错误"
                f"（已省略前 {hidden_count} 个）"
            )
        else:
            summary += "；错误"
        return f"{summary}: {'; '.join(shown_errors)}"

    def _fetch_from_instance(
        self,
        instance: str,
        username: str,
        limit: int,
        skip_plain_text: bool = False,
        retry_attempts: int | None = None,
        total_retry_attempts_per_instance: bool = False,
    ) -> InstanceFetchResult:
        if limit <= 0:
            return InstanceFetchResult([])

        tweets: list[TweetItem] = []
        seen: set[str] = set()
        seen_cursors: set[str] = set()
        cursor = ""
        saw_items = False
        plain_text_filtered_total = 0
        # Dedicated concurrent pools cap retries per instance across pagination;
        # the default pool keeps the older per-page retry behavior.
        attempt_budget = FetchAttemptBudget(
            self._retry_attempt_count(retry_attempts)
            if total_retry_attempts_per_instance
            else None
        )

        while len(tweets) < limit:
            if attempt_budget.exhausted:
                break
            try:
                page = self._fetch_page_with_retries(
                    instance,
                    username,
                    cursor,
                    limit,
                    skip_plain_text,
                    retry_attempts,
                    attempt_budget,
                )
            except Exception:
                if not tweets:
                    raise
                logger.warning(
                    "[NitterTweets] RSS 分页抓取在已有部分结果后失败: "
                    f"instance={instance}, username={username}, fetched={len(tweets)}"
                )
                break

            # 只有"真正空页"（既无推文也无被过滤的 item）才结束分页；
            # 整页被纯文本/转发过滤掉时仍要继续翻页，否则会漏掉后面的带媒体推文。
            if not page.tweets and page.plain_text_filtered == 0:
                break

            saw_items = True
            plain_text_filtered_total += page.plain_text_filtered
            page_tweets, page_filtered_reposts = self._filter_reposts(
                page.tweets, username
            )
            # 本页 RSS 有 item 但全被过滤（纯文本或转发），过滤后 page_tweets 为空
            page_all_filtered = (
                (page.plain_text_filtered > 0 or page_filtered_reposts > 0)
                and not page_tweets
            )

            added = 0
            for tweet in page_tweets:
                key = self._tweet_identity(tweet)
                if key in seen:
                    continue
                seen.add(key)
                tweets.append(tweet)
                added += 1
                if len(tweets) >= limit:
                    break

            if len(tweets) >= limit:
                break
            if not page.next_cursor or page.next_cursor in seen_cursors:
                break
            seen_cursors.add(page.next_cursor)
            cursor = page.next_cursor
            if added == 0 and not page_all_filtered:
                break

        return InstanceFetchResult(
            tweets=tweets,
            saw_items=saw_items,
            plain_text_filtered=plain_text_filtered_total,
        )

    def _fetch_for_scheduler_from_instance(
        self,
        instance: str,
        username: str,
        anchor_ids: list[str] | None,
        skip_plain_text: bool = False,
        retry_attempts: int | None = None,
        total_retry_attempts_per_instance: bool = False,
    ) -> SchedulerFetchResult:
        initial_scan = anchor_ids is None
        normalized_anchor_ids = (
            [anchor_ids] if isinstance(anchor_ids, str) else (anchor_ids or [])
        )
        boundary_ids = {
            str(status_id).strip()
            for status_id in normalized_anchor_ids
            if str(status_id or "").strip()
        }
        tweets: list[TweetItem] = []
        seen_tweets: set[str] = set()
        scanned_status_ids: list[str] = []
        seen_status_ids: set[str] = set()
        seen_cursors: set[str] = set()
        cursor = ""
        scanned_item_count = 0
        plain_text_filtered_total = 0
        reposts_filtered_total = 0
        reached_watermark = False
        complete = False
        next_anchor_ids: list[str] = []
        attempt_budget = FetchAttemptBudget(
            self._retry_attempt_count(retry_attempts)
            if total_retry_attempts_per_instance
            else None
        )

        while True:
            if attempt_budget.exhausted:
                raise RuntimeError("后台 RSS 扫描未完成：实例请求次数已耗尽")
            page = self._fetch_page_with_retries(
                instance,
                username,
                cursor,
                0,
                skip_plain_text,
                retry_attempts,
                attempt_budget,
            )
            if page.raw_item_count == 0 and page.plain_text_filtered == 0:
                if scanned_item_count == 0:
                    raise EmptyFeedError(f"{instance}: empty feed")
                if boundary_ids and not reached_watermark:
                    raise RuntimeError(
                        "后台 RSS 扫描未完成：未找到任何已记录基准 ID"
                    )
                complete = True
                break
            scanned_item_count += page.raw_item_count
            if scanned_item_count > self.SCHEDULER_SCAN_LIMIT:
                raise RuntimeError(
                    "后台 RSS 扫描未完成："
                    f"超过安全上限 {self.SCHEDULER_SCAN_LIMIT} 条"
                )

            page_status_ids = page.scanned_status_ids
            if scanned_item_count == page.raw_item_count:
                next_anchor_ids = list(
                    dict.fromkeys(
                        str(status_id)
                        for status_id in page_status_ids
                        if str(status_id)
                    )
                )[:20]
            watermark_index = None
            if boundary_ids:
                watermark_index = next(
                    (
                        index
                        for index, status_id in enumerate(page_status_ids)
                        if status_id in boundary_ids
                    ),
                    None,
                )
            if watermark_index is not None:
                # The RSS page also contains rows older than the boundary.
                # Keep only the prefix through the exact baseline so those
                # historical rows are not mistaken for new tweets.
                page_status_ids = page_status_ids[: watermark_index + 1]

            for status_id in page_status_ids:
                if status_id in seen_status_ids:
                    continue
                seen_status_ids.add(status_id)
                scanned_status_ids.append(status_id)

            plain_text_filtered_total += page.plain_text_filtered
            page_tweets, page_reposts_filtered = self._filter_reposts(
                page.tweets, username
            )
            if watermark_index is not None:
                allowed_status_ids = set(page_status_ids)
                page_tweets = [
                    tweet
                    for tweet in page_tweets
                    if tweet.status_id in allowed_status_ids
                ]
            reposts_filtered_total += page_reposts_filtered
            for tweet in page_tweets:
                key = self._tweet_identity(tweet)
                if key in seen_tweets:
                    continue
                seen_tweets.add(key)
                tweets.append(tweet)

            # A missing row means first initialization: only seed the current
            # first page. An explicit empty/non-numeric row means the source
            # was already initialized without a usable status boundary, so a
            # complete scan to feed end is required to avoid losing page 2+.
            if initial_scan:
                complete = True
                break

            if watermark_index is not None:
                # Only the exact stored boundary proves that the scan reached
                # the previous checkpoint; numeric ordering is not enough.
                reached_watermark = True
                complete = True
                break
            if page.raw_item_count == 0 or not page.next_cursor:
                if boundary_ids and not reached_watermark:
                    raise RuntimeError(
                        "后台 RSS 扫描未完成：未找到任何已记录基准 ID"
                    )
                complete = True
                break
            if page.next_cursor in seen_cursors:
                raise RuntimeError("后台 RSS 扫描未完成：分页游标重复")
            seen_cursors.add(page.next_cursor)
            cursor = page.next_cursor

        return SchedulerFetchResult(
            tweets=tweets,
            scanned_status_ids=scanned_status_ids,
            anchor_status_ids=next_anchor_ids,
            latest_status_id=self._latest_status_id(scanned_status_ids),
            plain_text_filtered=plain_text_filtered_total,
            reposts_filtered=reposts_filtered_total,
            complete=complete,
            reached_watermark=reached_watermark,
        )

    def _filter_reposts(
        self, tweets: list[TweetItem], username: str,
    ) -> tuple[list[TweetItem], int]:
        if not self.filter_reposts_enabled:
            return tweets, 0

        kept: list[TweetItem] = []
        filtered = 0
        for tweet in tweets:
            if self._is_repost(tweet, username):
                filtered += 1
                continue
            kept.append(tweet)
        return kept, filtered

    @staticmethod
    def _is_repost(tweet: TweetItem, username: str) -> bool:
        return NitterClient._is_repost_link(tweet.link, username)

    @staticmethod
    def _is_repost_link(link: str, username: str) -> bool:
        watched = str(username or "").strip().lstrip("@").lower()
        author = TweetItem(text="", link=link, published="").username
        author = str(author or "").strip().lstrip("@").lower()
        return bool(watched and author and author != watched)

    def _fetch_page_with_retries(
        self,
        instance: str,
        username: str,
        cursor: str,
        limit: int,
        skip_plain_text: bool = False,
        retry_attempts: int | None = None,
        attempt_budget: FetchAttemptBudget | None = None,
    ) -> RssPageResult:
        attempts = self._retry_attempt_count(retry_attempts)
        if attempt_budget is not None:
            attempts = attempt_budget.attempts_for_page(attempts)
        delay = max(0.0, float(self.retry_delay_seconds))
        last_error: TransientFetchError | None = None

        for attempt in range(1, attempts + 1):
            if attempt_budget is not None and not attempt_budget.consume():
                break
            try:
                return self._fetch_page_from_instance(
                    instance, username, cursor, limit, skip_plain_text,
                )
            except TransientFetchError as exc:
                last_error = exc
                if attempt >= attempts:
                    break
                if not self.brief_log_enabled:
                    logger.warning(
                        "[NitterTweets] RSS 抓取失败，准备重试: "
                        f"instance={instance}, username={username}, "
                        f"attempt={attempt}/{attempts}, delay={delay:g}s, error={exc}"
                    )
                if delay > 0:
                    time.sleep(delay)

        if last_error is not None:
            raise last_error
        raise RuntimeError("RSS 抓取失败")

    def _retry_attempt_count(self, retry_attempts: int | None = None) -> int:
        value = self.retry_attempts if retry_attempts is None else retry_attempts
        try:
            return max(1, int(value))
        except (TypeError, ValueError):
            return max(1, int(self.retry_attempts))

    def _fetch_page_from_instance(
        self,
        instance: str,
        username: str,
        cursor: str,
        limit: int,
        skip_plain_text: bool = False,
    ) -> RssPageResult:
        rss_url = self._rss_url(instance, username, cursor)
        request = Request(
            rss_url,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "application/rss+xml, application/xml, text/xml;q=0.9, */*;q=0.8",
            },
        )
        try:
            with compat_urlopen(request, self.timeout) as response:
                data = response.read(self.RSS_RESPONSE_LIMIT + 1)
                next_cursor = self._header_value(response.headers, "Min-Id")
        except HTTPError as exc:
            message = f"HTTP {exc.code}"
            if self._is_retryable_http_status(exc.code):
                raise TransientFetchError(message) from exc
            raise RuntimeError(message) from exc
        except URLError as exc:
            raise TransientFetchError(str(getattr(exc, "reason", exc))) from exc
        except (TimeoutError, ssl.SSLError) as exc:
            raise TransientFetchError(str(exc)) from exc
        tweets, plain_text_filtered, scanned_status_ids, raw_item_count = self._parse_rss(
            data, instance, 0, skip_plain_text, username,
        )
        return RssPageResult(
            tweets=tweets,
            next_cursor=next_cursor,
            scanned_status_ids=scanned_status_ids,
            raw_item_count=raw_item_count,
            plain_text_filtered=plain_text_filtered,
        )

    @staticmethod
    def _is_retryable_http_status(status_code: int) -> bool:
        return status_code in {408, 429, 500, 502, 503, 504, 520, 522, 523, 524}

    @staticmethod
    def _rss_url(instance: str, username: str, cursor: str = "") -> str:
        rss_url = f"{instance.rstrip('/')}/{quote(username)}/rss"
        if cursor:
            rss_url = f"{rss_url}?{urlencode({'cursor': cursor})}"
        return rss_url

    @staticmethod
    def _rotate_instances(instances: list[str], start_index: int = 0) -> list[str]:
        normalized: list[str] = []
        for instance in instances:
            text = str(instance or "").strip().rstrip("/")
            if not text:
                continue
            if not text.startswith(("http://", "https://")):
                text = f"https://{text}"
            if text not in normalized:
                normalized.append(text)
        if not normalized:
            return []
        offset = int(start_index or 0) % len(normalized)
        return normalized[offset:] + normalized[:offset]

    @staticmethod
    def _header_value(headers, name: str) -> str:
        value = headers.get(name) if hasattr(headers, "get") else ""
        if value:
            return str(value).strip()
        for key in getattr(headers, "keys", lambda: [])():
            if str(key).lower() == name.lower():
                return str(headers[key]).strip()
        return ""

    @staticmethod
    def _tweet_identity(tweet: TweetItem) -> str:
        return tweet.status_id or tweet.link or f"{tweet.published}:{tweet.text}"

    @staticmethod
    def _latest_status_id(status_ids: list[str]) -> str:
        # RSS is newest-first; preserve that feed boundary instead of taking
        # the numeric maximum, because repost links can reference an older ID.
        return next(
            (str(status_id) for status_id in status_ids if str(status_id).isdigit()),
            "",
        )

    def _parse_rss(
        self,
        data: bytes,
        instance: str,
        limit: int,
        skip_plain_text: bool = False,
        username: str = "",
    ) -> tuple[list[TweetItem], int, list[str], int]:
        if len(data) > self.RSS_RESPONSE_LIMIT:
            raise ValueError(
                f"RSS 响应超过安全上限 {self.RSS_RESPONSE_LIMIT} 字节"
            )
        if _UNSAFE_XML_DECLARATION_RE.search(data):
            raise ValueError("RSS XML 包含禁止的 DTD 或实体声明")
        root = ET.fromstring(data)
        channel = root.find("channel") if root.tag.lower().endswith("rss") else root
        if channel is None:
            return [], 0, [], 0
        tweets: list[TweetItem] = []
        scanned_status_ids: list[str] = []
        plain_text_filtered = 0
        items = channel.findall("item")
        for item in items:
            title = self._node_text(item, "title")
            description = self._node_text(item, "description")
            link = self._normalize_link(self._node_text(item, "link"), instance)
            published = self._format_pub_date(self._node_text(item, "pubDate"))
            status_id = TweetItem(text="", link=link, published="").status_id
            if status_id:
                scanned_status_ids.append(status_id)
            # 源头过滤纯文本推文：必须在 clean_text 之前判断原始 HTML，
            # clean_text 会剥掉 HTML 只剩纯文本。链接预览卡片图
            #（/pic/card_img）不算作者媒体。转发先交给转发过滤，避免
            # 把本来就会丢弃的转发也计入纯文本过滤数。
            lacks_author_media = skip_plain_text and not _has_author_media(description)
            if (
                lacks_author_media
                and not (
                    self.filter_reposts_enabled
                    and self._is_repost_link(link, username)
                )
            ):
                plain_text_filtered += 1
                continue
            text = normalize_external_links(clean_text(description or title))
            if not text and not link:
                continue
            tweets.append(
                TweetItem(text=text or "(无正文)", link=link, published=published)
            )
            if limit > 0 and len(tweets) >= limit:
                break
        return tweets, plain_text_filtered, scanned_status_ids, len(items)

    @staticmethod
    def _node_text(node: ET.Element, name: str) -> str:
        child = node.find(name)
        return (child.text or "").strip() if child is not None else ""

    @staticmethod
    def _format_pub_date(raw: str) -> str:
        if not raw:
            return ""
        try:
            parsed = parsedate_to_datetime(raw)
        except (TypeError, ValueError):
            return raw
        return parsed.strftime("%Y-%m-%d %H:%M:%S %Z").strip()

    @staticmethod
    def _normalize_link(link: str, instance: str) -> str:
        if not link:
            return ""
        if link.startswith("/"):
            return f"{instance.rstrip('/')}{link}"
        return link
