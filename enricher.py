from __future__ import annotations

import asyncio
import random
import re
from dataclasses import dataclass, field
from pathlib import Path

from astrbot.api import logger

try:
    from .group_config import GroupConfig
    from .utils import TweetItem, strip_external_links
except ImportError:
    from group_config import GroupConfig
    from utils import TweetItem, strip_external_links


LOG_PREFIX = "[NitterTweets]"

DEFAULT_VISION_PROMPT = (
    "请简要描述这张图片的主要内容、可见文字、关键信息和可能的语境。"
    "输出自然简体中文，不要使用 Markdown。"
)

DEFAULT_COMMENT_PROMPT = (
    "你是社交媒体评论助手。请基于下面的推文内容和可选图片描述，"
    "生成一句简短、自然、有信息量的中文点评。不要复述原文，不要使用 Markdown。"
    "\n\n推文：{text}\n中文翻译：{translation}\n图片描述：{image_caption}"
)

SPACE_RE = re.compile(r"\s+")

# 清理前缀
_PREFIXES_TO_STRIP = (
    "AI评论：", "评论：", "点评：",
    "AI识图：", "图片描述：", "识图结果：",
)

# 翻译相关
CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
KANA_RE = re.compile(r"[\u3040-\u30ff]")
HANGUL_RE = re.compile(r"[\uac00-\ud7af]")
URL_RE = re.compile(r"https?://\S+")
MENTION_RE = re.compile(r"(?<!\w)@\w+")

DEFAULT_TRANSLATE_PROMPT = (
    "你是专业翻译助手。请把下面这条推文翻译成自然简体中文。"
    "保留人名、账号、标签和原有换行；不要添加解释，不要输出原文。\n\n{text}"
)

VISION_UNAVAILABLE_NOTICE = (
    "AI识图未执行：未找到可用视觉模型。请在插件配置中设置 vision_provider_id，"
    "或在 AstrBot 中设置全局图片描述模型。"
)
VISION_UNAVAILABLE_LOG = (
    "AI vision skipped: no vision provider available. "
    "Set vision_provider_id or provider_settings.default_image_caption_provider_id."
)
VISION_FAILED_NOTICE = (
    "AI识图调用失败：当前模型可能不支持图片，或模型配置已失效。"
    "请检查 vision_provider_id 或 AstrBot 全局图片描述模型。"
)


@dataclass(slots=True)
class EnrichmentTweetResult:
    status_id: str
    vision_status: str = "off"
    vision_reason: str = ""
    vision_chars: int = 0
    vision_images: int = 0
    comment_status: str = "off"
    comment_reason: str = ""
    comment_chars: int = 0


@dataclass(slots=True)
class EnrichmentReport:
    vision_provider_id: str = ""
    vision_provider_source: str = ""
    vision_unavailable: bool = False
    vision_captioned: int = 0
    vision_skipped: int = 0
    vision_failed: int = 0
    comment_provider_id: str = ""
    comment_provider_source: str = ""
    commented: int = 0
    notice: str = ""
    tweet_results: list[EnrichmentTweetResult] = field(default_factory=list)

    def visible_notices(self) -> list[str]:
        return [self.notice] if self.notice else []


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


