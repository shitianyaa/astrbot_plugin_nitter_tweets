from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class SendAttempt:
    success: bool
    retryable: bool = False
    uncertain: bool = False
    #: 目标平台事实上拒收了这份内容，重发同样的字节不会有不同结果。
    #: 与 retryable=True 一起返回；消费方按 rejected 分支决定是否换字节重发，
    #: 不再靠 retryable=False 截断有损降级链。
    rejected: bool = False
    error: str = ""
    warning: str = ""


@dataclass(slots=True)
class SendOutcome:
    success: bool
    error: str = ""
    warning: str = ""
    delivery_status: str = "success"
    delivery_error: str = ""
    delivered_status_ids: tuple[str, ...] = ()


@dataclass(slots=True)
class MergedSendOutcome:
    success: bool
    mode: str
    omitted_videos: int = 0
    error: str = ""
    warning: str = ""
    delivery_status: str = "success"
    delivery_error: str = ""
    delivered_status_ids: tuple[str, ...] = ()
