"""Automated End-of-Day (EOD) Market Data Ingestion Worker.

Runs scheduled or on-demand daily EOD market data ingestion, status checks,
and sequential catch-up cycles without tying to HTTP requests.
"""
from __future__ import annotations

import argparse
import logging
from datetime import date, datetime
from typing import Sequence

from app.providers.tejhq import TejHQProvider
from app.ingestion.eod_service import EODUpdateResult, EODUpdateService

logger = logging.getLogger("app.workers.eod")


def parse_date(value: str) -> date:
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid date format '{value}'. Expected YYYY-MM-DD."
        ) from exc


def check_provider_status() -> dict[str, object]:
    """Query provider status and return metadata dict."""
    provider = TejHQProvider()
    status = provider.get_status()
    return {
        "provider_name": status.provider_name,
        "trading_date": str(status.trading_date) if status.trading_date else None,
        "stage": status.stage,
        "prices_published_at": status.prices_published_at.isoformat() if status.prices_published_at else None,
        "derived_published_at": status.derived_published_at.isoformat() if status.derived_published_at else None,
        "is_fresh": status.is_fresh,
        "run_url": status.run_url,
    }


def run_eod_worker(
    target_date: date | None = None,
    force: bool = False,
    dry_run: bool = False,
    min_coverage_threshold: int = EODUpdateService.DEFAULT_MIN_COVERAGE_THRESHOLD,
) -> EODUpdateResult:
    """Execute single-session EOD update."""
    service = EODUpdateService()
    logger.info(
        "Starting EOD update worker (date=%s, force=%s, dry_run=%s, min_coverage=%d)...",
        target_date or "auto-detect",
        force,
        dry_run,
        min_coverage_threshold,
    )
    result = service.run_update(
        target_date=target_date,
        force=force,
        dry_run=dry_run,
        min_coverage_threshold=min_coverage_threshold,
    )
    logger.info(
        "EOD update worker completed with status=%s for trading_date=%s (inserted=%d, updated=%d, skipped=%d, failed=%d)",
        result.status,
        result.trading_date,
        result.records_inserted,
        result.records_updated,
        result.records_skipped,
        result.records_failed,
    )
    return result


def run_catchup_worker(
    dry_run: bool = False,
    min_coverage_threshold: int = EODUpdateService.DEFAULT_MIN_COVERAGE_THRESHOLD,
) -> list[EODUpdateResult]:
    """Sequentially catch up all missing trading dates between local database and provider."""
    service = EODUpdateService()
    logger.info("Executing EOD catch-up sequence (dry_run=%s)...", dry_run)
    results = service.run_catchup(
        dry_run=dry_run,
        min_coverage_threshold=min_coverage_threshold,
    )
    logger.info("Catch-up completed across %d session(s)", len(results))
    return results
