from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class ProviderInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    source_type: str
    is_active: bool
    source_url: str | None = None
    terms_url: str | None = None
    permission_verified: bool = False


class ProviderStatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    primary_provider: str
    provider_availability: str = "available"  # "available", "unavailable", "unknown"
    latest_published_trading_date: date | None
    pipeline_stage: str | None
    prices_published_at: datetime | None
    derived_published_at: datetime | None
    is_fresh: bool
    last_successful_ingestion_date: date | None
    last_successful_ingestion_completed_at: datetime | None
    last_run_status: str | None
    last_run_completed_at: datetime | None
    incomplete_coverage: bool
    is_local_stale: bool
    providers: list[ProviderInfo]
    last_local_ingestion_date: date | None = None
    last_local_ingestion_status: str | None = None
