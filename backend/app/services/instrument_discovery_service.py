"""Backward-compatible facade for InstrumentDiscoveryService.

Canonical implementation has moved to app.instruments.discovery.
"""
from __future__ import annotations

from app.instruments.discovery import (
    ISIN_EQUITY_REGEX,
    ISIN_GENERAL_REGEX,
    SUPPORTED_EQUITY_SERIES,
    SYMBOL_REGEX,
    DiscoveryResult,
    DiscoverySummary,
    InstrumentDiscoveryService,
    normalize_company_name,
)

__all__ = [
    "InstrumentDiscoveryService",
    "DiscoveryResult",
    "DiscoverySummary",
    "SUPPORTED_EQUITY_SERIES",
    "ISIN_EQUITY_REGEX",
    "ISIN_GENERAL_REGEX",
    "SYMBOL_REGEX",
    "normalize_company_name",
]
