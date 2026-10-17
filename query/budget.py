"""Atomic, per-message LLM tool limits.

Keep budgets on the AstrBot *event* rather than UMO: every new user message
gets a fresh budget even when the same group, sender and query recur.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import RLock
from typing import Literal

_NETWORK_LIMIT = 3
_DATA_LIMIT = 20
_SEND_LIMIT = 5
_TEXT_LIMIT = 24_000
_EVENT_KEY = "nitter_tweets.llm_query_budget.v1"
_Resource = Literal["data", "text"]


class BudgetLimitExceeded(ValueError):
    def __init__(self, resource: str, remaining: int):
        self.resource = resource
        self.remaining = max(0, remaining)
        super().__init__(f"{resource} limit exceeded; remaining={self.remaining}")


@dataclass(slots=True)
class BudgetTicket:
    """An atomic reservation; commit on valid tool output or roll back."""

    budget: QueryBudget
    resource: _Resource
    amount: int
    resolved: bool = False

    def commit(self, consumed: int | None = None) -> None:
        """Keep only consumed units when a fetch returns fewer than requested."""
        if self.resolved:
            return
        if consumed is not None:
            if type(consumed) is not int or not 0 <= consumed <= self.amount:
                raise ValueError("consumed amount is outside reservation")
            self.budget._refund(self.resource, self.amount - consumed)
            self.amount = consumed
        self.resolved = True

    def rollback(self) -> None:
        if self.resolved:
            return
        self.resolved = True
        self.budget._refund(self.resource, self.amount)


@dataclass(slots=True)
class QueryBudget:
    """Cap *started* network jobs, data returned, sends attempted and text.

    Failed or cancelled network jobs and attempted deliveries are NOT refunded:
    the request may already have reached a provider or platform. Data and
    serialized output are reserved separately and can be rolled back before
    becoming an observable tool result.
    """

    max_network: int = _NETWORK_LIMIT
    max_data: int = _DATA_LIMIT
    max_sends: int = _SEND_LIMIT
    max_text: int = _TEXT_LIMIT
    network_used: int = 0
    data_used: int = 0
    sends_used: int = 0
    text_used: int = 0
    notice_sent: bool = False
    _lock: RLock = field(default_factory=RLock, init=False, repr=False)

    @classmethod
    def for_event(cls, event) -> QueryBudget:
        getter = getattr(event, "get_extra", None)
        setter = getattr(event, "set_extra", None)
        if not callable(getter) or not callable(setter):
            raise ValueError("AstrBot event extras are required for tool budgets")
        current = getter(_EVENT_KEY)
        if isinstance(current, cls):
            return current
        # This sync get/set pair has no suspension point in AstrBot's event
        # loop. Every later tool call for the same event obtains this object.
        budget = cls()
        setter(_EVENT_KEY, budget)
        return budget

    @staticmethod
    def _check_amount(value: int) -> None:
        if type(value) is not int or value < 0:
            raise ValueError("budget amount must be a nonnegative integer")

    def start_network(self) -> bool:
        """Claim a top-level fetch. Return True only for the first job."""
        with self._lock:
            if self.network_used >= self.max_network:
                raise BudgetLimitExceeded(
                    "network", self.max_network - self.network_used
                )
            self.network_used += 1
            return self.network_used == 1

    def start_send(self) -> None:
        """Charge one actual send attempt before invoking the platform."""
        with self._lock:
            if self.sends_used >= self.max_sends:
                raise BudgetLimitExceeded("send", self.max_sends - self.sends_used)
            self.sends_used += 1

    def progress_notice(self) -> bool:
        """Only one task may emit a media progress notice per user message."""
        with self._lock:
            if self.notice_sent:
                return False
            self.notice_sent = True
            return True

    def _reserve(self, resource: _Resource, value: int) -> BudgetTicket:
        self._check_amount(value)
        attr = "data_used" if resource == "data" else "text_used"
        max_value = self.max_data if resource == "data" else self.max_text
        with self._lock:
            used = getattr(self, attr)
            if used + value > max_value:
                raise BudgetLimitExceeded(resource, max_value - used)
            setattr(self, attr, used + value)
            return BudgetTicket(self, resource, value)

    def reserve_data(self, count: int) -> BudgetTicket:
        return self._reserve("data", count)

    def reserve_text(self, chars: int) -> BudgetTicket:
        return self._reserve("text", chars)

    def _refund(self, resource: _Resource, count: int) -> None:
        with self._lock:
            attr = "data_used" if resource == "data" else "text_used"
            setattr(self, attr, max(0, getattr(self, attr) - count))

    def remaining(self) -> dict[str, int]:
        with self._lock:
            return {
                "network": max(0, self.max_network - self.network_used),
                "data": max(0, self.max_data - self.data_used),
                "send": max(0, self.max_sends - self.sends_used),
                "text": max(0, self.max_text - self.text_used),
            }
