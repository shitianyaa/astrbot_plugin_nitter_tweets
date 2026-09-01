"""media cache file naming: clean suffixes against encoded/dirty URL tails."""

from __future__ import annotations

from shared.utils import generate_file_name

# 真实事故样本：nitter /video/ 代理 URL 把 twimg 直链（含 ?tag=29）百分号编码
# 塞在 path 里；naive 的 Path().suffix 曾把 ".mp4%3Ftag%3D29" 整个当成扩展名，
# NapCat 收到 file:// 路径做 URI 解码后文件名对不上磁盘文件 → ENOENT 1200。
NITTER_PROXY_VIDEO = (
    "http://nitter:8080/video/C26BBB8DC1653/"
    "https%3A%2F%2Fvideo.twimg.com%2Famplify_video%2F2094778591859146752"
    "%2Fvid%2Favc1%2F704x1280%2F573FQmGXgTmD3FuT.mp4%3Ftag%3D29"
)


def test_proxy_video_url_keeps_clean_mp4_name():
    name = generate_file_name(NITTER_PROXY_VIDEO, ".mp4")
    # md5 前缀由完整 URL 决定；后缀必须是干净的 .mp4
    assert name == "d574b203470fc4db.mp4"
    assert "?" not in name and "%" not in name and "=" not in name


def test_plain_url_extension_kept():
    name = generate_file_name("https://video.twimg.com/a/b.mp4?tag=29", ".mp4")
    assert name.endswith(".mp4") and "?" not in name


def test_query_format_without_path_extension():
    name = generate_file_name("https://example.com/dl?id=1&format=gif", ".jpg")
    assert name.endswith(".gif")


def test_dirty_query_format_falls_back_to_default():
    name = generate_file_name(
        "https://example.com/dl?id=1&format=mp4%3Ftag%3D29", ".mp4"
    )
    assert name.endswith(".mp4") and "?" not in name and "%" not in name


def test_no_extension_falls_back_to_default():
    name = generate_file_name("https://example.com/m", ".jpg")
    assert name.endswith(".jpg")
