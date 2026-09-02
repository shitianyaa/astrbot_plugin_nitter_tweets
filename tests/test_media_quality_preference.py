"""media_quality 三档选档测试。

high=候选最高分辨率、low=候选最低、medium=候选中位数档（偶数取偏低档）。
三档按候选内排序选档，不依赖宽高→p 换算，绕过横竖屏判定。
"""

from __future__ import annotations

from media_support.service import MediaService
from media_support.xdown import XdownMediaCandidate
from shared import TweetItem

TWEET = TweetItem(text="", link="https://x.com/u/status/1", published="")


def _service(media_quality: str) -> MediaService:
    service = object.__new__(MediaService)
    service.media_quality = media_quality
    service.max_video_duration_seconds = 480
    # 候选都带时长，不会触发真实探测；兜底返回 None 表示探测不到。
    service._probe_remote_media = lambda _url, *, need_duration=True: None  # type: ignore[method-assign]
    return service


def _candidate(resolution: int, duration: float = 60.0) -> XdownMediaCandidate:
    return XdownMediaCandidate(
        kind="video",
        url=f"https://x.com/u/status/1/vid/{resolution}",
        label=f"下载 MP4 ({resolution}p)",
        resolution=resolution,
        duration_seconds=duration,
    )


def _select(
    media_quality: str, candidates: list[XdownMediaCandidate]
) -> XdownMediaCandidate | None:
    service = _service(media_quality)
    allowed = service._filter_video_duration_candidates(TWEET, candidates)
    return service._select_video_candidate(TWEET, allowed)


def test_high_selects_highest_resolution():
    selected = _select("high", [_candidate(360), _candidate(720), _candidate(2160)])
    assert selected is not None
    assert selected.resolution == 2160


def test_low_selects_lowest_resolution():
    selected = _select("low", [_candidate(360), _candidate(720), _candidate(2160)])
    assert selected is not None
    assert selected.resolution == 360


def test_medium_odd_count_picks_middle():
    selected = _select("medium", [_candidate(360), _candidate(720), _candidate(2160)])
    assert selected is not None
    assert selected.resolution == 720


def test_medium_even_count_picks_lower_median():
    selected = _select(
        "medium", [_candidate(270), _candidate(360), _candidate(720), _candidate(1080)]
    )
    assert selected is not None
    assert selected.resolution == 360  # 4 档偏低中位 idx1


def test_medium_two_candidates_picks_lower():
    selected = _select("medium", [_candidate(720), _candidate(1080)])
    assert selected is not None
    assert selected.resolution == 720  # 2 档偏低 idx0


def test_unknown_resolution_returns_first_candidate():
    service = _service("high")
    candidates = [
        XdownMediaCandidate(
            kind="video", url="u1", label="x", resolution=None, duration_seconds=60
        ),
        XdownMediaCandidate(
            kind="video", url="u2", label="y", resolution=None, duration_seconds=60
        ),
    ]
    allowed = service._filter_video_duration_candidates(TWEET, candidates)
    selected = service._select_video_candidate(TWEET, allowed)
    assert selected is not None
    assert selected.url == "u1"


def test_unrecognized_quality_falls_back_to_highest():
    # _select_video_candidate 的 else 分支 = max，等价 high 行为。
    selected = _select("garbage", [_candidate(360), _candidate(2160)])
    assert selected is not None
    assert selected.resolution == 2160
