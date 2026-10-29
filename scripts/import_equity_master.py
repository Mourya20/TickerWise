"""Command-line script for importing an NSE equity instrument master CSV into MySQL."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Add backend directory to sys.path so app imports resolve
PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.db.session import SessionLocal
from app.ingestion.equity_master_importer import (
    DEFAULT_CSV,
    REJECTED_DIR,
    REQUIRED_HEADERS,
    SOURCE_NAME,
    SOURCE_TYPE,
    SOURCE_URL,
    EquityMasterImportResult,
    create_ingestion_run,
    get_source_id,
    import_equity_master,
    import_rows,
    normalized_name,
    normalized_row,
    normalized_text,
    parse_date,
    parse_decimal,
    parse_integer,
    read_input,
    utc_naive_now,
    write_rejected_rows,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Import an NSE equity instrument master CSV into MySQL."
    )
    parser.add_argument(
        "--file",
        type=Path,
        default=DEFAULT_CSV,
        help=f"CSV path (default: {DEFAULT_CSV})",
    )
    args = parser.parse_args()
    csv_path = args.file.expanduser().resolve()

    try:
        result = import_equity_master(csv_path)

        print("\nEquity master import finished.")
        print(f"Source file:       {csv_path}")
        print(f"Ingestion run ID:  {result.run_id}")
        print(f"Rows read:         {result.records_read}")
        print(f"Instruments added: {result.records_inserted}")
        print(f"Instruments updated: {result.records_updated}")
        print(f"Unchanged rows:    {result.records_skipped}")
        print(f"Rejected rows:     {result.records_failed}")
        if result.review_path is not None:
            print(f"Rejected row file: {result.review_path}")
        return 0
    except Exception as exc:
        print(f"Import failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
