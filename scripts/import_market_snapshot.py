from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import select  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    DataSource,
    DailyMarketSnapshot,
    IngestionRun,
    Instrument,
)

SOURCE_NAME = "NSE Traded Market Snapshot CSV"
SOURCE_TYPE = "manual_csv"
SOURCE_URL = "https://www.nseindia.com/market-data/live-equity-market"
DEFAULT_CSV = PROJECT_ROOT / "data" / "raw" / "StocksTraded.csv"
REVIEW_DIR = PROJECT_ROOT / "data" / "rejected"

HEADER_SYMBOL = "SYMBOL"
HEADER_SERIES = "SERIES"
HEADER_LTP = "LTP"
HEADER_CHANGE = "%CHANGE"
HEADER_MARKET_CAP = "MARKET CAPITAL (₹ CRORES)"
HEADER_VOLUME = "VOLUME (LAKHS)"
HEADER_VALUE = "VALUE (₹ CRORES)"
REQUIRED_HEADERS = {
    HEADER_SYMBOL,
    HEADER_SERIES,
    HEADER_LTP,
    HEADER_CHANGE,
    HEADER_MARKET_CAP,
    HEADER_VOLUME,
    HEADER_VALUE,
}


@dataclass(frozen=True)
class ImportResult:
    records_read: int
    records_inserted: int
    records_updated: int
    records_skipped: int
    records_failed: int
    records_unmatched: int
    review_path: Path | None


def utc_naive_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def normalized_header(value: object) -> str:
    return " ".join(str(value).strip().upper().split())


def normalized_text(value: object) -> str:
    return "" if value is None else str(value).strip()


def normalized_row(raw: dict[str | None, object]) -> dict[str, str]:
    return {
        normalized_header(key): normalized_text(value)
        for key, value in raw.items()
        if key is not None
    }


def parse_snapshot_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(
            f"Invalid snapshot date {value!r}; expected YYYY-MM-DD."
        ) from exc


def parse_decimal(value: str, field_name: str) -> Decimal | None:
    if not value:
        return None
    try:
        parsed = Decimal(value.replace(",", ""))
    except InvalidOperation as exc:
        raise ValueError(f"Invalid {field_name}: {value!r}") from exc
    if not parsed.is_finite():
        raise ValueError(f"Invalid {field_name}: {value!r}")
    return parsed


def parse_market_values(row: dict[str, str]) -> tuple[Decimal | None, ...]:
    return (
        parse_decimal(row.get(HEADER_LTP, ""), "LTP"),
        parse_decimal(row.get(HEADER_CHANGE, ""), "%CHANGE"),
        parse_decimal(
            row.get(HEADER_MARKET_CAP, ""),
            "MARKET CAPITAL (₹ Crores)",
        ),
        parse_decimal(row.get(HEADER_VOLUME, ""), "VOLUME (Lakhs)"),
        parse_decimal(row.get(HEADER_VALUE, ""), "VALUE (₹ Crores)"),
    )


def resolve_instrument(
    symbol: str,
    series: str | None,
    exact_instruments: dict[tuple[str, str, str], Instrument],
    symbol_instruments: dict[tuple[str, str], list[Instrument]],
) -> tuple[Instrument | None, str | None]:
    if series:
        instrument = exact_instruments.get(("NSE", symbol, series))
        if instrument is None:
            return None, f"No instrument matched {symbol}/{series}."
        return instrument, None

    candidates = symbol_instruments.get(("NSE", symbol), [])
    if len(candidates) != 1:
        return None, f"Missing SERIES has {len(candidates)} candidates for {symbol}."
    return candidates[0], None


def classify_duplicate(
    previous_values: tuple[Decimal | None, ...] | None,
    values: tuple[Decimal | None, ...],
) -> str | None:
    if previous_values is None:
        return None
    return "skipped" if previous_values == values else "failed"


def read_input(
    csv_path: Path,
) -> tuple[list[str], list[dict[str | None, str]]]:
    if not csv_path.is_file():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError("The CSV has no header row.")

        normalized_headers = [normalized_header(header) for header in reader.fieldnames]
        missing = sorted(REQUIRED_HEADERS - set(normalized_headers))
        if missing:
            raise ValueError(
                "CSV is missing required column(s): " + ", ".join(missing)
            )
        if len(normalized_headers) != len(set(normalized_headers)):
            raise ValueError("CSV contains duplicate column names after normalization.")

        rows = [
            row
            for row in reader
            if any(normalized_text(value) for value in row.values())
        ]
        return list(reader.fieldnames), rows


def get_source_id() -> int:
    with SessionLocal() as session:
        source = session.scalar(
            select(DataSource).where(DataSource.name == SOURCE_NAME)
        )
        if source is None:
            source = DataSource(
                name=SOURCE_NAME,
                source_type=SOURCE_TYPE,
                source_url=SOURCE_URL,
                terms_url=None,
                is_active=True,
            )
            session.add(source)
        else:
            if not source.source_type:
                source.source_type = SOURCE_TYPE
            if not source.source_url:
                source.source_url = SOURCE_URL

        session.flush()
        source_id = int(source.id)
        session.commit()
        return source_id


def create_ingestion_run(source_id: int, snapshot_date: date) -> int:
    with SessionLocal() as session:
        run = IngestionRun(
            source_id=source_id,
            dataset_name=f"market_snapshot_{snapshot_date.isoformat()}",
            status="running",
            records_read=0,
            records_inserted=0,
            records_updated=0,
            records_skipped=0,
            records_failed=0,
            records_unmatched=0,
        )
        session.add(run)
        session.commit()
        return int(run.id)


