"""Read-only database queries for corporate action events."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import CorporateAction, DataSource


def get_corporate_actions(
    db: Session,
    instrument_id: int,
) -> list[tuple[CorporateAction, DataSource | None]]:
    """Retrieve corporate actions for an instrument ordered by effective event date descending."""
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
    return list(db.execute(statement).all())
