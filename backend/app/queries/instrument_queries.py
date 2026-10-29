"""Read-only database queries for instruments, companies, and snapshot views."""
from __future__ import annotations

from datetime import date
from sqlalchemy import Select, case, func, or_, select
from sqlalchemy.orm import Session

from app.models import Company, DailyMarketSnapshot, DataSource, IngestionRun, Instrument


def search_instruments(
    db: Session,
    query: str,
    limit: int = 20,
    offset: int = 0,
) -> list[tuple[Instrument, Company]]:
    """Search active and inactive equity instruments by symbol or company name.

    Ordering priority:
    1. Exact symbol match
    2. Prefix symbol match
    3. Prefix company name match
    4. Alphabetical by symbol, series, id
    """
    search_term = query.strip()
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

    return list(db.execute(statement).all())


def get_instrument_with_company(
    db: Session,
    instrument_id: int,
) -> tuple[Instrument, Company] | None:
    """Retrieve instrument and associated company by instrument ID."""
    statement: Select[tuple[Instrument, Company]] = (
        select(Instrument, Company)
        .join(Company, Company.id == Instrument.company_id)
        .where(Instrument.id == instrument_id)
    )
    return db.execute(statement).one_or_none()


def get_latest_snapshot_with_source(
    db: Session,
    instrument_id: int,
) -> tuple[DailyMarketSnapshot, DataSource | None] | None:
    """Retrieve the most recent daily market snapshot and its data source for an instrument."""
    statement = (
        select(DailyMarketSnapshot, DataSource)
        .outerjoin(DataSource, DataSource.id == DailyMarketSnapshot.source_id)
        .where(DailyMarketSnapshot.instrument_id == instrument_id)
        .order_by(DailyMarketSnapshot.snapshot_date.desc())
        .limit(1)
    )
    return db.execute(statement).one_or_none()


def get_associated_ingestion_run(
    db: Session,
    source_id: int,
    snapshot_date: date,
) -> IngestionRun | None:
    """Find the most recent completed ingestion run matching the data source and trading date."""
    statement = (
        select(IngestionRun)
        .where(
            IngestionRun.source_id == source_id,
            IngestionRun.trading_date == snapshot_date,
        )
        .order_by(IngestionRun.completed_at.desc(), IngestionRun.id.desc())
        .limit(1)
    )
    return db.execute(statement).scalar_one_or_none()
