from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Select, func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models import Company, DailyMarketSnapshot, DataSource, IngestionRun, Instrument
from app.providers.tejhq import TejHQProvider
from app.schemas.instrument import (
    InstrumentDetailResponse,
    InstrumentSearchResult,
    MarketSnapshotResponse,
)
from app.schemas.provider import ProviderInfo, ProviderStatusResponse

router = APIRouter()


def database_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Database service is unavailable.",
    )


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def compute_snapshot_freshness(
    snapshot_date: date | None,
    db: Session,
) -> tuple[bool, str]:
    """Computes (is_stale, freshness_status) for a market snapshot.

    Freshness is derived from persisted EOD ingestion runs and snapshot trading dates
    without triggering remote network calls or relying naively on current clock time.
    """
    if snapshot_date is None:
        return True, "unknown"

    eod_run = db.execute(
        select(IngestionRun)
        .where(
            or_(
                IngestionRun.dataset_name.like("tejhq_eod_snapshot_%"),
                IngestionRun.dataset_name.like("market_snapshot_%"),
            )
        )
        .order_by(IngestionRun.trading_date.desc(), IngestionRun.started_at.desc(), IngestionRun.id.desc())
        .limit(1)
    ).scalar_one_or_none()

    max_db_date = db.scalar(select(func.max(DailyMarketSnapshot.snapshot_date)))

    ref_date = None
    if eod_run and eod_run.trading_date:
        ref_date = eod_run.trading_date
    if max_db_date:
        if ref_date is None or max_db_date > ref_date:
            ref_date = max_db_date

    if ref_date is None:
        return False, "unknown"

    if snapshot_date < ref_date:
        return True, "stale"

    # snapshot_date >= ref_date
    if eod_run and eod_run.trading_date == snapshot_date:
        if eod_run.status == "partial":
            return False, "incomplete"
        if eod_run.status == "failed":
            return True, "stale"

    return False, "fresh"


@router.get(
    "/api/v1/providers/status",
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

    try:
        remote_status = tejhq.get_status()
        latest_published_date = remote_status.trading_date
        pipeline_stage = remote_status.stage
        prices_published_at = remote_status.prices_published_at
        derived_published_at = remote_status.derived_published_at
        is_fresh = remote_status.is_fresh
    except Exception:
        # Gracefully handle network unavailability during provider status check
        provider_availability = "unavailable"
        pipeline_stage = "unavailable"
        is_fresh = False

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



@router.get(
    "/api/v1/instruments",
    response_model=list[InstrumentSearchResult],
)
def search_instruments(
    query: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> list[InstrumentSearchResult]:
    search_term = query.strip()
    if not search_term:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Query must contain non-whitespace text.",
        )

    pattern = f"%{search_term.lower()}%"
    statement = (
        select(Instrument, Company)
        .join(Company, Company.id == Instrument.company_id)
        .where(
            or_(
                func.lower(Instrument.symbol).like(pattern),
                func.lower(Company.name).like(pattern),
            )
        )
        .order_by(
            func.lower(Instrument.symbol),
            func.lower(Instrument.series),
            Instrument.id,
        )
        .offset(offset)
        .limit(limit)
    )

    try:
        rows = db.execute(statement).all()
    except SQLAlchemyError as exc:
        db.rollback()
        raise database_error() from exc

    return [
        InstrumentSearchResult(
            instrument_id=instrument.id,
            company_name=company.name,
            exchange=instrument.exchange,
            symbol=instrument.symbol,
            series=instrument.series,
            isin=instrument.isin,
            is_active=instrument.is_active,
        )
        for instrument, company in rows
    ]


@router.get(
    "/api/v1/instruments/{instrument_id}",
    response_model=InstrumentDetailResponse,
)
def get_instrument(
    instrument_id: int,
    db: Session = Depends(get_db),
) -> InstrumentDetailResponse:
    instrument_statement: Select[Instrument, Company] = (
        select(Instrument, Company)
        .join(Company, Company.id == Instrument.company_id)
        .where(Instrument.id == instrument_id)
    )

    snapshot_statement = (
        select(DailyMarketSnapshot, DataSource)
        .outerjoin(DataSource, DataSource.id == DailyMarketSnapshot.source_id)
        .where(DailyMarketSnapshot.instrument_id == instrument_id)
        .order_by(DailyMarketSnapshot.snapshot_date.desc())
        .limit(1)
    )

    try:
        instrument_row = db.execute(instrument_statement).one_or_none()
        if instrument_row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Instrument not found.",
            )
        snapshot_row = db.execute(snapshot_statement).one_or_none()
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise database_error() from exc

    instrument, company = instrument_row
    snapshot_response = None
    if snapshot_row is not None:
        snapshot, source = snapshot_row

        # Phase E: Market cap is strictly from current snapshot; never copied from older dates
        market_cap = snapshot.market_capitalization_crores

        # Phase D: Compute staleness honestly from persisted records
        is_stale, freshness_status = compute_snapshot_freshness(snapshot.snapshot_date, db)

        # Phase F: Associate last_ingested_at with matching IngestionRun if available
        last_ingested_at = snapshot.created_at
        if snapshot.source_id and snapshot.snapshot_date:
            associated_run = db.execute(
                select(IngestionRun)
                .where(
                    IngestionRun.source_id == snapshot.source_id,
                    IngestionRun.trading_date == snapshot.snapshot_date,
                )
                .order_by(IngestionRun.completed_at.desc(), IngestionRun.id.desc())
                .limit(1)
            ).scalar_one_or_none()
            if associated_run and associated_run.completed_at:
                last_ingested_at = associated_run.completed_at

        snapshot_response = MarketSnapshotResponse(
            snapshot_date=snapshot.snapshot_date,
            ltp=snapshot.last_traded_price,
            close=snapshot.close_price,
            open=snapshot.open_price,
            high=snapshot.high_price,
            low=snapshot.low_price,
            prev_close=snapshot.prev_close_price,
            percentage_change_pct=snapshot.percentage_change_pct,
            is_calculated_change=snapshot.is_calculated_change,
            market_capitalization_crores=market_cap,
            volume_lakhs=snapshot.volume_lakhs,
            traded_value_crores=snapshot.traded_value_crores,
            volume=snapshot.volume,
            turnover=snapshot.turnover,
            trade_count=snapshot.trade_count,
            source_name=source.name if source else None,
            last_ingested_at=last_ingested_at,
            is_stale=is_stale,
            freshness_status=freshness_status,
        )

    return InstrumentDetailResponse(
        instrument_id=instrument.id,
        company_id=instrument.company_id,
        company_name=company.name,
        exchange=instrument.exchange,
        symbol=instrument.symbol,
        series=instrument.series,
        instrument_type=instrument.instrument_type,
        isin=instrument.isin,
        listing_date=instrument.listing_date,
        paid_up_value=instrument.paid_up_value,
        market_lot=instrument.market_lot,
        face_value=instrument.face_value,
        is_active=instrument.is_active,
        snapshot=snapshot_response,
    )

