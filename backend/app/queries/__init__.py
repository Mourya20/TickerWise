"""Read-only query layer for Stock Intelligence Workbench.

All query functions in this module:
1. Execute exclusively SELECT statements.
2. Never mutate session or database state.
3. Never initiate network calls or provider backfills.
"""
from __future__ import annotations

from app.queries.corporate_action_queries import get_corporate_actions
from app.queries.freshness_queries import compute_snapshot_freshness
from app.queries.instrument_queries import (
    get_associated_ingestion_run,
    get_instrument_with_company,
    get_latest_snapshot_with_source,
    search_instruments,
)
from app.queries.market_data_queries import get_price_history
from app.queries.provider_queries import (
    get_cached_provider_status,
    get_local_provider_status_data,
    set_cached_provider_status,
)
from app.queries.share_count_queries import get_share_counts

__all__ = [
    "compute_snapshot_freshness",
    "search_instruments",
    "get_instrument_with_company",
    "get_latest_snapshot_with_source",
    "get_associated_ingestion_run",
    "get_price_history",
    "get_corporate_actions",
    "get_share_counts",
    "get_local_provider_status_data",
    "set_cached_provider_status",
    "get_cached_provider_status",
]
