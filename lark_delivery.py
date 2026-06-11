from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

from astrbot.api import logger

try:
    from astrbot.api.all import MessageChain
except ImportError:
    from astrbot.api.event import MessageChain

try:
    from astrbot.api.message_components import Image, Plain, Video
except ImportError:
    from astrbot.core.message.components import Image, Plain, Video


LARK_PLATFORM_NAMES = {"lark", "feishu"}
LARK_TEXT_CHUNK_SIZE = 28000


@dataclass(slots=True)
class LarkSendAttempt:
    success: bool
    retryable: bool = False
    uncertain: bool = False
    error: str = ""
    warning: str = ""


def is_lark_platform(platform: str) -> bool:
    return str(platform or "").strip().lower() in LARK_PLATFORM_NAMES


def lark_client_and_target(context, umo: str, platform_lookup):
    platform_id, message_type, session_id = parse_umo(umo)
    platform = platform_lookup(context, platform_id)
    client = lark_client_from_platform(platform)
    receive_id_type = lark_receive_id_type(message_type)
    receive_id = lark_receive_id(message_type, session_id)
    return client, receive_id_type, receive_id


def lark_client_from_event(event, platform_lookup=None):
    client = getattr(event, "bot", None)
    if is_lark_client(client):
        return client

    platform = getattr(event, "platform", None) or getattr(event, "platform_inst", None)
    client = lark_client_from_platform(platform)
    if client is not None:
        return client

    context = getattr(event, "context", None)
    try:
        umo = getattr(event, "unified_msg_origin", "")
    except Exception:
        umo = ""
    if context and umo and platform_lookup is not None:
        client, _, _ = lark_client_and_target(context, str(umo), platform_lookup)
        return client
    return None


def lark_client_from_platform(platform):
    if platform is None:
        return None
    for attr in ("lark_api", "client", "_client", "bot"):
        client = getattr(platform, attr, None)
        if is_lark_client(client):
            return client
    if is_lark_client(platform):
        return platform
    return None


def is_lark_client(client) -> bool:
    return bool(client is not None and getattr(client, "im", None) is not None)


def parse_umo(umo: str) -> tuple[str, str, str]:
    parts = str(umo or "").split(":", 2)
    if len(parts) != 3:
        return "", "", ""
    return parts[0].strip(), parts[1].strip(), parts[2].strip()


def lark_receive_id_type(message_type: str) -> str:
    message_type = message_type.strip().lower()
    if message_type in {"groupmessage", "group", "group_message"}:
        return "chat_id"
    if message_type in {"friendmessage", "private", "private_message"}:
        return "open_id"
    return ""


def lark_receive_id(message_type: str, session_id: str) -> str:
    if lark_receive_id_type(message_type) == "chat_id" and "%" in session_id:
        return session_id.split("%", 1)[1]
    return session_id


def lark_reply_message_id(event) -> str:
    message_obj = getattr(event, "message_obj", None)
    for source in (message_obj, event):
        for attr in ("message_id", "id"):
            value = getattr(source, attr, None)
            if value:
                return str(value)
    return ""


def lark_event_target(event) -> tuple[str, str]:
    try:
        umo = getattr(event, "unified_msg_origin", "")
    except Exception:
        umo = ""
    _, message_type, session_id = parse_umo(str(umo))
    receive_id_type = lark_receive_id_type(message_type)
    receive_id = lark_receive_id(message_type, session_id)
    return receive_id_type, receive_id


def plain_text_from_components(components) -> str:
    parts = [
        component.text
        for component in components
        if isinstance(component, Plain) and component.text
    ]
    return "\n".join(part.strip() for part in parts if part.strip())


def media_components(components) -> list:
    return [
        component
        for component in components
        if isinstance(component, (Image, Video))
    ]


def video_components(components) -> list:
    return [component for component in components if isinstance(component, Video)]


def split_lark_text(text: str) -> list[str]:
    text = text or ""
    if len(text) <= LARK_TEXT_CHUNK_SIZE:
        return [text]

    chunks = []
    remaining = text
    while len(remaining) > LARK_TEXT_CHUNK_SIZE:
        split_at = remaining.rfind("\n\n", 0, LARK_TEXT_CHUNK_SIZE)
        if split_at <= 0:
            split_at = remaining.rfind("\n", 0, LARK_TEXT_CHUNK_SIZE)
        if split_at <= 0:
            split_at = LARK_TEXT_CHUNK_SIZE
        chunks.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()
    if remaining:
        chunks.append(remaining)
    return [chunk for chunk in chunks if chunk]


def _lark_post_title(title: str) -> str:
    title = (title or "Nitter 推文").strip()
    return title[:120]


def lark_tweet_post_title(
    username: str,
    tweet_count: int,
    header_text: str = "",
) -> str:
    title = str(header_text or "").strip()
    if title:
        return _lark_post_title(title)
    return _lark_post_title(f"@{username} 最近 {tweet_count} 条推文")


