"""
yt-dlp 下载功能测试脚本
测试 Twitter 视频解析和下载是否正常工作
"""

import asyncio
import time
from pathlib import Path

# 测试用的 Twitter 视频 URL（公开推文）
TEST_URLS = [
    # NASA 的推文（通常包含视频）
    "https://twitter.com/NASA/status/1791157164961153024",
    # 短链接格式
    "https://x.com/NASA/status/1791157164961153024",
]


def check_dependencies():
    """检查依赖是否安装"""
    print("=" * 50)
    print("检查依赖...")
    print("=" * 50)
    
    results = {}
    
    # 检查 yt-dlp
    try:
        import yt_dlp
        results["yt-dlp"] = {"installed": True, "version": yt_dlp.version.__version__}
        print(f"✅ yt-dlp: {yt_dlp.version.__version__}")
    except ImportError:
        results["yt-dlp"] = {"installed": False}
        print("❌ yt-dlp: 未安装")
    
    # 检查 aiohttp
    try:
        import aiohttp
        results["aiohttp"] = {"installed": True, "version": aiohttp.__version__}
        print(f"✅ aiohttp: {aiohttp.__version__}")
    except ImportError:
        results["aiohttp"] = {"installed": False}
        print("❌ aiohttp: 未安装")
    
    # 检查 aiofiles
    try:
        import aiofiles  # noqa: F401
        results["aiofiles"] = {"installed": True}
        print("✅ aiofiles: 已安装")
    except ImportError:
        results["aiofiles"] = {"installed": False}
        print("❌ aiofiles: 未安装")
    
    # 检查 ffmpeg
    import subprocess
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            version_line = result.stdout.split('\n')[0]
            results["ffmpeg"] = {"installed": True, "version": version_line}
            print(f"✅ ffmpeg: {version_line}")
        else:
            results["ffmpeg"] = {"installed": False}
            print("❌ ffmpeg: 未正确安装")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        results["ffmpeg"] = {"installed": False}
        print("❌ ffmpeg: 未安装（音视频合并需要）")
    
    print("=" * 50)
    return results


def test_extract_info(url: str):
    """测试视频信息提取"""
    import yt_dlp
    
    print(f"\n{'=' * 50}")
    print("测试提取视频信息...")
    print(f"URL: {url}")
    print(f"{'=' * 50}")
    
    opts = {
        "quiet": True,
        "skip_download": True,
        "no_warnings": False,
    }
    
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            if info:
                print("✅ 提取成功!")
                print(f"   标题: {info.get('title', 'N/A')[:50]}...")
                print(f"   时长: {info.get('duration', 'N/A')} 秒")
                print(f"   上传者: {info.get('uploader', 'N/A')}")
                print(f"   格式: {info.get('format', 'N/A')}")
                
                # 检查可用格式
                formats = info.get('formats', [])
                if formats:
                    print(f"   可用格式数: {len(formats)}")
                    # 找出视频格式
                    video_formats = [f for f in formats if f.get('vcodec') != 'none']
                    audio_formats = [f for f in formats if f.get('acodec') != 'none' and f.get('vcodec') == 'none']
                    print(f"   视频格式: {len(video_formats)}")
                    print(f"   音频格式: {len(audio_formats)}")
                
                return info
            else:
                print("❌ 提取失败: 返回空数据")
                return None
                
    except Exception as e:
        print(f"❌ 提取失败: {type(e).__name__}: {e}")
        return None


def test_download_video(url: str, output_dir: Path):
    """测试视频下载"""
    import yt_dlp
    
    print(f"\n{'=' * 50}")
    print("测试下载视频...")
    print(f"URL: {url}")
    print(f"输出目录: {output_dir}")
    print(f"{'=' * 50}")
    
    output_dir.mkdir(parents=True, exist_ok=True)
    output_template = str(output_dir / "%(id)s.%(ext)s")
    
    opts = {
        "outtmpl": output_template,
        "merge_output_format": "mp4",
        "format": "best[height<=720]/best",  # 限制720p以加快测试
        "postprocessors": [
            {"key": "FFmpegVideoConvertor", "preferedformat": "mp4"}
        ],
        "quiet": False,
        "no_warnings": False,
        "progress_hooks": [lambda d: print_progress(d)],
    }
    
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            start_time = time.time()
            ydl.download([url])
            elapsed = time.time() - start_time
            
            # 查找下载的文件
            downloaded_files = list(output_dir.glob("*.mp4"))
            if downloaded_files:
                file_path = downloaded_files[0]
                file_size = file_path.stat().st_size / (1024 * 1024)  # MB
                print("\n✅ 下载成功!")
                print(f"   文件: {file_path.name}")
                print(f"   大小: {file_size:.2f} MB")
                print(f"   耗时: {elapsed:.2f} 秒")
                return file_path
            else:
                print("❌ 下载失败: 未找到输出文件")
                return None
                
    except Exception as e:
        print(f"❌ 下载失败: {type(e).__name__}: {e}")
        return None


