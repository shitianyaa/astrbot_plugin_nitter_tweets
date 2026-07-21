from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field

from astrbot.api import logger

try:
    from ..config import config_get
    from ..shared import TweetItem, clamp_float, clamp_int, strip_external_links
except ImportError:
    from config import config_get
    from shared import TweetItem, clamp_float, clamp_int, strip_external_links


LOG_PREFIX = "[NitterTweets]"
LLM_CALL_TIMEOUT_SECONDS = 15.0
LLM_CALL_MAX_ATTEMPTS = 3

AI_TRANSLATION_FAILED_WARNING = "翻译：AI 翻译调用失败，已跳过。"

SPACE_RE = re.compile(r"\s+")

# 翻译相关
CJK_RE = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
KANA_RE = re.compile(r"[぀-ヿ]")
HANGUL_RE = re.compile(r"[가-힯]")
URL_RE = re.compile(r"https?://\S+")
MENTION_RE = re.compile(r"(?<!\w)@\w+")

DEFAULT_TRANSLATE_PROMPT = (
    "你是专业翻译助手。请把下面这条推文翻译成自然简体中文。"
    "保留人名、账号、标签和原有换行；不要添加解释，不要输出原文。\n\n{text}"
)


@dataclass(slots=True)
class TranslationTweetResult:
    status_id: str
    status: str = "off"
    reason: str = ""
    chars: int = 0


@dataclass(slots=True)
class TranslationReport:
    provider_id: str = ""
    provider_source: str = ""
    translated: int = 0
    skipped: int = 0
    failed: int = 0
    tweet_results: list[TranslationTweetResult] = field(default_factory=list)


def _append_ai_warning(tweet: TweetItem, warning: str) -> None:
    if warning and warning not in tweet.ai_warnings:
        tweet.ai_warnings.append(warning)


async def _llm_generate_with_retry(
    context,
    *,
    provider_id: str,
    purpose: str,
    status_id: str,
    **kwargs,
):
    last_error = ""
    for attempt in range(1, LLM_CALL_MAX_ATTEMPTS + 1):
        try:
            response = await asyncio.wait_for(
                context.llm_generate(chat_provider_id=provider_id, **kwargs),
                timeout=LLM_CALL_TIMEOUT_SECONDS,
            )
            return response, ""
        except TimeoutError as exc:
            last_error = f"timeout({LLM_CALL_TIMEOUT_SECONDS:g}s)"
            logger.warning(
                f"{LOG_PREFIX} AI {purpose} 调用超时: status={status_id}, "
                f"provider={provider_id}, attempt={attempt}/{LLM_CALL_MAX_ATTEMPTS}, "
                f"error={exc}"
            )
        except Exception as exc:
            last_error = type(exc).__name__ or "exception"
            logger.warning(
                f"{LOG_PREFIX} AI {purpose} 调用失败: status={status_id}, "
                f"provider={provider_id}, attempt={attempt}/{LLM_CALL_MAX_ATTEMPTS}, "
                f"error={exc}"
            )
    return None, last_error or "failed"


def format_ai_tweet_summary(
    username: str,
    tweet: TweetItem,
    translation_report: TranslationReport | None = None,
    index: int = 1,
    total: int = 1,
) -> str:
    status_id = tweet.status_id or f"index-{index}"
    progress = f", progress={index}/{total}" if total > 1 else ""
    return (
        f"{LOG_PREFIX} AI 处理完成: username={username}, status={status_id}{progress}, "
        f"translation={_format_translation_result(translation_report, status_id)}, "
        f"media={_format_media_result(tweet)}"
    )


def _format_translation_result(
    report: TranslationReport | None, status_id: str
) -> str:
    if report is None or not getattr(report, "tweet_results", None):
        return "off"
    result = _find_report_item(report, status_id)
    if result is None:
        return "unknown"
    if result.status in {"done", "existing"}:
        suffix = f", chars={result.chars}" if result.chars else ""
        return f"{result.status}({suffix.lstrip(', ')})" if suffix else result.status
    if result.reason:
        return f"{result.status}({result.reason})"
    return result.status


