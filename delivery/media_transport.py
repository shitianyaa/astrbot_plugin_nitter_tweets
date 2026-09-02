"""媒体传输编码：把已下载的本地媒体按不同线上编码交给平台。

插件原本只有一种形态——本地文件路径。这隐含假设 AstrBot 与协议端
（NapCat / LLOneBot / Lagrange）共享文件系统；分容器或分机器部署时后端读不到该路径，
媒体必然失败并落进有损的内容降级链（去视频 → 纯文本），图和视频一起丢。

本模块提供一条正交的、**无损的**传输编码降级轴：同一份媒体换一种线上编码重试，
在动用任何有损降级之前先穷尽它。

只有 OneBot 适配器启用。其余平台在 AstrBot 进程内从本地路径上传，
Lark 甚至会把组件反解回 ``Path`` 再自己读字节（``delivery/lark_support.py``），
换成 base64 会直接打断它，而它们本就不存在跨进程读不到文件的问题。
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

try:
    from ..config import resolve_media_transport_base64_max_mb
    from ..media_support.network import is_safe_http_url
    from ..shared import file_uri
except ImportError:  # pragma: no cover - flat import fallback
    from config import resolve_media_transport_base64_max_mb
    from media_support.network import is_safe_http_url
    from shared import file_uri


class MediaEncoding:
    """一次媒体投递可用的线上编码。"""

    PATH = "path"
    BASE64 = "base64"
    URL = "url"
    # 仅视频：放弃附件，改发既有的「视频未发送」提示。
    SKIP = "skip"


#: 未启用传输层的适配器恒用这个梯度，等价于改动前的行为。
PATH_ONLY_LADDER: tuple[str, ...] = (MediaEncoding.PATH,)

TRANSPORT_MODES = ("auto", "path_only", "base64_first")

#: 允许交给协议端自行下载的主机。xdown.app 直链带 token、时效短且对 Referer 敏感
#: （见 ``media_support/service.py`` 的 ``_media_request_headers``），不交给后端。
BACKEND_FETCHABLE_HOSTS = ("video.twimg.com", "pbs.twimg.com")

#: base64 会把整个合并转发节点数组撑成一份 JSON 文档。合计超过这个预算就不提供
#: base64 档，交给既有的分块 / 二分机制处理，不在这里新写切分逻辑。
FORWARD_BASE64_BUDGET_BYTES = 24 * 1024 * 1024


def media_size_bytes(media) -> int | None:
    """已下载媒体的字节数；路径缺失或不可读时返回 ``None``。"""
    path = getattr(media, "path", None)
    if not path:
        return None
    try:
        return Path(path).stat().st_size
    except OSError:
        return None


def size_bucket(size: int | None) -> str:
    """粗粒度体积档位，用于结构化日志（避免逐条输出精确字节抖动）。"""
    if size is None:
        return "unknown"
    megabytes = size / (1024 * 1024)
    for limit, label in ((1, "<1MB"), (4, "1-4MB"), (8, "4-8MB"), (16, "8-16MB")):
        if megabytes < limit:
            return label
    return "16MB+" if megabytes < 32 else "32MB+"


def is_backend_fetchable_url(url) -> bool:
    """URL 是否可以直接交给协议端自行下载。"""
    text = str(url or "").strip()
    if not text or not is_safe_http_url(text):
        return False
    host = (urlparse(text).hostname or "").lower().rstrip(".")
    return any(
        host == allowed or host.endswith(f".{allowed}")
        for allowed in BACKEND_FETCHABLE_HOSTS
    )


def read_base64_payload(path) -> str:
    """读取缓存文件并返回 OneBot ``base64://`` 值。调用方负责放到线程里执行。"""
    data = Path(path).read_bytes()
    if not data:
        raise ValueError("empty media file")
    return "base64://" + base64.b64encode(data).decode("ascii")


def onebot_segment(media, encoding: str, base64_value: str = "") -> dict | None:
    """构造一个 OneBot 原始消息段；该编码无法表达时返回 ``None``。"""
    segment_type = "image" if getattr(media, "is_image", False) else "video"
    if encoding == MediaEncoding.PATH:
        path = getattr(media, "path", None)
        if not path:
            return None
        file_value = file_uri(Path(path))
    elif encoding == MediaEncoding.BASE64:
        if not base64_value:
            return None
        file_value = base64_value
    elif encoding == MediaEncoding.URL:
        file_value = str(getattr(media, "url", "") or "")
        if not file_value:
            return None
    else:
        return None
    return {"type": segment_type, "data": {"file": file_value}}


