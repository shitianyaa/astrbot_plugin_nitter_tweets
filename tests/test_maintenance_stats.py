"""维护区存量统计:媒体缓存 cache_stats() 与 seen 分组计数。

覆盖:
1. 缓存只读统计 —— 文件数/图片/视频/其他/字节,跳过受保护目录(staged/),
   合并 cache_dir 与 legacy_cache_dir(解析后去重)。
2. seen 计数 —— count_seen_tweets_by_group 按分组聚合,只读不删除。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from media_support.cache import MediaCacheMixin
from storage import SQLiteStorage


class _Cache(MediaCacheMixin):
    def __init__(self, root: Path):
        self.cache_dir = root / "cache"
        self.legacy_cache_dir = root / "legacy"
        self.cache_dir.mkdir()
        self.legacy_cache_dir.mkdir()


def test_cache_stats_counts_files_and_skips_staged(tmp_path):
    cache = _Cache(tmp_path)
    (cache.cache_dir / "a.jpg").write_bytes(b"x" * 100)
    (cache.cache_dir / "b.mp4").write_bytes(b"x" * 200)
    (cache.cache_dir / "c.txt").write_bytes(b"x" * 50)
    staged = cache.cache_dir / "staged"
    staged.mkdir()
    (staged / "keep.bin").write_bytes(b"x" * 999)
    (cache.legacy_cache_dir / "d.png").write_bytes(b"x" * 30)

    stats = cache.cache_stats()

    assert stats.files == 4, stats
    assert stats.images == 2, stats  # a.jpg + legacy d.png
    assert stats.videos == 1, stats
    assert stats.other == 1, stats
    assert stats.bytes == 100 + 200 + 50 + 30, stats


def test_cache_stats_empty_dirs_report_zero(tmp_path):
    stats = _Cache(tmp_path).cache_stats()
    assert stats.files == 0
    assert stats.bytes == 0


def test_seen_count_by_group_is_read_only(tmp_path):
    storage = SQLiteStorage(Path(tmp_path) / "stats.db")
    asyncio.run(_run_seen(storage))


async def _run_seen(storage: SQLiteStorage) -> None:
    await storage.connect()
    try:
        rows = [
            ("default", "nasa", "101", 1000),
            ("default", "nasa", "102", 1001),
            ("g2", "spacex", "201", 1002),
        ]
        storage.conn.executemany(
            "INSERT INTO seen_tweets (group_id, username, status_id, seen_at) "
            "VALUES (?, ?, ?, ?)",
            rows,
        )
        storage.conn.commit()

        counts = storage.count_seen_tweets_by_group()
        assert counts == {"default": 2, "g2": 1}, counts

        # 只读:数据原样保留
        remaining = storage.conn.execute(
            "SELECT COUNT(*) AS count FROM seen_tweets"
        ).fetchone()
        assert int(remaining["count"]) == 3
    finally:
        storage.close()
