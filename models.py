from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse


@dataclass(slots=True)
class TweetMedia:
    kind: str
    url: str
    path: Path | None = None

    @property
    def is_image(self) -> bool:
        return self.kind == "image"

    @property
    def is_video(self) -> bool:
        return self.kind in {"video", "dynamic"}


@dataclass(slots=True)
class TweetItem:
    text: str
    link: str
    published: str
    media: list[TweetMedia] = field(default_factory=list)
    translation: str = ""
    image_caption: str = ""
    ai_comment: str = ""

    @property
    def status_id(self) -> str:
        if match := re.search(r"/status(?:es)?/(\d+)", self.link):
            return match.group(1)
        return ""

    @property
    def username(self) -> str:
        path_parts = [part for part in urlparse(self.link).path.split("/") if part]
        if len(path_parts) >= 2 and path_parts[1] in {"status", "statuses"}:
            return path_parts[0].lstrip("@")
        return ""

    @property
    def x_url(self) -> str:
        if self.username and self.status_id:
            return f"https://x.com/{self.username}/status/{self.status_id}"
        return self.link
