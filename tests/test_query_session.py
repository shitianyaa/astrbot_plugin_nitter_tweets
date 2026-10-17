"""P-03: LLM search/timeline caches are sender-, session- and query-scoped."""

from __future__ import annotations

import time

import pytest

from query.session import ResultSessionStore
from shared.utils import TweetItem


class Event:
    def __init__(self, umo: str, sender: str):
        self.unified_msg_origin = umo
        self.sender = sender

    def get_sender_id(self):
        return self.sender


def _tweet(sid: str):
    return TweetItem(
        text="tweet", link=f"https://x.com/test/status/{sid}", published=""
    )


def test_sender_and_platform_scope_never_share_read_state():
    store = ResultSessionStore()
    a = Event("telegram:GroupMessage:1", "alice")
    b = Event("telegram:GroupMessage:1", "bob")
    other = Event("qq:GroupMessage:1", "alice")
    alice = store.llm_window(a, kind="search", source="#NEWS")
    alice.add_tweets([_tweet("10"), _tweet("11")])
    assert store.llm_window(a, kind="search", source="#news") is alice
    assert len(store.llm_window(b, kind="search", source="#news")) == 0
    assert len(store.llm_window(other, kind="search", source="#news")) == 0


def test_search_sort_media_type_and_timeline_have_different_windows():
    store = ResultSessionStore()
    event = Event("telegram:GroupMessage:1", "alice")
    search = store.llm_window(event, kind="search", source="topic", sort="latest")
    search.add_tweets([_tweet("10")])
    assert len(store.llm_window(event, kind="search", source="topic", sort="top")) == 0
    assert (
        len(store.llm_window(event, kind="search", source="topic", media_type="video"))
        == 0
    )
    assert len(store.llm_window(event, kind="timeline", source="@topic")) == 0


def test_refresh_clears_only_exact_own_window_and_known_ids():
    store = ResultSessionStore()
    alice = Event("telegram:GroupMessage:1", "alice")
    bob = Event("telegram:GroupMessage:1", "bob")
    first = store.llm_window(alice, kind="search", source="cats")
    other = store.llm_window(bob, kind="search", source="cats")
    first.add_tweets([_tweet("1"), _tweet("2")])
    other.add_tweets([_tweet("3")])
    first.take(1)
    refreshed = store.llm_window(alice, kind="search", source="cats", refresh=True)
    assert refreshed is not first
    assert len(refreshed) == 0
    assert not refreshed.known_ids
    assert [x.status_id for x in other.take(1)] == ["3"]
    assert refreshed.add_tweets([_tweet("1")]) == 1


def test_refresh_during_pending_reservation_cannot_evict_it():
    store = ResultSessionStore()
    event = Event("tg:Group:1", "u")
    first = store.llm_window(event, kind="timeline", source="alice")
    first.add_tweets([_tweet("1")])
    token, records = first.reserve(1)
    with pytest.raises(RuntimeError, match="reserved"):
        store.llm_window(event, kind="timeline", source="alice", refresh=True)
    first.rollback(token)
    assert len(first) == 1


def test_reserved_items_are_returned_if_tool_result_cannot_be_serialized():
    store = ResultSessionStore()
    event = Event("tg:Group:1", "u")
    buffer = store.llm_window(event, kind="search", source="cats")
    buffer.add_tweets([_tweet("1"), _tweet("2")])
    token, records = buffer.reserve(2)
    assert [x.status_id for x in records] == ["1", "2"]
    buffer.rollback(token)
    assert [x.status_id for x in buffer.take(2)] == ["1", "2"]


def test_stale_window_expires_without_changing_another_user():
    store = ResultSessionStore(ttl=600)
    event_a = Event("tg:Group:1", "alice")
    event_b = Event("tg:Group:1", "bob")
    a = store.llm_window(event_a, kind="search", source="cats")
    b = store.llm_window(event_b, kind="search", source="cats")
    a.add_tweets([_tweet("1")])
    b.add_tweets([_tweet("2")])
    a.updated_at = time.time() - 601
    assert store.llm_window(event_a, kind="search", source="cats") is not a
    assert store.llm_window(event_b, kind="search", source="cats") is b


@pytest.mark.parametrize("umo,sender", [("", "alice"), ("tg:Group:1", "")])
def test_missing_identity_is_rejected(umo, sender):
    store = ResultSessionStore()
    with pytest.raises(ValueError, match="UMO and sender"):
        store.llm_window(Event(umo, sender), kind="search", source="cats")
