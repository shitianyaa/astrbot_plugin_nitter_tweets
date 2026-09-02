"""media_quality must reach the status route (Fx/Vx/Syndication), not just HTML/xdown."""

from __future__ import annotations

import pytest

from media_support.status_resolve import _apply_image_quality
from shared.utils import TweetItem, TweetMedia


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
