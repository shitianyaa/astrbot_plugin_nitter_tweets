from __future__ import annotations

import asyncio
import random
import re
from dataclasses import dataclass
from pathlib import Path

from astrbot.api import logger

try:
    from .utils import TweetItem, clamp_float, clamp_int, strip_external_links
except ImportError:
    from utils import TweetItem, clamp_float, clamp_int, strip_external_links


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

    def visible_notices(self) -> list[str]:
        return [self.notice] if self.notice else []


class TweetEnricher:
    """AI 识图 + 评论，参照 get_px 的两步式设计。"""

    def __init__(self, context, config):
        self.context = context

        # ── 开关与概率 ──
        self.vision_enabled = bool(config.get("vision_enabled", False))
        self.comment_enabled = bool(config.get("comment_enabled", False))
        self.vision_probability = clamp_float(config.get("vision_probability", 0.3), 0.0, 1.0)
        self.comment_probability = clamp_float(config.get("comment_probability", 0.3), 0.0, 1.0)

        # ── Provider ──
        self.vision_provider_id = str(config.get("vision_provider_id", "") or "").strip()
        self.comment_provider_id = str(config.get("comment_provider_id", "") or "").strip()

        # ── 图片 ──
        self.vision_max_images = clamp_int(config.get("vision_max_images", 3), 1, 20)
        self.vision_max_total = clamp_int(config.get("vision_max_total", 6), 1, 50)
        self.comment_max_chars = clamp_int(config.get("comment_max_chars", 2000), 100, 10000)

        # ── 提示词 ──
        self.vision_prompt = self._load_prompt(config, "vision_prompt", DEFAULT_VISION_PROMPT)
        self.comment_prompt_template = self._load_prompt(config, "comment_prompt", DEFAULT_COMMENT_PROMPT)

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
            logger.info(f"{LOG_PREFIX} AI enrich skipped: disabled")
            return report
        if not tweets:
            logger.info(f"{LOG_PREFIX} AI enrich skipped: no tweets")
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
                logger.info(f"{LOG_PREFIX} AI vision provider: {v_pid} ({v_source})")
            else:
                report.vision_unavailable = True
                if self._has_image_paths(tweets):
                    report.notice = VISION_UNAVAILABLE_NOTICE
                logger.warning(f"{LOG_PREFIX} {VISION_UNAVAILABLE_LOG}")
        if self.comment_enabled and self.comment_probability > 0:
            c_pid, c_source = await self._resolve_provider(
                self.comment_provider_id, umo
            )
            report.comment_provider_id = c_pid
            report.comment_provider_source = c_source
            if c_pid:
                logger.info(f"{LOG_PREFIX} AI comment provider: {c_pid} ({c_source})")
            else:
                logger.warning(f"{LOG_PREFIX} AI comment enabled but no provider available")

        # ── 逐条处理 ──
        captioned = commented = skipped = failed = 0
        vision_used = 0  # 已识图总数

        for index, tweet in enumerate(tweets, 1):
            sid = tweet.status_id or f"index-{index}"

            # ── 识图（受 vision_max_images 单条上限 + vision_max_total 全局上限控制）──
            if (
                self.vision_enabled
                and v_pid
                and not tweet.image_caption
                and self._roll(self.vision_probability)
            ):
                remaining = self.vision_max_total - vision_used
                if remaining <= 0:
                    logger.info(f"{LOG_PREFIX} AI vision skipped: status={sid}, reason=global_limit_reached ({self.vision_max_total})")
                    skipped += 1
                    report.vision_skipped += 1
                else:
                    per_tweet_cap = min(self.vision_max_images, remaining)
                    image_paths = self._image_paths(tweet, per_tweet_cap)
                    if image_paths:
                        actual = len(image_paths)
                        if actual < len([m for m in tweet.media if m.is_image and m.path]):
                            logger.info(f"{LOG_PREFIX} AI vision capped: status={sid}, {actual} images (global remaining={remaining})")
                        captions = await self._vision_images(v_pid, image_paths, sid)
                        vision_used += actual
                        if captions:
                            tweet.image_caption = (
                                captions[0] if len(captions) == 1
                                else "\n".join(f"[{i}/{len(captions)}] {c}" for i, c in enumerate(captions, 1))
                            )
                            captioned += 1
                            report.vision_captioned += 1
                        else:
                            failed += 1
                            report.vision_failed += 1
                    else:
                        skipped += 1
                        report.vision_skipped += 1
                        logger.info(f"{LOG_PREFIX} AI vision skipped: status={sid}, reason=no_image")

            # ── 评论 ──
            if self.comment_enabled and c_pid and not tweet.ai_comment and self._roll(self.comment_probability):
                comment = await self._comment_tweet(c_pid, tweet, sid)
                if comment:
                    tweet.ai_comment = comment
                    commented += 1
                    report.commented += 1
                else:
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
            if text:
                logger.info(f"{LOG_PREFIX} AI vision done: status={status_id} img={idx}, chars={len(text)}")
            else:
                logger.warning(f"{LOG_PREFIX} AI vision empty: status={status_id} img={idx}")
            return text

        results = await asyncio.gather(*[_caption_one(i, p) for i, p in enumerate(image_paths, 1)])
        return [r for r in results if r]

    # ──────────────────────────────────────────────────────────────────
    # 评论
    # ──────────────────────────────────────────────────────────────────

    async def _comment_tweet(self, provider_id: str, tweet: TweetItem, status_id: str) -> str:
        text = (tweet.text or "").strip()
        if len(text) > self.comment_max_chars:
            text = text[: self.comment_max_chars].rstrip()
        caption = (tweet.image_caption or "").strip()
        if not text and not caption:
            logger.info(f"{LOG_PREFIX} AI comment skipped: status={status_id}, reason=no_content")
            return ""

        prompt = self._render_comment_prompt(text, tweet.translation, caption, tweet.link)
        try:
            resp = await self.context.llm_generate(chat_provider_id=provider_id, prompt=prompt)
        except Exception as exc:
            logger.warning(f"{LOG_PREFIX} AI comment failed: status={status_id}, error={exc}")
            return ""

        comment = self._clean((resp.completion_text or "").strip())
        if self._same(comment, tweet.text) or self._same(comment, tweet.translation):
            return ""
        if comment:
            logger.info(f"{LOG_PREFIX} AI comment done: status={status_id}, chars={len(comment)}")
        else:
            logger.warning(f"{LOG_PREFIX} AI comment empty: status={status_id}")
        return comment

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

    @staticmethod
    def _load_prompt(config, key: str, default: str) -> str:
        prompt = str(config.get(key, "") or "").strip()
        return prompt or default


