from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime
from pathlib import Path

# Setup paths so app modules can be imported
PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
LOGS_DIR = PROJECT_ROOT / "logs"
sys.path.insert(0, str(BACKEND_DIR))

from app.providers.tejhq import TejHQProvider  # noqa: E402
from app.services.eod_update_service import EODUpdateService  # noqa: E402


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
        "--backfill-symbol",
        type=str,
        default=None,
        help="Symbol to backfill historical OHLCV data for.",
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
        provider = TejHQProvider()
        try:
            status = provider.get_status()
            print("\n--- Provider Status ---")
            print(f"Provider:             {status.provider_name}")
            print(f"Latest Trading Date:  {status.trading_date}")
            print(f"Pipeline Stage:       {status.stage}")
            print(f"Prices Published At:  {status.prices_published_at}")
            print(f"Derived Published At: {status.derived_published_at}")
            print(f"Is Fresh:             {status.is_fresh}")
            print(f"Run URL:              {status.run_url}")
            return 0
        except Exception as exc:
            logger.error("Failed to check provider status: %s", exc)
            return 1

    # Backfill symbol mode
    if args.backfill_symbol:
        if not args.from_date or not args.to_date:
            logger.error("--from-date and --to-date are required when using --backfill-symbol")
            return 1
        provider = TejHQProvider()
        try:
            logger.info(
                "Fetching historical OHLCV for %s from %s to %s...",
                args.backfill_symbol,
                args.from_date,
                args.to_date,
            )
            rows = provider.get_historical_ohlcv(
                args.backfill_symbol, args.from_date, args.to_date
            )
            logger.info("Successfully fetched %d OHLCV rows for %s", len(rows), args.backfill_symbol)
            for r in rows:
                print(f"  {r.date}: Open={r.open}, High={r.high}, Low={r.low}, Close={r.close}, LTP={r.last_price}, Volume={r.volume}")
            return 0
        except Exception as exc:
            logger.error("Historical OHLCV fetch failed: %s", exc)
            return 1

    # Daily EOD Update
    service = EODUpdateService()
    result = service.run_update(
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
