"""Backward-compatible facade for HistoricalBackfillService.

Canonical implementation has moved to app.market_data.backfill.
"""
from __future__ import annotations

from app.market_data.backfill import (
    CHECKPOINT_FILE,
    TEJHQ_SOURCE_NAME,
    TEJHQ_SOURCE_TYPE,
    TEJHQ_SOURCE_URL,
    TEJHQ_TERMS_URL,
    BackfillAudit,
    HistoricalBackfillService,
)

__all__ = [
    "HistoricalBackfillService",
    "BackfillAudit",
    "CHECKPOINT_FILE",
    "TEJHQ_SOURCE_NAME",
    "TEJHQ_SOURCE_TYPE",
    "TEJHQ_SOURCE_URL",
    "TEJHQ_TERMS_URL",
]
