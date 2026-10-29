from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

# Setup paths so app modules can be imported
PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
LOGS_DIR = PROJECT_ROOT / "logs"
sys.path.insert(0, str(BACKEND_DIR))

from app.providers.tejhq import TejHQProvider  # noqa: E402
from app.ingestion.eod_service import EODUpdateService  # noqa: E402
from app.market_data.backfill import HistoricalBackfillService  # noqa: E402
from app.workers import (  # noqa: E402
    check_provider_status,
    run_backfill_worker,
    run_catchup_worker,
    run_eod_worker,
)


def setup_logging(verbose: bool = False) -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOGS_DIR / "eod_update.log"

    log_level = logging.DEBUG if verbose else logging.INFO
    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.setLevel(log_level)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(log_level)

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.handlers.clear()
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)


def parse_date(value: str) -> date:
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid date format '{value}'. Expected YYYY-MM-DD.") from exc


def main() -> int:
    parser = argparse.ArgumentParser(
        description="TickerWise Automated End-of-Day (EOD) Market Data Ingestion"
    )
    parser.add_argument(
        "--date",
        type=parse_date,
        default=None,
        help="Target trading date in YYYY-MM-DD. If omitted, checks provider status for latest published date.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-ingestion even if this trading date was already processed.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and validate data without writing to database.",
    )
    parser.add_argument(
        "--check-status",
        action="store_true",
        help="Check provider freshness status and exit.",
    )
    parser.add_argument(
        "--catch-up",
        action="store_true",
        help="Sequentially catch up all missing trading dates between local database and latest provider publication.",
    )
    parser.add_argument(
        "--backfill-symbol",
        type=str,
        default=None,
        help="Symbol to backfill historical OHLCV data for into the database.",
    )
    parser.add_argument(
        "--backfill-symbols",
        type=str,
        default=None,
        help="Comma-separated list of symbols to backfill historical OHLCV data for.",
    )
    parser.add_argument(
        "--from-date",
        type=parse_date,
        default=None,
        help="Start date for backfill in YYYY-MM-DD.",
    )
    parser.add_argument(
        "--to-date",
        type=parse_date,
        default=None,
        help="End date for backfill in YYYY-MM-DD.",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Do not resume backfill from checkpoint; re-process all specified symbols.",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable debug logging.",
    )
    parser.add_argument(
        "--min-coverage",
        type=int,
        default=EODUpdateService.DEFAULT_MIN_COVERAGE_THRESHOLD,
        help="Minimum required matched instruments for a successful EOD run (default: 1500).",
    )

    args = parser.parse_args()
    setup_logging(args.verbose)
    logger = logging.getLogger("eod_update")

    # Check provider status mode
    if args.check_status:
        try:
            status = check_provider_status()
            print("\n--- Provider Status ---")
            print(f"Provider:             {status['provider_name']}")
            print(f"Latest Trading Date:  {status['trading_date']}")
            print(f"Pipeline Stage:       {status['stage']}")
            print(f"Prices Published At:  {status['prices_published_at']}")
            print(f"Derived Published At: {status['derived_published_at']}")
            print(f"Is Fresh:             {status['is_fresh']}")
            print(f"Run URL:              {status['run_url']}")
            return 0
        except Exception as exc:
            logger.error("Failed to check provider status: %s", exc)
            return 1

    # Catch-up mode
    if args.catch_up:
        results = run_catchup_worker(dry_run=args.dry_run, min_coverage_threshold=args.min_coverage)
        if not results:
            print("\nDatabase is already up to date with the latest published provider trading date.")
            return 0

        print(f"\n================ CATCH-UP SUMMARY ({len(results)} session(s)) ================")
        has_failure = False
        has_partial = False
        for res in results:
            print(f"[{res.trading_date}] Status: {res.status.upper()} | Inserted: {res.records_inserted} | Updated: {res.records_updated} | Skipped: {res.records_skipped} | Failed: {res.records_failed}")
            if res.status == "failed":
                has_failure = True
            elif res.status == "partial":
                has_partial = True
        print("========================================================================\n")
        if has_failure:
            return 1
        elif has_partial:
            return 2
        return 0

    # Backfill mode
    symbols_to_backfill: list[str] = []
    if args.backfill_symbol:
        symbols_to_backfill.append(args.backfill_symbol.strip().upper())
    elif args.backfill_symbols:
        symbols_to_backfill = [s.strip().upper() for s in args.backfill_symbols.split(",") if s.strip()]

    if symbols_to_backfill:
        try:
            audit = run_backfill_worker(
                symbols=symbols_to_backfill,
                from_date=args.from_date,
                to_date=args.to_date,
                resume=not args.no_resume,
                dry_run=args.dry_run,
            )
            print("\n================ HISTORICAL BACKFILL REPORT ================")
            print(f"Symbols Requested: {audit.symbols_requested}")
            print(f"Symbols Completed: {audit.symbols_completed}")
            print(f"Symbols Failed:    {audit.symbols_failed}")
            print(f"Bars Read:         {audit.bars_read}")
            print(f"Bars Inserted:     {audit.bars_inserted}")
            print(f"Bars Updated:      {audit.bars_updated}")
            print(f"Bars Skipped:      {audit.bars_skipped}")
            print(f"Bars Failed:       {audit.bars_failed}")
            if audit.failures:
                print(f"First 5 Errors:    {audit.failures[:5]}")
            print("============================================================\n")
            return 0 if audit.symbols_failed == 0 else 1
        except Exception as exc:
            logger.error("Historical backfill error: %s", exc)
            return 1

    # Daily EOD Update
    result = run_eod_worker(
        target_date=args.date,
        force=args.force,
        dry_run=args.dry_run,
        min_coverage_threshold=args.min_coverage,
    )

    print("\n================ EOD INGESTION REPORT ================")
    print(f"Status:            {result.status.upper()}")
    print(f"Trading Date:      {result.trading_date}")
    print(f"Ingestion Run ID:  {result.run_id}")
    print(f"Records Read:      {result.records_read}")
    print(f"Records Inserted:  {result.records_inserted}")
    print(f"Records Updated:   {result.records_updated}")
    print(f"Records Skipped:   {result.records_skipped}")
    print(f"Records Failed:    {result.records_failed}")
    print(f"Records Unmatched: {result.records_unmatched}")
    print(f"Discovered IPOs:   {result.instruments_discovered}")
    if result.review_path:
        print(f"Review CSV:        {result.review_path}")
    print(f"Message:           {result.message}")
    print("======================================================")

    if result.status == "failed":
        return 1
    elif result.status == "partial":
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

