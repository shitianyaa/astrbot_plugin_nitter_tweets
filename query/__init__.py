"""Shared, side-effect-free query contracts (P-01).

Old manual commands and scheduled checks are intentionally not rewired yet.
"""

from .models import (
    FetchOutcome,
    FetchStatus,
    SearchQuery,
    TimelineQuery,
    TrendQuery,
)
from .service import QueryService

__all__ = [
    "FetchOutcome",
    "FetchStatus",
    "QueryService",
    "SearchQuery",
    "TimelineQuery",
    "TrendQuery",
]
