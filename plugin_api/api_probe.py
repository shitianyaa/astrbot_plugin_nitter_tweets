"""推送目标探测与镜像连通性测试。

`NitterWebAPI` 的 mixin：只通过 `self` 协作，不 import 宿主类。
"""

from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import urlsplit

from astrbot.api import logger

try:
    from ..delivery import PlatformResolver, parse_umo
    from ..media_support.html_backend.query import (
        MAX_QUERY_LENGTH,
        normalize_query,
        query_kind,
    )
    from ..media_support.network import UnsafeUrlError, validate_http_url
    from ..scheduler import ScheduleGroup
    from ..shared import normalize_username
except ImportError:
    from delivery import PlatformResolver, parse_umo
    from media_support.html_backend.query import (
        MAX_QUERY_LENGTH,
        normalize_query,
        query_kind,
    )
    from media_support.network import UnsafeUrlError, validate_http_url
    from scheduler import ScheduleGroup
    from shared import normalize_username


def _instance_log_label(value: str) -> str:
    """只保留 host:port，剥掉 scheme/path/凭据，避免日志写入完整私有 URL。"""
    try:
        parsed = urlsplit(str(value or "").strip())
        host = parsed.hostname or ""
        if not host:
            return "<invalid>"
        port = f":{parsed.port}" if parsed.port else ""
        return f"{host}{port}"
    except ValueError:
        return "<invalid>"


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
        limit = self._parse_int(
            data.get("limit"),
            int(getattr(self.plugin, "default_limit", 5) or 5),
            minimum=1,
            maximum=50,
        )

        username = normalize_username(self._data_text(data, "username") or "nasa")
        if not username:
            return self._error("关注账号格式无效")
        raw_query = (self._data_text(data, "query") or username).strip()
        if len(raw_query) > MAX_QUERY_LENGTH:
            return self._error(f"搜索内容过长（最多 {MAX_QUERY_LENGTH} 字符）")
        query = normalize_query(raw_query)
        if not query:
            return self._error("请填写搜索内容（#标签 或短语）")
        kind = query_kind(query)
        list_id = self._data_text(data, "list_id")
        if list_id and not list_id.isdigit():
            return self._error("List ID 必须为纯数字")

        raw_instance = self._data_text(data, "instance")
        if raw_instance:
            try:
                instances = [validate_http_url(raw_instance).rstrip("/")]
            except UnsafeUrlError:
                return self._error(
                    "请填写完整自建 Nitter 地址，例如 http://nitter:8080"
                )
        else:
            instances = self._configured_instances()
            if not instances:
                return self._error("未配置自建 Nitter 实例")

        results: list[dict[str, Any]] = []
        for configured_instance in instances:
            try:
                instance = validate_http_url(configured_instance).rstrip("/")
                result = await self._probe_instance_capabilities(
                    instance,
                    username=username,
                    query=query,
                    kind=kind,
                    list_id=list_id,
                    limit=limit,
                )
                results.append(result)
            except Exception as exc:
                logger.warning(
                    "[NitterTweets] WebUI 实例测试失败: "
                    f"instance={_instance_log_label(configured_instance)}, error={exc}"
                )
                results.append(
                    {
                        "instance": configured_instance,
                        "success": False,
                        "checks": {},
                        "error": str(exc),
                    }
                )

        succeeded = sum(1 for item in results if item["success"])
        return self._ok(
            username=username,
            query=query,
            kind=kind,
            list_id=list_id,
            limit=limit,
            results=results,
            summary={
                "total": len(results),
                "succeeded": succeeded,
                "failed": len(results) - succeeded,
            },
        )

    async def _probe_instance_capabilities(
        self,
        instance: str,
        *,
        username: str,
        query: str,
        kind: str,
        list_id: str,
        limit: int,
    ) -> dict[str, Any]:
        checks: dict[str, dict[str, Any]] = {}

        async def run_check(name: str, call) -> None:
            started = asyncio.get_running_loop().time()
            try:
                used_instance, tweets = await call()
                tweets = list(tweets or [])
                checks[name] = {
                    "success": True,
                    "instance": used_instance or instance,
                    "tweet_count": len(tweets),
                    "duration_ms": round(
                        (asyncio.get_running_loop().time() - started) * 1000, 1
                    ),
                    "error": "",
                    "tweets": [
                        self._serialize_probe_tweet(tweet) for tweet in tweets[:limit]
                    ],
                }
            except Exception as exc:
                checks[name] = {
                    "success": False,
                    "instance": instance,
                    "tweet_count": 0,
                    "duration_ms": round(
                        (asyncio.get_running_loop().time() - started) * 1000, 1
                    ),
                    "error": str(exc),
                    "tweets": [],
                }

        async def rss_call():
            return await self.plugin.nitter.fetch_tweets_from_instance(
                instance, username, limit
            )

        async def user_html_call():
            return await asyncio.to_thread(
                self.plugin.nitter.fetch_user_html,
                username,
                limit,
                instance=instance,
            )

        async def search_call():
            return await asyncio.to_thread(
                self.plugin.nitter.search,
                query,
                limit,
                kind=kind,
                instance=instance,
            )

        await run_check("rss_user", rss_call)
        await run_check("html_user", user_html_call)
        await run_check("search", search_call)
        if list_id:

            async def list_call():
                return await asyncio.to_thread(
                    self.plugin.nitter.fetch_list,
                    list_id,
                    limit,
                    instance=instance,
                )

            await run_check("list", list_call)

        required = [item for item in checks.values() if not item.get("skipped")]
        return {
            "instance": instance,
            "success": bool(required) and all(item["success"] for item in required),
            "checks": checks,
            "error": "",
        }

    def _configured_instances(self) -> list[str]:
        values = list(
            getattr(getattr(self.plugin, "nitter", None), "instances", []) or []
        )
        return self._dedupe_instances(values)

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
