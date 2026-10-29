from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.common import database_error
from app.db.session import get_db
from app.models import Instrument
from app.queries import get_price_history
from app.schemas.instrument import PriceBarResponse

router = APIRouter(prefix="/api/v1/instruments", tags=["market_data"])


@router.get(
    "/{instrument_id}/prices",
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

    try:
        rows = get_price_history(
            db=db,
            instrument_id=instrument_id,
            from_date=from_date,
            to_date=to_date,
            limit=limit,
            offset=offset,
        )
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


@router.post(
    "/{instrument_id}/prices/backfill",
    summary="Trigger historical price backfill for instrument",
)
def backfill_instrument_prices(
    instrument_id: int,
    from_date: date | None = Query(None, alias="from"),
    to_date: date | None = Query(None, alias="to"),
    db: Session = Depends(get_db),
):
    inst = db.get(Instrument, instrument_id)
    if inst is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Instrument not found.",
        )

    from app.services.historical_backfill_service import HistoricalBackfillService
    from app.providers.tejhq import TejHQProvider

    try:
        bf_svc = HistoricalBackfillService(provider=TejHQProvider())
        source = bf_svc.get_or_create_source(db)
        bf_from = from_date or date(2020, 1, 1)
        bf_to = to_date or date.today()
        read, inserted, updated, skipped, failed, errs = bf_svc.backfill_single_instrument(
            inst.symbol, bf_from, bf_to, db, source.id
        )
        db.commit()
        return {
            "status": "completed" if failed == 0 else "partial" if inserted > 0 else "failed",
            "symbol": inst.symbol,
            "bars_read": read,
            "bars_inserted": inserted,
            "bars_skipped": skipped,
            "bars_failed": failed,
            "errors": errs,
        }
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Backfill failed: {exc}",
        )

