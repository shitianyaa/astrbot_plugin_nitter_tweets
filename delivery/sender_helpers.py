"""发送层无状态 helper：计数、分块、拆分降级、status id 归一。

`TweetSender` 的 mixin：只通过 `self` / `cls` 协作，不 import 宿主类。
分块与拆分阈值常量（`FORWARD_TWEET_CHUNK_SIZE` / `FORWARD_SPLIT_MIN_TWEETS`）
仍定义在 `TweetSender` 上，这里按 MRO 取用。

`_is_forward_payload_rejected_error` 刻意留在 `delivery/sender.py`：
它依赖模块级 `ActionFailed`，而测试用 `monkeypatch.setattr(sender_mod, "ActionFailed", ...)`
打桩，搬到本模块会让该 patch 静默失效。
"""

from __future__ import annotations

from astrbot.api import logger

try:
    from ..shared import TweetItem, safe_call
    from ..rendering import TweetBatch
except ImportError:
    from shared import TweetItem, safe_call
    from rendering import TweetBatch


class SenderHelpersMixin:
    """与平台无关的纯计算 helper。"""

    @classmethod
    def event_target(cls, event) -> str:
        return cls._event_target(event)

    @classmethod
    def _event_target(cls, event) -> str:
        try:
            umo = getattr(event, "unified_msg_origin", "")
        except Exception:
            umo = ""
        if umo:
            return str(umo)

        group_id = safe_call(event, "get_group_id")
        if group_id:
            return f"group:{group_id}"

        sender_id = safe_call(event, "get_sender_id")
        if sender_id:
            return f"private:{sender_id}"

        platform = cls._event_platform(event)
        return platform or "unknown"

    @staticmethod
    def _count_attached_videos(batches: list[TweetBatch]) -> int:
        return sum(
            1
            for _, _, tweets in batches
            for tweet in tweets
            for media in tweet.media
            if media.path and media.is_video
        )

    @staticmethod
    def _count_batch_tweets(batches: list[TweetBatch]) -> int:
        return sum(len(tweets) for _, _, tweets in batches)

    @staticmethod
    def _has_attached_videos(tweets: list[TweetItem]) -> bool:
        return any(
            media.is_video for tweet in tweets for media in tweet.media if media.path
        )

    @staticmethod
    def _has_attached_images(tweets: list[TweetItem]) -> bool:
        return any(
            media.is_image for tweet in tweets for media in tweet.media if media.path
        )

    def _merged_forward_has_video(self, batches: list[TweetBatch]) -> bool:
        return bool(
            self.send_video_attachments
            and any(
                media.path and media.is_video
                for _, _, tweets in batches
                for tweet in tweets
                for media in tweet.media
            )
        )

    def _should_use_merge_for_count(self, tweet_count: int) -> bool:
        return (
            self.merge_tweet_threshold > 0
            and tweet_count >= self.merge_tweet_threshold
        )

    def _should_chunk_forward_tweets(self, tweet_count: int) -> bool:
        return tweet_count > self.FORWARD_TWEET_CHUNK_SIZE

    def _split_tweets_for_forward_retry(
        self, tweets: list[TweetItem]
    ) -> list[list[TweetItem]] | None:
        if len(tweets) <= self.FORWARD_SPLIT_MIN_TWEETS:
            return None
        mid = max(1, len(tweets) // 2)
        left = tweets[:mid]
        right = tweets[mid:]
        if not left or not right:
            return None
        return [left, right]

    @staticmethod
    def _notify_sent_progress(callback, count: int) -> None:
        if not callable(callback):
            return
        try:
            callback(count)
        except Exception as exc:
            logger.warning(f"[NitterTweets] 手动发送进度回调失败: {exc}")

    @staticmethod
    def _notify_delivered(callback, count: int) -> None:
        if not callable(callback) or count <= 0:
            return
        try:
            callback(count)
        except Exception as exc:
            logger.warning(f"[NitterTweets] 手动发送分段进度回调失败: {exc}")

    @staticmethod
    async def _send_chunked_bool(chunks, send_chunk) -> bool:
        for chunk in chunks:
            if not await send_chunk(chunk):
                return False
        return True

    def _tweet_chunks(self, tweets: list[TweetItem]) -> list[list[TweetItem]]:
        size = self.FORWARD_TWEET_CHUNK_SIZE
        return [tweets[index : index + size] for index in range(0, len(tweets), size)]

    @staticmethod
    def _status_ids_from_tweets(tweets: list[TweetItem]) -> tuple[str, ...]:
        return tuple(
            str(getattr(tweet, "status_id", "") or "")
            for tweet in tweets
            if str(getattr(tweet, "status_id", "") or "")
        )

    @classmethod
    def _status_ids_from_batches(
        cls, batches: list[TweetBatch]
    ) -> tuple[str, ...]:
        ids: list[str] = []
        for _username, _instance, tweets in batches:
            ids.extend(cls._status_ids_from_tweets(tweets))
        return tuple(ids)

    @staticmethod
    def _dedupe_status_ids(values) -> tuple[str, ...]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values or ():
            text = str(value or "")
            if text and text not in seen:
                seen.add(text)
                result.append(text)
        return tuple(result)

    @staticmethod
    def _normalized_delivery_status(outcome) -> str:
        return str(
            getattr(outcome, "delivery_status", "success") or "success"
        ).strip().lower()

    def _batch_chunks(self, batches: list[TweetBatch]) -> list[list[TweetBatch]]:
        chunks: list[list[TweetBatch]] = []
        current: list[TweetBatch] = []
        current_count = 0
        size = self.FORWARD_TWEET_CHUNK_SIZE

        for username, instance, tweets in batches:
            for tweet_chunk in self._tweet_chunks(tweets):
                if current and current_count + len(tweet_chunk) > size:
                    chunks.append(current)
                    current = []
                    current_count = 0
                current.append((username, instance, tweet_chunk))
                current_count += len(tweet_chunk)

        if current:
            chunks.append(current)
        return chunks

    def _split_batches_for_forward_retry(
        self, batches: list[TweetBatch]
    ) -> list[list[TweetBatch]] | None:
        total = self._count_batch_tweets(batches)
        if total <= self.FORWARD_SPLIT_MIN_TWEETS:
            return None
        mid = max(1, total // 2)
        left: list[TweetBatch] = []
        right: list[TweetBatch] = []
        consumed = 0
        for username, instance, tweets in batches:
            split_at = max(0, min(len(tweets), mid - consumed))
            if split_at:
                left.append((username, instance, list(tweets[:split_at])))
            if split_at < len(tweets):
                right.append((username, instance, list(tweets[split_at:])))
            consumed += split_at
        if not left or not right:
            return None
        return [left, right]

    @staticmethod
    def _batches_without_status_ids(
        batches: list[TweetBatch], delivered_status_ids
    ) -> tuple[list[TweetBatch], int]:
        delivered = {str(value or "") for value in delivered_status_ids if value}
        result: list[TweetBatch] = []
        first_remaining_offset: int | None = None
        offset = 0
        for username, instance, tweets in batches:
            remaining = []
            for tweet in tweets:
                status_id = str(getattr(tweet, "status_id", "") or "")
                if status_id and status_id in delivered:
                    offset += 1
                    continue
                if first_remaining_offset is None:
                    first_remaining_offset = offset
                remaining.append(tweet)
                offset += 1
            if remaining:
                result.append((username, instance, remaining))
        return result, first_remaining_offset or 0
