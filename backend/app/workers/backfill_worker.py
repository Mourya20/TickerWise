"""Historical OHLCV Price Backfill Worker.

Executes symbol batch historical price ingestion, checkpoint tracking, and rate-limited API fetching.
"""
from __future__ import annotations

import argparse
import logging
from datetime import date, datetime, timedelta
from typing import Sequence

from app.providers.tejhq import TejHQProvider
from app.services.historical_backfill_service import (
    BackfillAudit,
    HistoricalBackfillService,
)

logger = logging.getLogger("app.workers.backfill")


def parse_date(value: str) -> date:
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid date format '{value}'. Expected YYYY-MM-DD."
        ) from exc


def run_backfill_worker(
    symbols: Sequence[str],
    from_date: date | None = None,
    to_date: date | None = None,
    resume: bool = True,
    dry_run: bool = False,
    delay_seconds: float = 0.2,
) -> BackfillAudit:
    """Execute historical price backfill across target symbols."""
    clean_symbols = [s.strip().upper() for s in symbols if s.strip()]
    if not clean_symbols:
        raise ValueError("At least one symbol must be specified for backfill.")

    actual_from = from_date or HistoricalBackfillService.DEFAULT_HISTORICAL_START_DATE
    actual_to = to_date
    if not actual_to:
        try:
            provider_status = TejHQProvider().get_status()
            actual_to = provider_status.trading_date or (date.today() - timedelta(days=1))
        except Exception:
            actual_to = date.today() - timedelta(days=1)

    service = HistoricalBackfillService()
    logger.info(
        "Starting historical backfill worker for %d symbols (%s to %s, resume=%s, dry_run=%s)...",
        len(clean_symbols),
        actual_from,
        actual_to,
        resume,
        dry_run,
    )

    audit = service.backfill_instruments(
        symbols=clean_symbols,
        from_date=actual_from,
        to_date=actual_to,
        resume=resume,
        dry_run=dry_run,
        delay_seconds=delay_seconds,
    )

    logger.info(
        "Historical backfill worker completed: %d/%d symbols succeeded (%d bars inserted, %d updated, %d failed)",
        audit.symbols_completed,
        audit.symbols_requested,
        audit.bars_inserted,
        audit.bars_updated,
        audit.bars_failed,
    )
    return audit
