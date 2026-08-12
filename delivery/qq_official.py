from __future__ import annotations

from itertools import count
from collections.abc import Awaitable, Callable
from typing import Any

try:
    from astrbot.api.all import MessageChain
except ImportError:
    from astrbot.api.event import MessageChain

try:
    from astrbot.api.message_components import Plain
except ImportError:
    from astrbot.core.message.components import Plain

from .default import DefaultDeliveryAdapter
from .outcomes import SendAttempt, SendOutcome


class QQOfficialDeliveryAdapter(DefaultDeliveryAdapter):
    """QQ Official delivery using botpy for UMO text and MessageChain for media.

    QQ Official's AstrBot adapter does not translate ``use_markdown_`` on its
    proactive UMO path, so Markdown UMO text is sent through the official botpy
    message API when the platform client is available.  Media remains on
    AstrBot's public MessageChain path because QQ requires Markdown and media
    to be separate messages.

    Event replies continue to use AstrBot's MessageChain Markdown flag.  Both
    Event and UMO media delivery send the Markdown body first and each media
    component separately, which keeps the API payloads unambiguous.
    """

    name = "qq_official"
    MARKDOWN_NOT_ALLOWED_ERROR = "不允许发送原生 markdown"
    _msg_seq = count(1)

    @staticmethod
    def _message_chain(
        components,
        *,
        link_style: str = "plain",
        plain_text: str | None = None,
    ) -> MessageChain:
        chain = MessageChain(components)
        use_markdown = link_style == "qq_official_md"
        if hasattr(chain, "use_markdown"):
            chain.use_markdown(use_markdown)
        else:
            # Keep compatibility with lightweight AstrBot MessageChain
            # implementations used by older runtimes and tests.
            chain.use_markdown_ = use_markdown
        if plain_text is not None:
            chain._qq_official_plain_text = plain_text
        return chain

    @staticmethod
    def _has_attached_media(sender: Any, tweets: list) -> bool:
        for tweet in tweets:
            for media in getattr(tweet, "media", ()) or ():
                if not getattr(media, "path", None):
                    continue
                if getattr(media, "is_image", False) and sender.send_image_attachments:
                    return True
                if getattr(media, "is_video", False) and sender.send_video_attachments:
                    return True
        return False

    @staticmethod
    def _event_link_style(link_style: str) -> str:
        if link_style in {"plain", "qq_official_md"}:
            return "qq_official_md"
        return "plain"

    @staticmethod
    def _official_api(profile: Any):
        """Return the botpy API object without assuming one wrapper shape."""

        platform = getattr(profile, "platform", None)
        candidates = (
            platform,
            getattr(platform, "adapter", None),
            getattr(platform, "platform", None),
        )
        for candidate in candidates:
            if candidate is None:
                continue
            api = getattr(candidate, "api", None)
            if api is not None:
                return api
            client = getattr(candidate, "client", None) or getattr(
                candidate, "bot", None
            )
            api = getattr(client, "api", None)
            if api is not None:
                return api
        return None

    @staticmethod
    def _message_type_name(profile: Any) -> str:
        value = getattr(profile, "message_type", "")
        return str(getattr(value, "value", value) or "").strip().lower()

    @staticmethod
    def _is_plain_component(component: Any) -> bool:
        if isinstance(component, Plain):
            return True
        # AstrBot reloads and lightweight compatibility adapters can expose a
        # Plain component class from a different module object. Keep the guard
        # type-specific while accepting that equivalent component shape.
        return type(component).__name__.endswith("Plain") and hasattr(component, "text")

    @classmethod
    def _plain_chain_text(cls, chain: MessageChain) -> str | None:
        components = getattr(chain, "chain", None)
        if components is None:
            components = getattr(chain, "components", ())
        components = list(components or ())
        if not components or not all(
            cls._is_plain_component(component) for component in components
        ):
            return None
        text = "".join(
            str(getattr(component, "text", "") or "") for component in components
        )
        return text or None

    async def send_context_chain(
        self,
        context,
        umo: str,
        chain: MessageChain,
        label: str,
    ) -> SendAttempt | None:
        """Send a Markdown-only UMO chain through the official message API.

        Plain and media chains return ``None`` so ``TweetSender`` keeps using
        AstrBot's normal path. Markdown text falls back to AstrBot's plain
        path when the botpy client is unavailable.
        """

        if getattr(chain, "use_markdown_", None) is not True:
            return None

        text = self._plain_chain_text(chain)
        session_id = str(getattr(self.profile, "session_id", "") or "").strip()
        api = self._official_api(self.profile)
        if not text or not session_id:
            return None

        message_type = self._message_type_name(self.profile)
        if message_type not in {"groupmessage", "friendmessage"}:
            return None

        plain_text = str(getattr(chain, "_qq_official_plain_text", "") or text)
        if api is None:
            return await self._send_plain_context_fallback(
                context,
                umo,
                chain,
                label,
                plain_text=plain_text,
            )

        if message_type == "groupmessage":
            method = getattr(api, "post_group_message", None)
            target_key = "group_openid"
        else:
            method = getattr(api, "post_c2c_message", None)
            target_key = "openid"
        if not callable(method):
            return await self._send_plain_context_fallback(
                context,
                umo,
                chain,
                label,
                plain_text=plain_text,
            )

        async def send_payload(*, markdown: bool):
            payload = {
                target_key: session_id,
                "msg_type": 2 if markdown else 0,
                "msg_seq": next(self._msg_seq),
            }
            if markdown:
                payload["markdown"] = {"content": text}
            else:
                payload["content"] = plain_text
            return await method(**payload)

        try:
            result = await send_payload(markdown=True)
        except Exception as exc:
            if self.MARKDOWN_NOT_ALLOWED_ERROR not in str(exc):
                return self.sender._send_exception_attempt(exc, label, umo)
            try:
                result = await send_payload(markdown=False)
            except Exception as fallback_exc:
                return self.sender._send_exception_attempt(
                    fallback_exc,
                    f"{label} plain fallback",
                    umo,
                )

        if result is None or result is False:
            return SendAttempt(
                success=False,
                retryable=True,
                error="QQ Official API 返回空响应",
            )
        return SendAttempt(success=True)

    async def _send_plain_context_fallback(
        self,
        context,
        umo: str,
        chain: MessageChain,
        label: str,
        *,
        plain_text: str | None = None,
    ) -> SendAttempt:
        """Use AstrBot's public path without leaking Markdown markers."""

        plain_chain = self._message_chain(
            [Plain(plain_text or self._plain_chain_text(chain) or "")],
            link_style="plain",
        )
        try:
            sent = await context.send_message(umo, plain_chain)
        except Exception as exc:
            flood_attempt = await self.sender._adapter_flood_control_attempt(
                self,
                lambda: context.send_message(umo, plain_chain),
                label,
                umo,
                exc,
            )
            if flood_attempt is not None:
                return flood_attempt
            return self.sender._send_exception_attempt(exc, label, umo)

        if sent is False:
            return SendAttempt(
                success=False,
                retryable=True,
                error="未找到目标平台或平台不支持主动发送",
            )
        return SendAttempt(success=True)

    async def send_summary_to_umo(
        self,
        context,
        umo: str,
        summary: str,
    ) -> SendOutcome:
        text = summary.strip()
        if not text:
            return SendOutcome(success=True)
        markdown_renderer = getattr(
            self.sender.renderer,
            "qq_official_markdown_text",
            None,
        )
        markdown_text = markdown_renderer(text) if callable(markdown_renderer) else text
        attempt = await self.sender._send_context_message(
            context,
            umo,
            self._message_chain(
                [Plain(markdown_text)],
                link_style="qq_official_md",
                plain_text=text,
            ),
            "scheduled summary",
        )
        return SendOutcome(
            success=attempt.success or attempt.uncertain,
            error=attempt.error,
            warning=attempt.warning,
        )

    async def send_event(
        self,
        event,
        username: str,
        instance: str,
        tweets: list,
        notices: list[str] | None = None,
        header_text: str = "",
        tweet_start_index: int = 1,
        media_only: bool = False,
        omit_status_url: bool = True,
        hide_original_when_translated: bool = False,
        link_style: str = "plain",
    ) -> bool:
        sender = self.sender
        if not self._has_attached_media(sender, tweets):
            return await super().send_event(
                event,
                username,
                instance,
                tweets,
                notices=notices,
                header_text=header_text,
                tweet_start_index=tweet_start_index,
                media_only=media_only,
                omit_status_url=omit_status_url,
                hide_original_when_translated=hide_original_when_translated,
                link_style=self._event_link_style(link_style),
            )

        text_components = sender.renderer.build_direct_components(
            username,
            instance,
            tweets,
            start_index=tweet_start_index,
            include_videos=False,
            include_images=False,
            notices=notices,
            header_text=header_text,
            media_only=media_only,
            omit_status_url=omit_status_url,
            hide_original_when_translated=hide_original_when_translated,
            link_style=self._event_link_style(link_style),
        )
        image_components = sender.renderer.build_direct_image_components(tweets)
        video_components = (
            sender.renderer.build_direct_video_components(tweets)
            if sender.send_video_attachments
            else []
        )

        async def send_chain(
            components,
            label: str,
            _include_plain_text: bool = False,
        ) -> SendAttempt:
            return await self._send_event_chain_with_retry(
                event,
                components,
                label,
                link_style=self._event_link_style(link_style),
            )

        async def send_component(component, label: str) -> SendAttempt:
            return await self._send_event_component_with_retry(
                sender,
                event,
                component,
                label,
                link_style="plain",
            )

        (
            text_delivered,
            media_delivered,
            _error,
            _warning,
        ) = await self._send_media_parts(
            send_chain=send_chain,
            send_component=send_component,
            text_components=text_components,
            image_components=image_components,
            video_components=video_components,
            tweets=tweets,
            media_only=media_only,
            label_prefix="QQ Official manual",
        )
        return text_delivered and (media_delivered or not media_only)

    async def send_to_umo(
        self,
        context,
        umo: str,
        username: str,
        instance: str,
        tweets: list,
        group_label: str = "",
        header_text: str = "",
        batch_summary: str = "",
        tweet_start_index: int = 1,
        media_only: bool = False,
        omit_status_url: bool = True,
        hide_original_when_translated: bool = False,
        link_style: str = "plain",
    ) -> SendOutcome:
        sender = self.sender
        text_components = sender.renderer.build_direct_components(
            username,
            instance,
            tweets,
            start_index=tweet_start_index,
            include_videos=False,
            include_images=False,
            group_label=group_label,
            header_text=header_text,
            batch_summary=batch_summary,
            media_only=media_only,
            omit_status_url=omit_status_url,
            hide_original_when_translated=hide_original_when_translated,
            link_style=self._event_link_style(link_style),
        )
        plain_text = sender.renderer.format_plain(
            username,
            instance,
            tweets,
            start_index=tweet_start_index,
            group_label=group_label,
            header_text=header_text,
            batch_summary=batch_summary,
            media_only=media_only,
            omit_status_url=omit_status_url,
            hide_original_when_translated=hide_original_when_translated,
            link_style="plain",
        )
        image_components = sender.renderer.build_direct_image_components(tweets)
        video_components = (
            sender.renderer.build_direct_video_components(tweets)
            if sender.send_video_attachments
            else []
        )

        async def send_chain(
            components,
            label: str,
            include_plain_text: bool = False,
        ) -> SendAttempt:
            return await self._send_context_chain_with_retry(
                context,
                umo,
                components,
                label,
                link_style=self._event_link_style(link_style),
                plain_text=plain_text if include_plain_text else None,
            )

        async def send_component(component, label: str) -> SendAttempt:
            return await self._send_context_component_with_retry(
                sender,
                context,
                umo,
                component,
                label,
                link_style="plain",
            )

        text_delivered, media_delivered, error, warning = await self._send_media_parts(
            send_chain=send_chain,
            send_component=send_component,
            text_components=text_components,
            image_components=image_components,
            video_components=video_components,
            tweets=tweets,
            media_only=media_only,
            label_prefix="QQ Official scheduled",
        )
        delivery_error = error or ""
        media_failed = bool(delivery_error)
        media_delivery_incomplete = media_only and not media_delivered
        success = text_delivered and (media_delivered or not media_only)
        return SendOutcome(
            success=success,
            error=delivery_error,
            warning=warning,
            delivery_status=(
                "partial_failed"
                if media_failed or media_delivery_incomplete
                else "success"
            ),
            delivery_error=delivery_error,
            delivered_status_ids=(
                sender._status_ids_from_tweets(tweets)
                if text_delivered and (not media_only or media_delivered)
                else ()
            ),
        )

    async def _send_event_fallback(
        self,
        event,
        username: str,
        instance: str,
        tweets: list,
        notices: list[str] | None = None,
        header_text: str = "",
        tweet_start_index: int = 1,
        media_only: bool = False,
        omit_status_url: bool = True,
        hide_original_when_translated: bool = False,
        link_style: str = "plain",
    ) -> bool:
        # If AstrBot surfaces the Markdown failure, retry with the plugin's
        # plain renderer. Some AstrBot versions may handle fallback internally.
        return await super()._send_event_fallback(
            event,
            username,
            instance,
            tweets,
            notices=notices,
            header_text=header_text,
            tweet_start_index=tweet_start_index,
            media_only=media_only,
            omit_status_url=omit_status_url,
            hide_original_when_translated=hide_original_when_translated,
            link_style="plain",
        )

    async def _send_event_chain_with_retry(
        self,
        event,
        components,
        label: str,
        link_style: str = "plain",
    ) -> SendAttempt:
        attempt = await self.sender._send_event_chain(
            event,
            self._message_chain(components, link_style=link_style),
            label,
        )
        if attempt.success or attempt.uncertain or not attempt.retryable:
            return attempt
        return await self.sender._send_event_chain(
            event,
            self._message_chain(components, link_style=link_style),
            label,
        )

    async def _send_context_chain_with_retry(
        self,
        context,
        umo: str,
        components,
        label: str,
        link_style: str = "plain",
        plain_text: str | None = None,
    ) -> SendAttempt:
        attempt = await self.sender._send_context_message(
            context,
            umo,
            self._message_chain(
                components,
                link_style=link_style,
                plain_text=plain_text,
            ),
            label,
        )
        if attempt.success or attempt.uncertain or not attempt.retryable:
            return attempt
        return await self.sender._send_context_message(
            context,
            umo,
            self._message_chain(
                components,
                link_style=link_style,
                plain_text=plain_text,
            ),
            label,
        )

    async def _send_media_parts(
        self,
        *,
        send_chain: Callable[[list, str, bool], Awaitable[SendAttempt]],
        send_component: Callable[[Any, str], Awaitable[SendAttempt]],
        text_components: list,
        image_components: list,
        video_components: list,
        tweets: list,
        media_only: bool,
        label_prefix: str,
    ) -> tuple[bool, bool, str, str]:
        """Send the Markdown body first, then each media component separately."""

        text_delivered = False
        image_succeeded = False
        image_failed = False
        video_succeeded = False
        video_failed = False
        errors: list[str] = []
        warnings: list[str] = []

        def collect(attempt: SendAttempt) -> None:
            if attempt.warning:
                warnings.append(attempt.warning)
            if attempt.error:
                errors.append(attempt.error)

        text_attempt = await send_chain(
            text_components,
            f"{label_prefix} text",
            True,
        )
        collect(text_attempt)
        if text_attempt.success or text_attempt.uncertain:
            text_delivered = True
            if text_attempt.uncertain and not media_only:
                return (
                    True,
                    False,
                    errors[-1] if errors else "",
                    "\n".join(warnings),
                )
        else:
            return (
                False,
                False,
                errors[-1] if errors else "send failed",
                "\n".join(warnings),
            )

        for offset, component in enumerate(image_components, start=1):
            attempt = await send_component(
                component,
                f"{label_prefix} image {offset}/{len(image_components)}",
            )
            collect(attempt)
            if attempt.success or attempt.uncertain:
                image_succeeded = True
            else:
                image_failed = True
            # Image failures are reported through ``errors`` but do not add a
            # video-specific omitted notice.

        for offset, component in enumerate(video_components, start=1):
            attempt = await send_component(
                component,
                f"{label_prefix} video {offset}/{len(video_components)}",
            )
            collect(attempt)
            if attempt.success or attempt.uncertain:
                video_succeeded = True
            else:
                video_failed = True

        if video_failed and not media_only:
            notice_components = (
                self.sender.renderer.build_video_omitted_notice_components(tweets)
            )
            if notice_components:
                notice = await send_chain(
                    notice_components,
                    f"{label_prefix} omitted video notice",
                    False,
                )
                collect(notice)

        return (
            text_delivered,
            # Ordinary delivery is complete once the body is accepted; media
            # errors are surfaced through the scheduled outcome's partial
            # status instead of causing the whole tweet to be retried.
            (
                (
                    video_succeeded and not video_failed
                    if video_components
                    else image_succeeded and not image_failed
                    if image_components
                    else False
                )
                if media_only
                else True
            ),
            errors[-1] if errors else "",
            "\n".join(warnings),
        )
