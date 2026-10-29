import time
from fastapi import APIRouter, Depends
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models import DataSource, IngestionRun
from app.providers.tejhq import TejHQProvider
from app.schemas.provider import ProviderInfo, ProviderStatusResponse

router = APIRouter(prefix="/api/v1/providers", tags=["providers"])

_remote_status_cache: dict[str, tuple[float, any]] = {}
PROVIDER_CACHE_TTL_SECONDS: float = 60.0


@router.get(
    "/status",
    response_model=ProviderStatusResponse,
)
def get_providers_status(db: Session = Depends(get_db)) -> ProviderStatusResponse:
    # 1. Primary provider remote freshness
    tejhq = TejHQProvider()
    latest_published_date = None
    pipeline_stage = None
    prices_published_at = None
    derived_published_at = None
    is_fresh = False
    provider_availability = "available"

    now = time.monotonic()
    cached = _remote_status_cache.get("tejhq")
    remote_status = None

    if cached and (now - cached[0] < PROVIDER_CACHE_TTL_SECONDS):
        remote_status = cached[1]
    else:
        try:
            remote_status = tejhq.get_status()
            _remote_status_cache["tejhq"] = (now, remote_status)
        except Exception:
            if cached:
                remote_status = cached[1]
            else:
                provider_availability = "unavailable"
                pipeline_stage = "unavailable"
                is_fresh = False

    if remote_status is not None:
        latest_published_date = remote_status.trading_date
        pipeline_stage = remote_status.stage
        prices_published_at = remote_status.prices_published_at
        derived_published_at = remote_status.derived_published_at
        is_fresh = remote_status.is_fresh

    # 2. Local ingestion status filtered by relevant EOD provider & datasets
    eod_source = db.execute(
        select(DataSource).where(DataSource.name == "TejHQ EOD Market Data")
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

    # Successful run strictly requires status == 'completed' (partial is not reported as successful)
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

    # Check local staleness: stale if remote trading date exists and is newer than last successful local date
    is_local_stale = False
    if latest_published_date:
        if last_successful_date:
            is_local_stale = latest_published_date > last_successful_date
        elif last_run and last_run.trading_date:
            is_local_stale = (latest_published_date > last_run.trading_date) or (last_run.status != "completed")
        else:
            is_local_stale = True

    # 3. Data sources in DB
    sources = db.execute(select(DataSource)).scalars().all()
    providers_list = [
        ProviderInfo(
            name=s.name,
            source_type=s.source_type,
            is_active=s.is_active,
            source_url=s.source_url,
            terms_url=s.terms_url,
            permission_verified=bool(
                s.name != "0xramm Indian Stock Market API"
                or (
                    settings.TICKERWISE_0XRAMM_ENABLED
                    and settings.TICKERWISE_0XRAMM_AUTOMATION_PERMISSION_CONFIRMED
                )
            ),
        )
        for s in sources
    ]

    return ProviderStatusResponse(
        primary_provider="TejHQ",
        provider_availability=provider_availability,
        latest_published_trading_date=latest_published_date,
        pipeline_stage=pipeline_stage,
        prices_published_at=prices_published_at,
        derived_published_at=derived_published_at,
        is_fresh=is_fresh,
        last_successful_ingestion_date=last_successful_date,
        last_successful_ingestion_completed_at=last_successful_completed_at,
        last_run_status=last_run_status,
        last_run_completed_at=last_run_completed_at,
        incomplete_coverage=incomplete_coverage,
        is_local_stale=is_local_stale,
        providers=providers_list,
        last_local_ingestion_date=last_run.trading_date if last_run else None,
        last_local_ingestion_status=last_run_status,
    )
