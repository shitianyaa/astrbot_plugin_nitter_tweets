"""『web/history』状态筛选与『has_media』序列化测试。

覆盖:
1. 存储层 status 筛选 —— 基于「每目标最新送达结果」的分组级语义:
   success=全部目标成功,failed=全部目标失败,partial_failed=存在失败/部分失败但不全是失败
   (与 _group_history_records 徽章一致,含同一目标重推的去重场景)。
2. 序列化层 has_media —— 来自记录 tweet 的 media 数组,零 schema 依赖。
"""

from __future__ import annotations

import asyncio
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from plugin_api.api_history import WebAPIHistoryMixin
from shared.utils import TweetItem, TweetMedia
from storage import SQLiteStorage
from storage.records import PushHistoryRecord

GROUP = "default"
USER = "nasa"
LINK = "https://x.com/nasa/status/101"


def make_tweet(with_media: bool = False) -> TweetItem:
    media = [
        TweetMedia(kind="image", url="http://nitter:8080/pic/a.jpg"),
        TweetMedia(kind="video", url="http://nitter:8080/video/b.mp4"),
    ]
    return TweetItem(
        text="hello", link=LINK, published="", media=media if with_media else []
    )


async def record_samples(storage: SQLiteStorage) -> None:
    # 推文 101:两个目标均送达成功;推文 102:唯一目标失败;推文 103:混合(一成功一失败)。
    samples = [
        ("https://x.com/nasa/status/101", "aiocqhttp:GroupMessage:1", "success", ""),
        ("https://x.com/nasa/status/101", "telegram:FriendMessage:2", "success", ""),
        ("https://x.com/nasa/status/102", "aiocqhttp:GroupMessage:1", "failed", "boom"),
        ("https://x.com/nasa/status/103", "aiocqhttp:GroupMessage:1", "success", ""),
        (
            "https://x.com/nasa/status/103",
            "telegram:FriendMessage:2",
            "failed",
            "boom2",
        ),
    ]
    for link, target, status, error in samples:
        tweet = TweetItem(text="hello", link=link, published="")
        await asyncio.to_thread(
            storage.record_push_history,
            GROUP,
            USER,
            tweet,
            target,
            "blogger",
            "",
            None,
            status,
            error,
        )


class WebHistoryFilterTest(unittest.TestCase):
    def test_status_filter_matches_group_level_delivery_status(self):
        with TemporaryDirectory() as temp_dir:
            storage = SQLiteStorage(Path(temp_dir) / "nitter_tweets.db")
            asyncio.run(self._run(storage))

    async def _run(self, storage: SQLiteStorage) -> None:
        await storage.connect()
        try:
            await record_samples(storage)

            def rows(**kwargs):
                return storage.get_push_history(GROUP, USER, 50, 0, **kwargs)

            def count(**kwargs):
                return storage.count_push_history(GROUP, USER, **kwargs)

            # 无筛选:三张分组卡,共 5 条原始目标行
            self._assert_unfiltered(rows)
            # failed:只有推文 102(全部目标失败)命中 → 1 行
            failed_rows = rows(status="failed")
            assert len(failed_rows) == 1, failed_rows
            assert failed_rows[0].delivery_status == "failed"
            assert count(status="failed") == 1
            # success:只有推文 101(全部目标成功)命中 → 2 行
            success_rows = rows(status="success")
            assert len(success_rows) == 2, success_rows
            assert all(r.delivery_status == "success" for r in success_rows)
            assert count(status="success") == 1
            # partial_failed:只有推文 103(混合结果)命中 → 2 行
            partial_rows = rows(status="partial_failed")
            assert len(partial_rows) == 2, partial_rows
            assert {r.delivery_status for r in partial_rows} == {"success", "failed"}
            assert count(status="partial_failed") == 1
            # 非法状态值按空处理(全量返回,不回退成 SQL 注入)
            assert len(rows(status="all; DROP TABLE push_history")) == 5
        finally:
            storage.close()

    def test_status_filter_uses_latest_delivery_per_target(self):
        with TemporaryDirectory() as temp_dir:
            storage = SQLiteStorage(Path(temp_dir) / "nitter_tweets.db")
            asyncio.run(self._run_latest_per_target(storage))

    async def _run_latest_per_target(self, storage: SQLiteStorage) -> None:
        await storage.connect()
        try:
            tweet = TweetItem(text="hello", link=LINK, published="")
            target = "aiocqhttp:GroupMessage:1"
            # 同一推文同一目标重推两次:先失败后成功 → 分组状态以最新一次为准(success)。
            await asyncio.to_thread(
                storage.record_push_history,
                GROUP,
                USER,
                tweet,
                target,
                "replay",
                "",
                1000,
                "failed",
                "boom",
            )
            await asyncio.to_thread(
                storage.record_push_history,
                GROUP,
                USER,
                tweet,
                target,
                "replay",
                "",
                2000,
                "success",
                "",
            )
            # success 命中该分组,返回其全部原始行(含已被最新结果覆盖语义的失败行)。
            rows = storage.get_push_history(GROUP, USER, 50, 0, status="success")
            assert len(rows) == 2, rows
            assert storage.count_push_history(GROUP, USER, status="success") == 1
            assert (
                storage.get_push_history(GROUP, USER, 50, 0, status="partial_failed")
                == []
            )
            assert storage.count_push_history(GROUP, USER, status="partial_failed") == 0
            assert storage.count_push_history(GROUP, USER, status="failed") == 0
        finally:
            storage.close()

    def _assert_unfiltered(self, rows_func) -> None:
        unfiltered = rows_func()
        # 推文 101(2)+ 推文 102(1)+ 推文 103(2)= 5 条原始目标行
        assert len(unfiltered) == 5, unfiltered
        assert sum(1 for r in unfiltered if r.delivery_status == "success") == 3
        assert sum(1 for r in unfiltered if r.delivery_status == "failed") == 2


class WebHistorySerializeTest(unittest.TestCase):
    def test_serialize_adds_has_media_from_tweet_media(self):
        record = PushHistoryRecord(
            id=1,
            group_id=GROUP,
            username=USER,
            status_id="101",
            original_link="",
            target_umo="aiocqhttp:GroupMessage:1",
            source="blogger",
            instance="",
            pushed_at=0,
            tweet=make_tweet(with_media=True),
        )
        item = WebAPIHistoryMixin._serialize_history_record(
            record, {GROUP: "默认分组"}, "blogger"
        )
        assert item["has_media"] is True

    def test_serialize_reports_no_media_for_plain_tweet(self):
        record = PushHistoryRecord(
            id=2,
            group_id=GROUP,
            username=USER,
            status_id="102",
            original_link="",
            target_umo="aiocqhttp:GroupMessage:1",
            source="blogger",
            instance="",
            pushed_at=0,
            tweet=make_tweet(with_media=False),
        )
        item = WebAPIHistoryMixin._serialize_history_record(
            record, {GROUP: "默认分组"}, "blogger"
        )
        assert item["has_media"] is False
