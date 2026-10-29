"""Command-line script for importing an NSE end-of-day market snapshot CSV into MySQL."""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

# Add backend directory to sys.path so app imports resolve
PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.db.session import SessionLocal
from app.ingestion.market_snapshot_importer import (
    DEFAULT_CSV,
    HEADER_CHANGE,
    HEADER_LTP,
    HEADER_MARKET_CAP,
    HEADER_SERIES,
    HEADER_SYMBOL,
    HEADER_VALUE,
    HEADER_VOLUME,
    REQUIRED_HEADERS,
    REVIEW_DIR,
    SOURCE_NAME,
    SOURCE_TYPE,
    SOURCE_URL,
    ImportResult,
    classify_duplicate,
    create_ingestion_run,
    get_source_id,
    import_market_snapshot,
    import_rows,
    normalized_header,
    normalized_row,
    normalized_text,
    parse_decimal,
    parse_market_values,
    parse_snapshot_date,
    read_input,
    resolve_instrument,
    utc_naive_now,
    write_review_rows,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Import an NSE end-of-day market snapshot into MySQL."
    )
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--snapshot-date", required=True)
    args = parser.parse_args()
    csv_path = args.file.expanduser().resolve()

    try:
        snapshot_date = parse_snapshot_date(args.snapshot_date)
        original_headers, raw_rows = read_input(csv_path)
        if not raw_rows:
            raise ValueError("The CSV contains no data rows.")
        source_id = get_source_id()
        run_id = create_ingestion_run(source_id, snapshot_date)
        result = import_rows(
            original_headers,
            raw_rows,
            source_id,
            run_id,
            snapshot_date,
        )
        print("\nMarket snapshot import finished.")
        print(f"Source file:       {csv_path}")
        print(f"Ingestion run ID:  {run_id}")
        print(f"Snapshot date:     {snapshot_date}")
        print(f"Rows read:         {result.records_read}")
        print(f"Snapshots added:   {result.records_inserted}")
        print(f"Snapshots updated: {result.records_updated}")
        print(f"Unchanged rows:    {result.records_skipped}")
        print(f"Failed rows:       {result.records_failed}")
        print(f"Unmatched rows:    {result.records_unmatched}")
        if result.review_path is not None:
            print(f"Review file:       {result.review_path}")
        return 2 if result.records_failed or result.records_unmatched else 0
    except Exception as exc:
        print(f"Market snapshot import failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
