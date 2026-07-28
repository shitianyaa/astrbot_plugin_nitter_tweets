"""Passive X/Twitter status link preview handler."""

from __future__ import annotations

import asyncio
import time

from astrbot.api.all import logger
from astrbot.api.event import AstrMessageEvent

try:
    from ..config import (
        config_get,
        parse_config_bool,
        resolve_hide_original_when_translated,
    )
    from ..media_support.status_link import extract_status_links
    from ..media_support.status_resolve import (
        StatusResolveError,
        resolve_status_tweet_async,
    )
except ImportError:
    from config import (
        config_get,
        parse_config_bool,
        resolve_hide_original_when_translated,
    )
    from media_support.status_link import extract_status_links
    from media_support.status_resolve import (
        StatusResolveError,
        resolve_status_tweet_async,
    )

LINK_PREVIEW_MAX_LINKS = 3
LINK_PREVIEW_DEBOUNCE_SECONDS = 60.0
LINK_PREVIEW_SOURCE = "status-link"


class LinkPreviewMixin:
    """Mixin: auto-parse public status URLs in chat messages."""

    def _link_preview_enabled(self) -> bool:
        return parse_config_bool(
            config_get(self.config, "auto_parse_tweet_links_enabled", False),
            False,
        )

    def _link_preview_debounce_store(self) -> dict[str, float]:
        store = getattr(self, "_link_preview_debounce", None)
        if store is None:
            store = {}
            self._link_preview_debounce = store
        return store

    def _link_preview_debounce_hit(self, umo: str, status_id: str) -> bool:
        key = f"{umo}|{status_id}"
        now = time.monotonic()
        store = self._link_preview_debounce_store()
        expire_before = now - LINK_PREVIEW_DEBOUNCE_SECONDS
        for old_key, ts in list(store.items()):
            if ts < expire_before:
                store.pop(old_key, None)
        return key in store and store[key] >= expire_before

    def _record_link_preview_debounce(self, umo: str, status_id: str) -> None:
        self._link_preview_debounce_store()[f"{umo}|{status_id}"] = time.monotonic()

    def _is_bot_self_message(self, event: AstrMessageEvent) -> bool:
        try:
            sender = str(event.get_sender_id() or "").strip()
            self_id = str(event.get_self_id() or "").strip()
        except Exception:
            return False
        return bool(sender and self_id and sender == self_id)

    async def _cmd_link_preview_impl(self, event: AstrMessageEvent):
        """Handle passive status-link preview for one message."""
        if not self._link_preview_enabled():
            return
        if self._is_bot_self_message(event):
            return

        text = ""
        try:
            text = str(event.get_message_str() or event.message_str or "")
        except Exception:
            text = str(getattr(event, "message_str", "") or "")

        links = extract_status_links(text)
        if not links:
            return

        event.stop_event()
        links = links[:LINK_PREVIEW_MAX_LINKS]
        umo = str(getattr(event, "unified_msg_origin", "") or "")
        hide_original = resolve_hide_original_when_translated(self.config)

        for link in links:
            if self._link_preview_debounce_hit(umo, link.status_id):
                logger.debug(
                    "[NitterTweets] link preview debounced: status_id=%s umo=%s",
                    link.status_id,
                    umo,
                )
                continue

            tweet = None
            try:
                tweet = await resolve_status_tweet_async(link)
            except StatusResolveError as exc:
                logger.warning(
                    "[NitterTweets] link preview resolve failed: status_id=%s error=%s",
                    link.status_id,
                    exc,
                )
                try:
                    await event.send(
                        event.plain_result(f"推文链接解析失败：{link.canonical_url}")
                    )
                except Exception as send_exc:
                    logger.debug(
                        "[NitterTweets] link preview failure notice send failed: %s",
                        send_exc,
                    )
                continue
            except Exception as exc:
                logger.warning(
                    "[NitterTweets] link preview resolve error: status_id=%s error=%s",
                    link.status_id,
                    exc,
                    exc_info=True,
                )
                try:
                    await event.send(
                        event.plain_result(f"推文链接解析失败：{link.canonical_url}")
                    )
                except Exception as send_exc:
                    logger.debug(
                        "[NitterTweets] link preview failure notice send failed: %s",
                        send_exc,
                    )
                continue

            try:
                try:
                    await self.translator.attach_translations([tweet], umo)
                except Exception as exc:
                    logger.warning(
                        "[NitterTweets] link preview translate failed: status_id=%s error=%s",
                        link.status_id,
                        exc,
                    )

                try:
                    await self.media.attach_media_with_results(
                        [tweet], force_all_media=True
                    )
                except Exception as exc:
                    logger.warning(
                        "[NitterTweets] link preview media failed: status_id=%s error=%s",
                        link.status_id,
                        exc,
                    )

                username = tweet.username or link.username or "unknown"
                sent = await self.sender.send(
                    event,
                    username,
                    LINK_PREVIEW_SOURCE,
                    [tweet],
                    omit_status_url=True,
                    hide_original_when_translated=hide_original,
                    force_media=True,
                )
                if sent:
                    self._record_link_preview_debounce(umo, link.status_id)
                else:
                    logger.warning(
                        "[NitterTweets] link preview send failed; debounce not recorded: "
                        "status_id=%s umo=%s",
                        link.status_id,
                        umo,
                    )
            finally:
                try:
                    await asyncio.to_thread(self.media.cleanup_after_send, [tweet])
                except Exception as cleanup_exc:
                    logger.debug(
                        "[NitterTweets] link preview async cleanup failed: %s",
                        cleanup_exc,
                    )
                    try:
                        self.media.cleanup_after_send([tweet])
                    except Exception as cleanup_exc2:
                        logger.debug(
                            "[NitterTweets] link preview sync cleanup failed: %s",
                            cleanup_exc2,
                        )
