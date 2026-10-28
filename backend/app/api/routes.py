from datetime import date
from decimal import Decimal
import logging
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Select, case, func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models import (
    Company,
    CorporateAction,
    DailyMarketSnapshot,
    DataSource,
    IngestionRun,
    Instrument,
    InstrumentShareCount,
)
from app.providers.tejhq import TejHQProvider
from app.schemas.instrument import (
    CorporateActionResponse,
    InstrumentDetailResponse,
    InstrumentSearchResult,
    MarketSnapshotResponse,
    PriceBarResponse,
    ShareCountHistoryResponse,
)
from app.schemas.provider import ProviderInfo, ProviderStatusResponse
from app.services.corporate_action_service import CorporateActionService
from app.services.historical_backfill_service import HistoricalBackfillService
from app.services.market_cap_service import MarketCapService

logger = logging.getLogger(__name__)
_empty_history_symbols: set[str] = set()

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
    lower_query = search_term.lower()
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
            case((func.lower(Instrument.symbol) == lower_query, 0), else_=1),
            case((func.lower(Instrument.symbol).like(f"{lower_query}%"), 0), else_=1),
            case((func.lower(Company.name).like(f"{lower_query}%"), 0), else_=1),
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

        # Calculate dated, defensible market capitalization using MarketCapService
        mcap_res = MarketCapService.calculate_for_instrument(instrument.id, db)
        market_cap = mcap_res.market_cap_crores if mcap_res.market_cap_crores is not None else snapshot.market_capitalization_crores
        share_count = mcap_res.share_count
        share_count_date = mcap_res.share_count_date
        share_count_source = mcap_res.share_count_source
        share_count_method = mcap_res.share_count_method
        share_count_status = mcap_res.share_count_status
        market_cap_explanation = mcap_res.explanation
        price_basis = mcap_res.price_type
        price_date = mcap_res.price_date or snapshot.snapshot_date

        # Staleness computation from persisted records
        is_stale, freshness_status = compute_snapshot_freshness(snapshot.snapshot_date, db)

        # Associate last_ingested_at with matching IngestionRun if available
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
            market_cap_price_basis=price_basis,
            market_cap_price_date=price_date,
            share_count=share_count,
            share_count_date=share_count_date,
            share_count_source=share_count_source,
            share_count_method=share_count_method,
            share_count_status=share_count_status,
            market_cap_explanation=market_cap_explanation,
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
        first_seen_date=instrument.first_seen_date,
        paid_up_value=instrument.paid_up_value,
        market_lot=instrument.market_lot,
        face_value=instrument.face_value,
        is_active=instrument.is_active,
        snapshot=snapshot_response,
    )


@router.get(
    "/api/v1/instruments/{instrument_id}/prices",
    response_model=list[PriceBarResponse],
)
def get_instrument_prices(
    instrument_id: int,
    from_date: date | None = Query(None, alias="from"),
    to_date: date | None = Query(None, alias="to"),
    limit: int = Query(1000, ge=1, le=10000),
    offset: int = Query(0, ge=0),
    auto_backfill: bool = Query(False),
    db: Session = Depends(get_db),
) -> list[PriceBarResponse]:
    inst = db.get(Instrument, instrument_id)
    if inst is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Instrument not found.",
        )

    if from_date is not None and to_date is not None and from_date > to_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid date range: 'from' date cannot be after 'to' date.",
        )

    if auto_backfill and inst.symbol not in _empty_history_symbols:
        try:
            snapshot_count = db.scalar(
                select(func.count(DailyMarketSnapshot.id)).where(
                    DailyMarketSnapshot.instrument_id == instrument_id
                )
            ) or 0
            earliest_date = db.scalar(
                select(func.min(DailyMarketSnapshot.snapshot_date)).where(
                    DailyMarketSnapshot.instrument_id == instrument_id
                )
            )

            needs_backfill = False
            if snapshot_count <= 15:
                needs_backfill = True
            elif from_date is not None and earliest_date is not None and from_date < earliest_date:
                needs_backfill = True
            elif from_date is None and earliest_date is not None and earliest_date >= date(2026, 10, 14):
                needs_backfill = True

            if needs_backfill:
                bf_svc = HistoricalBackfillService()
                source = bf_svc.get_or_create_source(db)
                bf_from = min(from_date, date(2020, 1, 1)) if from_date else date(2020, 1, 1)
                bf_to = to_date or date.today()
                read_cnt, ins_cnt, upd_cnt, _, _, _ = bf_svc.backfill_single_instrument(
                    inst.symbol, bf_from, bf_to, db, source.id, dry_run=False
                )
                if read_cnt == 0:
                    _empty_history_symbols.add(inst.symbol)
        except Exception as exc:
            logger.warning("On-demand historical backfill failed for %s: %s", inst.symbol, exc)

    statement = (
        select(DailyMarketSnapshot, DataSource)
        .outerjoin(DataSource, DataSource.id == DailyMarketSnapshot.source_id)
        .where(DailyMarketSnapshot.instrument_id == instrument_id)
    )

    if from_date is not None:
        statement = statement.where(DailyMarketSnapshot.snapshot_date >= from_date)
    if to_date is not None:
        statement = statement.where(DailyMarketSnapshot.snapshot_date <= to_date)

    # Order descending with limit/offset to capture the most recent bars up to to_date,
    # then reverse to present in ascending chronological order for charts.
    statement = (
        statement.order_by(DailyMarketSnapshot.snapshot_date.desc())
        .offset(offset)
        .limit(limit)
    )

    try:
        rows = list(reversed(db.execute(statement).all()))
    except SQLAlchemyError as exc:
        db.rollback()
        raise database_error() from exc

    return [
        PriceBarResponse(
            trading_date=snapshot.snapshot_date,
            open=snapshot.open_price,
            high=snapshot.high_price,
            low=snapshot.low_price,
            close=snapshot.close_price,
            ltp=snapshot.last_traded_price,
            prev_close=snapshot.prev_close_price,
            volume=snapshot.volume,
            volume_lakhs=snapshot.volume_lakhs,
            turnover=snapshot.turnover,
            traded_value_crores=snapshot.traded_value_crores,
            percentage_change_pct=snapshot.percentage_change_pct,
            trade_count=snapshot.trade_count,
            source_name=source.name if source else None,
        )
        for snapshot, source in rows
    ]


