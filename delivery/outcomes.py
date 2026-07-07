from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class SendAttempt:
    success: bool
    retryable: bool = False
    uncertain: bool = False
    error: str = ""
    warning: str = ""


@dataclass(slots=True)
class SendOutcome:
    success: bool
    error: str = ""
    warning: str = ""
    delivery_status: str = "success"
    delivery_error: str = ""


@dataclass(slots=True)
class MergedSendOutcome:
    success: bool
    mode: str
    omitted_videos: int = 0
    error: str = ""
    warning: str = ""
    delivery_status: str = "success"
    delivery_error: str = ""
