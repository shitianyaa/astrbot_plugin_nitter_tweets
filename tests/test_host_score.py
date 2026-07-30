"""HostScoreBook: success boost, failure penalty, stable order."""

from __future__ import annotations

from media_support.host_score import (
    DEFAULT_SCORE,
    FAILURE_FACTOR,
    MAX_SCORE,
    MIN_SCORE,
    SUCCESS_DELTA,
    HostScoreBook,
)


def test_default_score_and_order_preserves_input_when_equal():
    book = HostScoreBook()
    urls = [
        "https://a.example",
        "https://b.example",
        "https://c.example",
    ]
    assert book.order(urls) == urls
    assert book.score("https://a.example") == DEFAULT_SCORE


def test_success_raises_and_failure_penalizes():
    book = HostScoreBook()
    book.record_success("https://good.example")
    book.record_failure("https://bad.example")
    assert book.score("good.example") == DEFAULT_SCORE + SUCCESS_DELTA
    assert book.score("bad.example") == DEFAULT_SCORE * FAILURE_FACTOR
    ordered = book.order(
        ["https://bad.example", "https://good.example", "https://mid.example"]
    )
    assert ordered[0].endswith("good.example")
    assert ordered[-1].endswith("bad.example")


def test_score_clamped():
    book = HostScoreBook()
    for _ in range(50):
        book.record_success("https://hot.example")
    assert book.score("hot.example") == MAX_SCORE
    for _ in range(50):
        book.record_failure("https://cold.example")
    assert book.score("cold.example") == MIN_SCORE


def test_soft_success_smaller_than_full():
    book = HostScoreBook()
    book.record_success("https://a.example", soft=True)
    book.record_success("https://b.example", soft=False)
    assert book.score("b.example") > book.score("a.example")


def test_pool_orders_ready_by_score(monkeypatch=None):
    from unittest.mock import MagicMock

    from media_support.host_score import HostScoreBook
    from media_support.html_backend.pool import HtmlNitterPool, PoolConfig

    book = HostScoreBook()
    book.record_success("https://b.example")
    book.record_failure("https://a.example")
    pool = HtmlNitterPool.__new__(HtmlNitterPool)
    pool.config = PoolConfig(
        instances=["https://a.example", "https://b.example", "https://c.example"]
    )
    pool.instances = ["https://a.example", "https://b.example", "https://c.example"]
    pool.scores = book
    pool.log = MagicMock()
    pool.session = MagicMock()
    pool.session.host_of = lambda base: base.replace("https://", "").split("/")[0]
    pool.limiter = MagicMock()
    pool.limiter.is_cooling = MagicMock(return_value=False)
    ordered = pool._hosts_for_rotation()
    assert ordered[0] == "https://b.example"
    assert ordered[1] == "https://c.example"
    assert ordered[2] == "https://a.example"


def test_pool_cooling_hosts_last():
    from unittest.mock import MagicMock

    from media_support.host_score import HostScoreBook
    from media_support.html_backend.pool import HtmlNitterPool, PoolConfig

    book = HostScoreBook()
    book.record_success("https://cool.example")  # high score but cooling
    book.record_failure("https://ready.example")
    pool = HtmlNitterPool.__new__(HtmlNitterPool)
    pool.config = PoolConfig(
        instances=["https://cool.example", "https://ready.example"]
    )
    pool.instances = ["https://cool.example", "https://ready.example"]
    pool.scores = book
    pool.log = MagicMock()
    pool.session = MagicMock()
    pool.session.host_of = lambda base: base.replace("https://", "").split("/")[0]
    pool.limiter = MagicMock()
    pool.limiter.is_cooling = MagicMock(side_effect=lambda h: "cool" in h)
    pool.limiter.cooldown_remaining = MagicMock(return_value=10.0)
    ordered = pool._hosts_for_rotation()
    assert ordered[0] == "https://ready.example"
    assert ordered[1] == "https://cool.example"


