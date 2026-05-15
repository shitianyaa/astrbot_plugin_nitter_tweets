from __future__ import annotations

import re

from astrbot.api import logger

try:
    from .models import TweetItem
    from .utils import clamp_float, clamp_int
except ImportError:
    from models import TweetItem
    from utils import clamp_float, clamp_int


CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
KANA_RE = re.compile(r"[\u3040-\u30ff]")
HANGUL_RE = re.compile(r"[\uac00-\ud7af]")
URL_RE = re.compile(r"https?://\S+")
MENTION_RE = re.compile(r"(?<!\w)@\w+")
SPACE_RE = re.compile(r"\s+")


DEFAULT_TRANSLATE_PROMPT = (
    "你是专业翻译助手。请把下面这条推文翻译成自然简体中文。"
    "保留人名、账号、链接、标签和原有换行；不要添加解释，不要输出原文。\n\n{text}"
)


class TweetTranslator:
    def __init__(self, context, config):
        self.context = context
        self.enabled = bool(config.get("translate_enabled", False))
        self.provider_id = str(config.get("translation_provider_id", "") or "").strip()
        self.min_chars = clamp_int(config.get("translate_min_chars", 8), 0, 1000)
        self.max_chars = clamp_int(config.get("translate_max_chars", 2000), 100, 10000)
        self.chinese_ratio_threshold = clamp_float(
            config.get("translate_chinese_ratio_threshold", 0.2), 0.0, 1.0
        )
        self.prompt_template = self._load_prompt(config)
        if "{text}" not in self.prompt_template:
            self.prompt_template = f"{self.prompt_template}\n\n{{text}}"

    async def attach_translations(
        self, tweets: list[TweetItem], umo: str | None = None
    ) -> None:
        if not self.enabled:
            logger.info("[NitterTweets] translation skipped: translate_enabled=false")
            return

        if not tweets:
            logger.info("[NitterTweets] translation skipped: no tweets")
            return

        provider_id, provider_source = await self._resolve_provider_id(umo)
        if not provider_id:
            logger.warning(
                "[NitterTweets] translation enabled but no LLM provider is available"
            )
            return

        logger.info(
            "[NitterTweets] translation check started: "
            f"tweets={len(tweets)}, provider={provider_id} ({provider_source})"
        )

        translated = 0
        skipped = 0
        failed = 0
        for index, tweet in enumerate(tweets, 1):
            status_id = tweet.status_id or f"index-{index}"
            if tweet.translation:
                skipped += 1
                logger.info(
                    f"[NitterTweets] translation skipped: status={status_id}, reason=already_translated"
                )
                continue

            should_translate, reason = self._translation_decision(tweet.text)
            if not should_translate:
                skipped += 1
                logger.info(
                    f"[NitterTweets] translation skipped: status={status_id}, reason={reason}"
                )
                continue

            logger.info(
                f"[NitterTweets] translation requested: status={status_id}, reason={reason}"
            )
            translation = await self._translate(provider_id, tweet.text, status_id)
            if translation:
                tweet.translation = translation
                translated += 1
                logger.info(
                    "[NitterTweets] translation completed: "
                    f"status={status_id}, chars={len(translation)}"
                )
            else:
                failed += 1
                logger.warning(
                    f"[NitterTweets] translation produced no text: status={status_id}"
                )

        logger.info(
            "[NitterTweets] translation check finished: "
            f"translated={translated}, skipped={skipped}, failed={failed}"
        )

    async def _resolve_provider_id(self, umo: str | None) -> tuple[str, str]:
        if self.provider_id:
            return self.provider_id, "config"

        provider_id = ""

        if umo:
            try:
                try:
                    provider_id = await self.context.get_current_chat_provider_id(umo=umo)
                except TypeError:
                    provider_id = await self.context.get_current_chat_provider_id(umo)
            except Exception as exc:
                logger.info(f"[NitterTweets] current chat provider lookup failed: {exc}")

        provider_id = str(provider_id or "").strip()
        if provider_id:
            return provider_id, "current_chat"

        provider_id = self._first_provider_id()
        if provider_id:
            logger.info(
                "[NitterTweets] using first configured provider for translation "
                "because no chat-specific provider was found"
            )
            return provider_id, "first_provider"

        return "", "none"

    def _should_translate(self, text: str) -> bool:
        return self._translation_decision(text)[0]

    def _translation_decision(self, text: str) -> tuple[bool, str]:
        cleaned = self._clean_for_detection(text)
        if len(cleaned) < self.min_chars:
            return False, f"too_short(len={len(cleaned)}, min={self.min_chars})"

        if KANA_RE.search(cleaned) or HANGUL_RE.search(cleaned):
            return True, f"kana_or_hangul(len={len(cleaned)})"

        meaningful = [ch for ch in cleaned if not ch.isspace()]
        if not meaningful:
            return False, "empty_after_clean"

        chinese_count = sum(1 for ch in meaningful if CJK_RE.match(ch))
        chinese_ratio = chinese_count / len(meaningful)
        reason = (
            f"chinese_ratio={chinese_ratio:.2f}, "
            f"threshold={self.chinese_ratio_threshold:.2f}, len={len(meaningful)}"
        )
        return chinese_ratio < self.chinese_ratio_threshold, reason

    async def _translate(self, provider_id: str, text: str, status_id: str) -> str:
        prompt_text = text.strip()
        if len(prompt_text) > self.max_chars:
            prompt_text = prompt_text[: self.max_chars].rstrip()

        prompt = self.prompt_template.replace("{text}", prompt_text)
        try:
            resp = await self.context.llm_generate(
                chat_provider_id=provider_id,
                prompt=prompt,
            )
        except Exception as exc:
            logger.warning(
                f"[NitterTweets] tweet translation failed: status={status_id}, error={exc}"
            )
            return ""

        completion = str(getattr(resp, "completion_text", "") or "").strip()
        completion = self._clean_completion(completion)
        if self._same_text(completion, text):
            return ""
        return completion

    @staticmethod
    def _clean_for_detection(text: str) -> str:
        text = URL_RE.sub("", text or "")
        text = MENTION_RE.sub("", text)
        return SPACE_RE.sub("", text)

    @staticmethod
    def _load_prompt(config) -> str:
        prompt = str(config.get("translate_prompt", "") or "").strip()
        if prompt:
            return prompt

        old_system = str(config.get("translate_system_prompt", "") or "").strip()
        old_template = str(config.get("translate_prompt_template", "") or "").strip()
        if old_system or old_template:
            return "\n\n".join(
                part for part in (old_system, old_template) if part
            ).strip()

        return DEFAULT_TRANSLATE_PROMPT

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

    @staticmethod
    def _clean_completion(text: str) -> str:
        text = text.strip()
        text = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
        for prefix in ("译文：", "翻译：", "中文翻译："):
            if text.startswith(prefix):
                return text[len(prefix) :].strip()
        return text

    @staticmethod
    def _same_text(left: str, right: str) -> bool:
        normalize = lambda value: SPACE_RE.sub("", value or "").casefold()
        return bool(left) and normalize(left) == normalize(right)
