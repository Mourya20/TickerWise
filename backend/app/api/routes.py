"""API Routes Backward-Compatibility Facade.

This module re-exports the modular routers and endpoint handlers from app.api.endpoints.*
to preserve 100% backward compatibility for all existing tests and callers.
"""
from app.api.common import compute_snapshot_freshness, database_error
from app.api.endpoints.corporate_actions import (
    get_instrument_corporate_actions,
    get_instrument_corporate_actions_status,
)
from app.api.endpoints.health import health
from app.api.endpoints.instruments import get_instrument, search_instruments
from app.api.endpoints.market_data import get_instrument_prices
from app.api.endpoints.providers import (
    PROVIDER_CACHE_TTL_SECONDS,
    TejHQProvider,
    _remote_status_cache,
    get_providers_status,
)
from app.api.endpoints.share_counts import get_instrument_share_counts
from app.api.router import api_router as router

__all__ = [
    "router",
    "database_error",
    "compute_snapshot_freshness",
    "health",
    "get_providers_status",
    "search_instruments",
    "get_instrument",
    "get_instrument_prices",
    "get_instrument_share_counts",
    "get_instrument_corporate_actions",
    "get_instrument_corporate_actions_status",
    "TejHQProvider",
    "_remote_status_cache",
    "PROVIDER_CACHE_TTL_SECONDS",
]
