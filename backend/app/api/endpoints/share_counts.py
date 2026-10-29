from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.common import database_error
from app.db.session import get_db
from app.models import Instrument
from app.queries import get_share_counts
from app.schemas.instrument import ShareCountHistoryResponse

router = APIRouter(prefix="/api/v1/instruments", tags=["share_counts"])


@router.get(
    "/{instrument_id}/share-counts",
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

    try:
        rows = get_share_counts(db, instrument_id)
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