@dataclass(frozen=True, slots=True)
class TransportConfig:
    mode: str = "auto"
    base64_max_bytes: int = 8 * 1024 * 1024
    url_fallback: bool = True

    @classmethod
    def from_config(cls, config) -> TransportConfig:
        max_mb = resolve_media_transport_base64_max_mb(config)
        return cls(
            mode="auto",
            base64_max_bytes=int(max_mb * 1024 * 1024),
            url_fallback=True,
        )


class MediaTransportPolicy:
    """按媒体类型、体积和配置决定一条降级梯度。"""

    def __init__(self, config: TransportConfig | None = None):
        self.config = config or TransportConfig()

    def ladder_for(
        self,
        media,
        *,
        allow_base64: bool = True,
        allow_skip: bool = True,
    ) -> tuple[str, ...]:
        """返回按尝试顺序排列的编码档。

        ``allow_base64=False`` 供合并转发在合计体积超预算时压制 base64 档。
        ``allow_skip=False`` 供调用方自己承接失败（如已有内容降级会接手）。
        """
        if self.config.mode == "path_only":
            return PATH_ONLY_LADDER

        base64_ok = allow_base64 and self._base64_allowed(media)
        if self.config.mode == "base64_first" and base64_ok:
            steps = [MediaEncoding.BASE64, MediaEncoding.PATH]
        else:
            steps = [MediaEncoding.PATH]
            if base64_ok:
                steps.append(MediaEncoding.BASE64)

        if self._url_allowed(media):
            steps.append(MediaEncoding.URL)
        # 视频有既成的「未发送」提示可退；图片没有对应文案，失败交给内容降级链。
        if allow_skip and getattr(media, "is_video", False):
            steps.append(MediaEncoding.SKIP)
        return tuple(steps)

    def _base64_allowed(self, media) -> bool:
        # 同一个上限同时管住图片和视频：默认 8MB 天然把视频排除在 base64 之外，
        # 用户调高即表示明确接受更大的内存与 payload 开销。
        size = media_size_bytes(media)
        return size is not None and 0 < size <= self.config.base64_max_bytes

    def _url_allowed(self, media) -> bool:
        if not self.config.url_fallback:
            return False
        return is_backend_fetchable_url(getattr(media, "url", ""))

    def forward_allows_base64(
        self,
        tweets,
        *,
        budget: int = FORWARD_BASE64_BUDGET_BYTES,
    ) -> bool:
        """合并转发整份 payload 的 base64 体积是否还在预算内。"""
        if self.config.mode == "path_only":
            return False
        total = 0
        for tweet in tweets or ():
            for media in getattr(tweet, "media", ()) or ():
                size = media_size_bytes(media)
                if not size:
                    continue
                # base64 膨胀约 4/3。
                total += size + size // 3
                if total > budget:
                    return False
        return True


class TransportMemo:
    """记住每个平台最近一次成功的编码档，作为下次的起步提示。

    只是起步提示，不是限制：记住的档失败时仍会回落到更早的档，
    否则一次偶然的 base64 成功会永久放弃更省的路径档。
    """

    def __init__(self):
        self._entries: dict[tuple[str, str], str] = {}

    @staticmethod
    def _key(platform_id, media_kind) -> tuple[str, str]:
        return str(platform_id or ""), str(media_kind or "")

    def preferred(self, platform_id, media_kind) -> str:
        return self._entries.get(self._key(platform_id, media_kind), "")

    def record_success(self, platform_id, media_kind, encoding: str) -> None:
        # SKIP 不是投递成功，不记忆。
        if encoding in {MediaEncoding.PATH, MediaEncoding.BASE64, MediaEncoding.URL}:
            self._entries[self._key(platform_id, media_kind)] = encoding

    def forget(self, platform_id, media_kind) -> None:
        self._entries.pop(self._key(platform_id, media_kind), None)


def apply_memo(ladder: tuple[str, ...], preferred: str) -> tuple[str, ...]:
    """把记住的档提到最前，被它越过的档保留在其后继续作为兜底。"""
    if not preferred or preferred not in ladder:
        return ladder
    index = ladder.index(preferred)
    if index == 0:
        return ladder
    return (preferred, *ladder[:index], *ladder[index + 1 :])


def media_kind(media) -> str:
    return "video" if getattr(media, "is_video", False) else "image"


__all__ = [
    "BACKEND_FETCHABLE_HOSTS",
    "FORWARD_BASE64_BUDGET_BYTES",
    "PATH_ONLY_LADDER",
    "TRANSPORT_MODES",
    "MediaEncoding",
    "MediaTransportPolicy",
    "TransportConfig",
    "TransportMemo",
    "apply_memo",
    "is_backend_fetchable_url",
    "media_kind",
    "media_size_bytes",
    "onebot_segment",
    "read_base64_payload",
    "size_bucket",
]
