"""media_quality contracts across HTML, status, and xdown media routes."""

from __future__ import annotations

import pytest

from media_support.html_backend.parser import prefer_pbs_quality
from media_support.service import MediaService
from media_support.status_resolve import _apply_image_quality
from media_support.xdown import XdownMediaCandidate
from shared import TweetItem
from shared.utils import TweetMedia

PBS = "https://pbs.twimg.com/media/Gx1b48AJecgip5fZ.jpg"


def test_high_uses_orig():
    assert "name=orig" in prefer_pbs_quality(PBS, "high")


def test_medium_uses_large():
    assert "name=large" in prefer_pbs_quality(PBS, "medium")


def test_low_uses_small():
    assert "name=small" in prefer_pbs_quality(PBS, "low")


def test_default_quality_is_high():
    assert "name=orig" in prefer_pbs_quality(PBS)


def test_rewrites_existing_name_param():
    url = "https://pbs.twimg.com/media/Gx1.jpg?name=small&format=jpg"
    assert prefer_pbs_quality(url, "high") == (
        "https://pbs.twimg.com/media/Gx1.jpg?name=orig&format=jpg"
    )


def test_non_pbs_url_unchanged():
    url = "https://video.twimg.com/amplify_video/x/vid/avc1/720x1280/y.mp4?tag=29"
    assert prefer_pbs_quality(url, "high") == url


def test_profile_images_not_rewritten():
    url = "https://pbs.twimg.com/profile_images/123/x.jpg"
    assert prefer_pbs_quality(url, "high") == url


def test_unknown_quality_falls_back_to_orig():
    assert "name=orig" in prefer_pbs_quality(PBS, "garbage")


def _tweet(*media: TweetMedia) -> TweetItem:
    tweet = TweetItem(
        text="hi",
        link="https://x.com/nasa/status/1",
        published="",
    )
    tweet.media = list(media)
    return tweet


ORIG = "https://pbs.twimg.com/media/Fabc123.jpg?name=orig"


@pytest.mark.parametrize(
    ("quality", "expected"),
    [
        ("high", "name=orig"),
        ("medium", "name=large"),
        ("low", "name=small"),
    ],
)
def test_image_quality_tier_applied(quality, expected):
    tweet = _tweet(TweetMedia(kind="image", url=ORIG))
    _apply_image_quality(tweet, quality)
    assert expected in tweet.media[0].url


def test_unknown_quality_falls_back_to_high():
    tweet = _tweet(TweetMedia(kind="image", url=ORIG))
    _apply_image_quality(tweet, "ultra")
    assert "name=orig" in tweet.media[0].url


def test_image_without_name_param_gets_one():
    tweet = _tweet(TweetMedia(kind="image", url="https://pbs.twimg.com/media/Fabc.jpg"))
    _apply_image_quality(tweet, "low")
    assert tweet.media[0].url.endswith("?name=small")


def test_video_url_untouched():
    # 视频档位由 xdown 的多分辨率候选决定，pbs 改写只针对图片。
    video = "https://video.twimg.com/amplify_video/1/vid/avc1/720x1280/x.mp4?tag=29"
    tweet = _tweet(TweetMedia(kind="video", url=video))
    _apply_image_quality(tweet, "low")
    assert tweet.media[0].url == video


def test_non_pbs_image_untouched():
    url = "https://example.com/pic/media/abc.jpg"
    tweet = _tweet(TweetMedia(kind="image", url=url))
    _apply_image_quality(tweet, "low")
    assert tweet.media[0].url == url


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
