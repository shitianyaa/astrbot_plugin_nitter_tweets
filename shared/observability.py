"""Safe, structured logging for NitterTweets task summaries and diagnostics.

Inspired by modern AstrBot plugin observability patterns:
- ``safe_task_log`` emits readable multi-line indented Chinese blocks for high-level tasks.
- ``safe_log`` emits structured single-line diagnostic events with field allow-listing.
"""

from __future__ import annotations

import logging
import re

try:
    from astrbot.api import logger
except ImportError:  # pragma: no cover
    logger = logging.getLogger("astrbot")

LOG_PREFIX = "[NitterTweets]"

ALLOWED_DIAGNOSTIC_FIELDS = {
    "event",
    "host",
    "from_host",
    "to_host",
    "reason",
    "status",
    "http_code",
    "gate",
    "mode",
    "limit",
    "media_kind",
    "encoding",
    "size_bucket",
    "tweets",
    "filtered",
    "group_id",
    "elapsed_ms",
    "source",
    "action",
    "error",
}

TASK_FIELDS = {
    "operation",
    "group_name",
    "group_id",
    "group_type",
    "source",
    "trigger",
    "instance",
    "failover_trace",
    "scanned_count",
    "tweet_count",
    "sent_count",
    "filtered_count",
    "filtered_label",
    "target_success_ratio",
    "ai_translation",
    "media_summary",
    "result_status",
    "warning_detail",
    "elapsed_ms",
    "error_detail",
}

_GROUP_TYPE_LABELS = {
    "blogger": "博主推文",
    "tag": "标签 / 关键词",
    "list": "Twitter List",
}

_TRIGGER_LABELS = {
    "manual_command": "手动命令 (！推文检查)",
    "passive_link": "聊天消息中的推文链接",
    "interval": "定时轮询",
    "cron": "Cron 定时",
}

_TASK_LABELS = {
    "operation": "操作类型",
    "group": "分组名称",
    "group_type": "订阅类型",
    "source": "目标来源",
    "trigger": "触发原因",
    "instance": "生效实例",
    "failover_trace": "轮换轨迹",
    "tweet_summary": "推文统计",
    "target_success_ratio": "推送结果",
    "ai_translation": "AI 翻译",
    "media_summary": "媒体附件",
    "result_status": "执行状态",
    "elapsed_ms": "任务耗时",
    "error_detail": "失败详情",
}

_KEY_RE = re.compile(r"g2a_[A-Za-z0-9_]+")
_B64_RE = re.compile(r"base64,[A-Za-z0-9+/=\s]+", re.IGNORECASE)
_USERINFO_RE = re.compile(r"(://)([^/@\s]+)@")
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")
_SENSITIVE_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|token|password|passwd|secret|"
    r"signature|credential)"
    r"([\"']?\s*[:=]\s*)(?:\"[^\"]*\"|'[^']*'|[^\s,;}\]]+)"
)
_URL_QUERY_RE = re.compile(r"(https?://[^\s/?#]+(?:/[^\s?#]*)?)\?[^\s)]+")
_WS_RE = re.compile(r"\s+")


def format_elapsed(milliseconds: float | int) -> str:
    """Format milliseconds into human-friendly Chinese duration string."""
    try:
        ms = float(milliseconds)
    except (TypeError, ValueError):
        return "0 毫秒"
    if ms < 0:
        return "0 毫秒"
    if ms >= 1000:
        return f"{ms / 1000:.1f} 秒"
    return f"{int(round(ms))} 毫秒"


def sanitize_sensitive_text(text: str) -> str:
    """Mask tokens, passwords, and sensitive keys in log strings."""
    if not text:
        return ""
    text = _USERINFO_RE.sub(r"\1***@", text)
    text = _URL_QUERY_RE.sub(r"\1?***", text)
    text = _B64_RE.sub("***", text)
    text = _KEY_RE.sub("***", text)
    text = _JWT_RE.sub("***", text)
    text = _BEARER_RE.sub("Bearer ***", text)
    text = _SENSITIVE_ASSIGNMENT_RE.sub(r"\1\2***", text)
    return text


def sanitize_diagnostic(value: object) -> str:
    """Strip secrets and control characters from diagnostic values."""
    text = sanitize_sensitive_text(str(value))
    text = _WS_RE.sub(" ", text).strip()
    if len(text) > 500:
        text = text[:500].rstrip() + "..."
    return text


