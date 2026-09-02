"""prefer_pbs_quality 三档画质改写测试。

high=name=orig、medium=name=large、low=name=small；非 pbs.twimg.com/media/ 的 URL 不变。
"""

from __future__ import annotations

from media_support.html_backend.parser import prefer_pbs_quality

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
