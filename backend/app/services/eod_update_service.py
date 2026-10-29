"""Backward-compatible facade for EODUpdateService.

Canonical implementation has moved to app.ingestion.eod_service.
"""
from __future__ import annotations

from app.ingestion.eod_service import (
    EODUpdateResult,
    EODUpdateService,
    PROJECT_ROOT,
    REVIEW_DIR,
    ReconciledQuote,
    TEJHQ_SOURCE_NAME,
    TEJHQ_SOURCE_TYPE,
    TEJHQ_SOURCE_URL,
    TEJHQ_TERMS_URL,
    ZEROM_SOURCE_NAME,
    ZEROM_SOURCE_TYPE,
    ZEROM_SOURCE_URL,
    ZEROM_TERMS_URL,
    utc_naive_now,
)

__all__ = [
    "EODUpdateService",
    "EODUpdateResult",
    "ReconciledQuote",
    "utc_naive_now",
    "PROJECT_ROOT",
    "REVIEW_DIR",
    "TEJHQ_SOURCE_NAME",
    "TEJHQ_SOURCE_TYPE",
    "TEJHQ_SOURCE_URL",
    "TEJHQ_TERMS_URL",
    "ZEROM_SOURCE_NAME",
    "ZEROM_SOURCE_TYPE",
    "ZEROM_SOURCE_URL",
    "ZEROM_TERMS_URL",
]
