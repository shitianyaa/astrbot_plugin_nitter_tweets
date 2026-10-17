"""P-03: budget is atomic per user message, not per UMO or tool."""

import asyncio
from concurrent.futures import ThreadPoolExecutor

import pytest

from query.budget import BudgetLimitExceeded, QueryBudget


class Event:
    def __init__(self, umo="telegram:GroupMessage:1"):
        self.unified_msg_origin = umo
        self.extras = {}

    def get_extra(self, key, default=None):
        return self.extras.get(key, default)

    def set_extra(self, key, value):
        self.extras[key] = value


def test_one_event_shares_budget_across_tools_but_new_event_resets():
    event_a = Event()
    event_b = Event()
    first = QueryBudget.for_event(event_a)
    assert QueryBudget.for_event(event_a) is first
    assert QueryBudget.for_event(event_b) is not first
    assert first.start_network() is True
    assert first.start_network() is False
    assert first.start_network() is False
    with pytest.raises(BudgetLimitExceeded) as raised:
        first.start_network()
    assert raised.value.resource == "network"
    assert raised.value.remaining == 0
    # A failed operation must not reset its spent network quota.
    assert first.remaining()["network"] == 0
    assert QueryBudget.for_event(event_b).remaining()["network"] == 3


def test_data_reservation_can_be_rolled_back_or_committed_once():
    b = QueryBudget()
    token = b.reserve_data(10)
    assert b.remaining()["data"] == 10
    with pytest.raises(BudgetLimitExceeded):
        b.reserve_data(11)
    token.rollback()
    token.rollback()
    assert b.remaining()["data"] == 20
    committed = b.reserve_data(20)
    committed.commit()
    committed.rollback()
    assert b.remaining()["data"] == 0


def test_network_and_send_attempts_are_never_refunded_by_data_rollback():
    b = QueryBudget()
    for _ in range(3):
        b.start_network()
    for _ in range(5):
        b.start_send()
    with pytest.raises(BudgetLimitExceeded):
        b.start_send()
    t = b.reserve_data(4)
    t.rollback()
    assert b.remaining() == {"network": 0, "data": 20, "send": 0, "text": 24000}


def test_text_budget_is_atomic_and_independent_of_data():
    b = QueryBudget()
    txt = b.reserve_text(23999)
    with pytest.raises(BudgetLimitExceeded):
        b.reserve_text(2)
    txt.commit()
    b.reserve_text(1).commit()
    assert b.remaining()["text"] == 0
    assert b.remaining()["data"] == 20


def test_progress_notice_only_once_per_message():
    b = QueryBudget()
    assert b.progress_notice()
    assert not b.progress_notice()


def test_invalid_amount_does_not_consume_budget():
    b = QueryBudget()
    for invalid in [True, 1.0, -1, "2"]:
        with pytest.raises(ValueError):
            b.reserve_data(invalid)
    assert b.data_used == 0


def test_concurrent_claims_never_break_limits():
    b = QueryBudget()

    def attempt(_):
        try:
            b.start_network()
            b.start_send()
            b.reserve_data(1).commit()
            return True
        except BudgetLimitExceeded:
            return False

    with ThreadPoolExecutor(max_workers=16) as executor:
        list(executor.map(attempt, range(100)))
    assert b.network_used == 3
    assert b.sends_used == 3
    assert b.data_used == 3


@pytest.mark.asyncio
async def test_async_competing_calls_cannot_exceed_data_or_send_limits():
    b = QueryBudget()

    async def worker():
        await asyncio.sleep(0)
        try:
            ticket = b.reserve_data(4)
            b.start_send()
            ticket.commit()
            return True
        except BudgetLimitExceeded:
            return False

    results = await asyncio.gather(*(worker() for _ in range(12)))
    assert sum(results) == 5
    assert b.data_used == 20
    assert b.sends_used == 5