def _lark_post_append_text_line(content: list[list[dict]], line: str) -> None:
    content.append([{"tag": "text", "text": line if line else " "}])


def _local_image_path(component) -> Path | None:
    for attr in ("path", "file", "url"):
        value = str(getattr(component, attr, "") or "").strip()
        if not value:
            continue
        if value.startswith("file://"):
            parsed = urlparse(value)
            path = url2pathname(unquote(parsed.path))
            if parsed.netloc:
                path = f"//{parsed.netloc}{path}"
            candidate = Path(path)
        elif value.startswith(("http://", "https://", "base64://", "data:")):
            continue
        else:
            candidate = Path(value)
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


async def _upload_lark_image(client, image_path: Path, label: str) -> str:
    from lark_oapi.api.im.v1 import CreateImageRequest, CreateImageRequestBody

    with image_path.open("rb") as image_file:
        request = (
            CreateImageRequest.builder()
            .request_body(
                CreateImageRequestBody.builder()
                .image_type("message")
                .image(image_file)
                .build()
            )
            .build()
        )
        response = await client.im.v1.image.acreate(request)

    if not response.success():
        raise RuntimeError(
            f"{label} image upload returned {getattr(response, 'code', '')}: "
            f"{getattr(response, 'msg', '')}"
        )
    data = getattr(response, "data", None)
    image_key = str(getattr(data, "image_key", "") or "").strip()
    if not image_key:
        raise RuntimeError(f"{label} image upload returned empty image_key")
    return image_key


async def send_lark_post(
    client,
    title: str,
    components: list,
    label: str,
    *,
    is_uncertain_delivery_error,
    log_uncertain_delivery,
    uncertain_delivery_warning: str,
    reply_message_id: str | None = None,
    receive_id: str | None = None,
    receive_id_type: str | None = None,
) -> LarkSendAttempt:
    if client is None or getattr(client, "im", None) is None:
        error = "Lark API client is unavailable"
        logger.warning(f"Failed to send {label}: {error}")
        return LarkSendAttempt(success=False, retryable=False, error=error)

    try:
        from lark_oapi.api.im.v1 import (
            CreateMessageRequest,
            CreateMessageRequestBody,
            ReplyMessageRequest,
            ReplyMessageRequestBody,
        )
    except Exception as exc:
        error = f"lark_oapi is unavailable: {exc}"
        logger.warning(f"Failed to send {label}: {error}")
        return LarkSendAttempt(success=False, retryable=True, error=error)

    text_len = sum(
        len(component.text)
        for component in components
        if isinstance(component, Plain) and component.text
    )
    if text_len > LARK_TEXT_CHUNK_SIZE:
        error = "Lark post text is too long"
        logger.warning(f"Failed to send {label}: {error}")
        return LarkSendAttempt(success=False, retryable=True, error=error)

    try:
        content_lines: list[list[dict]] = []
        for component in components:
            if isinstance(component, Plain) and component.text:
                for line in component.text.strip().splitlines():
                    _lark_post_append_text_line(content_lines, line)
                continue
            if isinstance(component, Image):
                image_path = _local_image_path(component)
                if image_path is None:
                    error = "Lark post image is not a local file"
                    logger.warning(f"Failed to send {label}: {error}")
                    return LarkSendAttempt(
                        success=False, retryable=True, error=error
                    )
                image_key = await _upload_lark_image(client, image_path, label)
                content_lines.append([{"tag": "img", "image_key": image_key}])

        if not content_lines:
            return LarkSendAttempt(success=True)

        content = json.dumps(
            {
                "zh_cn": {
                    "title": _lark_post_title(title),
                    "content": content_lines,
                }
            },
            ensure_ascii=False,
        )
        if reply_message_id:
            request = (
                ReplyMessageRequest.builder()
                .message_id(reply_message_id)
                .request_body(
                    ReplyMessageRequestBody.builder()
                    .content(content)
                    .msg_type("post")
                    .build()
                )
                .build()
            )
            response = await client.im.v1.message.areply(request)
        else:
            if not receive_id or not receive_id_type:
                error = "Lark receive_id or receive_id_type is missing"
                logger.warning(f"Failed to send {label}: {error}")
                return LarkSendAttempt(success=False, retryable=True, error=error)
            request = (
                CreateMessageRequest.builder()
                .receive_id_type(receive_id_type)
                .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(receive_id)
                    .msg_type("post")
                    .content(content)
                    .build()
                )
                .build()
            )
            response = await client.im.v1.message.acreate(request)

        if not response.success():
            error = (
                f"Lark API returned {getattr(response, 'code', '')}: "
                f"{getattr(response, 'msg', '')}"
            )
            logger.warning(f"Failed to send {label}: {error}")
            return LarkSendAttempt(success=False, retryable=True, error=error)
    except Exception as exc:
        error = str(exc)
        if is_uncertain_delivery_error(exc):
            target = receive_id or reply_message_id or receive_id_type or "unknown"
            log_uncertain_delivery(label, target, exc)
            return LarkSendAttempt(
                success=False,
                retryable=False,
                uncertain=True,
                error=error,
                warning=uncertain_delivery_warning,
            )
        logger.warning(f"Failed to send {label}: {error}")
        return LarkSendAttempt(success=False, retryable=True, error=error)

    return LarkSendAttempt(success=True)


