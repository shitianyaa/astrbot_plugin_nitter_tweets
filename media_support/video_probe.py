from __future__ import annotations

import base64
import json
import re
from urllib.parse import parse_qs, urlparse


def parse_resolution_preference(value: str) -> int | None:
    match = re.search(r"(\d{3,4})\s*p?", str(value or "").lower())
    if not match:
        return None
    return int(match.group(1))


def extract_video_resolution(label: str, url: str) -> int | None:
    text_parts = [label or "", url or ""]
    token_payload = xdown_token_payload(url)
    if token_payload:
        text_parts.extend(
            [
                str(token_payload.get("filename") or ""),
                str(token_payload.get("url") or ""),
            ]
        )
    text = " ".join(text_parts)

    p_matches = [int(value) for value in re.findall(r"(?i)(\d{3,4})\s*p\b", text)]
    if p_matches:
        return max(p_matches)

    size_matches = [
        max(int(width), int(height))
        for width, height in re.findall(r"(?i)(\d{3,4})x(\d{3,4})", text)
    ]
    if size_matches:
        return max(size_matches)
    return None


def extract_video_duration(label: str, url: str) -> float | None:
    token_payload = xdown_token_payload(url)
    duration = duration_from_mapping(token_payload)
    if duration is not None:
        return duration

    text = " ".join(
        [
            label or "",
            url or "",
            str(token_payload.get("filename") or ""),
            str(token_payload.get("url") or ""),
        ]
    )
    return duration_from_text(text)


def duration_from_mapping(data: dict) -> float | None:
    for key in (
        "duration",
        "duration_seconds",
        "durationSeconds",
        "length",
        "length_seconds",
    ):
        duration = coerce_duration_seconds(data.get(key))
        if duration is not None:
            return duration
    return None


def duration_from_text(text: str) -> float | None:
    text = str(text or "")
    for match in re.finditer(r"(?<!\d)(\d{1,2}):(\d{2})(?::(\d{2}))?(?!\d)", text):
        parts = [int(value) for value in match.groups(default="0")]
        if match.group(3) is None:
            minutes, seconds = parts[0], parts[1]
            return float(minutes * 60 + seconds)
        hours, minutes, seconds = parts
        return float(hours * 3600 + minutes * 60 + seconds)

    match = re.search(
        r"(?i)(\d+(?:\.\d+)?)\s*(seconds?|secs?|s|minutes?|mins?|m)\b",
        text,
    )
    if not match:
        return None
    value = float(match.group(1))
    unit = match.group(2).lower()
    if unit.startswith("m") and unit != "ms":
        return value * 60
    return value


def coerce_duration_seconds(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if number > 0 else None
    text = str(value).strip()
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return duration_from_text(text)
    return number if number > 0 else None


def probe_mp4_duration(data: bytes) -> float | None:
    if not data:
        return None
    return find_mp4_duration(data, 0, len(data))


def find_mp4_duration(data: bytes, start: int, end: int) -> float | None:
    offset = start
    container_types = {b"moov", b"trak", b"mdia"}
    while offset + 8 <= end:
        size = int.from_bytes(data[offset : offset + 4], "big")
        box_type = data[offset + 4 : offset + 8]
        header_size = 8
        if size == 1 and offset + 16 <= end:
            size = int.from_bytes(data[offset + 8 : offset + 16], "big")
            header_size = 16
        elif size == 0:
            size = end - offset
        if size < header_size or offset + size > end:
            break

        box_start = offset + header_size
        box_end = offset + size
        if box_type == b"mvhd":
            return parse_mvhd_duration(data[box_start:box_end])
        if box_type in container_types:
            duration = find_mp4_duration(data, box_start, box_end)
            if duration is not None:
                return duration
        offset += size
    return None


def parse_mvhd_duration(payload: bytes) -> float | None:
    if len(payload) < 20:
        return None
    version = payload[0]
    if version == 0:
        if len(payload) < 20:
            return None
        timescale = int.from_bytes(payload[12:16], "big")
        duration = int.from_bytes(payload[16:20], "big")
    elif version == 1:
        if len(payload) < 32:
            return None
        timescale = int.from_bytes(payload[20:24], "big")
        duration = int.from_bytes(payload[24:32], "big")
    else:
        return None
    if timescale <= 0 or duration <= 0:
        return None
    return duration / timescale


def xdown_token_payload(url: str) -> dict:
    token = (parse_qs(urlparse(url).query).get("token") or [""])[0]
    if not token:
        return {}
    parts = token.split(".")
    if len(parts) < 2:
        return {}
    payload = parts[1]
    padding = "=" * (-len(payload) % 4)
    try:
        decoded = base64.urlsafe_b64decode((payload + padding).encode("ascii"))
        data = json.loads(decoded.decode("utf-8", errors="replace"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}
