"""Corporate Actions domain module.

Owns corporate action events, point-in-time share adjustments, and deduplication keys.
"""
from __future__ import annotations

from app.corporate_actions.service import (
    ApplicableShareCountResult,
    CorporateActionAdjustment,
    CorporateActionIngestionResult,
    CorporateActionService,
    DEFAULT_SOURCE_NAME,
    generate_dedup_key,
    get_action_effective_date,
)

__all__ = [
    "CorporateActionService",
    "ApplicableShareCountResult",
    "CorporateActionAdjustment",
    "CorporateActionIngestionResult",
    "DEFAULT_SOURCE_NAME",
    "generate_dedup_key",
    "get_action_effective_date",
]
