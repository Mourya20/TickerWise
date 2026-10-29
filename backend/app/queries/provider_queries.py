"""Read-only queries for provider status, local ingestion provenance, and data freshness."""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import DataSource, IngestionRun
from app.providers.base import ProviderStatus
from app.providers.registry import ProviderRegistry

logger = logging.getLogger("app.queries.provider")

# Telemetry store updated by background workers / scheduled runs without stalling HTTP requests
_provider_telemetry_cache: dict[str, tuple[float, ProviderStatus]] = {}
PROVIDER_CACHE_TTL_SECONDS: float = 300.0  # 5 minutes


def set_cached_provider_status(provider_id: str, status: ProviderStatus, timestamp: float | None = None) -> None:
    """Store fresh provider status telemetry from background worker."""
    import time
    t = timestamp if timestamp is not None else time.monotonic()
    _provider_telemetry_cache[provider_id.lower().strip()] = (t, status)


def get_cached_provider_status(provider_id: str) -> ProviderStatus | None:
    """Retrieve telemetry without initiating network requests."""
    import time
    cached = _provider_telemetry_cache.get(provider_id.lower().strip())
    if cached and (time.monotonic() - cached[0] < PROVIDER_CACHE_TTL_SECONDS):
        return cached[1]
    return None


def get_local_provider_status_data(db: Session, primary_provider_id: str = "tejhq") -> dict[str, Any]:
    """Compile provider operational status and local ingestion metrics strictly using local state.

    Ensures that interactive GET requests never make outbound provider calls or execute database writes.
    """
    # 1. Resolve remote status from telemetry cache
    cached_status = get_cached_provider_status(primary_provider_id)
    provider_eval = ProviderRegistry.get_provider(primary_provider_id)
    provider_display_name = provider_eval.name if provider_eval else "TejHQ EOD Market Data"

    # 2. Local ingestion runs
    eod_source = db.execute(
        select(DataSource).where(DataSource.name == provider_display_name)
    ).scalar_one_or_none()

    eod_filter = or_(
        IngestionRun.dataset_name.like("tejhq_eod_snapshot_%"),
        IngestionRun.dataset_name.like("market_snapshot_%"),
    )
    if eod_source:
        eod_filter = or_(eod_filter, IngestionRun.source_id == eod_source.id)

    last_run = db.execute(
        select(IngestionRun)
        .where(eod_filter)
        .order_by(IngestionRun.started_at.desc(), IngestionRun.id.desc())
        .limit(1)
    ).scalar_one_or_none()

    last_successful_run = db.execute(
        select(IngestionRun)
        .where(eod_filter, IngestionRun.status == "completed")
        .order_by(IngestionRun.started_at.desc(), IngestionRun.id.desc())
        .limit(1)
    ).scalar_one_or_none()

    last_successful_date = last_successful_run.trading_date if last_successful_run else None
    last_successful_completed_at = last_successful_run.completed_at if last_successful_run else None
    last_run_status = last_run.status if last_run else None
    last_run_completed_at = last_run.completed_at if last_run else None

    incomplete_coverage = bool(
        last_run and (last_run.status == "partial" or (last_run.records_unmatched and last_run.records_unmatched > 0))
    )

    # 3. Derive published dates from cached telemetry or latest local run metadata
    latest_published_date = None
    pipeline_stage = None
    prices_published_at = None
    derived_published_at = None
    is_fresh = False
    provider_availability = "available"

    if cached_status is not None:
        latest_published_date = cached_status.trading_date
        pipeline_stage = cached_status.stage
        prices_published_at = cached_status.prices_published_at
        derived_published_at = cached_status.derived_published_at
        is_fresh = cached_status.is_fresh
    elif last_run is not None:
        # Fall back to latest known local ingestion run data
        latest_published_date = last_run.trading_date
        pipeline_stage = last_run.source_status or "active"
        is_fresh = bool(last_run.status == "completed")

    # Local staleness check
    is_local_stale = False
    if latest_published_date:
        if last_successful_date:
            is_local_stale = latest_published_date > last_successful_date
        elif last_run and last_run.trading_date:
            is_local_stale = (latest_published_date > last_run.trading_date) or (last_run.status != "completed")
        else:
            is_local_stale = True

    # 4. Data sources
    sources = db.execute(select(DataSource)).scalars().all()
    providers_list = []
    for s in sources:
        perm_verified = bool(
            s.name != "0xramm Indian Stock Market API"
            or (
                settings.TICKERWISE_0XRAMM_ENABLED
                and settings.TICKERWISE_0XRAMM_AUTOMATION_PERMISSION_CONFIRMED
            )
        )
        providers_list.append({
            "name": s.name,
            "source_type": s.source_type,
            "is_active": s.is_active,
            "source_url": s.source_url,
            "terms_url": s.terms_url,
            "permission_verified": perm_verified,
        })

    return {
        "primary_provider": "TejHQ",
        "provider_availability": provider_availability,
        "latest_published_trading_date": latest_published_date,
        "pipeline_stage": pipeline_stage,
        "prices_published_at": prices_published_at,
        "derived_published_at": derived_published_at,
        "is_fresh": is_fresh,
        "last_successful_ingestion_date": last_successful_date,
        "last_successful_ingestion_completed_at": last_successful_completed_at,
        "last_run_status": last_run_status,
        "last_run_completed_at": last_run_completed_at,
        "incomplete_coverage": incomplete_coverage,
        "is_local_stale": is_local_stale,
        "providers": providers_list,
        "last_local_ingestion_date": last_run.trading_date if last_run else None,
        "last_local_ingestion_status": last_run_status,
    }