# ──────────────────────────────────────────────────────────────────────
# 翻译
# ──────────────────────────────────────────────────────────────────────

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
        self, tweets: list[TweetItem], umo: str | None = None,
    ) -> None:
        if not self.enabled:
            logger.info(f"{LOG_PREFIX} translation skipped: translate_enabled=false")
            return
        if not tweets:
            logger.info(f"{LOG_PREFIX} translation skipped: no tweets")
            return

        provider_id, source = await self._resolve_provider(umo)
        if not provider_id:
            logger.warning(f"{LOG_PREFIX} translation enabled but no provider available")
            return
        logger.info(f"{LOG_PREFIX} translation started: tweets={len(tweets)}, provider={provider_id} ({source})")

        translated = skipped = failed = 0
        for index, tweet in enumerate(tweets, 1):
            sid = tweet.status_id or f"index-{index}"
            if tweet.translation:
                skipped += 1
                continue

            should, reason = self._should_translate(tweet.text)
            if not should:
                skipped += 1
                logger.info(f"{LOG_PREFIX} translation skipped: status={sid}, reason={reason}")
                continue

            logger.info(f"{LOG_PREFIX} translation requested: status={sid}, reason={reason}")
            result = await self._translate(provider_id, tweet.text, sid)
            if result:
                tweet.translation = result
                translated += 1
                logger.info(f"{LOG_PREFIX} translation done: status={sid}, chars={len(result)}")
            else:
                failed += 1

        logger.info(f"{LOG_PREFIX} translation finished: translated={translated}, skipped={skipped}, failed={failed}")

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
    def _load_prompt(config) -> str:
        prompt = str(config.get("translate_prompt", "") or "").strip()
        if prompt:
            return prompt
        old_system = str(config.get("translate_system_prompt", "") or "").strip()
        old_template = str(config.get("translate_prompt_template", "") or "").strip()
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
