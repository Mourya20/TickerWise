"""CLI script to synchronize exchange corporate actions for NSE equity securities."""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Add backend directory to sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import select
from app.db.session import SessionLocal
from app.models.data_source import DataSource
from app.models.ingestion_run import IngestionRun
from app.models.instrument import Instrument
from app.providers.tejhq import TejHQProvider
from app.corporate_actions.service import (
    DEFAULT_SOURCE_NAME,
    CorporateActionIngestionResult,
    CorporateActionService,
)

CHECKPOINT_FILE = PROJECT_ROOT / "data" / "corporate_actions_checkpoint.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("sync_corporate_actions")


def load_checkpoint() -> dict:
    if CHECKPOINT_FILE.exists():
        try:
            with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as exc:
            logger.warning("Failed to read checkpoint file, starting fresh: %s", exc)
    return {
        "completed_symbols": [],
        "empty_symbols": [],
        "failed_symbols": {},
        "updated_at": None,
    }


def save_checkpoint(checkpoint_data: dict) -> None:
    CHECKPOINT_FILE.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_data["updated_at"] = datetime.now(timezone.utc).isoformat()
    try:
        temp_file = CHECKPOINT_FILE.with_suffix(".tmp")
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(checkpoint_data, f, indent=2)
        temp_file.replace(CHECKPOINT_FILE)
    except Exception as exc:
        logger.warning("Failed to save checkpoint: %s", exc)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Synchronize exchange corporate actions from TejHQ for NSE equities."
    )
    parser.add_argument(
        "--symbols",
        type=str,
        help="Comma-separated list of symbols to synchronize (e.g. RELIANCE,TCS,INFY)",
    )
    parser.add_argument(
        "--top",
        type=int,
        help="Synchronize top N instruments by turnover in latest snapshot",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Synchronize all active NSE equity instruments",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.1,
        help="Delay in seconds between provider calls (default: 0.1s)",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Do not resume from checkpoint file; reprocess all requested symbols",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and validate actions without committing changes to database",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    symbols: list[str] = []

    with SessionLocal() as session:
        if args.symbols:
            symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
        elif args.top:
            from app.models.daily_market_snapshot import DailyMarketSnapshot
            from sqlalchemy import func

            latest_date = session.scalar(select(func.max(DailyMarketSnapshot.snapshot_date)))
            rows = session.execute(
                select(Instrument.symbol)
                .join(DailyMarketSnapshot, DailyMarketSnapshot.instrument_id == Instrument.id)
                .where(
                    DailyMarketSnapshot.snapshot_date == latest_date,
                    Instrument.series == "EQ",
                    Instrument.is_active == True,
                )
                .order_by(DailyMarketSnapshot.turnover.desc())
                .limit(args.top)
            ).all()
            symbols = [r[0] for r in rows]
        elif args.all:
            rows = session.execute(
                select(Instrument.symbol)
                .where(
                    Instrument.exchange == "NSE",
                    Instrument.series == "EQ",
                    Instrument.is_active == True,
                )
                .distinct()
                .order_by(Instrument.symbol.asc())
            ).all()
            symbols = [r[0] for r in rows]
        else:
            logger.error("Must specify --symbols, --top N, or --all")
            sys.exit(1)

    # Deduplicate symbols preserving order
    unique_symbols = list(dict.fromkeys(symbols))

    checkpoint = load_checkpoint() if not args.no_resume else {
        "completed_symbols": [],
        "empty_symbols": [],
        "failed_symbols": {},
        "updated_at": None,
    }

    already_done = set(checkpoint.get("completed_symbols", [])) | set(checkpoint.get("empty_symbols", []))
    symbols_to_sync = [s for s in unique_symbols if s not in already_done] if not args.no_resume else unique_symbols

    logger.info(
        "Starting corporate actions synchronization for %d symbols (total requested: %d, skipped via checkpoint: %d, dry_run=%s, delay=%.2fs)...",
        len(symbols_to_sync),
        len(unique_symbols),
        len(unique_symbols) - len(symbols_to_sync),
        args.dry_run,
        args.delay,
    )

    provider = TejHQProvider()
    ca_service = CorporateActionService(provider=provider)

    total_requested = len(unique_symbols)
    successful_fetches = 0
    confirmed_empty = 0
    failed_fetches = 0
    total_received = 0
    total_inserted = 0
    total_updated = 0
    total_unchanged = 0
    total_rejected = 0
    total_unmatched = 0
    total_ambiguous = 0

    batch_start = datetime.now(timezone.utc).replace(tzinfo=None)

    for i, symbol in enumerate(symbols_to_sync, start=1):
        logger.info("[%d/%d] Synchronizing corporate actions for %s...", i, len(symbols_to_sync), symbol)
        fetch_error: str | None = None
        actions = []

        try:
            actions = provider.get_actions(symbol)
        except Exception as exc:
            fetch_error = str(exc)
            logger.warning("Provider fetch failed for %s: %s", symbol, exc)

        with SessionLocal() as session:
            source = ca_service.get_or_create_source(session)
            source_id = source.id

            if fetch_error:
                failed_fetches += 1
                checkpoint["failed_symbols"][symbol] = fetch_error
                if not args.dry_run:
                    ca_service.record_sync_status(
                        session=session,
                        symbol=symbol,
                        status="failed",
                        records_read=0,
                        records_failed=1,
                        error_summary=fetch_error,
                        source_id=source_id,
                    )
                    session.commit()
            elif len(actions) == 0:
                confirmed_empty += 1
                successful_fetches += 1
                if symbol not in checkpoint["empty_symbols"]:
                    checkpoint["empty_symbols"].append(symbol)
                if symbol in checkpoint["failed_symbols"]:
                    del checkpoint["failed_symbols"][symbol]
                if not args.dry_run:
                    ca_service.record_sync_status(
                        session=session,
                        symbol=symbol,
                        status="empty",
                        records_read=0,
                        source_id=source_id,
                    )
                    session.commit()
            else:
                successful_fetches += 1
                audit = CorporateActionIngestionResult()
                try:
                    persisted = ca_service.ingest_actions(
                        session=session,
                        actions=actions,
                        source_id=source_id,
                        audit_result=audit,
                    )

                    total_received += audit.actions_received
                    total_inserted += audit.actions_inserted
                    total_updated += audit.actions_updated
                    total_unchanged += audit.actions_unchanged
                    total_rejected += audit.actions_rejected
                    total_unmatched += audit.actions_unmatched
                    total_ambiguous += audit.actions_ambiguous

                    status = "completed"
                    if audit.actions_rejected > 0 or audit.actions_ambiguous > 0:
                        status = "partial"

                    if not args.dry_run:
                        ca_service.record_sync_status(
                            session=session,
                            symbol=symbol,
                            status=status,
                            records_read=audit.actions_received,
                            records_inserted=audit.actions_inserted,
                            records_updated=audit.actions_updated,
                            records_skipped=audit.actions_unchanged,
                            records_failed=audit.actions_rejected,
                            records_unmatched=audit.actions_unmatched,
                            error_summary="; ".join(audit.rejection_reasons) if audit.rejection_reasons else None,
                            source_id=source_id,
                        )
                        session.commit()

                    if symbol not in checkpoint["completed_symbols"]:
                        checkpoint["completed_symbols"].append(symbol)
                    if symbol in checkpoint["failed_symbols"]:
                        del checkpoint["failed_symbols"][symbol]

                except Exception as exc:
                    session.rollback()
                    failed_fetches += 1
                    checkpoint["failed_symbols"][symbol] = str(exc)
                    logger.exception("Failed to persist corporate actions for %s: %s", symbol, exc)
                    if not args.dry_run:
                        with SessionLocal() as err_session:
                            ca_service.record_sync_status(
                                session=err_session,
                                symbol=symbol,
                                status="failed",
                                records_read=len(actions),
                                records_failed=len(actions),
                                error_summary=str(exc),
                                source_id=source_id,
                            )
                            err_session.commit()

        if not args.dry_run:
            save_checkpoint(checkpoint)

        if args.delay > 0:
            time.sleep(args.delay)

    batch_end = datetime.now(timezone.utc).replace(tzinfo=None)

    # Record overall batch IngestionRun
    if not args.dry_run and len(symbols_to_sync) > 0:
        with SessionLocal() as session:
            source = ca_service.get_or_create_source(session)
            overall_status = "completed" if failed_fetches == 0 else "partial" if successful_fetches > 0 else "failed"
            batch_run = IngestionRun(
                source_id=source.id,
                dataset_name="tejhq_corporate_actions_batch",
                trading_date=None,
                source_status="active",
                status=overall_status,
                started_at=batch_start,
                completed_at=batch_end,
                records_read=total_received,
                records_inserted=total_inserted,
                records_updated=total_updated,
                records_skipped=total_unchanged,
                records_failed=total_rejected + failed_fetches,
                records_unmatched=total_unmatched,
                error_summary=f"Symbols: requested={total_requested}, succeeded={successful_fetches}, empty={confirmed_empty}, failed={failed_fetches}",
            )
            session.add(batch_run)
            session.commit()

    logger.info("=" * 60)
    logger.info("CORPORATE ACTIONS SYNCHRONIZATION COMPLETED")
    logger.info("=" * 60)
    logger.info("Symbols requested:       %d", total_requested)
    logger.info("Symbols processed:       %d", len(symbols_to_sync))
    logger.info("Successful fetches:      %d", successful_fetches)
    logger.info("Confirmed empty (0 act): %d", confirmed_empty)
    logger.info("Failed fetches:          %d", failed_fetches)
    logger.info("-" * 60)
    logger.info("Actions received:        %d", total_received)
    logger.info("Actions inserted:        %d", total_inserted)
    logger.info("Actions updated:         %d", total_updated)
    logger.info("Actions unchanged:       %d", total_unchanged)
    logger.info("Actions rejected:        %d", total_rejected)
    logger.info("Actions unmatched:       %d", total_unmatched)
    logger.info("Actions ambiguous:       %d", total_ambiguous)
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
