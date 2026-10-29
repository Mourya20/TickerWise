"""Read-only database queries for market data, price history, and OHLCV bars."""
from __future__ import annotations

from datetime import date
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DailyMarketSnapshot, DataSource


def get_price_history(
    db: Session,
    instrument_id: int,
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = 1000,
    offset: int = 0,
) -> list[tuple[DailyMarketSnapshot, DataSource | None]]:
    """Retrieve historical price snapshots for an instrument within an optional date range.

    Returns rows in ascending chronological order (earliest to latest) suitable for charts.
    """
    statement = (
        select(DailyMarketSnapshot, DataSource)
        .outerjoin(DataSource, DataSource.id == DailyMarketSnapshot.source_id)
        .where(DailyMarketSnapshot.instrument_id == instrument_id)
    )

    if from_date is not None:
        statement = statement.where(DailyMarketSnapshot.snapshot_date >= from_date)
    if to_date is not None:
        statement = statement.where(DailyMarketSnapshot.snapshot_date <= to_date)

    # Order descending to capture the most recent bars within window, then reverse
    statement = (
        statement.order_by(DailyMarketSnapshot.snapshot_date.desc())
        .offset(offset)
        .limit(limit)
    )

    rows = list(reversed(db.execute(statement).all()))
    return rows
