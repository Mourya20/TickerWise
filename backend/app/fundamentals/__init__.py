"""Fundamentals domain module.

Owns shareholding disclosures, dated reported share counts, and capital history.
"""
from __future__ import annotations

from app.fundamentals.share_capital_service import (
    get_latest_reported_shares,
    is_share_count_stale,
)

__all__ = [
    "is_share_count_stale",
    "get_latest_reported_shares",
]