def test_rss_instances_for_run_orders_by_score():
    from media_support.client import NitterClient

    client = NitterClient.__new__(NitterClient)
    client.host_scores = HostScoreBook()
    client._run_host_skip = None
    client.host_scores.record_success("https://b.example")
    client.host_scores.record_failure("https://a.example")
    ordered = client._instances_for_run(
        ["https://a.example", "https://b.example", "https://c.example"]
    )
    assert ordered[0] == "https://b.example"
    assert ordered[-1] == "https://a.example"


def test_get_html_transport_error_records_failure():
    from unittest.mock import MagicMock

    from media_support.host_score import DEFAULT_SCORE, FAILURE_FACTOR, HostScoreBook
    from media_support.html_backend.pool import HtmlNitterPool, PoolConfig

    pool = HtmlNitterPool.__new__(HtmlNitterPool)
    pool.config = PoolConfig(instances=["https://down.example"])
    pool.scores = HostScoreBook()
    pool.log = MagicMock()
    pool.session = MagicMock()
    pool.session.host_of = lambda base: "down.example"
    pool.session.request = MagicMock(side_effect=TimeoutError("timed out"))
    pool.limiter = MagicMock()
    pool.gates = MagicMock()
    pool.gates.ensure = MagicMock(return_value=True)

    try:
        pool._get_html("https://down.example", "/search?q=x")
        raised = False
    except TimeoutError:
        raised = True
    assert raised
    assert pool.scores.score("down.example") == DEFAULT_SCORE * FAILURE_FACTOR


def test_get_html_explicit_failure_not_double_scored():
    from unittest.mock import MagicMock

    from media_support.host_score import DEFAULT_SCORE, FAILURE_FACTOR, HostScoreBook
    from media_support.html_backend.pool import HtmlNitterPool, PoolConfig

    pool = HtmlNitterPool.__new__(HtmlNitterPool)
    pool.config = PoolConfig(instances=["https://x.example"])
    pool.scores = HostScoreBook()
    pool.log = MagicMock()
    pool.session = MagicMock()
    pool.session.host_of = lambda base: "x.example"
    pool.session.request = MagicMock(
        return_value=MagicMock(code=429, body=b"rate", error=None)
    )
    pool.limiter = MagicMock()
    pool.limiter.punish = MagicMock(return_value=30.0)
    pool.gates = MagicMock()
    pool.gates.ensure = MagicMock(return_value=True)

    try:
        pool._get_html("https://x.example", "/u")
        raised = False
    except RuntimeError:
        raised = True
    assert raised
    # One failure only (not explicit branch + outer except).
    assert pool.scores.score("x.example") == DEFAULT_SCORE * FAILURE_FACTOR


def test_search_empty_soft_success_and_nonempty_full():
    from unittest.mock import MagicMock

    from media_support.host_score import (
        DEFAULT_SCORE,
        SOFT_SUCCESS_DELTA,
        SUCCESS_DELTA,
        HostScoreBook,
    )
    from media_support.html_backend.pool import HtmlNitterPool, PoolConfig
    from shared.utils import TweetItem

    pool = HtmlNitterPool.__new__(HtmlNitterPool)
    pool.config = PoolConfig(instances=["https://a.example", "https://b.example"])
    pool.instances = ["https://a.example", "https://b.example"]
    pool.scores = HostScoreBook()
    pool.log = MagicMock()
    pool.session = MagicMock()
    pool.session.host_of = lambda base: base.replace("https://", "").split("/")[0]
    pool.limiter = MagicMock()
    pool.limiter.is_cooling = MagicMock(return_value=False)

    def paginate(base, query, limit, *, kind, max_pages=None):
        if "a.example" in base:
            return []
        return [
            TweetItem(
                text="hit",
                link="https://x.com/u/status/1",
                published="",
            )
        ]

    pool._paginate_search = paginate  # type: ignore[method-assign]
    base, tweets = pool.search("q", 5, kind="phrase")
    assert "b.example" in base
    assert len(tweets) == 1
    assert pool.scores.score("a.example") == DEFAULT_SCORE + SOFT_SUCCESS_DELTA
    assert pool.scores.score("b.example") == DEFAULT_SCORE + SUCCESS_DELTA
