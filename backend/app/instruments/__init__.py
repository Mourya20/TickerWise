"""Instrument Catalog domain module.

Owns companies, equity instruments, identity resolution, and IPO discovery.
"""
from __future__ import annotations

from app.instruments.catalog import (
    ISIN_EQUITY_REGEX,
    SUPPORTED_EQUITY_SERIES,
    SYMBOL_REGEX,
    normalize_company_name,
    resolve_or_create_company,
    validate_equity_isin,
)
from app.instruments.discovery import (
    DiscoveryResult,
    DiscoverySummary,
    InstrumentDiscoveryService,
)

__all__ = [
    "resolve_or_create_company",
    "validate_equity_isin",
    "normalize_company_name",
    "SUPPORTED_EQUITY_SERIES",
    "ISIN_EQUITY_REGEX",
    "SYMBOL_REGEX",
    "InstrumentDiscoveryService",
    "DiscoveryResult",
    "DiscoverySummary",
]
