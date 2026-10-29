"""Backward-compatible facade for MarketCapService.

Canonical implementation has moved to app.analytics.service.
"""
from __future__ import annotations

from app.analytics.constants import STALE_SHARE_COUNT_THRESHOLD_DAYS
from app.analytics.service import MarketCapResult, MarketCapService

__all__ = [
    "MarketCapService",
    "MarketCapResult",
    "STALE_SHARE_COUNT_THRESHOLD_DAYS",
]
