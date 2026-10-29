"""NSE Shareholding Pattern Disclosure Ingestion Worker.

Processes official SEBI LODR Regulation 31 filings (.xml, .xbrl, .json, .csv)
and executes corporate action adjustments with compliance checks.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Sequence

from app.providers.nse_shareholding import (
    NSEPermissionStatus,
    NSEShareholdingIngestionService,
    NSEShareholdingParser,
    ParsedShareCount,
)

logger = logging.getLogger("app.workers.shareholding")


def check_nse_permissions() -> dict[str, object]:
    """Retrieve official legal terms and automated scraping permission status."""
    return NSEPermissionStatus.get_status_report()


def parse_filing_file(file_path: Path) -> list[ParsedShareCount]:
    """Parse a single filing file into structured ParsedShareCount objects."""
    if not file_path.is_file():
        raise FileNotFoundError(f"Filing file not found: {file_path}")

    content = file_path.read_text(encoding="utf-8", errors="replace")
    suffix = file_path.suffix.lower()

    if suffix in (".xml", ".xbrl"):
        return NSEShareholdingParser.parse_xbrl(content, source_ref=file_path.name)
    elif suffix == ".json":
        return NSEShareholdingParser.parse_json(content, source_ref=file_path.name)
    elif suffix == ".csv":
        return NSEShareholdingParser.parse_csv(content, source_ref=file_path.name)
    else:
        stripped = content.strip()
        if stripped.startswith("<"):
            return NSEShareholdingParser.parse_xbrl(content, source_ref=file_path.name)
        elif stripped.startswith("{") or stripped.startswith("["):
            return NSEShareholdingParser.parse_json(content, source_ref=file_path.name)
        else:
            return NSEShareholdingParser.parse_csv(content, source_ref=file_path.name)


def run_shareholding_worker(
    files: Sequence[Path],
    adjust_for_corporate_actions: bool = True,
) -> dict[str, int]:
    """Parse filing files and ingest into instrument_share_counts."""
    existing_files = [f for f in files if f.is_file()]
    if not existing_files:
        raise ValueError("No valid filing files provided to shareholding worker.")

    logger.info("Starting shareholding worker for %d file(s)...", len(existing_files))
    all_records: list[ParsedShareCount] = []
    for fp in existing_files:
        try:
            records = parse_filing_file(fp)
            all_records.extend(records)
            logger.info("Extracted %d shareholding record(s) from %s", len(records), fp.name)
        except Exception as exc:
            logger.error("Failed to parse %s: %s", fp.name, exc)

    if not all_records:
        logger.warning("No records extracted from provided files.")
        return {
            "total_read": 0,
            "inserted": 0,
            "updated": 0,
            "skipped": 0,
            "failed": 0,
            "unmatched": 0,
        }

    service = NSEShareholdingIngestionService()
    result = service.ingest_records(
        all_records,
        adjust_for_corporate_actions=adjust_for_corporate_actions,
    )
    logger.info(
        "Shareholding worker completed: %d read, %d inserted, %d updated, %d failed",
        result.get("total_read", 0),
        result.get("inserted", 0),
        result.get("updated", 0),
        result.get("failed", 0),
    )
    return result