def test_stream_download(url: str, output_dir: Path):
    """测试流式下载（不依赖 ffmpeg）"""
    import yt_dlp
    
    print(f"\n{'=' * 50}")
    print("测试流式下载（不合并）...")
    print(f"URL: {url}")
    print(f"{'=' * 50}")
    
    output_dir.mkdir(parents=True, exist_ok=True)
    output_template = str(output_dir / "%(id)s.%(ext)s")
    
    opts = {
        "outtmpl": output_template,
        "format": "best[ext=mp4]/best",  # 优先mp4格式，无需合并
        "quiet": False,
        "no_warnings": False,
        "progress_hooks": [lambda d: print_progress(d)],
    }
    
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            start_time = time.time()
            ydl.download([url])
            elapsed = time.time() - start_time
            
            # 查找下载的文件
            downloaded_files = list(output_dir.glob("*"))
            downloaded_files = [f for f in downloaded_files if f.is_file() and not f.name.endswith('.part')]
            
            if downloaded_files:
                file_path = downloaded_files[0]
                file_size = file_path.stat().st_size / (1024 * 1024)  # MB
                print("\n✅ 下载成功!")
                print(f"   文件: {file_path.name}")
                print(f"   大小: {file_size:.2f} MB")
                print(f"   耗时: {elapsed:.2f} 秒")
                return file_path
            else:
                print("❌ 下载失败: 未找到输出文件")
                return None
                
    except Exception as e:
        print(f"❌ 下载失败: {type(e).__name__}: {e}")
        return None


def print_progress(d):
    """打印下载进度"""
    if d['status'] == 'downloading':
        percent = d.get('_percent_str', 'N/A')
        speed = d.get('_speed_str', 'N/A')
        eta = d.get('_eta_str', 'N/A')
        print(f"\r   下载中: {percent} | 速度: {speed} | 剩余: {eta}   ", end='', flush=True)
    elif d['status'] == 'finished':
        print("\n   下载完成，处理中...")


def cleanup_test_files(output_dir: Path):
    """清理测试文件"""
    if output_dir.exists():
        for file in output_dir.iterdir():
            if file.is_file():
                file.unlink()
                print(f"   清理: {file.name}")
        output_dir.rmdir()
        print(f"   删除目录: {output_dir}")


async def main():
    """主测试函数"""
    print("\n" + "=" * 60)
    print("  yt-dlp Twitter 视频下载测试")
    print("=" * 60 + "\n")
    
    # 1. 检查依赖
    deps = check_dependencies()
    
    if not deps.get("yt-dlp", {}).get("installed"):
        print("\n❌ yt-dlp 未安装，请先运行: pip install yt-dlp")
        return
    
    # 2. 测试目录
    test_dir = Path(__file__).parent / "test_downloads"
    
    # 3. 选择测试 URL
    test_url = TEST_URLS[0]
    print(f"\n使用测试 URL: {test_url}")
    
    # 4. 测试信息提取
    info = test_extract_info(test_url)
    
    if info:
        # 5. 测试下载
        print("\n" + "-" * 50)
        print("选择下载测试模式:")
        print("1. 流式下载（推荐，不需要 ffmpeg）")
        print("2. 完整下载（需要 ffmpeg 合并音视频）")
        print("-" * 50)
        
        # 自动选择流式下载进行测试
        print("自动选择: 流式下载\n")
        result = test_stream_download(test_url, test_dir)
        
        if result:
            print(f"\n{'=' * 50}")
            print("✅ 所有测试通过！")
            print(f"{'=' * 50}")
            
            # 询问是否清理
            print(f"\n测试文件位置: {result}")
            print("测试完成，文件已保留供检查。")
        else:
            print(f"\n{'=' * 50}")
            print("❌ 下载测试失败")
            print(f"{'=' * 50}")
    else:
        print(f"\n{'=' * 50}")
        print("❌ 信息提取测试失败，跳过下载测试")
        print(f"{'=' * 50}")


if __name__ == "__main__":
    asyncio.run(main())
