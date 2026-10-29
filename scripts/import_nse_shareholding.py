from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.providers.nse_shareholding import (  # noqa: E402
    NSEPermissionStatus,
    NSEShareholdingIngestionService,
    NSEShareholdingParser,
    ParsedShareCount,
)
from app.workers import (  # noqa: E402
    check_nse_permissions,
    parse_filing_file,
    run_shareholding_worker,
)

logger = logging.getLogger("import_shareholding")


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="[%(asctime)s] [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def process_file(
    file_path: Path,
) -> list[ParsedShareCount]:
    content = file_path.read_text(encoding="utf-8", errors="replace")
    suffix = file_path.suffix.lower()

    if suffix in (".xml", ".xbrl"):
        return NSEShareholdingParser.parse_xbrl(content, source_ref=file_path.name)
    elif suffix == ".json":
        return NSEShareholdingParser.parse_json(content, source_ref=file_path.name)
    elif suffix == ".csv":
        return NSEShareholdingParser.parse_csv(content, source_ref=file_path.name)
    else:
        # Auto-detect from content
        stripped = content.strip()
        if stripped.startswith("<"):
            return NSEShareholdingParser.parse_xbrl(content, source_ref=file_path.name)
        elif stripped.startswith("{") or stripped.startswith("["):
            return NSEShareholdingParser.parse_json(content, source_ref=file_path.name)
        else:
            return NSEShareholdingParser.parse_csv(content, source_ref=file_path.name)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="TickerWise NSE Shareholding Pattern Disclosure Ingestion"
    )
    parser.add_argument(
        "--file",
        type=Path,
        help="Path to an authorized filing file (.xml, .xbrl, .json, .csv).",
    )
    parser.add_argument(
        "--dir",
        type=Path,
        help="Path to a directory containing authorized filing files.",
    )
    parser.add_argument(
        "--check-permissions",
        action="store_true",
        help="Display official NSE legal terms, scraping prohibition and automation feasibility.",
    )
    parser.add_argument(
        "--no-corporate-actions",
        action="store_true",
        help="Do not check or apply corporate-action adjustments (splits/bonuses).",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable debug logging.",
    )

    args = parser.parse_args()
    setup_logging(args.verbose)

    if args.check_permissions:
        report = NSEPermissionStatus.get_status_report()
        print("\n--- NSE Shareholding Pattern Data Permission Report ---")
        print(f"Automated Web Scraping Permitted: {report['automated_scraping_permitted']}")
        print(f"Technical Restriction:            {report['technical_restriction']}")
        print(f"Authorized Modes:                 {', '.join(report['authorized_modes'])}")
        print(f"\nLegal Terms Summary:\n{report['legal_limitation']}")
        print("--------------------------------------------------------\n")
        return 0

    if not args.file and not args.dir:
        print("Error: Specify either --file, --dir, or --check-permissions.")
        parser.print_help()
        return 1

    files_to_process: list[Path] = []
    if args.file:
        if not args.file.exists():
            print(f"Error: File not found: {args.file}")
            return 1
        files_to_process.append(args.file)
    elif args.dir:
        if not args.dir.exists() or not args.dir.is_dir():
            print(f"Error: Directory not found: {args.dir}")
            return 1
        for ext in ("*.xml", "*.xbrl", "*.json", "*.csv"):
            files_to_process.extend(args.dir.glob(ext))

    if not files_to_process:
        print("No filing files found to process.")
        return 1

    all_records: list[ParsedShareCount] = []
    for fp in files_to_process:
        try:
            logger.info("Parsing filing: %s", fp.name)
            records = process_file(fp)
            all_records.extend(records)
            logger.info("Extracted %d share count record(s) from %s", len(records), fp.name)
        except Exception as exc:
            logger.error("Failed to parse %s: %s", fp.name, exc)

    if not all_records:
        print("No valid shareholding records extracted.")
        return 1

    service = NSEShareholdingIngestionService()
    result = service.ingest_records(
        all_records,
        adjust_for_corporate_actions=not args.no_corporate_actions,
    )

    print("\n================ SHAREHOLDING INGESTION REPORT ================")
    print(f"Total Records Read:      {result['total_read']}")
    print(f"Records Inserted:        {result['inserted']}")
    print(f"Records Updated:         {result['updated']}")
    print(f"Records Skipped:         {result['skipped']}")
    print(f"Records Failed:          {result['failed']}")
    print(f"Records Unmatched:       {result['unmatched']}")
    print("===============================================================\n")

    return 0 if result["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
