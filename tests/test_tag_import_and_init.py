from __future__ import annotations

from config.subscriptions import set_import_group_queries
from media_support.html_backend import normalize_watch_query
from scheduler.config import GROUP_TYPE_TAG, SchedulerConfigReader
from scheduler.runner import NitterTweetScheduler
from shared.utils import TweetItem, TweetMedia


class _DummyConfig(dict):
    def get(self, key, default=None):
        return super().get(key, default)

    def save_config(self):
        return None


def test_normalize_watch_query_for_import():
    q, k = normalize_watch_query("#a", None)
    assert k == "tag" and q == "#a"
    q2, k2 = normalize_watch_query("hello world", None)
    assert k2 == "phrase" and q2 == "hello world"


def test_filter_html_plain_text_keeps_media():
    tweets = [
        TweetItem(text="a", link="https://x.com/a/status/1", published="", media=[]),
        TweetItem(
            text="b",
            link="https://x.com/b/status/2",
            published="",
            media=[TweetMedia(kind="image", url="https://pbs.twimg.com/media/x")],
        ),
    ]
    kept, filtered = NitterTweetScheduler._filter_html_tweets_plain_text(
        tweets, skip_plain_text=True
    )
    assert filtered == 1
    assert len(kept) == 1
    assert kept[0].status_id == "2"


def test_parse_tag_group_account_keys():
    reader = SchedulerConfigReader(
        _DummyConfig(
            {
                "tweet_groups": [
                    {
                        "name": "t",
                        "group_id": "t1",
                        "group_type": "tag",
                        "watch_queries": ["#foo", "bar"],
                        "enabled": True,
                    }
                ]
            }
        ),
        None,
    )
    group = reader.schedule_groups(False)[0]
    assert group.group_type == GROUP_TYPE_TAG
    assert all(k.startswith("q:") for k in group.account_keys)


def test_tag_import_persists_reversible_string_queries():
    config = _DummyConfig(
        {
            "tweet_groups": [
                {
                    "name": "t",
                    "group_id": "t1",
                    "group_type": "tag",
                    "watch_queries": [],
                    "enabled": True,
                }
            ]
        }
    )
    reader = SchedulerConfigReader(config, None)
    group = reader.schedule_groups(False)[0]

    set_import_group_queries(
        config,
        reader,
        group,
        [
            {"query": "#foo", "type": "tag"},
            {"query": "#literal", "type": "phrase"},
        ],
    )

    stored = config["tweet_groups"][0]["watch_queries"]
    assert stored == ["#foo", "nitter-query:phrase:#literal"]
    parsed = reader.parse_watch_queries(stored)
    assert [(item.query, item.type) for item in parsed.queries] == [
        ("#foo", "tag"),
        ("#literal", "phrase"),
    ]