@router.get(
    "/api/v1/instruments/{instrument_id}/share-counts",
    response_model=list[ShareCountHistoryResponse],
)
def get_instrument_share_counts(
    instrument_id: int,
    db: Session = Depends(get_db),
) -> list[ShareCountHistoryResponse]:
    inst = db.get(Instrument, instrument_id)
    if inst is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Instrument not found.",
        )

    statement = (
        select(InstrumentShareCount, DataSource)
        .outerjoin(DataSource, DataSource.id == InstrumentShareCount.source_id)
        .where(InstrumentShareCount.instrument_id == instrument_id)
        .order_by(InstrumentShareCount.reporting_date.desc(), InstrumentShareCount.id.desc())
    )

    try:
        rows = db.execute(statement).all()
    except SQLAlchemyError as exc:
        db.rollback()
        raise database_error() from exc

    return [
        ShareCountHistoryResponse(
            id=rec.id,
            instrument_id=rec.instrument_id,
            symbol=rec.symbol,
            series=rec.series,
            share_class=rec.share_class,
            reported_share_count=rec.reported_share_count,
            fully_paid_shares=rec.fully_paid_shares,
            partly_paid_shares=rec.partly_paid_shares,
            source_capital_amount=rec.source_capital_amount,
            face_value=rec.face_value,
            reporting_date=rec.reporting_date,
            filing_date=rec.filing_date,
            retrieved_at=rec.retrieved_at,
            source_name=source.name if source else None,
            extraction_method=rec.extraction_method,
            validation_status=rec.validation_status,
            corporate_action_adjusted=rec.corporate_action_adjusted,
            corporate_action_details=rec.corporate_action_details,
        )
        for rec, source in rows
    ]


@router.get(
    "/api/v1/instruments/{instrument_id}/corporate-actions",
    response_model=list[CorporateActionResponse],
)
def get_instrument_corporate_actions(
    instrument_id: int,
    db: Session = Depends(get_db),
) -> list[CorporateActionResponse]:
    inst = db.get(Instrument, instrument_id)
    if inst is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Instrument not found.",
        )

    statement = (
        select(CorporateAction, DataSource)
        .outerjoin(DataSource, DataSource.id == CorporateAction.source_id)
        .where(CorporateAction.instrument_id == instrument_id)
        .order_by(
            func.coalesce(
                CorporateAction.effective_date,
                CorporateAction.ex_date,
                CorporateAction.allotment_date,
                CorporateAction.completion_date,
                CorporateAction.record_date,
                CorporateAction.announcement_date,
            ).desc(),
            CorporateAction.id.desc(),
        )
    )

    try:
        rows = db.execute(statement).all()
        if not rows:
            ca_svc = CorporateActionService()
            count = ca_svc.fetch_and_persist_for_symbol(db, inst.symbol)
            if count > 0:
                rows = db.execute(statement).all()
    except SQLAlchemyError as exc:
        db.rollback()
        raise database_error() from exc

    return [
        CorporateActionResponse(
            id=act.id,
            instrument_id=act.instrument_id,
            exchange=act.exchange,
            symbol=act.symbol,
            event_type=act.event_type,
            dedup_key=act.dedup_key,
            announcement_date=act.announcement_date,
            record_date=act.record_date,
            ex_date=act.ex_date,
            issue_open_date=act.issue_open_date,
            issue_close_date=act.issue_close_date,
            allotment_date=act.allotment_date,
            completion_date=act.completion_date,
            effective_date=act.effective_date,
            ratio_num=act.ratio_num,
            ratio_den=act.ratio_den,
            face_value_from=act.face_value_from,
            face_value_to=act.face_value_to,
            cash_amount=act.cash_amount,
            proposed_shares=act.proposed_shares,
            proposed_amount=act.proposed_amount,
            actual_shares=act.actual_shares,
            actual_amount=act.actual_amount,
            status=act.status,
            source_id=act.source_id,
            source_name=source.name if source else None,
            source_reference=act.source_reference,
            retrieved_at=act.retrieved_at,
            raw_subject=act.raw_subject,
            validation_status=act.validation_status,
            notes=act.notes,
        )
        for act, source in rows
    ]


