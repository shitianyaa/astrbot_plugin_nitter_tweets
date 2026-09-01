"""size 预检降级测试。

下载前 Range 探测 total，视频选中档超 media_max_size_mb 时降到下一低分辨率
档直到不超；都超则选最小档留给 _download 在线检查。size 未知（探测失败）不降级。
"""

from __future__ import annotations

from media_support.service import MediaService
from media_support.xdown import XdownMediaCandidate
from shared import TweetItem

TWEET = TweetItem(text="", link="https://x.com/u/status/1", published="")
MB = 1024 * 1024


def _service(max_bytes: int) -> MediaService:
    service = object.__new__(MediaService)
    service.media_quality = "high"
    service.max_video_duration_seconds = 480
    service.max_bytes = max_bytes
    service._probe_remote_media = lambda _url: None  # type: ignore[method-assign]
    return service


def _candidate(
    resolution: int, size_bytes: int | None, duration: float = 60.0
) -> XdownMediaCandidate:
    return XdownMediaCandidate(
        kind="video",
        url=f"https://x.com/u/status/1/vid/{resolution}",
        label=f"下载 MP4 ({resolution}p)",
        resolution=resolution,
        duration_seconds=duration,
        size_bytes=size_bytes,
    )


def _select(candidates: list[XdownMediaCandidate], max_bytes: int):
    service = _service(max_bytes)
    allowed = service._filter_video_duration_candidates(TWEET, candidates)
    return service._select_video_candidate(TWEET, allowed)


def test_high_downgrades_when_highest_exceeds_size_limit():
    cands = [
        _candidate(720, int(8.6 * MB)),
        _candidate(1080, int(31.1 * MB)),
        _candidate(2160, int(94.9 * MB)),
    ]
    selected = _select(cands, 25 * MB)
    assert selected is not None
    # high 本选 2160p(94.9MB)超限 → 降级到 720p(8.6MB，不超)
    assert selected.resolution == 720


def test_high_keeps_highest_when_under_limit():
    cands = [
        _candidate(720, int(8.6 * MB)),
        _candidate(2160, int(15 * MB)),
    ]
    selected = _select(cands, 25 * MB)
    assert selected is not None
    assert selected.resolution == 2160


def test_all_exceed_returns_smallest():
    cands = [
        _candidate(720, int(30 * MB)),
        _candidate(2160, int(94.9 * MB)),
    ]
    selected = _select(cands, 25 * MB)
    assert selected is not None
    # 都超限 → 选最小档(720p)，留给 _download 在线检查跳过
    assert selected.resolution == 720


def test_unknown_size_does_not_downgrade():
    cands = [
        _candidate(720, None),
        _candidate(2160, None),
    ]
    selected = _select(cands, 25 * MB)
    assert selected is not None
    # size 未知(探测失败)→ 保留选中档，不降级
    assert selected.resolution == 2160


def test_medium_picks_median_then_downgrades_if_oversized():
    cands = [
        _candidate(360, int(2 * MB)),
        _candidate(720, int(8.6 * MB)),
        _candidate(2160, int(94.9 * MB)),
    ]
    service = _service(25 * MB)
    service.media_quality = "medium"
    allowed = service._filter_video_duration_candidates(TWEET, cands)
    selected = service._select_video_candidate(TWEET, allowed)
    assert selected is not None
    # medium 中位 = 720p(8.6MB，不超)→ 保留
    assert selected.resolution == 720
