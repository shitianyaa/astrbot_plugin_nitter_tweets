# -*- coding: utf-8 -*-
from __future__ import annotations

from types import SimpleNamespace

from media_support.search_session_buffer import (
    SearchSessionStore,
    SessionSearchBuffer,
    tweet_item_key,
)


def _t(sid: str, text: str = "hi") -> SimpleNamespace:
    return SimpleNamespace(
        status_id=sid, link=f"https://x.com/u/status/{sid}", text=text
    )


def test_tweet_item_key_prefers_status_id():
    assert tweet_item_key(_t("123")) == "123"
    assert (
        tweet_item_key(SimpleNamespace(status_id="", link="https://x.com/a"))
        == "https://x.com/a"
    )


def test_buffer_stores_all_and_take_preserves_order():
    buf = SessionSearchBuffer()
    added = buf.add_tweets(
        [_t("1"), _t("2"), _t("3"), _t("1")], instance="https://nitter.example"
    )
    assert added == 3
    assert len(buf) == 3
    assert buf.instance.endswith("example")
    batch = buf.take(2)
    assert [x.status_id for x in batch] == ["1", "2"]
    assert len(buf) == 1
    assert buf.take(5)[0].status_id == "3"
    assert len(buf) == 0


def test_known_ids_skip_refetch_duplicates():
    buf = SessionSearchBuffer()
    buf.add_tweets([_t("1"), _t("2")])
    buf.take(2)
    # first page again should not re-queue
    assert buf.add_tweets([_t("1"), _t("2"), _t("3")]) == 1
    assert [x.status_id for x in buf.take(10)] == ["3"]


def test_store_keys_by_session_and_query():
    store = SearchSessionStore()
    a = store.get_or_create("sess-a", "#tag")
    b = store.get_or_create("sess-a", "phrase")
    c = store.get_or_create("sess-b", "#tag")
    a.add_tweets([_t("1")])
    assert len(b) == 0
    assert len(c) == 0
    assert len(store.get("sess-a", "#tag")) == 1


def test_finalize_invalid_send_count_restores_all_items():
    buf = SessionSearchBuffer()
    buf.add_tweets([_t("1"), _t("2")])
    token, reserved = buf.reserve(2)
    assert [item.status_id for item in reserved] == ["1", "2"]

    buf.finalize(token, None)

    assert [item.status_id for item in buf.take(10)] == ["1", "2"]


def test_out_of_order_reservations_restore_original_order():
    buf = SessionSearchBuffer()
    buf.add_tweets([_t("1"), _t("2"), _t("3"), _t("4")])
    first_token, first = buf.reserve(2)
    second_token, second = buf.reserve(2)
    assert [item.status_id for item in first] == ["1", "2"]
    assert [item.status_id for item in second] == ["3", "4"]

    # The second send can finish first; the queue must still be 2, 4 rather
    # than being reversed by front insertion.
    buf.finalize(second_token, 1)
    buf.finalize(first_token, 1)

    assert [item.status_id for item in buf.take(10)] == ["2", "4"]


def test_prepopulated_items_get_stable_fetch_order_for_rollback():
    buf = SessionSearchBuffer(items={"1": _t("1"), "2": _t("2"), "3": _t("3")})
    token, reserved = buf.reserve(2)
    assert [item.status_id for item in reserved] == ["1", "2"]
    buf.finalize(token, 1)
    assert [item.status_id for item in buf.take(10)] == ["2", "3"]


def test_known_id_pruning_keeps_ids_in_active_reservations():
    buf = SessionSearchBuffer()
    buf.add_tweets([_t(str(i)) for i in range(100)])
    token, reserved = buf.reserve(1)
    reserved_id = reserved[0].status_id
    buf.add_tweets([_t(f"new-{i}") for i in range(100)])

    # A refetch of the reserved item must not be accepted as a duplicate copy
    # while the first reservation is still in flight.
    assert buf.add_tweets([_t(reserved_id)]) == 0
    buf.rollback(token)
