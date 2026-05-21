from __future__ import annotations

import random
import re
from pathlib import Path

from astrbot.api import logger

try:
    from .models import TweetItem
    from .utils import clamp_float, clamp_int, file_uri
except ImportError:
    from models import TweetItem
    from utils import clamp_float, clamp_int, file_uri


DEFAULT_COMMENT_PROMPT = (
    "你是社交媒体评论助手。请基于下面的推文内容和可选图片描述，"
    "生成一句简短、自然、有信息量的中文点评。不要复述原文，不要使用 Markdown。"
    "\n\n推文：{text}\n中文翻译：{translation}\n图片描述：{image_caption}"
)

DEFAULT_VISION_PROMPT = (
    "请简要描述这张图片的主要内容、可见文字、关键信息和可能的语境。"
    "输出自然简体中文，不要使用 Markdown。"
)

SPACE_RE = re.compile(r"\s+")


class TweetEnricher:
    def __init__(self, context, config):
        self.context = context
        self.comment_enabled = bool(config.get("comment_enabled", False))
        self.vision_enabled = bool(config.get("vision_enabled", False))
        self.comment_provider_id = str(config.get("comment_provider_id", "") or "").strip()
        self.vision_provider_id = str(config.get("vision_provider_id", "") or "").strip()
        self.comment_probability = clamp_float(
            config.get("comment_probability", 0.3), 0.0, 1.0
        )
        self.vision_probability = clamp_float(
            config.get("vision_probability", 0.3), 0.0, 1.0
        )
        self.comment_max_chars = clamp_int(
            config.get("comment_max_chars", 2000), 100, 10000
        )
        self.vision_first_image_only = bool(config.get("vision_first_image_only", True))
        self.comment_prompt_template = self._load_comment_prompt(config)
        self.vision_prompt = self._load_vision_prompt(config)
        self._cached_framework_vlm_id: str | None = None

    @property
    def enabled(self) -> bool:
        return self.comment_enabled or self.vision_enabled

    async def attach_enrichments(
        self, tweets: list[TweetItem], umo: str | None = None
    ) -> None:
        if not self.enabled:
            logger.info("[NitterTweets] AI enrich skipped: disabled")
            return
        if not tweets:
            logger.info("[NitterTweets] AI enrich skipped: no tweets")
            return

        comment_provider_id = ""
        vision_provider_id = ""
        if self.comment_enabled and self.comment_probability > 0:
            comment_provider_id, comment_source = await self._resolve_comment_provider(umo)
            if comment_provider_id:
                logger.info(
                    "[NitterTweets] AI comment provider resolved: "
                    f"{comment_provider_id} ({comment_source})"
                )
            else:
                logger.warning("[NitterTweets] AI comment enabled but no provider is available")
        if self.vision_enabled and self.vision_probability > 0:
            vision_provider_id, vision_source = await self._resolve_vision_provider(umo)
            if vision_provider_id:
                logger.info(
                    "[NitterTweets] AI vision provider resolved: "
                    f"{vision_provider_id} ({vision_source})"
                )
            else:
                logger.warning("[NitterTweets] AI vision enabled but no provider is available")

        captioned = 0
        commented = 0
        skipped = 0
        failed = 0
        for index, tweet in enumerate(tweets, 1):
            status_id = tweet.status_id or f"index-{index}"

            if (
                self.vision_enabled
                and vision_provider_id
                and not tweet.image_caption
                and self._roll(self.vision_probability)
            ):
                image_path = self._first_image_path(tweet)
                if image_path:
                    caption = await self._caption_image(
                        vision_provider_id, image_path, status_id
                    )
                    if caption:
                        tweet.image_caption = caption
                        captioned += 1
                    else:
                        failed += 1
                else:
                    skipped += 1
                    logger.info(
                        f"[NitterTweets] AI vision skipped: status={status_id}, reason=no_image"
                    )

            if (
                self.comment_enabled
                and comment_provider_id
                and not tweet.ai_comment
                and self._roll(self.comment_probability)
            ):
                comment = await self._comment_tweet(
                    comment_provider_id, tweet, status_id
                )
                if comment:
                    tweet.ai_comment = comment
                    commented += 1
                else:
                    failed += 1

        logger.info(
            "[NitterTweets] AI enrich finished: "
            f"tweets={len(tweets)}, captioned={captioned}, "
            f"commented={commented}, skipped={skipped}, failed={failed}"
        )

    async def _caption_image(
        self, provider_id: str, image_path: Path, status_id: str
    ) -> str:
        image_url = file_uri(image_path)
        try:
            response = await self._llm_generate_with_image(
                provider_id=provider_id,
                prompt=self.vision_prompt,
                image_url=image_url,
            )
        except Exception as exc:
            logger.warning(
                f"[NitterTweets] AI vision failed: status={status_id}, error={exc}"
            )
            return ""

        caption = self._clean_completion(getattr(response, "completion_text", "") or "")
        if caption:
            logger.info(
                f"[NitterTweets] AI vision completed: status={status_id}, chars={len(caption)}"
            )
        else:
            logger.warning(f"[NitterTweets] AI vision returned empty text: status={status_id}")
        return caption

    async def _comment_tweet(
        self, provider_id: str, tweet: TweetItem, status_id: str
    ) -> str:
        text = (tweet.text or "").strip()
        if len(text) > self.comment_max_chars:
            text = text[: self.comment_max_chars].rstrip()
        image_caption = (tweet.image_caption or "").strip()
        if not text and not image_caption:
            logger.info(
                f"[NitterTweets] AI comment skipped: status={status_id}, reason=no_text_or_caption"
            )
            return ""

        prompt = self._render_comment_prompt(
            text=text,
            translation=tweet.translation,
            image_caption=image_caption,
            link=tweet.link,
        )
        try:
            response = await self.context.llm_generate(
                chat_provider_id=provider_id,
                prompt=prompt,
            )
        except Exception as exc:
            logger.warning(
                f"[NitterTweets] AI comment failed: status={status_id}, error={exc}"
            )
            return ""

        comment = self._clean_completion(getattr(response, "completion_text", "") or "")
        if self._same_text(comment, tweet.text) or self._same_text(comment, tweet.translation):
            return ""
        if comment:
            logger.info(
                f"[NitterTweets] AI comment completed: status={status_id}, chars={len(comment)}"
            )
        else:
            logger.warning(f"[NitterTweets] AI comment returned empty text: status={status_id}")
        return comment

    async def _resolve_comment_provider(self, umo: str | None) -> tuple[str, str]:
        if self.comment_provider_id:
            return self.comment_provider_id, "config"
        provider_id = await self._current_chat_provider_id(umo)
        if provider_id:
            return provider_id, "current_chat"
        provider_id = self._first_provider_id()
        if provider_id:
            return provider_id, "first_provider"
        return "", "none"

    async def _resolve_vision_provider(self, umo: str | None) -> tuple[str, str]:
        if self.vision_provider_id:
            return self.vision_provider_id, "config"

        framework_provider_id = self._framework_vision_provider_id()
        if framework_provider_id:
            return framework_provider_id, "default_image_caption_provider"

        provider_id = await self._current_chat_provider_id(umo)
        if provider_id:
            return provider_id, "current_chat"

        provider_id = self._first_provider_id()
        if provider_id:
            return provider_id, "first_provider"
        return "", "none"

    async def _current_chat_provider_id(self, umo: str | None) -> str:
        if not umo:
            return ""
        try:
            try:
                provider_id = await self.context.get_current_chat_provider_id(umo=umo)
            except TypeError:
                provider_id = await self.context.get_current_chat_provider_id(umo)
        except Exception as exc:
            logger.info(f"[NitterTweets] current chat provider lookup failed: {exc}")
            return ""
        return str(provider_id or "").strip()

    def _framework_vision_provider_id(self) -> str:
        if self._cached_framework_vlm_id is not None:
            return self._cached_framework_vlm_id

        provider_id = ""
        try:
            astrbot_config = self.context.get_config()
            provider_settings = astrbot_config.get("provider_settings", {})
            provider_id = str(
                provider_settings.get("default_image_caption_provider_id", "") or ""
            ).strip()
        except Exception as exc:
            logger.info(f"[NitterTweets] framework vision provider lookup failed: {exc}")

        self._cached_framework_vlm_id = provider_id
        return provider_id

    def _first_provider_id(self) -> str:
        try:
            provider_manager = getattr(self.context, "provider_manager", None)
            if provider_manager is None:
                return ""
            providers = provider_manager.get_all_providers()
            if isinstance(providers, dict) and providers:
                return str(next(iter(providers.keys())) or "").strip()
            if isinstance(providers, list) and providers:
                first = providers[0]
                for attr in ("id", "provider_id", "name"):
                    value = getattr(first, attr, None)
                    if value:
                        return str(value).strip()
        except Exception as exc:
            logger.info(f"[NitterTweets] provider fallback lookup failed: {exc}")
        return ""

    async def _llm_generate_with_image(self, provider_id: str, prompt: str, image_url: str):
        try:
            return await self.context.llm_generate(
                chat_provider_id=provider_id,
                prompt=prompt,
                image_urls=[image_url],
            )
        except Exception as exc:
            if not self._should_retry_image_url_as_string(exc):
                raise
            logger.warning(
                "[NitterTweets] image_urls list form failed, retrying as string: "
                f"{exc}"
            )
            return await self.context.llm_generate(
                chat_provider_id=provider_id,
                prompt=prompt,
                image_urls=image_url,
            )

    def _render_comment_prompt(
        self, text: str, translation: str, image_caption: str, link: str
    ) -> str:
        replacements = {
            "text": text,
            "translation": translation or "无",
            "image_caption": image_caption or "无",
            "link": link or "",
        }
        return re.sub(
            r"\{(text|translation|image_caption|link)\}",
            lambda match: replacements[match.group(1)],
            self.comment_prompt_template,
        )

    @staticmethod
    def _load_comment_prompt(config) -> str:
        prompt = str(config.get("comment_prompt", "") or "").strip()
        if not prompt:
            return DEFAULT_COMMENT_PROMPT
        if (
            "{text}" not in prompt
            and "{translation}" not in prompt
            and "{image_caption}" not in prompt
        ):
            prompt = (
                f"{prompt}\n\n推文：{{text}}\n中文翻译：{{translation}}"
                "\n图片描述：{image_caption}"
            )
        return prompt

    @staticmethod
    def _load_vision_prompt(config) -> str:
        prompt = str(config.get("vision_prompt", "") or "").strip()
        return prompt or DEFAULT_VISION_PROMPT

    @staticmethod
    def _first_image_path(tweet: TweetItem) -> Path | None:
        for media in tweet.media:
            if media.is_image and media.path:
                return media.path
        return None

    @staticmethod
    def _roll(probability: float) -> bool:
        if probability <= 0:
            return False
        if probability >= 1:
            return True
        return random.random() < probability

    @staticmethod
    def _should_retry_image_url_as_string(exc: Exception) -> bool:
        text = str(exc).lower()
        markers = (
            "list object",
            "startswith",
            "image_urls",
            "expected list",
            "expected str",
            "typeerror",
        )
        return any(marker in text for marker in markers)

    @staticmethod
    def _clean_completion(text: str) -> str:
        text = str(text or "").strip()
        text = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
        for prefix in (
            "AI评论：",
            "评论：",
            "点评：",
            "AI识图：",
            "图片描述：",
            "识图结果：",
        ):
            if text.startswith(prefix):
                return text[len(prefix) :].strip()
        return text

    @staticmethod
    def _same_text(left: str, right: str) -> bool:
        normalize = lambda value: SPACE_RE.sub("", value or "").casefold()
        return bool(left) and bool(right) and normalize(left) == normalize(right)
