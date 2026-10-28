"""CLI script to backfill historical OHLCV data for NSE equity instruments."""

import argparse
import logging
import sys
from datetime import date, datetime
from pathlib import Path

# Add backend directory to path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.db.session import SessionLocal
from app.models import DailyMarketSnapshot, Instrument
from app.services.historical_backfill_service import HistoricalBackfillService
from sqlalchemy import func, select

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("historical_backfill")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Backfill historical OHLCV data for NSE equity instruments."
    )
    parser.add_argument(
        "--symbols",
        type=str,
        help="Comma-separated list of symbols to backfill (e.g. RELIANCE,TCS,LTFOODS)",
    )
    parser.add_argument(
        "--from-date",
        dest="from_date",
        type=str,
        default="2020-01-01",
        help="Start date in YYYY-MM-DD format (default: 2020-01-01)",
    )
    parser.add_argument(
        "--to-date",
        dest="to_date",
        type=str,
        default=None,
        help="End date in YYYY-MM-DD format (default: latest trading date or today)",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=None,
        help="Backfill the top N instruments sorted by traded turnover in latest snapshot",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.1,
        help="Delay in seconds between provider requests (default: 0.1)",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Do not resume from checkpoint file; reprocess all symbols",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Perform validation without saving to database",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    from_d = date.fromisoformat(args.from_date)
    to_d = (
        date.fromisoformat(args.to_date)
        if args.to_date
        else date.today()
    )

    symbols: list[str] = []

    with SessionLocal() as session:
        if args.symbols:
            symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
        elif args.top:
            latest_snap_date = session.scalar(
                select(func.max(DailyMarketSnapshot.snapshot_date))
            )
            logger.info("Selecting top %d instruments by turnover on %s...", args.top, latest_snap_date)
            rows = session.execute(
                select(Instrument.symbol)
                .join(DailyMarketSnapshot, DailyMarketSnapshot.instrument_id == Instrument.id)
                .where(
                    DailyMarketSnapshot.snapshot_date == latest_snap_date,
                    Instrument.series == "EQ",
                )
                .order_by(DailyMarketSnapshot.turnover.desc())
                .limit(args.top)
            ).all()
            symbols = [r[0] for r in rows]
        else:
            logger.error("Must specify --symbols or --top N")
            sys.exit(1)

    logger.info(
        "Starting backfill for %d symbols from %s to %s (resume=%s, delay=%.2fs)...",
        len(symbols),
        from_d,
        to_d,
        not args.no_resume,
        args.delay,
    )

    svc = HistoricalBackfillService()
    audit = svc.backfill_instruments(
        symbols=symbols,
        from_date=from_d,
        to_date=to_d,
        resume=not args.no_resume,
        delay_seconds=args.delay,
        dry_run=args.dry_run,
    )

    logger.info("=" * 60)
    logger.info("BACKFILL COMPLETED")
    logger.info("Symbols requested:   %d", audit.symbols_requested)
    logger.info("Symbols completed:   %d", audit.symbols_completed)
    logger.info("Symbols empty:       %d", audit.symbols_empty)
    logger.info("Symbols quarantined: %d", audit.symbols_quarantined)
    logger.info("Symbols failed:      %d", audit.symbols_failed)
    logger.info("Bars read:           %d", audit.bars_read)
    logger.info("Bars inserted:       %d", audit.bars_inserted)
    logger.info("Bars updated:        %d", audit.bars_updated)
    logger.info("Bars skipped:        %d", audit.bars_skipped)
    logger.info("Bars failed:         %d", audit.bars_failed)
    if audit.failures:
        logger.info("Failures / Notes (%d):", len(audit.failures))
        for f in audit.failures[:10]:
            logger.info("  - %s", f)
        if len(audit.failures) > 10:
            logger.info("  ... and %d more", len(audit.failures) - 10)
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
