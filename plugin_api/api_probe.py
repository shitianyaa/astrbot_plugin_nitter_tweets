"""推送目标探测与镜像连通性测试。

`NitterWebAPI` 的 mixin：只通过 `self` 协作，不 import 宿主类。
"""

from __future__ import annotations

import asyncio
from typing import Any

from astrbot.api import logger

try:
    from ..config import config_get
    from ..scheduler import ScheduleGroup
    from ..delivery import PlatformResolver, parse_umo
    from ..shared import normalize_username
    from ..media_support.html_backend.query import (
        MAX_QUERY_LENGTH,
        normalize_query,
        query_kind,
    )
    from ..media_support.network import UnsafeUrlError, validate_http_url
except ImportError:
    from config import config_get
    from scheduler import ScheduleGroup
    from delivery import PlatformResolver, parse_umo
    from shared import normalize_username
    from media_support.html_backend.query import (
        MAX_QUERY_LENGTH,
        normalize_query,
        query_kind,
    )
    from media_support.network import UnsafeUrlError, validate_http_url


class WebAPIProbeMixin:
    """targets / mirror 探测。"""

    async def probe_targets(self, data: dict[str, Any]) -> dict[str, Any]:
        group_id = self._data_text(data, "group_id")
        group: ScheduleGroup | None = None
        if group_id:
            group, error = self._resolve_group(group_id)
            if error:
                return self._error(error)

        targets = self._data_text_list(data, "target_umos")
        if not targets and group is not None:
            targets = [*group.targets, *group.invalid_targets]
        if not targets:
            return self._error("请填写要检测的推送目标")

        results = [self._probe_target(target) for target in targets]
        valid_count = sum(1 for item in results if item["valid"])
        invalid_count = len(results) - valid_count
        found_count = sum(1 for item in results if item.get("platform_found"))
        merge_count = sum(1 for item in results if item.get("supports_merged_forward"))
        return self._ok(
            group_id=group.group_id if group is not None else group_id,
            group_name=group.name if group is not None else "",
            targets=results,
            summary={
                "total": len(results),
                "valid": valid_count,
                "invalid": invalid_count,
                "platform_found": found_count,
                "supports_merged_forward": merge_count,
            },
        )

    def _probe_target(self, target_umo: str) -> dict[str, Any]:
        target_umo = str(target_umo or "").strip()
        platform_id, message_type, session_id = parse_umo(target_umo)
        if not platform_id or not message_type or not session_id:
            return {
                "umo": target_umo,
                "valid": False,
                "error": "推送目标必须是 /sid 返回的完整 UMO：platform:MessageType:session_id",
                "platform_id": platform_id,
                "message_type": message_type,
                "session_id": session_id,
                "platform_kind": "unknown",
                "platform_found": False,
                "supports_merged_forward": False,
            }

        context = getattr(self.scheduler, "context", None) or getattr(
            self.plugin, "context", None
        )
        profile = PlatformResolver().from_umo(context, target_umo)
        supports_merged_forward = False
        sender = getattr(self.plugin, "sender", None) or getattr(
            self.scheduler, "sender", None
        )
        supports = getattr(sender, "supports_merged_forward_for_umo", None)
        if callable(supports):
            try:
                supports_merged_forward = bool(supports(context, target_umo))
            except Exception:
                supports_merged_forward = False

        return {
            "umo": target_umo,
            "valid": True,
            "error": "",
            "platform_id": platform_id,
            "message_type": message_type,
            "session_id": session_id,
            "platform_kind": self._platform_kind(profile),
            "platform_types": list(profile.platform_types),
            "platform_found": profile.platform is not None,
            "supports_merged_forward": supports_merged_forward,
        }

    @staticmethod
    def _platform_kind(profile: Any) -> str:
        if getattr(profile, "is_lark", False):
            return "lark"
        if getattr(profile, "is_telegram", False):
            return "telegram"
        if getattr(profile, "is_onebot", False):
            return "onebot"
        if getattr(profile, "is_known_non_onebot", False):
            return "non_onebot"
        return "default"

    async def probe_mirror(self, data: dict[str, Any]) -> dict[str, Any]:
        instance = self._data_text(data, "instance")
        try:
            # Keep the UI probe deterministic even when DNS is temporarily
            # unavailable; the actual opener repeats strict DNS and redirect
            # validation immediately before connecting.
            instance = validate_http_url(instance, resolve_dns=False).rstrip("/")
        except UnsafeUrlError:
            return self._error("请填写完整 Nitter 镜像站地址，例如 https://nitter.net")

        mode = self._data_text(data, "mode") or "blogger_rss"
        mode = mode.strip().lower().replace("-", "_")
        if mode not in {"blogger_rss", "search"}:
            if mode == "blogger_html":
                return self._error("博主 HTML 回退已移除；请用 blogger_rss 或 search")
            return self._error("mode 仅支持 blogger_rss / search")

        limit = self._parse_int(
            data.get("limit"),
            int(getattr(self.plugin, "default_limit", 5) or 5),
            minimum=1,
            maximum=50,
        )

        try:
            if mode == "blogger_rss":
                username = normalize_username(
                    self._data_text(data, "username")
                    or self._data_text(data, "query")
                    or "nasa"
                )
                if not username:
                    return self._error("关注账号格式无效")
                (
                    used_instance,
                    tweets,
                ) = await self.plugin.nitter.fetch_tweets_from_instance(
                    instance,
                    username,
                    limit,
                )
                subject = username
                kind = ""
            else:
                raw_query = (
                    self._data_text(data, "query")
                    or self._data_text(data, "username")
                    or ""
                ).strip()
                if len(raw_query) > MAX_QUERY_LENGTH:
                    return self._error(f"搜索内容过长（最多 {MAX_QUERY_LENGTH} 字符）")
                query = normalize_query(raw_query)
                if not query:
                    return self._error("请填写搜索内容（#标签 或短语）")
                html_backend = getattr(self.plugin, "html_backend", None)
                if html_backend is None:
                    return self._error("HTML 后端未初始化")
                if not bool(
                    getattr(
                        getattr(html_backend, "config", None), "search_enabled", True
                    )
                ):
                    return self._error("search_enabled 已关闭")
                kind = query_kind(query)
                used_instance, tweets = await asyncio.to_thread(
                    html_backend.search,
                    query,
                    limit,
                    kind=kind,
                    instance=instance,
                )
                subject = query
                username = query
        except Exception as exc:
            logger.warning(
                "[NitterTweets] WebUI 镜像测试失败: "
                f"mode={mode}, instance={instance}, error={exc}"
            )
            if mode == "search":
                return self._error(
                    f"通过 {instance} 搜索失败：实例不可达、被限流，或搜索门禁未通过。"
                )
            return self._error(
                f"通过 {instance} 获取失败：Nitter 暂时不可用，或用户没有公开 RSS。"
            )

        return self._ok(
            mode=mode,
            instance=used_instance,
            username=username if mode != "search" else "",
            query=subject if mode == "search" else "",
            kind=kind,
            subject=subject,
            limit=limit,
            tweet_count=len(tweets),
            tweets=[self._serialize_probe_tweet(tweet) for tweet in tweets[:limit]],
        )

    def _configured_instance_lists(self) -> dict[str, list[str]]:
        """Three config lists for mirror probe UI (deduped, order preserved)."""
        rss = list(getattr(getattr(self.plugin, "nitter", None), "instances", []) or [])
        html_backend = getattr(self.plugin, "html_backend", None)
        search: list[str] = []
        if html_backend is not None:
            cfg = getattr(html_backend, "config", None)
            if cfg is not None:
                search = list(getattr(cfg, "search_instances", []) or [])
        # Do not use load_instances() here: empty config must stay empty
        # (load_instances falls back to DEFAULT_INSTANCES / nitter.net).
        if not search:
            search = list(config_get(self.config, "search_instances", []) or [])
        return {
            "rss": self._dedupe_instances(rss),
            # Kept for dashboard API shape; blogger HTML pool is always empty.
            "blogger_html": [],
            "search": self._dedupe_instances(search),
        }

    @staticmethod
    def _dedupe_instances(values: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for raw in values:
            item = str(raw or "").strip().rstrip("/")
            if not item:
                continue
            if not item.startswith(("http://", "https://")):
                item = f"https://{item}"
            key = item.rstrip("/").lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(item.rstrip("/"))
        return out