def write_review_rows(
    original_headers: list[str],
    review_rows: list[tuple[dict[str | None, str], str, str]],
) -> Path | None:
    if not review_rows:
        return None

    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    review_path = REVIEW_DIR / f"market_snapshot_review_{stamp}.csv"
    output_headers = [*original_headers, "REVIEW_CATEGORY", "REVIEW_REASON"]

    with review_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=output_headers,
            extrasaction="ignore",
        )
        writer.writeheader()
        for raw_row, category, reason in review_rows:
            output = dict(raw_row)
            output["REVIEW_CATEGORY"] = category
            output["REVIEW_REASON"] = reason
            writer.writerow(output)

    return review_path


def import_rows(
    original_headers: list[str],
    raw_rows: list[dict[str | None, str]],
    source_id: int,
    run_id: int,
    snapshot_date: date,
) -> ImportResult:
    inserted = 0
    updated = 0
    skipped = 0
    failed = 0
    unmatched = 0
    review_rows: list[tuple[dict[str | None, str], str, str]] = []

    try:
        with SessionLocal() as session:
            run = session.get(IngestionRun, run_id)
            if run is None:
                raise RuntimeError(f"Ingestion run {run_id} could not be found.")

            instruments = session.scalars(select(Instrument)).all()
            exact_instruments: dict[tuple[str, str, str], Instrument] = {}
            symbol_instruments: dict[tuple[str, str], list[Instrument]] = {}
            for instrument in instruments:
                exchange = instrument.exchange.strip().upper()
                symbol = instrument.symbol.strip().upper()
                series = instrument.series.strip().upper()
                exact_instruments[(exchange, symbol, series)] = instrument
                symbol_instruments.setdefault((exchange, symbol), []).append(instrument)

            snapshots = session.scalars(
                select(DailyMarketSnapshot).where(
                    DailyMarketSnapshot.snapshot_date == snapshot_date
                )
            ).all()
            snapshots_by_key = {
                (snapshot.instrument_id, snapshot.snapshot_date): snapshot
                for snapshot in snapshots
            }
            input_values_by_key: dict[tuple[int, date], tuple[Decimal | None, ...]] = {}

            for raw in raw_rows:
                row = normalized_row(raw)
                try:
                    symbol = row.get(HEADER_SYMBOL, "").upper()
                    series = row.get(HEADER_SERIES, "").upper() or None
                    if not symbol:
                        raise ValueError("Missing SYMBOL")

                    values = parse_market_values(row)
                except ValueError as exc:
                    failed += 1
                    review_rows.append((raw, "failed", str(exc)))
                    continue

                instrument, match_error = resolve_instrument(
                    symbol,
                    series,
                    exact_instruments,
                    symbol_instruments,
                )
                if instrument is None:
                    unmatched += 1
                    review_rows.append((raw, "unmatched", match_error or "No match."))
                    continue

                key = (int(instrument.id), snapshot_date)
                duplicate_result = classify_duplicate(
                    input_values_by_key.get(key), values
                )
                if duplicate_result is not None:
                    if duplicate_result == "skipped":
                        skipped += 1
                    else:
                        failed += 1
                        review_rows.append(
                            (
                                raw,
                                "failed",
                                "Conflicting duplicate input row for the same instrument/date.",
                            )
                        )
                    continue
                input_values_by_key[key] = values

                fields = {
                    "last_traded_price": values[0],
                    "percentage_change_pct": values[1],
                    "market_capitalization_crores": values[2],
                    "volume_lakhs": values[3],
                    "traded_value_crores": values[4],
                }
                snapshot = snapshots_by_key.get(key)
                if snapshot is None:
                    snapshot = DailyMarketSnapshot(
                        instrument_id=instrument.id,
                        source_id=source_id,
                        snapshot_date=snapshot_date,
                        **fields,
                    )
                    session.add(snapshot)
                    snapshots_by_key[key] = snapshot
                    inserted += 1
                    continue

                row_changed = False
                for field, new_value in fields.items():
                    if getattr(snapshot, field) != new_value:
                        setattr(snapshot, field, new_value)
                        row_changed = True
                if row_changed:
                    updated += 1
                else:
                    skipped += 1

            review_path = write_review_rows(original_headers, review_rows)
            run.records_read = len(raw_rows)
            run.records_inserted = inserted
            run.records_updated = updated
            run.records_skipped = skipped
            run.records_failed = failed
            run.records_unmatched = unmatched
            run.completed_at = utc_naive_now()
            run.status = "partial" if failed or unmatched else "completed"
            if review_path is None:
                run.error_summary = None
            else:
                run.error_summary = (
                    f"{failed} failed and {unmatched} unmatched row(s). Review: "
                    f"{review_path.relative_to(PROJECT_ROOT)}"
                )
            session.commit()

        return ImportResult(
            records_read=len(raw_rows),
            records_inserted=inserted,
            records_updated=updated,
            records_skipped=skipped,
            records_failed=failed,
            records_unmatched=unmatched,
            review_path=review_path,
        )
    except Exception as exc:
        with SessionLocal() as error_session:
            failed_run = error_session.get(IngestionRun, run_id)
            if failed_run is not None:
                failed_run.status = "failed"
                failed_run.completed_at = utc_naive_now()
                failed_run.error_summary = str(exc)[:60000]
                error_session.commit()
        raise


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
