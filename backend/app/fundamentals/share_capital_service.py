"""Fundamentals and share capital domain services.

Owns dated reported share counts, shareholding pattern filings, and capital history.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics.constants import STALE_SHARE_COUNT_THRESHOLD_DAYS
from app.models.instrument_share_count import InstrumentShareCount

logger = logging.getLogger(__name__)


def is_share_count_stale(reporting_date: date | None, as_of_date: date) -> bool:
    """Return True if share count reporting date is more than 120 days before as_of_date or in the future."""
    if reporting_date is None:
        return True
    days = (as_of_date - reporting_date).days
    return bool(days > STALE_SHARE_COUNT_THRESHOLD_DAYS or days < 0)


def get_latest_reported_shares(
    session: Session,
    instrument_id: int,
    as_of_date: date | None = None,
) -> InstrumentShareCount | None:
    """Query the most recent active equity share count reported on or before as_of_date."""
    stmt = select(InstrumentShareCount).where(
        InstrumentShareCount.instrument_id == instrument_id,
        InstrumentShareCount.share_class == "EQUITY",
        InstrumentShareCount.is_active == True,
    )
    if as_of_date is not None:
        stmt = stmt.where(InstrumentShareCount.reporting_date <= as_of_date)

    stmt = stmt.order_by(
        InstrumentShareCount.reporting_date.desc(),
        InstrumentShareCount.id.desc(),
    ).limit(1)

    return session.scalar(stmt)
