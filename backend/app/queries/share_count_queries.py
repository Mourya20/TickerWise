"""Read-only database queries for dated share capital and shareholding disclosures."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DataSource, InstrumentShareCount


def get_share_counts(
    db: Session,
    instrument_id: int,
) -> list[tuple[InstrumentShareCount, DataSource | None]]:
    """Retrieve historical reported share counts for an instrument ordered by reporting date descending."""
    statement = (
        select(InstrumentShareCount, DataSource)
        .outerjoin(DataSource, DataSource.id == InstrumentShareCount.source_id)
        .where(InstrumentShareCount.instrument_id == instrument_id)
        .order_by(InstrumentShareCount.reporting_date.desc(), InstrumentShareCount.id.desc())
    )
    return list(db.execute(statement).all())
