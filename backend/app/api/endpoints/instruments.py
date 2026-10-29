from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.common import database_error
from app.db.session import get_db
from app.queries import (
    compute_snapshot_freshness,
    get_associated_ingestion_run,
    get_instrument_with_company,
    get_latest_snapshot_with_source,
    search_instruments as search_instruments_query,
)
from app.schemas.instrument import InstrumentDetailResponse, InstrumentSearchResult, MarketSnapshotResponse
from app.services.market_cap_service import MarketCapService

router = APIRouter(prefix="/api/v1/instruments", tags=["instruments"])


@router.get(
    "",
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

    try:
        rows = search_instruments_query(db, search_term, limit=limit, offset=offset)
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
    "/{instrument_id}",
    response_model=InstrumentDetailResponse,
)
def get_instrument(
    instrument_id: int,
    db: Session = Depends(get_db),
) -> InstrumentDetailResponse:
    try:
        instrument_row = get_instrument_with_company(db, instrument_id)
        if instrument_row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Instrument not found.",
            )
        snapshot_row = get_latest_snapshot_with_source(db, instrument_id)
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
        market_cap = mcap_res.market_cap_crores
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
            associated_run = get_associated_ingestion_run(db, snapshot.source_id, snapshot.snapshot_date)
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
