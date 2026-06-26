from __future__ import annotations

import asyncio
import re
import ssl
import time
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request
from xml.etree import ElementTree as ET

from astrbot.api import logger

try:
    from ..config_compat import config_get
    from ..utils import (
        TweetItem, clean_text, clamp_float, load_instances, normalize_external_links,
    )
except ImportError:
    from config_compat import config_get
    from utils import (
        TweetItem, clean_text, clamp_float, load_instances, normalize_external_links,
    )

from .network import compat_urlopen


class TransientFetchError(RuntimeError):
    pass


# 作者上传的媒体标记：Nitter RSS 的 <description> 是 HTML，作者上传的图片走
# /pic/media（链接预览卡片图走 /pic/card_img，不算作者媒体）；视频/GIF 包成
# <video> 标签。只认这两类，用于源头过滤纯文本推文。
_AUTHOR_MEDIA_RE = re.compile(
    r'(?i)<img[^>]+src=["\'][^"\']*?/pic/media[^"\']*["\']|<video\b'
)


@dataclass(slots=True)
class InstanceFetchResult:
    tweets: list[TweetItem]
    saw_items: bool = False
    plain_text_filtered: int = 0


class NitterClient:
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
        errors: list[str] = []
        for index, instance in enumerate(self.instances):
            try:
                result = await asyncio.to_thread(
                    self._fetch_from_instance,
                    instance, username, limit, skip_plain_text,
                )
            except Exception as exc:
                errors.append(f"{instance}: {exc}")
                self._log_instance_fetch_failure(index, instance, username, exc)
                continue
            if result.tweets or result.saw_items:
                self._log_instance_fetch_success(index, instance, username, result)
                return instance, result.tweets, result.plain_text_filtered
            errors.append(f"{instance}: empty feed")
            self._log_instance_fetch_failure(index, instance, username, "empty feed")
        raise RuntimeError(self._format_fetch_errors(errors))

    def _log_instance_fetch_failure(
        self, index: int, instance: str, username: str, error,
    ) -> None:
        total = len(self.instances)
        if total <= 1:
            return

        if index + 1 < total:
            logger.warning(
                "[NitterTweets] RSS 实例失败，尝试下一个实例: "
                f"instance={instance}, next_instance={self.instances[index + 1]}, "
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

    def _format_fetch_errors(self, errors: list[str]) -> str:
        if not errors:
            return "未配置 Nitter 实例"

        shown_errors = errors[-3:]
        hidden_count = len(errors) - len(shown_errors)
        total_count = len(self.instances)
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
    ) -> InstanceFetchResult:
        if limit <= 0:
            return InstanceFetchResult([])

        tweets: list[TweetItem] = []
        seen: set[str] = set()
        seen_cursors: set[str] = set()
        cursor = ""
        saw_items = False
        plain_text_filtered_total = 0

        while len(tweets) < limit:
            try:
                page_tweets, next_cursor, plain_text_filtered = (
                    self._fetch_page_with_retries(
                        instance, username, cursor, limit, skip_plain_text,
                    )
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
            if not page_tweets and plain_text_filtered == 0:
                break

            saw_items = True
            plain_text_filtered_total += plain_text_filtered
            page_tweets, page_filtered_reposts = self._filter_reposts(
                page_tweets, username
            )
            # 本页 RSS 有 item 但全被过滤（纯文本或转发），过滤后 page_tweets 为空
            page_all_filtered = (
                (plain_text_filtered > 0 or page_filtered_reposts > 0)
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
            if not next_cursor or next_cursor in seen_cursors:
                break
            seen_cursors.add(next_cursor)
            cursor = next_cursor
            if added == 0 and not page_all_filtered:
                break

        return InstanceFetchResult(
            tweets=tweets,
            saw_items=saw_items,
            plain_text_filtered=plain_text_filtered_total,
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
        watched = str(username or "").strip().lstrip("@").lower()
        author = str(tweet.username or "").strip().lstrip("@").lower()
        return bool(watched and author and author != watched)

    def _fetch_page_with_retries(
        self,
        instance: str,
        username: str,
        cursor: str,
        limit: int,
        skip_plain_text: bool = False,
    ) -> tuple[list[TweetItem], str, int]:
        attempts = max(1, int(self.retry_attempts))
        delay = max(0.0, float(self.retry_delay_seconds))
        last_error: TransientFetchError | None = None

        for attempt in range(1, attempts + 1):
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

    def _fetch_page_from_instance(
        self,
        instance: str,
        username: str,
        cursor: str,
        limit: int,
        skip_plain_text: bool = False,
    ) -> tuple[list[TweetItem], str, int]:
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
                data = response.read(2_000_000)
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
        tweets, plain_text_filtered = self._parse_rss(
            data, instance, 0, skip_plain_text,
        )
        return tweets, next_cursor, plain_text_filtered

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

    def _parse_rss(
        self,
        data: bytes,
        instance: str,
        limit: int,
        skip_plain_text: bool = False,
    ) -> tuple[list[TweetItem], int]:
        root = ET.fromstring(data)
        channel = root.find("channel") if root.tag.lower().endswith("rss") else root
        if channel is None:
            return [], 0
        tweets: list[TweetItem] = []
        plain_text_filtered = 0
        for item in channel.findall("item"):
            title = self._node_text(item, "title")
            description = self._node_text(item, "description")
            # 源头过滤纯文本推文：必须在 clean_text 之前判断原始 HTML，
            # clean_text 会剥掉 HTML 只剩纯文本。链接预览卡片图
            #（/pic/card_img）不算作者媒体，只有 /pic/media 和 <video> 算。
            if skip_plain_text and not _AUTHOR_MEDIA_RE.search(description or ""):
                plain_text_filtered += 1
                continue
            text = normalize_external_links(clean_text(description or title))
            link = self._normalize_link(self._node_text(item, "link"), instance)
            published = self._format_pub_date(self._node_text(item, "pubDate"))
            if not text and not link:
                continue
            tweets.append(
                TweetItem(text=text or "(无正文)", link=link, published=published)
            )
            if limit > 0 and len(tweets) >= limit:
                break
        return tweets, plain_text_filtered

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
