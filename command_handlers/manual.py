from __future__ import annotations

import asyncio
import re
import time

from astrbot.api.all import At, MessageChain, Plain, logger
from astrbot.api.event import AstrMessageEvent
from astrbot.core.star.filter.command import GreedyStr

try:
    from ..ai import format_ai_tweet_summary
    from ..shared import normalize_username, safe_call
except ImportError:
    from ai import format_ai_tweet_summary
    from shared import normalize_username, safe_call


class ManualCommandMixin:
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
                event.plain_result(
                    "用法：/推文 用户名 [数量]\n例如：/推文 nasa 5"
                )
            )
            return

        cooldown_left = self._cooldown_left(event)
        if cooldown_left > 0:
            await event.send(event.plain_result(f"请求太快啦，{cooldown_left:.0f} 秒后再试。"))
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

        try:
            instance, tweets = await self.nitter.fetch_tweets(username, limit)
        except Exception as exc:
            logger.warning(f"[NitterTweets] 手动获取 @{username} 推文失败: {exc}")
            await event.send(
                event.plain_result(
                    f"获取 @{username} 推文失败：Nitter 实例暂时不可用或该用户无公开 RSS。"
                )
            )
            return

        if not tweets:
            await event.send(event.plain_result(f"没有找到 @{username} 的公开推文。"))
            return

        await self._send_tweets_response(event, username, instance, tweets)

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
            await event.send(event.plain_result(f"请求太快啦，{cooldown_left:.0f} 秒后再试。"))
            return

        self._mark_cooldown(event)
        await event.send(
            event.plain_result(
                f"正在测试 {instance_text}：获取 @{username} 最近最多 {limit} 条推文..."
            )
        )

        try:
            instance, tweets = await self.nitter.fetch_tweets_from_instance(
                instance_text, username, limit
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
    ) -> None:
        if self.sender.should_merge_for_event(event, len(tweets)):
            notices = []
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
                await self._send_manual_tweets_with_fallback(
                    event,
                    username,
                    instance,
                    tweets,
                    notices=self._dedupe_texts(notices),
                )
            finally:
                await asyncio.to_thread(self.media.cleanup_after_send, tweets)
            return

        sent_notices: set[str] = set()
        total = len(tweets)
        for index, tweet in enumerate(tweets, 1):
            try:
                notices = await self._prepare_manual_tweets(
                    [tweet],
                    event.unified_msg_origin,
                    username=username,
                    progress_index=index,
                    progress_total=total,
                )
                notices = [
                    notice for notice in notices if notice not in sent_notices
                ]
                sent_notices.update(notices)
                await self._send_manual_tweets_with_fallback(
                    event,
                    username,
                    instance,
                    [tweet],
                    notices=notices,
                    header_text=f"@{username} 本次结果 {index}/{total}",
                    tweet_start_index=index,
                )
            finally:
                await asyncio.to_thread(self.media.cleanup_after_send, [tweet])

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
        enrich_report = await self.enricher.attach_enrichments(tweets, umo)
        if username:
            self._log_ai_process_results(
                username,
                tweets,
                translation_report,
                enrich_report,
                progress_index,
                progress_total,
            )
        return enrich_report.visible_notices()

    def _log_ai_process_results(
        self,
        username: str,
        tweets,
        translation_report=None,
        enrich_report=None,
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
                    enrich_report,
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
    ) -> None:
        notices = notices or []
        if await self.sender.send(
            event,
            username,
            instance,
            tweets,
            notices=notices,
            header_text=header_text,
            tweet_start_index=tweet_start_index,
        ):
            return
        fallback_text = self.sender.renderer.format_plain(
            username,
            instance,
            tweets,
            start_index=tweet_start_index,
            notices=notices,
            header_text=header_text,
        )
        try:
            await event.send(MessageChain([Plain(fallback_text)]))
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
                logger.warning(
                    "[NitterTweets] 发送手动推文失败提示失败: "
                    f"{notice_exc}"
                )

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
            return "", 0, "", (
                "请提供完整 Nitter 镜像站地址，例如：/镜像测试 https://nitter.net"
            )

        instance_text = tokens[instance_index]
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
                    return "", 0, "", (
                        "数量只能填写一次，例如：/镜像测试 3 https://nitter.net"
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
                return "", 0, "", (
                    "用户名只能填写一次，例如：/镜像测试 nasa https://nitter.net"
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
        value = str(value or "").strip().lower()
        if not value or value.startswith("@") or " " in value:
            return False
        if not value.startswith(("http://", "https://")):
            return False
        return "." in value or "localhost" in value

    def _cooldown_key(self, event: AstrMessageEvent) -> str:
        sender = safe_call(event, "get_sender_id") or "unknown"
        group = safe_call(event, "get_group_id") or "private"
        return f"{group}:{sender}"

    def _cooldown_left(self, event: AstrMessageEvent) -> float:
        if self.cooldown_seconds <= 0:
            return 0
        last = self._cooldowns.get(self._cooldown_key(event), 0)
        return max(0.0, self.cooldown_seconds - (time.time() - last))

    def _mark_cooldown(self, event: AstrMessageEvent) -> None:
        self._cooldowns[self._cooldown_key(event)] = time.time()
