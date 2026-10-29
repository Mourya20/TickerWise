"""Backward-compatible facade for CorporateActionService.

Canonical implementation has moved to app.corporate_actions.service.
"""
from __future__ import annotations

from app.corporate_actions.service import (
    DEFAULT_SOURCE_NAME,
    ApplicableShareCountResult,
    CorporateActionAdjustment,
    CorporateActionIngestionResult,
    CorporateActionService,
    generate_dedup_key,
    get_action_effective_date,
)

__all__ = [
    "CorporateActionService",
    "CorporateActionAdjustment",
    "CorporateActionIngestionResult",
    "ApplicableShareCountResult",
    "DEFAULT_SOURCE_NAME",
    "generate_dedup_key",
    "get_action_effective_date",
]
