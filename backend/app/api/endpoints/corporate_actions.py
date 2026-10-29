from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.common import database_error
from app.db.session import get_db
from app.models import Instrument
from app.queries import get_corporate_actions
from app.schemas.instrument import CorporateActionResponse, CorporateActionSyncStatusResponse

router = APIRouter(prefix="/api/v1/instruments", tags=["corporate_actions"])


@router.get(
    "/{instrument_id}/corporate-actions",
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

    try:
        rows = get_corporate_actions(db, instrument_id)
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


@router.get(
    "/{instrument_id}/corporate-actions/status",
    response_model=CorporateActionSyncStatusResponse,
)
def get_instrument_corporate_actions_status(
    instrument_id: int,
    db: Session = Depends(get_db),
) -> CorporateActionSyncStatusResponse:
    """Check synchronization status of corporate actions for an instrument."""
    inst = db.get(Instrument, instrument_id)
    if inst is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Instrument not found.",
        )

    try:
        from app.services.corporate_action_service import CorporateActionService

        sync_info = CorporateActionService.get_sync_status(db, inst.symbol)
        return CorporateActionSyncStatusResponse(
            instrument_id=inst.id,
            symbol=inst.symbol,
            status=sync_info["status"],
            last_checked_at=sync_info.get("last_checked_at"),
            last_success_at=sync_info.get("last_success_at"),
            events_count=sync_info.get("events_count", 0),
            provider_name="TejHQ",
            error_message=sync_info.get("error_message"),
        )
    except SQLAlchemyError as exc:
        db.rollback()
        raise database_error() from exc


@router.post(
    "/{instrument_id}/corporate-actions/sync",
    response_model=CorporateActionSyncStatusResponse,
    summary="Synchronize corporate actions from exchange for instrument",
)
def sync_instrument_corporate_actions(
    instrument_id: int,
    db: Session = Depends(get_db),
) -> CorporateActionSyncStatusResponse:
    inst = db.get(Instrument, instrument_id)
    if inst is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Instrument not found.",
        )

    from app.providers.tejhq import TejHQProvider
    from app.services.corporate_action_service import (
        CorporateActionIngestionResult,
        CorporateActionService,
    )

    provider = TejHQProvider()
    svc = CorporateActionService(provider=provider)

    try:
        raw_actions = provider.get_actions(inst.symbol)
        source = svc.get_or_create_source(db)
        audit = CorporateActionIngestionResult()

        if not raw_actions:
            CorporateActionService.record_sync_status(
                db,
                symbol=inst.symbol,
                status="empty",
                records_read=0,
                error_summary=None,
            )
            db.commit()
        else:
            svc.ingest_actions(db, raw_actions, source_id=source.id, audit_result=audit)
            db.commit()
            run_status = "completed" if audit.actions_rejected == 0 else "partial"
            CorporateActionService.record_sync_status(
                db,
                symbol=inst.symbol,
                status=run_status,
                records_read=audit.actions_received,
                records_inserted=audit.actions_inserted,
                records_updated=audit.actions_updated,
                records_skipped=audit.actions_unchanged,
                records_failed=audit.actions_rejected,
                records_unmatched=audit.actions_unmatched,
            )
            db.commit()

        sync_info = CorporateActionService.get_sync_status(db, inst.symbol)
        return CorporateActionSyncStatusResponse(
            instrument_id=inst.id,
            symbol=inst.symbol,
            status=sync_info["status"],
            last_checked_at=sync_info.get("last_checked_at"),
            last_success_at=sync_info.get("last_success_at"),
            events_count=sync_info.get("events_count", 0),
            provider_name="TejHQ",
            error_message=sync_info.get("error_message"),
        )
    except Exception as exc:
        db.rollback()
        CorporateActionService.record_sync_status(
            db,
            symbol=inst.symbol,
            status="failed",
            error_summary=str(exc),
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Synchronization failed: {exc}",
        )


