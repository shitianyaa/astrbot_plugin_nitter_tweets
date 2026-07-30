"""API 响应体的序列化与入参解析。

`NitterWebAPI` 的 mixin：只通过 `self` 协作，不 import 宿主类。
"""

from __future__ import annotations

from typing import Any

try:
    from ..scheduler import ScheduleGroup
    from ..shared import TweetItem, format_subscription_count
except ImportError:
    from scheduler import ScheduleGroup
    from shared import TweetItem, format_subscription_count


class WebAPISerializersMixin:
    """结果序列化与 data 取值。"""

    @staticmethod
    def _serialize_check_result(result: Any) -> dict[str, Any]:
        return {
            "group_id": getattr(result, "group_id", ""),
            "group_name": getattr(result, "group_name", ""),
            "group_type": getattr(result, "group_type", "blogger") or "blogger",
            "reason": getattr(result, "reason", ""),
            "source_count": len(getattr(result, "users", []) or []),
            "target_count": len(getattr(result, "targets", []) or []),
            "skipped_reason": getattr(result, "skipped_reason", ""),
            "new_tweet_count": getattr(result, "new_tweet_count", 0),
            "failed_count": len(getattr(result, "failed_users", {}) or {}),
            "pushed_target_successes": getattr(result, "pushed_target_successes", 0),
            "pushed_target_attempts": getattr(result, "pushed_target_attempts", 0),
        }

    @staticmethod
    def _serialize_cache_result(result: Any) -> dict[str, int]:
        return {
            "removed": int(getattr(result, "removed", 0) or 0),
            "failed": int(getattr(result, "failed", 0) or 0),
            "skipped_dirs": int(getattr(result, "skipped_dirs", 0) or 0),
            "removed_images": int(
                getattr(result, "removed_images", getattr(result, "images", 0)) or 0
            ),
            "removed_videos": int(
                getattr(result, "removed_videos", getattr(result, "videos", 0)) or 0
            ),
            "removed_other": int(
                getattr(result, "removed_other", getattr(result, "other", 0)) or 0
            ),
            "skipped_active": int(getattr(result, "skipped_active", 0) or 0),
            "removed_empty_dirs": int(getattr(result, "removed_empty_dirs", 0) or 0),
        }

    @staticmethod
    def _serialize_probe_tweet(tweet: TweetItem) -> dict[str, Any]:
        return {
            "status_id": tweet.status_id,
            "username": tweet.username,
            "link": tweet.x_url,
            "published": tweet.published,
            "text_preview": WebAPISerializersMixin._text_preview(tweet.text),
            "media_count": len(tweet.media),
        }

    @staticmethod
    def _format_times(times: list[tuple[int, int]]) -> list[str]:
        return [f"{hour:02d}:{minute:02d}" for hour, minute in times]

    @staticmethod
    def _text_preview(text: str, limit: int = 160) -> str:
        text = " ".join(str(text or "").split())
        return text if len(text) <= limit else text[: limit - 1] + "…"

    @staticmethod
    def _terminology() -> dict[str, str]:
        return {
            "watch_users": "博主订阅",
            "watch_queries": "搜索订阅",
            "watch_lists": "List",
            "subscription_source": "订阅源",
            "subscription_count": "订阅数量",
            "push_targets": "推送目标",
            "seen": "推送记录",
        }

    @staticmethod
    def _group_label(group: ScheduleGroup | None) -> str:
        if group is None:
            return "全部分组"
        return f"{group.name} ({group.group_id})"

    @staticmethod
    def _group_payload_label(group: ScheduleGroup) -> dict[str, str]:
        return {
            "group_id": group.group_id,
            "name": group.name,
            "subscription_label": format_subscription_count(
                len(group.account_keys), group.group_type
            ),
        }

    @staticmethod
    def _data_text(data: dict[str, Any], key: str) -> str:
        return str(data.get(key, "") or "").strip()

    @staticmethod
    def _data_text_list(data: dict[str, Any], key: str) -> list[str]:
        value = data.get(key, [])
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return []

    @staticmethod
    def _parse_int(
        value: Any,
        fallback: int,
        *,
        minimum: int,
        maximum: int,
    ) -> int:
        try:
            number = int(value)
        except (TypeError, ValueError):
            number = fallback
        return max(minimum, min(maximum, number))
