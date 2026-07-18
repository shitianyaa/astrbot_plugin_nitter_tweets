from __future__ import annotations

import argparse
import asyncio
import shutil
import sys
import tempfile
import types
from pathlib import Path
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SUPPORTED_PROXY_TYPES = {"http", "https", "socks5", "socks5h"}


def _configure_output_encoding() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


def _install_astrbot_logger_stub() -> None:
    if "astrbot.api" in sys.modules:
        return

    astrbot_module = types.ModuleType("astrbot")
    astrbot_api_module = types.ModuleType("astrbot.api")

    class _Logger:
        def info(self, *args, **kwargs):
            print("[info]", *args, file=sys.stderr)

        def warning(self, *args, **kwargs):
            print("[warning]", *args, file=sys.stderr)

        def debug(self, *args, **kwargs):
            pass

    astrbot_api_module.logger = _Logger()
    sys.modules.setdefault("astrbot", astrbot_module)
    sys.modules.setdefault("astrbot.api", astrbot_api_module)


def parse_proxy_url(value: str) -> dict:
    try:
        parsed = urlsplit(str(value or "").strip())
        port = parsed.port
    except ValueError as exc:
        raise argparse.ArgumentTypeError("代理地址或端口无效") from exc
    proxy_type = parsed.scheme.lower()
    if proxy_type not in SUPPORTED_PROXY_TYPES:
        raise argparse.ArgumentTypeError(
            "代理协议必须是 http、https、socks5 或 socks5h"
        )
    if not parsed.hostname or port is None:
        raise argparse.ArgumentTypeError("代理必须包含主机和端口")
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("代理端口必须在 1-65535 范围内")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise argparse.ArgumentTypeError("代理 URL 不能包含路径、查询参数或片段")
    username = unquote(parsed.username or "")
    password = unquote(parsed.password or "")
    if proxy_type in {"socks5", "socks5h"} and bool(username) != bool(password):
        raise argparse.ArgumentTypeError("SOCKS5 代理的用户名和密码必须同时提供")
    return {
        "__template_key": "proxy",
        "enabled": True,
        "type": proxy_type,
        "host": parsed.hostname,
        "port": port,
        "username": username,
        "password": password,
    }


def proxy_label(entry: dict) -> str:
    host = str(entry["host"])
    if ":" in host:
        host = f"[{host}]"
    return f"{entry['type']}://{host}:{entry['port']}"


def media_signature(path: Path) -> str:
    with path.open("rb") as file:
        head = file.read(32)
    if head.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        return "webp"
    if len(head) >= 12 and head[4:8] == b"ftyp":
        return "mp4"
    return "unknown"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Use one explicit proxy for Nitter RSS, xdown resolution, and media "
            "download. The proxy credentials are never printed."
        )
    )
    parser.add_argument(
        "proxy",
        type=parse_proxy_url,
        help=(
            "Proxy URL, for example socks5h://127.0.0.1:1080 or "
            "http://user:password@127.0.0.1:8080"
        ),
    )
    parser.add_argument("username", nargs="?", default="nasa")
    parser.add_argument("limit", nargs="?", type=int, default=1)
    parser.add_argument("--instance", default="https://nitter.net")
    parser.add_argument(
        "--include-plain-text",
        action="store_true",
        help="Do not require author-uploaded media in the selected RSS items.",
    )
    parser.add_argument("--timeout", type=float, default=25.0)
    parser.add_argument("--media-timeout", type=float, default=40.0)
    parser.add_argument("--max-size-mb", type=float, default=25.0)
    parser.add_argument("--retry-attempts", type=int, default=3)
    parser.add_argument("--retry-delay", type=float, default=5.0)
    parser.add_argument("--resolution", default="lowest")
    parser.add_argument(
        "--keep-dir",
        type=Path,
        default=None,
        help="Copy verified media to this directory before cleaning temporary files.",
    )
    return parser.parse_args()


def _build_config(args: argparse.Namespace) -> dict:
    return {
        "basic": {
            "instances": [args.instance],
            "request_timeout": args.timeout,
            "filter_reposts_enabled": True,
            "proxies": [args.proxy],
        },
        "media": {
            "send_image_attachments": True,
            "send_video_attachments": True,
            "max_media_per_tweet": 1,
            "media_timeout": args.media_timeout,
            "media_max_size_mb": args.max_size_mb,
            "media_retry_attempts": args.retry_attempts,
            "media_retry_delay_seconds": args.retry_delay,
            "video_resolution_preference": args.resolution,
        },
    }


def _copy_verified_media(tweets, destination: Path) -> int:
    destination.mkdir(parents=True, exist_ok=True)
    copied = 0
    for tweet in tweets:
        for index, media in enumerate(tweet.media, start=1):
            if media.path is None or not media.path.exists():
                continue
            suffix = media.path.suffix or (".mp4" if media.is_video else ".jpg")
            target = destination / f"{tweet.status_id}_{index}_{media.kind}{suffix}"
            shutil.copy2(media.path, target)
            copied += 1
            print(f"KEPT {target} bytes={target.stat().st_size}")
    return copied


async def _run(args: argparse.Namespace) -> int:
    _install_astrbot_logger_stub()
    import media_support.service as service_module
    from media_support import MediaService, NetworkClient, NitterClient

    config = _build_config(args)
    tweets = []
    with tempfile.TemporaryDirectory(prefix="nitter-proxy-probe-") as temp_name:
        original_data_dir = service_module._plugin_data_dir
        service_module._plugin_data_dir = lambda: Path(temp_name)
        try:
            network = NetworkClient(config)
            nitter = NitterClient(config, network=network)
            media = MediaService(config, network=network)
            instance, tweets = await nitter.fetch_tweets(
                args.username,
                max(1, args.limit),
                skip_plain_text=not args.include_plain_text,
            )
            await media.attach_media(tweets)

            print(f"PROXY {proxy_label(args.proxy)}")
            print(f"INSTANCE {instance}")
            print(f"COUNT {len(tweets)}")
            downloaded = 0
            invalid = 0
            for index, tweet in enumerate(tweets, start=1):
                print(
                    f"TWEET {index} author={tweet.username} "
                    f"status={tweet.status_id} published={tweet.published}"
                )
                print(tweet.x_url)
                print(tweet.text)
                for item in tweet.media:
                    if item.path is None or not item.path.exists():
                        continue
                    signature = media_signature(item.path)
                    size = item.path.stat().st_size
                    downloaded += 1
                    invalid += int(signature == "unknown" or size <= 0)
                    print(
                        f"MEDIA kind={item.kind} signature={signature} bytes={size}"
                    )
                for warning in tweet.media_warnings:
                    print(f"MEDIA_WARNING {warning}")
                print("---")

            copied = 0
            if args.keep_dir is not None:
                copied = _copy_verified_media(tweets, args.keep_dir)
            print(
                f"RESULT downloaded={downloaded} invalid={invalid} kept={copied}"
            )
            return 0 if tweets and downloaded > 0 and invalid == 0 else 1
        finally:
            try:
                if tweets:
                    media.cleanup_after_send(tweets)
            finally:
                service_module._plugin_data_dir = original_data_dir


def main() -> int:
    _configure_output_encoding()
    args = _parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