def format_ai_tweet_summary(
    username: str,
    tweet: TweetItem,
    translation_report: TranslationReport | None = None,
    enrichment_report: EnrichmentReport | None = None,
    index: int = 1,
    total: int = 1,
) -> str:
    status_id = tweet.status_id or f"index-{index}"
    progress = f", progress={index}/{total}" if total > 1 else ""
    return (
        f"{LOG_PREFIX} AI processed @{username} status={status_id}{progress}: "
        f"translation={_format_translation_result(translation_report, status_id)}, "
        f"media={_format_media_result(tweet)}, "
        f"vision={_format_vision_result(enrichment_report, status_id)}, "
        f"comment={_format_comment_result(enrichment_report, status_id)}"
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


def _format_vision_result(report: EnrichmentReport | None, status_id: str) -> str:
    if report is None or not getattr(report, "tweet_results", None):
        return "off"
    result = _find_report_item(report, status_id)
    if result is None:
        return "unknown"
    if result.vision_status == "done":
        return f"done(images={result.vision_images}, chars={result.vision_chars})"
    if result.vision_reason:
        return f"{result.vision_status}({result.vision_reason})"
    return result.vision_status


def _format_comment_result(report: EnrichmentReport | None, status_id: str) -> str:
    if report is None or not getattr(report, "tweet_results", None):
        return "off"
    result = _find_report_item(report, status_id)
    if result is None:
        return "unknown"
    if result.comment_status == "done":
        return f"done(chars={result.comment_chars})"
    if result.comment_reason:
        return f"{result.comment_status}({result.comment_reason})"
    return result.comment_status


def _find_report_item(report, status_id: str):
    items = getattr(report, "tweet_results", []) or []
    for item in items:
        if getattr(item, "status_id", "") == status_id:
            return item
    if len(items) == 1:
        return items[0]
    return None


class TweetEnricher:
    """AI 识图 + 评论，参照 get_px 的两步式设计。"""

    def __init__(self, context, group_config: GroupConfig):
        self.context = context

        self.vision_enabled = group_config.vision_enabled
        self.comment_enabled = group_config.comment_enabled
        self.vision_probability = group_config.vision_probability
        self.comment_probability = group_config.comment_probability

        self.vision_provider_id = group_config.vision_provider_id
        self.comment_provider_id = group_config.comment_provider_id

        self.vision_max_images = group_config.vision_max_images
        self.vision_max_total = group_config.vision_max_total
        self.comment_max_chars = group_config.comment_max_chars

        self.vision_prompt = group_config.vision_prompt
        self.comment_prompt_template = group_config.comment_prompt
        self._logged_vision_provider = ""
        self._logged_comment_provider = ""
        self._warned_vision_unavailable = False
        self._warned_comment_unavailable = False

    @property
    def enabled(self) -> bool:
        return self.vision_enabled or self.comment_enabled

    # ──────────────────────────────────────────────────────────────────
    # 入口
    # ──────────────────────────────────────────────────────────────────

    async def attach_enrichments(
        self, tweets: list[TweetItem], umo: str | None = None,
    ) -> EnrichmentReport:
        report = EnrichmentReport()
        if not self.enabled:
            logger.debug(f"{LOG_PREFIX} AI enrich skipped: disabled")
            report.tweet_results = [
                EnrichmentTweetResult(
                    status_id=tweet.status_id or f"index-{index}",
                    vision_status="off",
                    comment_status="off",
                )
                for index, tweet in enumerate(tweets, 1)
            ]
            return report
        if not tweets:
            logger.debug(f"{LOG_PREFIX} AI enrich skipped: no tweets")
            return report

        # ── 解析模型 ──
        v_pid = ""
        c_pid = ""
        if self.vision_enabled and self.vision_probability > 0:
            v_pid, v_source = await self._resolve_provider(
                self.vision_provider_id, umo, prefer_vision=True
            )
            report.vision_provider_id = v_pid
            report.vision_provider_source = v_source
            if v_pid:
                provider_key = f"{v_pid}:{v_source}"
                if provider_key != self._logged_vision_provider:
                    logger.info(f"{LOG_PREFIX} AI vision provider: {v_pid} ({v_source})")
                    self._logged_vision_provider = provider_key
            else:
                report.vision_unavailable = True
                if self._has_image_paths(tweets):
                    report.notice = VISION_UNAVAILABLE_NOTICE
                if not self._warned_vision_unavailable:
                    logger.warning(f"{LOG_PREFIX} {VISION_UNAVAILABLE_LOG}")
                    self._warned_vision_unavailable = True
        if self.comment_enabled and self.comment_probability > 0:
            c_pid, c_source = await self._resolve_provider(
                self.comment_provider_id, umo
            )
            report.comment_provider_id = c_pid
            report.comment_provider_source = c_source
            if c_pid:
                provider_key = f"{c_pid}:{c_source}"
                if provider_key != self._logged_comment_provider:
                    logger.info(f"{LOG_PREFIX} AI comment provider: {c_pid} ({c_source})")
                    self._logged_comment_provider = provider_key
            else:
                if not self._warned_comment_unavailable:
                    logger.warning(f"{LOG_PREFIX} AI comment enabled but no provider available")
                    self._warned_comment_unavailable = True

        # ── 逐条处理 ──
        captioned = commented = skipped = failed = 0
        vision_used = 0  # 已识图总数

        for index, tweet in enumerate(tweets, 1):
            sid = tweet.status_id or f"index-{index}"
            tweet_result = EnrichmentTweetResult(status_id=sid)
            report.tweet_results.append(tweet_result)

            # ── 识图（受 vision_max_images 单条上限 + vision_max_total 全局上限控制）──
            if not self.vision_enabled:
                tweet_result.vision_status = "off"
            elif not v_pid:
                tweet_result.vision_status = "unavailable"
            elif tweet.image_caption:
                tweet_result.vision_status = "existing"
                tweet_result.vision_chars = len(tweet.image_caption)
            elif self.vision_probability <= 0:
                tweet_result.vision_status = "skipped"
                tweet_result.vision_reason = "probability_zero"
            elif not self._roll(self.vision_probability):
                tweet_result.vision_status = "skipped"
                tweet_result.vision_reason = "probability"
            else:
                remaining = self.vision_max_total - vision_used
                if remaining <= 0:
                    tweet_result.vision_status = "skipped"
                    tweet_result.vision_reason = (
                        f"global_limit_reached({self.vision_max_total})"
                    )
                    skipped += 1
                    report.vision_skipped += 1
                else:
                    per_tweet_cap = min(self.vision_max_images, remaining)
                    image_paths = self._image_paths(tweet, per_tweet_cap)
                    if image_paths:
                        actual = len(image_paths)
                        captions = await self._vision_images(v_pid, image_paths, sid)
                        vision_used += actual
                        if captions:
                            tweet.image_caption = (
                                captions[0] if len(captions) == 1
                                else "\n".join(
                                    f"[{i}/{len(captions)}] {c}"
                                    for i, c in enumerate(captions, 1)
                                )
                            )
                            tweet_result.vision_status = "done"
                            tweet_result.vision_images = len(captions)
                            tweet_result.vision_chars = len(tweet.image_caption)
                            captioned += 1
                            report.vision_captioned += 1
                        else:
                            tweet_result.vision_status = "failed"
                            tweet_result.vision_reason = "empty_or_failed"
                            failed += 1
                            report.vision_failed += 1
                    else:
                        tweet_result.vision_status = "skipped"
                        tweet_result.vision_reason = "no_image"
                        skipped += 1
                        report.vision_skipped += 1

            # ── 评论 ──
            if not self.comment_enabled:
                tweet_result.comment_status = "off"
            elif not c_pid:
                tweet_result.comment_status = "unavailable"
            elif tweet.ai_comment:
                tweet_result.comment_status = "existing"
                tweet_result.comment_chars = len(tweet.ai_comment)
            elif self.comment_probability <= 0:
                tweet_result.comment_status = "skipped"
                tweet_result.comment_reason = "probability_zero"
            elif not self._roll(self.comment_probability):
                tweet_result.comment_status = "skipped"
                tweet_result.comment_reason = "probability"
            else:
                comment, reason = await self._comment_tweet(c_pid, tweet, sid)
                if comment:
                    tweet.ai_comment = comment
                    tweet_result.comment_status = "done"
                    tweet_result.comment_chars = len(comment)
                    commented += 1
                    report.commented += 1
                elif reason == "no_translation_or_vision":
                    tweet_result.comment_status = "skipped"
                    tweet_result.comment_reason = reason
                else:
                    tweet_result.comment_status = "failed"
                    tweet_result.comment_reason = reason or "empty"
                    failed += 1

        if (
            report.vision_failed > 0
            and report.vision_captioned == 0
            and not report.notice
            and self._has_image_paths(tweets)
        ):
            report.notice = VISION_FAILED_NOTICE
            logger.warning(
                f"{LOG_PREFIX} AI vision failed for all attempted tweets: "
                f"provider={report.vision_provider_id} "
                f"source={report.vision_provider_source}"
            )

        if len(tweets) > 1:
            logger.info(
                f"{LOG_PREFIX} AI enrich finished: tweets={len(tweets)}, "
                f"captioned={captioned}, commented={commented}, "
                f"skipped={skipped}, failed={failed}"
            )
        return report

    # ──────────────────────────────────────────────────────────────────
    # 识图（并发）
    # ──────────────────────────────────────────────────────────────────

    async def _vision_images(
        self, provider_id: str, image_paths: list[Path], status_id: str,
    ) -> list[str]:
        """并发识图多张图片，返回描述列表。"""

        async def _caption_one(idx: int, path: Path) -> str:
            image_url = path.as_uri()
            try:
                resp = await self.context.llm_generate(
                    chat_provider_id=provider_id,
                    prompt=self.vision_prompt,
                    image_urls=[image_url],
                )
            except Exception as exc:
                logger.warning(f"{LOG_PREFIX} AI vision failed: status={status_id} img={idx}, error={exc}")
                return ""
            text = self._clean((resp.completion_text or "").strip())
            return text

        results = await asyncio.gather(*[_caption_one(i, p) for i, p in enumerate(image_paths, 1)])
        return [r for r in results if r]

    # ──────────────────────────────────────────────────────────────────
    # 评论
    # ──────────────────────────────────────────────────────────────────

    async def _comment_tweet(
        self, provider_id: str, tweet: TweetItem, status_id: str
    ) -> tuple[str, str]:
        text = (tweet.text or "").strip()
        if len(text) > self.comment_max_chars:
            text = text[: self.comment_max_chars].rstrip()
        translation = (tweet.translation or "").strip()
        caption = (tweet.image_caption or "").strip()
        if not translation and not caption:
            return "", "no_translation_or_vision"

        prompt = self._render_comment_prompt(text, translation, caption, tweet.link)
        try:
            resp = await self.context.llm_generate(chat_provider_id=provider_id, prompt=prompt)
        except Exception as exc:
            logger.warning(f"{LOG_PREFIX} AI comment failed: status={status_id}, error={exc}")
            return "", "exception"

        comment = self._clean((resp.completion_text or "").strip())
        if self._same(comment, tweet.text) or self._same(comment, tweet.translation):
            return "", "same_as_source"
        if not comment:
            return "", "empty"
        return comment, ""

    # ──────────────────────────────────────────────────────────────────
    # Provider 解析（配置 > 框架全局视觉模型 > 当前会话）
    # ──────────────────────────────────────────────────────────────────

    async def _resolve_provider(
        self, config_pid: str, umo: str | None, prefer_vision: bool = False,
    ) -> tuple[str, str]:
        if config_pid:
            return config_pid, "config"

        # 框架全局图片描述模型（仅视觉）
        if prefer_vision:
            try:
                cfg = self.context.get_config()
                vlm = str((cfg.get("provider_settings") or {}).get(
                    "default_image_caption_provider_id", "",
                ) or "").strip()
                if vlm:
                    return vlm, "global_image_caption"
            except Exception:
                pass

        # 当前会话模型
        if umo:
            try:
                pid = str(
                    await self.context.get_current_chat_provider_id(umo=umo) or ""
                ).strip()
                if pid:
                    return pid, "current_chat"
            except Exception:
                pass

        # 视觉模型不盲目使用第一个 provider，避免把纯文本模型误当识图模型。
        if prefer_vision:
            return "", "none"

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

    # ──────────────────────────────────────────────────────────────────
    # 提示词渲染
    # ──────────────────────────────────────────────────────────────────

    def _render_comment_prompt(self, text: str, translation: str, caption: str, link: str) -> str:
        mapping = {
            "text": text,
            "translation": translation or "无",
            "image_caption": caption or "无",
            "link": link or "",
        }
        return re.sub(
            r"\{(text|translation|image_caption|link)\}",
            lambda m: mapping[m.group(1)],
            self.comment_prompt_template,
        )

    # ──────────────────────────────────────────────────────────────────
    # 工具方法
    # ──────────────────────────────────────────────────────────────────

    @staticmethod
    def _image_paths(tweet: TweetItem, max_count: int = 1) -> list[Path]:
        paths: list[Path] = []
        for media in tweet.media:
            if media.is_image and media.path:
                paths.append(media.path)
                if len(paths) >= max_count:
                    break
        return paths

    @staticmethod
    def _has_image_paths(tweets: list[TweetItem]) -> bool:
        return any(
            bool(media.is_image and media.path)
            for tweet in tweets
            for media in tweet.media
        )

    @staticmethod
    def _roll(probability: float) -> bool:
        if probability <= 0:
            return False
        if probability >= 1:
            return True
        return random.random() < probability

    @staticmethod
    def _clean(text: str) -> str:
        text = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
        for prefix in _PREFIXES_TO_STRIP:
            if text.startswith(prefix):
                return text[len(prefix):].strip()
        return text

    @staticmethod
    def _same(left: str, right: str) -> bool:
        def norm(v: str) -> str:
            return SPACE_RE.sub("", v or "").casefold()
        return bool(left) and bool(right) and norm(left) == norm(right)


# ──────────────────────────────────────────────────────────────────────
# 翻译
# ──────────────────────────────────────────────────────────────────────

class TweetTranslator:
    def __init__(self, context, group_config: GroupConfig):
        self.context = context
        self.enabled = group_config.translate_enabled
        self.provider_id = group_config.translation_provider_id
        self.min_chars = group_config.translate_min_chars
        self.max_chars = group_config.translate_max_chars
        self.chinese_ratio_threshold = group_config.translate_chinese_ratio_threshold
        self.prompt_template = group_config.translate_prompt
        if "{text}" not in self.prompt_template:
            self.prompt_template = f"{self.prompt_template}\n\n{{text}}"
        self._warned_no_provider = False

    async def attach_translations(
        self, tweets: list[TweetItem], umo: str | None = None,
    ) -> TranslationReport:
        report = TranslationReport()
        if not self.enabled:
            logger.debug(f"{LOG_PREFIX} translation skipped: translate_enabled=false")
            report.tweet_results = [
                TranslationTweetResult(
                    status_id=tweet.status_id or f"index-{index}",
                    status="off",
                )
                for index, tweet in enumerate(tweets, 1)
            ]
            return report
        if not tweets:
            logger.debug(f"{LOG_PREFIX} translation skipped: no tweets")
            return report

        provider_id, source = await self._resolve_provider(umo)
        report.provider_id = provider_id
        report.provider_source = source
        if not provider_id:
            if not self._warned_no_provider:
                logger.warning(f"{LOG_PREFIX} translation enabled but no provider available")
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
            logger.info(f"{LOG_PREFIX} translation started: tweets={len(tweets)}, provider={provider_id} ({source})")

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

            result = await self._translate(provider_id, tweet.text, sid)
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
            logger.info(f"{LOG_PREFIX} translation finished: translated={translated}, skipped={skipped}, failed={failed}")
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

    async def _translate(self, provider_id: str, text: str, status_id: str) -> str:
        prompt_text = strip_external_links(text)
        if not prompt_text:
            return ""
        if len(prompt_text) > self.max_chars:
            prompt_text = prompt_text[: self.max_chars].rstrip()

        prompt = self.prompt_template.replace("{text}", prompt_text)
        try:
            resp = await self.context.llm_generate(chat_provider_id=provider_id, prompt=prompt)
        except Exception as exc:
            logger.warning(f"{LOG_PREFIX} translation failed: status={status_id}, error={exc}")
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