def safe_task_log(level: int, title: str, **fields: object) -> None:
    """Emit a clean, indented multi-line Chinese task summary block."""
    fields = {key: value for key, value in fields.items() if key in TASK_FIELDS}
    lines = [f"{LOG_PREFIX} {title}"]

    # 1. Combined Group Name & ID
    group_name = fields.get("group_name")
    group_id = fields.get("group_id")
    if group_name or group_id:
        group_display = (
            f"{group_name} ({group_id})"
            if (group_name and group_id)
            else str(group_name or group_id)
        )
        lines.append(f"  分组名称: {sanitize_diagnostic(group_display)}")

    # 2. Group Type
    group_type = fields.get("group_type")
    if group_type:
        type_str = str(group_type).strip()
        type_label = _GROUP_TYPE_LABELS.get(type_str, type_str)
        lines.append(f"  订阅类型: {type_label}")

    # 3. Source (User/Query/List)
    source = fields.get("source")
    if source:
        lines.append(f"  目标来源: {sanitize_diagnostic(source)}")

    # 4. Trigger Reason
    trigger = fields.get("trigger")
    if trigger:
        trigger_str = str(trigger).strip()
        trigger_label = _TRIGGER_LABELS.get(trigger_str, trigger_str)
        lines.append(f"  触发原因: {trigger_label}")

    # 5. Effective Instance
    instance = fields.get("instance")
    if instance:
        inst_str = str(instance).strip()
        if inst_str:
            lines.append(f"  生效实例: {sanitize_diagnostic(inst_str)}")

    # 6. Failover Trace
    failover_trace = fields.get("failover_trace")
    if failover_trace:
        trace_str = str(failover_trace).strip()
        if trace_str:
            lines.append(f"  轮换轨迹: {sanitize_diagnostic(trace_str)}")

    # 7. Tweet Summary
    tweet_count = fields.get("tweet_count")
    sent_count = fields.get("sent_count")
    scanned_count = fields.get("scanned_count")
    filtered_count = fields.get("filtered_count")
    if tweet_count is not None or sent_count is not None or scanned_count is not None:
        parts: list[str] = []
        if scanned_count is not None:
            parts.append(f"扫描 {scanned_count} 条")
        if tweet_count is not None:
            try:
                tc = int(tweet_count)
                parts.append(f"新推文 {tc} 条" if tc > 0 else "无新推文")
            except (TypeError, ValueError):
                parts.append(f"获取 {sanitize_diagnostic(tweet_count)} 条")
        if sent_count is not None:
            try:
                parts.append(f"实际发送 {max(0, int(sent_count))} 条")
            except (TypeError, ValueError):
                parts.append(f"实际发送 {sanitize_diagnostic(sent_count)} 条")
        if filtered_count is not None:
            try:
                fc = int(filtered_count)
                if fc > 0:
                    filtered_label = sanitize_diagnostic(
                        fields.get("filtered_label") or "已过滤"
                    )
                    parts.append(f"{filtered_label} {fc} 条")
            except (TypeError, ValueError):
                pass
        if parts:
            lines.append(f"  推文统计: {'; '.join(parts)}")

    # 8. Push Target Success Ratio
    target_success_ratio = fields.get("target_success_ratio")
    if target_success_ratio is not None:
        lines.append(f"  推送结果: 成功推送 {target_success_ratio} 个目标")

    # 9. AI Translation
    ai_translation = fields.get("ai_translation")
    if ai_translation:
        lines.append(f"  AI 翻译: {sanitize_diagnostic(ai_translation)}")

    # 10. Media Summary
    media_summary = fields.get("media_summary")
    if media_summary:
        lines.append(f"  媒体附件: {sanitize_diagnostic(media_summary)}")

    result_status = fields.get("result_status")
    if result_status:
        lines.append(f"  执行状态: {sanitize_diagnostic(result_status)}")

    warning_detail = fields.get("warning_detail")
    if warning_detail:
        lines.append(f"  状态提示: {sanitize_diagnostic(warning_detail)}")

    # 11. Error Details (if any)
    error_detail = fields.get("error_detail")
    if error_detail:
        lines.append(f"  失败详情: {sanitize_diagnostic(error_detail)}")

    # 12. Elapsed Time
    elapsed_ms = fields.get("elapsed_ms")
    if elapsed_ms is not None:
        lines.append(f"  任务耗时: {format_elapsed(elapsed_ms)}")

    logger.log(level, "\n".join(lines))


def safe_log(level: int, event_name: str, **fields: object) -> None:
    """Emit a structured single-line diagnostic log event."""
    parts = [f"event={event_name}"]
    for key, value in fields.items():
        if key not in ALLOWED_DIAGNOSTIC_FIELDS:
            continue
        sanitized = sanitize_diagnostic(value)
        parts.append(f"{key}={sanitized}")
    logger.log(level, f"{LOG_PREFIX} " + " | ".join(parts))


__all__ = [
    "LOG_PREFIX",
    "format_elapsed",
    "sanitize_sensitive_text",
    "sanitize_diagnostic",
    "safe_task_log",
    "safe_log",
]