def _format_media_result(tweet: TweetItem) -> str:
    image_total = sum(1 for item in tweet.media if item.is_image)
    video_total = sum(1 for item in tweet.media if item.is_video)
    if not image_total and not video_total:
        return "none"
    parts = []
    if image_total:
        image_attached = sum(1 for item in tweet.media if item.is_image and item.path)
        parts.append(f"images={image_attached}/{image_total}")
    if video_total:
        video_attached = sum(1 for item in tweet.media if item.is_video and item.path)
        parts.append(f"videos={video_attached}/{video_total}")
    return ",".join(parts)


def _find_report_item(report, status_id: str):
    items = getattr(report, "tweet_results", []) or []
    for item in items:
        if getattr(item, "status_id", "") == status_id:
            return item
    if len(items) == 1:
        return items[0]
    return None


# ──────────────────────────────────────────────────────────────────────
# 翻译
# ──────────────────────────────────────────────────────────────────────

class TweetTranslator:
    def __init__(self, context, config):
        self.context = context
        self.enabled = bool(config_get(config, "translate_enabled", False))
        self.provider_id = str(
            config_get(config, "translation_provider_id", "") or ""
        ).strip()
        self.min_chars = clamp_int(
            config_get(config, "translate_min_chars", 8), 0, 1000
        )
        self.max_chars = clamp_int(
            config_get(config, "translate_max_chars", 2000), 100, 10000
        )
        self.chinese_ratio_threshold = clamp_float(
            config_get(config, "translate_chinese_ratio_threshold", 0.2), 0.0, 1.0
        )
        self.prompt_template = self._load_prompt(config)
        if "{text}" not in self.prompt_template:
            self.prompt_template = f"{self.prompt_template}\n\n{{text}}"
        self._warned_no_provider = False

    async def attach_translations(
        self, tweets: list[TweetItem], umo: str | None = None,
    ) -> TranslationReport:
        report = TranslationReport()
        if not self.enabled:
            logger.debug(f"{LOG_PREFIX} 翻译已跳过: translate_enabled=false")
            report.tweet_results = [
                TranslationTweetResult(
                    status_id=tweet.status_id or f"index-{index}",
                    status="off",
                )
                for index, tweet in enumerate(tweets, 1)
            ]
            return report
        if not tweets:
            logger.debug(f"{LOG_PREFIX} 翻译已跳过: no_tweets")
            return report

        provider_id, source = await self._resolve_provider(umo)
        report.provider_id = provider_id
        report.provider_source = source
        if not provider_id:
            if not self._warned_no_provider:
                logger.warning(f"{LOG_PREFIX} 翻译已启用但没有可用模型")
                self._warned_no_provider = True
            report.tweet_results = [
                TranslationTweetResult(
                    status_id=tweet.status_id or f"index-{index}",
                    status="unavailable",
                )
                for index, tweet in enumerate(tweets, 1)
            ]
            return report
        if len(tweets) > 1:
            logger.info(f"{LOG_PREFIX} 翻译开始: tweets={len(tweets)}, provider={provider_id} ({source})")

        translated = skipped = failed = 0
        for index, tweet in enumerate(tweets, 1):
            sid = tweet.status_id or f"index-{index}"
            tweet_result = TranslationTweetResult(status_id=sid)
            report.tweet_results.append(tweet_result)
            if tweet.translation:
                tweet_result.status = "existing"
                tweet_result.chars = len(tweet.translation)
                skipped += 1
                continue

            should, reason = self._should_translate(tweet.text)
            if not should:
                tweet_result.status = "skipped"
                tweet_result.reason = reason
                skipped += 1
                continue

            result = await self._translate(provider_id, tweet, sid)
            if result:
                tweet.translation = result
                tweet_result.status = "done"
                tweet_result.reason = reason
                tweet_result.chars = len(result)
                translated += 1
            else:
                tweet_result.status = "failed"
                tweet_result.reason = reason
                failed += 1

        report.translated = translated
        report.skipped = skipped
        report.failed = failed
        if len(tweets) > 1:
            logger.info(f"{LOG_PREFIX} 翻译完成: translated={translated}, skipped={skipped}, failed={failed}")
        return report

    # ── 判断是否需要翻译 ──

    def _should_translate(self, text: str) -> tuple[bool, str]:
        cleaned = self._clean_for_detect(text)
        if len(cleaned) < self.min_chars:
            return False, f"too_short(len={len(cleaned)}, min={self.min_chars})"

        if KANA_RE.search(cleaned) or HANGUL_RE.search(cleaned):
            return True, f"kana_or_hangul(len={len(cleaned)})"

        meaningful = [ch for ch in cleaned if not ch.isspace()]
        if not meaningful:
            return False, "empty_after_clean"

        chinese_count = sum(1 for ch in meaningful if CJK_RE.match(ch))
        ratio = chinese_count / len(meaningful)
        reason = f"chinese_ratio={ratio:.2f}, threshold={self.chinese_ratio_threshold:.2f}, len={len(meaningful)}"
        return ratio < self.chinese_ratio_threshold, reason

    async def _translate(self, provider_id: str, tweet: TweetItem, status_id: str) -> str:
        text = tweet.text
        prompt_text = strip_external_links(text)
        if not prompt_text:
            return ""
        if len(prompt_text) > self.max_chars:
            prompt_text = prompt_text[: self.max_chars].rstrip()

        prompt = self.prompt_template.replace("{text}", prompt_text)
        resp, error = await _llm_generate_with_retry(
            self.context,
            provider_id=provider_id,
            purpose="translation",
            status_id=status_id,
            prompt=prompt,
        )
        if resp is None:
            _append_ai_warning(tweet, AI_TRANSLATION_FAILED_WARNING)
            logger.warning(
                f"{LOG_PREFIX} 翻译重试后仍失败: "
                f"status={status_id}, error={error}"
            )
            return ""

        result = strip_external_links(self._clean((resp.completion_text or "").strip()))
        if self._same(result, prompt_text):
            return ""
        return result

    # ── Provider 解析（配置 > 当前会话 > 第一个） ──

    async def _resolve_provider(self, umo: str | None) -> tuple[str, str]:
        if self.provider_id:
            return self.provider_id, "config"

        if umo:
            try:
                pid = await self.context.get_current_chat_provider_id(umo=umo)
                pid = str(pid or "").strip()
                if pid:
                    return pid, "current_chat"
            except Exception:
                pass

        # 第一个可用 provider
        try:
            pm = getattr(self.context, "provider_manager", None)
            if pm is not None:
                providers = pm.get_all_providers()
                if isinstance(providers, dict) and providers:
                    return str(next(iter(providers.keys()))).strip(), "first_provider"
                if isinstance(providers, list) and providers:
                    for attr in ("id", "provider_id", "name"):
                        val = getattr(providers[0], attr, None)
                        if val:
                            return str(val).strip(), "first_provider"
        except Exception:
            pass

        return "", "none"

    # ── 工具方法 ──

    @staticmethod
    def _clean_for_detect(text: str) -> str:
        text = URL_RE.sub("", text or "")
        text = MENTION_RE.sub("", text)
        return SPACE_RE.sub("", text)

    @staticmethod
    def _load_prompt(config) -> str:
        prompt = str(config_get(config, "translate_prompt", "") or "").strip()
        if prompt:
            return prompt
        old_system = str(
            config_get(config, "translate_system_prompt", "") or ""
        ).strip()
        old_template = str(
            config_get(config, "translate_prompt_template", "") or ""
        ).strip()
        if old_system or old_template:
            return "\n\n".join(p for p in (old_system, old_template) if p).strip()
        return DEFAULT_TRANSLATE_PROMPT

    @staticmethod
    def _clean(text: str) -> str:
        text = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
        for prefix in ("译文：", "翻译：", "中文翻译："):
            if text.startswith(prefix):
                return text[len(prefix):].strip()
        return text

    @staticmethod
    def _same(left: str, right: str) -> bool:
        def norm(v: str) -> str:
            return SPACE_RE.sub("", v or "").casefold()
        return bool(left) and norm(left) == norm(right)
