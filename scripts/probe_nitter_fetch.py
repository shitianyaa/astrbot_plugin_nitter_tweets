from __future__ import annotations

import argparse
import asyncio
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


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
            pass

        def warning(self, *args, **kwargs):
            print("[warning]", *args, file=sys.stderr)

        def debug(self, *args, **kwargs):
            pass

    astrbot_api_module.logger = _Logger()
    sys.modules.setdefault("astrbot", astrbot_module)
    sys.modules.setdefault("astrbot.api", astrbot_api_module)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Probe Nitter RSS with the plugin's NitterClient logic."
    )
    parser.add_argument("username", nargs="?", default="kozika1110")
    parser.add_argument("limit", nargs="?", type=int, default=5)
    parser.add_argument(
        "--instance",
        action="append",
        dest="instances",
        default=[],
        help="Nitter instance URL. Repeat to test multiple instances in order.",
    )
    parser.add_argument(
        "--include-reposts",
        action="store_true",
        help="Disable repost filtering for this probe.",
    )
    plain_text_group = parser.add_mutually_exclusive_group()
    plain_text_group.add_argument(
        "--skip-plain-text",
        action="store_true",
        help="启用纯文本推文过滤（模拟定时推送行为）：跳过没有作者上传媒体的推文。",
    )
    plain_text_group.add_argument(
        "--include-plain-text",
        action="store_true",
        help="显式关闭纯文本过滤（默认行为，与手动命令一致）。",
    )
    parser.add_argument("--timeout", type=float, default=12.0)
    parser.add_argument("--retry-delay", type=float, default=0.0)
    return parser.parse_args()


async def _main() -> None:
    _configure_output_encoding()
    _install_astrbot_logger_stub()
    from media import NitterClient

    args = _parse_args()
    skip_plain_text = args.skip_plain_text
    config = {
        "instances": args.instances or ["https://nitter.net", "http://nitter.top"],
        "request_timeout": args.timeout,
        "basic": {"filter_reposts_enabled": not args.include_reposts},
    }
    client = NitterClient(config)
    client.retry_delay_seconds = args.retry_delay

    instance, tweets = await client.fetch_tweets(
        args.username, args.limit, skip_plain_text=skip_plain_text
    )
    print(f"INSTANCE {instance}")
    print(f"COUNT {len(tweets)}")
    print(f"FILTER_REPOSTS {client.filter_reposts_enabled}")
    print(f"SKIP_PLAIN_TEXT {skip_plain_text}")
    for index, tweet in enumerate(tweets, 1):
        print(
            f"#{index} author={tweet.username} "
            f"status={tweet.status_id} published={tweet.published}"
        )
        print(tweet.x_url)
        print(tweet.text)
        print("---")


if __name__ == "__main__":
    asyncio.run(_main())