async def send_lark_event_media_with_retry(
    event,
    components: list,
    label: str,
    send_event_chain,
):
    async def send_chain(chain: MessageChain, send_label: str):
        return await send_event_chain(event, chain, send_label)

    return await send_media_with_video_retry(
        components,
        label,
        send_chain,
        "[NitterTweets] sent media without video/GIF attachments after initial failure",
    )


async def send_lark_umo_media_with_retry(
    context,
    umo: str,
    components: list,
    label: str,
    send_context_message,
):
    async def send_chain(chain: MessageChain, send_label: str):
        return await send_context_message(context, umo, chain, send_label)

    return await send_media_with_video_retry(
        components,
        label,
        send_chain,
        f"[NitterTweets] sent media to {umo} without video/GIF attachments "
        "after initial failure",
    )


async def send_media_with_video_retry(
    components: list,
    label: str,
    send_chain,
    retry_success_log: str,
):
    if not components:
        return LarkSendAttempt(success=True)

    attempt = await send_chain(MessageChain(components), label)
    if attempt.success or not attempt.retryable:
        return attempt

    without_videos = [
        component for component in components if not isinstance(component, Video)
    ]
    if len(without_videos) == len(components):
        return attempt
    if not without_videos:
        logger.warning("[NitterTweets] 媒体附件发送失败，全部为视频/GIF，标记为不确定")
        return LarkSendAttempt(
            success=False,
            retryable=False,
            uncertain=True,
            error=attempt.error,
            warning="视频/GIF 附件发送状态不确定，已跳过降级重试。",
        )

    retry_attempt = await send_chain(
        MessageChain(without_videos), f"{label} without videos"
    )
    if retry_attempt.success:
        logger.warning(retry_success_log)
        return LarkSendAttempt(success=True, error=attempt.error)
    return retry_attempt


async def send_lark_text(
    client,
    text: str,
    label: str,
    *,
    is_uncertain_delivery_error,
    log_uncertain_delivery,
    uncertain_delivery_warning: str,
    reply_message_id: str | None = None,
    receive_id: str | None = None,
    receive_id_type: str | None = None,
) -> LarkSendAttempt:
    text = (text or "").strip()
    if not text:
        return LarkSendAttempt(success=True)
    if client is None or getattr(client, "im", None) is None:
        error = "Lark API client is unavailable"
        logger.warning(f"Failed to send {label}: {error}")
        return LarkSendAttempt(success=False, retryable=False, error=error)

    try:
        from lark_oapi.api.im.v1 import (
            CreateMessageRequest,
            CreateMessageRequestBody,
            ReplyMessageRequest,
            ReplyMessageRequestBody,
        )
    except Exception as exc:
        error = f"lark_oapi is unavailable: {exc}"
        logger.warning(f"Failed to send {label}: {error}")
        return LarkSendAttempt(success=False, retryable=True, error=error)

    try:
        for chunk in split_lark_text(text):
            content = json.dumps({"text": chunk}, ensure_ascii=False)
            if reply_message_id:
                request = (
                    ReplyMessageRequest.builder()
                    .message_id(reply_message_id)
                    .request_body(
                        ReplyMessageRequestBody.builder()
                        .content(content)
                        .msg_type("text")
                        .build()
                    )
                    .build()
                )
                response = await client.im.v1.message.areply(request)
            else:
                if not receive_id or not receive_id_type:
                    error = "Lark receive_id or receive_id_type is missing"
                    logger.warning(f"Failed to send {label}: {error}")
                    return LarkSendAttempt(
                        success=False, retryable=True, error=error
                    )
                request = (
                    CreateMessageRequest.builder()
                    .receive_id_type(receive_id_type)
                    .request_body(
                        CreateMessageRequestBody.builder()
                        .receive_id(receive_id)
                        .msg_type("text")
                        .content(content)
                        .build()
                    )
                    .build()
                )
                response = await client.im.v1.message.acreate(request)

            if not response.success():
                error = (
                    f"Lark API returned {getattr(response, 'code', '')}: "
                    f"{getattr(response, 'msg', '')}"
                )
                logger.warning(f"Failed to send {label}: {error}")
                return LarkSendAttempt(success=False, retryable=True, error=error)
    except Exception as exc:
        error = str(exc)
        if is_uncertain_delivery_error(exc):
            target = receive_id or reply_message_id or receive_id_type or "unknown"
            log_uncertain_delivery(label, target, exc)
            return LarkSendAttempt(
                success=False,
                retryable=False,
                uncertain=True,
                error=error,
                warning=uncertain_delivery_warning,
            )
        logger.warning(f"Failed to send {label}: {error}")
        return LarkSendAttempt(success=False, retryable=True, error=error)

    return LarkSendAttempt(success=True)
