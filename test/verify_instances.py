"""验证插件实例配置：RSS vs HTML 搜索分离"""

import sys
from pathlib import Path

# 添加项目根目录到路径
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from media_support.html_backend.service import (
    DEFAULT_KAREEM,
    DEFAULT_POAST,
    DEFAULT_SEARCH_INSTANCES,
    DEFAULT_TIEKOETTER,
)
from shared.utils import DEFAULT_INSTANCES


def main():
    import io

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    print("=" * 60)
    print("插件实例配置验证")
    print("=" * 60)

    print("\n✅ RSS 实例（用户订阅专用）")
    print("=" * 40)
    for i, instance in enumerate(DEFAULT_INSTANCES, 1):
        print(f"  {i}. {instance}")
    print("\n  用途: 用户时间线 RSS 订阅")
    print("  特点: nitter.net RSS 稳定，HTML 路径不可用")

    print("\n✅ HTML 搜索实例（标签搜索专用）")
    print("=" * 40)
    for i, instance in enumerate(DEFAULT_SEARCH_INSTANCES, 1):
        gate = {
            DEFAULT_TIEKOETTER: "Anubis PoW",
            DEFAULT_POAST: "Poast SHA1",
            DEFAULT_KAREEM: "轻量门禁",
        }.get(instance, "未知")
        print(f"  {i}. {instance}")
        print(f"     门禁: {gate}")
    print("\n  用途: 标签搜索（#NASA）")
    print("  特点: CF 实验验证，支持自动门禁解算")

    print("\n✅ 实例分离策略")
    print("=" * 40)
    print("  • nitter.net → 仅 RSS（搜索返回 200 空 body）")
    print("  • tiekoetter/poast/kareem → 仅搜索（RSS 403）")
    print("  • 健康度评分 + 自动轮换")
    print("  • 429 冷却保护")

    print("\n✅ 验证结果")
    print("=" * 40)

    # 验证分离
    rss_set = set(DEFAULT_INSTANCES)
    search_set = set(DEFAULT_SEARCH_INSTANCES)
    overlap = rss_set & search_set

    if not overlap:
        print("  ✓ RSS 和搜索实例完全分离")
    else:
        print(f"  ✗ 发现重叠实例: {overlap}")
        return 1

    # 验证搜索实例完整
    expected = {DEFAULT_TIEKOETTER, DEFAULT_POAST, DEFAULT_KAREEM}
    if search_set == expected:
        print("  ✓ 搜索实例包含所有 CF 验证的镜像")
    else:
        missing = expected - search_set
        extra = search_set - expected
        if missing:
            print(f"  ✗ 缺失实例: {missing}")
        if extra:
            print(f"  ✗ 多余实例: {extra}")
        return 1

    # 验证 RSS 只有 nitter.net
    if rss_set == {"https://nitter.net"}:
        print("  ✓ RSS 实例仅包含 nitter.net")
    else:
        print(f"  ✗ RSS 实例配置异常: {rss_set}")
        return 1

    print("\n" + "=" * 60)
    print("✅ 所有验证通过！")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
