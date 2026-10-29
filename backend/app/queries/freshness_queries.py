"""Read-only queries to compute market snapshot data freshness from persisted records."""
from __future__ import annotations

from datetime import date
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import DailyMarketSnapshot, IngestionRun


def compute_snapshot_freshness(
    snapshot_date: date | None,
    db: Session,
) -> tuple[bool, str]:
    """Computes (is_stale, freshness_status) for a market snapshot.

    Freshness is derived strictly from persisted EOD ingestion runs and snapshot trading dates
    without triggering remote network calls or relying naively on current clock time.

    Returns:
        tuple[is_stale: bool, freshness_status: str]
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
