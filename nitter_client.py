from __future__ import annotations

import asyncio
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

try:
    from .models import TweetItem
    from .utils import clean_text, clamp_float, load_instances
except ImportError:
    from models import TweetItem
    from utils import clean_text, clamp_float, load_instances


class NitterClient:
    def __init__(self, config):
        self.instances = load_instances(config.get("instances"))
        self.timeout = clamp_float(config.get("request_timeout", 12.0), 3.0, 60.0)
        self.user_agent = config.get(
            "user_agent",
            "Mozilla/5.0 (compatible; AstrBotNitterTweets/0.3)",
        )

    async def fetch_tweets(
        self, username: str, limit: int
    ) -> tuple[str, list[TweetItem]]:
        errors: list[str] = []
        for instance in self.instances:
            try:
                tweets = await asyncio.to_thread(
                    self._fetch_from_instance, instance, username, limit
                )
            except Exception as exc:
                errors.append(f"{instance}: {exc}")
                continue

            if tweets:
                return instance, tweets
            errors.append(f"{instance}: empty feed")

        raise RuntimeError("; ".join(errors[-3:]) or "no instance available")

    def _fetch_from_instance(
        self, instance: str, username: str, limit: int
    ) -> list[TweetItem]:
        rss_url = f"{instance.rstrip('/')}/{quote(username)}/rss"
        request = Request(
            rss_url,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "application/rss+xml, application/xml, text/xml;q=0.9, */*;q=0.8",
            },
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                data = response.read(2_000_000)
        except HTTPError as exc:
            raise RuntimeError(f"HTTP {exc.code}") from exc
        except URLError as exc:
            reason = getattr(exc, "reason", exc)
            raise RuntimeError(str(reason)) from exc

        return self._parse_rss(data, instance, limit)

    def _parse_rss(self, data: bytes, instance: str, limit: int) -> list[TweetItem]:
        root = ET.fromstring(data)
        channel = root.find("channel") if root.tag.lower().endswith("rss") else root
        if channel is None:
            return []

        tweets: list[TweetItem] = []
        for item in channel.findall("item"):
            title = self._node_text(item, "title")
            description = self._node_text(item, "description")
            text = clean_text(description or title)
            link = self._normalize_link(self._node_text(item, "link"), instance)
            published = self._format_pub_date(self._node_text(item, "pubDate"))
            if not text and not link:
                continue
            tweets.append(TweetItem(text=text or "(无正文)", link=link, published=published))
            if len(tweets) >= limit:
                break
        return tweets

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
