"""
快速测试 yt-dlp 对 Twitter 视频的解析能力

结论：yt-dlp 访问 Twitter 视频 **必须提供 Cookies**，
否则会返回 "No video could be found in this tweet"。
这与 astrbot_plugin_parser 中使用 cookiefile 的做法一致。
"""
import yt_dlp

test_urls = [
    "https://twitter.com/SpaceX/status/1790844183328841728",
    "https://x.com/elonmusk/status/1829223953108967650",
    "https://twitter.com/BillGates/status/1756739082318033198",
]

# 无 Cookie 测试
print("=" * 50)
print("测试 1: 无 Cookie（预期失败）")
print("=" * 50)
opts_no_cookie = {"quiet": True, "skip_download": True}

for url in test_urls:
    print(f"  {url}")
    try:
        with yt_dlp.YoutubeDL(opts_no_cookie) as ydl:
            info = ydl.extract_info(url, download=False)
            if info:
                print(f"    OK 标题: {info.get('title', 'N/A')[:50]}")
                print(f"    时长: {info.get('duration', 'N/A')}秒")
                break
            else:
                print("    FAIL 无数据")
    except Exception as e:
        err_msg = str(e)
        if "No video" in err_msg:
            print("    FAIL: 需要认证")
        else:
            print(f"    FAIL: {err_msg[:80]}")

# 带 Cookie 测试（如果存在）
import os  # noqa: E402
from pathlib import Path  # noqa: E402

cookie_paths = [
    Path("cookies.txt"),
    Path("twitter_cookies.txt"),
    Path(os.path.expanduser("~/cookies.txt")),
]

found_cookie = None
for cp in cookie_paths:
    if cp.exists():
        found_cookie = cp
        break

print()
print("=" * 50)
if found_cookie:
    print(f"测试 2: 使用 Cookie 文件 ({found_cookie})")
    print("=" * 50)
    opts_with_cookie = {
        "quiet": True,
        "skip_download": True,
        "cookiefile": str(found_cookie),
    }
    for url in test_urls:
        print(f"  {url}")
        try:
            with yt_dlp.YoutubeDL(opts_with_cookie) as ydl:
                info = ydl.extract_info(url, download=False)
                if info:
                    dur = info.get("duration", "N/A")
                    title = info.get("title", "N/A")[:50]
                    fmt_count = len(info.get("formats", []))
                    print(f"    OK 标题: {title}")
                    print(f"    时长: {dur}秒, 格式数: {fmt_count}")
                    break
                else:
                    print("    FAIL 无数据")
        except Exception as e:
            print(f"    FAIL: {str(e)[:80]}")
else:
    print("测试 2: 未找到 Cookie 文件，跳过")
    print("=" * 50)
    print("  需要在项目根目录放置 cookies.txt")
    print("  可以用浏览器插件导出 Netscape 格式的 Cookie 文件")

print()
print("=" * 50)
print("结论")
print("=" * 50)
print("""
yt-dlp 访问 Twitter 视频必须提供认证 Cookies。
这与 astrbot_plugin_parser 中的做法一致：
  - parser 的 ytdlp_download_video() 支持 cookiefile 参数
  - 需要用户在配置中提供 Cookie 文件路径

实现建议：
  1. 在 _conf_schema.json 中添加 ytdlp_cookiefile 配置项
  2. 用户需自行导出 Twitter Cookie 文件
  3. 将 cookiefile 路径传递给 yt-dlp
  4. 如果未配置 Cookie，回退到 xdown.app 方案
""")
