from __future__ import annotations

import argparse
import asyncio
import logging
import shutil
import sys
import types
from datetime import datetime
from pathlib import Path


DEFAULT_URL = "https://nitter.net/JuanEgg18/status/2064692617242448015#m"


def _install_astrbot_logger_stub() -> None:
    """Allow running the plugin media module outside AstrBot."""
    if "astrbot.api" in sys.modules:
        return

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s:%(name)s:%(message)s",
    )
    astrbot_module = types.ModuleType("astrbot")
    api_module = types.ModuleType("astrbot.api")
    api_module.logger = logging.getLogger("nitter-video-test")
    astrbot_module.api = api_module
    sys.modules.setdefault("astrbot", astrbot_module)
    sys.modules.setdefault("astrbot.api", api_module)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _import_plugin_modules():
    root = _repo_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    _install_astrbot_logger_stub()

    from media_support import MediaService
    from shared import TweetItem

    return MediaService, TweetItem


def _build_config(args: argparse.Namespace) -> dict:
    return {
        "send_image_attachments": args.images,
        "send_video_attachments": True,
        "max_media_per_tweet": args.max_media,
        "media_timeout": args.timeout,
        "media_max_size_mb": args.max_size_mb,
        "max_video_duration_minutes": args.max_duration_minutes,
        "xdown_api_url": args.xdown_url,
        "media_user_agent": args.user_agent,
        "video_resolution_preference": args.resolution,
    }


def _print_candidates(label: str, candidates) -> None:
    print(label)
    print(f"  count={len(candidates)}")
    if not candidates:
        print("  none")
        return
    for index, item in enumerate(candidates, start=1):
        resolution = f" resolution={item.resolution}p" if item.resolution else ""
        duration = (
            f" duration={item.duration_seconds:.1f}s"
            if item.duration_seconds is not None
            else ""
        )
        print(
            f"  {index}. kind={item.kind}{resolution}{duration} "
            f"label={item.label!r} url={item.url}"
        )


def _print_media(label: str, media_items) -> None:
    print(label)
    print(f"  count={len(media_items)}")
    if not media_items:
        print("  none")
        return
    for index, item in enumerate(media_items, start=1):
        duration = (
            f" duration={item.duration_seconds:.1f}s"
            if item.duration_seconds is not None
            else ""
        )
        print(f"  {index}. kind={item.kind}{duration} url={item.url}")
        if item.path:
            path = Path(item.path)
            size = path.stat().st_size if path.exists() else 0
            print(f"     path={path}")
            print(f"     size={size} bytes")


def _default_output_dir(tweet) -> Path:
    status_id = tweet.status_id or datetime.now().strftime("%Y%m%d-%H%M%S")
    return _repo_root() / "tests" / "downloads" / f"video_download_{status_id}"


def _copy_downloaded_media(tweet, output_dir: Path | None) -> Path:
    target_dir = output_dir or _default_output_dir(tweet)
    target_dir.mkdir(parents=True, exist_ok=True)

    copied = 0
    for index, item in enumerate(tweet.media, start=1):
        if not item.path:
            continue
        source = Path(item.path)
        if not source.exists():
            continue
        target = target_dir / f"{index:02d}_{item.kind}{source.suffix}"
        shutil.copy2(source, target)
        copied += 1
        print(f"copied={target} ({target.stat().st_size} bytes)")

    if copied == 0:
        print(f"copied=0 output_dir={target_dir}")
    else:
        print(f"output_dir={target_dir}")
    return target_dir


async def _run(args: argparse.Namespace) -> int:
    MediaService, TweetItem = _import_plugin_modules()

    tweet = TweetItem(
        text="video download test",
        link=args.url,
        published="",
    )
    service = MediaService(_build_config(args))

    print(f"source_url={tweet.link}")
    print(f"x_url={tweet.x_url}")
    print(f"cache_dir={service.cache_dir}")
    print(f"xdown_api={service.xdown_url}")
    print(f"resolution={service.video_resolution_preference}")
    print(f"max_video_duration={service.max_video_duration_seconds}s")

    try:
        candidates = await asyncio.to_thread(service._resolve_media_candidates, tweet)
    except Exception as exc:
        print(f"resolve_failed={type(exc).__name__}: {exc}")
        return 1

    _print_candidates("raw_candidates:", candidates)
    resolved = service._normalize_media_candidates(tweet, candidates)
    _print_media("filtered_media:", resolved)
    if args.resolve_only:
        return 0 if resolved else 1

    try:
        tweet.media = await service.resolve_and_download(tweet)
    except Exception as exc:
        print(f"download_failed={type(exc).__name__}: {exc}")
        return 1

    _print_media("downloaded_media:", tweet.media)
    _copy_downloaded_media(tweet, args.output_dir)
    if tweet.media_warnings:
        print("warnings:")
        for warning in tweet.media_warnings:
            print(f"  - {warning}")

    video_count = sum(1 for item in tweet.media if item.is_video and item.path)
    return 0 if video_count else 1


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Test the existing Nitter video resolve/download logic.",
    )
    parser.add_argument("url", nargs="?", default=DEFAULT_URL)
    parser.add_argument("--resolve-only", action="store_true")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Folder to copy downloaded media into.",
    )
    parser.add_argument("--images", action="store_true", help="Also download images.")
    parser.add_argument(
        "--resolution",
        default="highest",
        help="Video resolution preference: highest, lowest, 1280p, 852p, 568p, etc.",
    )
    parser.add_argument("--max-media", type=int, default=4)
    parser.add_argument(
        "--max-duration-minutes",
        type=float,
        default=8.0,
        help="Skip videos longer than this many minutes; range is clamped to 1-8.",
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--max-size-mb", type=float, default=100.0)
    parser.add_argument(
        "--xdown-url",
        default="https://xdown.app/api/ajaxSearch",
    )
    parser.add_argument(
        "--user-agent",
        default=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0 Safari/537.36"
        ),
    )
    return parser.parse_args()


def main() -> int:
    return asyncio.run(_run(_parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
