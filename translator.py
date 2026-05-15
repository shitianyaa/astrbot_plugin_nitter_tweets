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
            return

        provider_id = await self._resolve_provider_id(umo)
        if not provider_id:
            logger.warning(
                "[NitterTweets] translation enabled but no LLM provider is available"
            )
            return

        for tweet in tweets:
            if tweet.translation or not self._should_translate(tweet.text):
                continue
            translation = await self._translate(provider_id, tweet.text)
            if translation:
                tweet.translation = translation

    async def _resolve_provider_id(self, umo: str | None) -> str:
        if self.provider_id:
            return self.provider_id

        if not umo:
            return ""

        try:
            try:
                provider_id = await self.context.get_current_chat_provider_id(umo=umo)
            except TypeError:
                provider_id = await self.context.get_current_chat_provider_id(umo)
        except Exception as exc:
            logger.debug(f"[NitterTweets] failed to resolve chat provider: {exc}")
            return ""
        return str(provider_id or "").strip()

    def _should_translate(self, text: str) -> bool:
        cleaned = self._clean_for_detection(text)
        if len(cleaned) < self.min_chars:
            return False

        if KANA_RE.search(cleaned) or HANGUL_RE.search(cleaned):
            return True

        meaningful = [ch for ch in cleaned if not ch.isspace()]
        if not meaningful:
            return False

        chinese_count = sum(1 for ch in meaningful if CJK_RE.match(ch))
        chinese_ratio = chinese_count / len(meaningful)
        return chinese_ratio < self.chinese_ratio_threshold

    async def _translate(self, provider_id: str, text: str) -> str:
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
            logger.warning(f"[NitterTweets] tweet translation failed: {exc}")
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
