from __future__ import annotations

import argparse
import csv
import sys
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

# This script lives in <project-root>/scripts. Add backend/ so imports such as
# `from app.db.session import SessionLocal` work when run from backend/.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import select  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models import Company, DataSource, IngestionRun, Instrument  # noqa: E402

SOURCE_NAME = "NSE Equity Master CSV"
SOURCE_TYPE = "manual_csv"
SOURCE_URL = "https://www.nseindia.com/static/market-data/securities-available-for-trading"
DEFAULT_CSV = PROJECT_ROOT / "data" / "raw" / "EQUITY_L.csv"
REJECTED_DIR = PROJECT_ROOT / "data" / "rejected"

REQUIRED_HEADERS = {
    "SYMBOL",
    "NAME OF COMPANY",
    "SERIES",
    "DATE OF LISTING",
    "PAID UP VALUE",
    "MARKET LOT",
    "ISIN NUMBER",
    "FACE VALUE",
}


def utc_naive_now() -> datetime:
    """Return current UTC time for storage in MySQL DATETIME columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def normalized_text(value: object) -> str:
    return "" if value is None else str(value).strip()


def normalized_name(value: str) -> str:
    return " ".join(value.casefold().split())


def normalized_row(raw: dict[str | None, object]) -> dict[str, str]:
    return {
        str(key).strip().upper(): normalized_text(value)
        for key, value in raw.items()
        if key is not None
    }


def parse_date(value: str, field_name: str) -> date | None:
    if not value:
        return None
    try:
        # Source values look like 06-OCT-2008.
        return datetime.strptime(value.title(), "%d-%b-%Y").date()
    except ValueError as exc:
        raise ValueError(f"Invalid {field_name}: {value!r}") from exc


def parse_decimal(value: str, field_name: str) -> Decimal | None:
    if not value:
        return None
    try:
        result = Decimal(value.replace(",", ""))
    except InvalidOperation as exc:
        raise ValueError(f"Invalid {field_name}: {value!r}") from exc
    if not result.is_finite():
        raise ValueError(f"Invalid {field_name}: {value!r}")
    return result


def parse_integer(value: str, field_name: str) -> int | None:
    number = parse_decimal(value, field_name)
    if number is None:
        return None
    if number != number.to_integral_value():
        raise ValueError(f"{field_name} must be a whole number: {value!r}")
    return int(number)


def read_input(csv_path: Path) -> tuple[list[str], list[dict[str | None, str]]]:
    if not csv_path.is_file():
        raise FileNotFoundError(
            f"CSV file not found: {csv_path}\n"
            f"Place EQUITY_L.csv at: {DEFAULT_CSV}"
        )

    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError("The CSV has no header row.")

        present = {str(header).strip().upper() for header in reader.fieldnames}
        missing = sorted(REQUIRED_HEADERS - present)
        if missing:
            raise ValueError(
                "CSV is missing required column(s): " + ", ".join(missing)
            )

        rows = [
            row for row in reader
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
            # Preserve any user-entered source metadata, filling only gaps.
            if not source.source_type:
                source.source_type = SOURCE_TYPE
            if not source.source_url:
                source.source_url = SOURCE_URL

        session.flush()
        source_id = int(source.id)
        session.commit()
        return source_id


def create_ingestion_run(source_id: int) -> int:
    with SessionLocal() as session:
        run = IngestionRun(
            source_id=source_id,
            dataset_name="equity_master",
            status="running",
            records_read=0,
            records_inserted=0,
            records_skipped=0,
            records_failed=0,
                records_unmatched=0,
        )
        session.add(run)
        session.commit()
        return int(run.id)


def write_rejected_rows(
    original_headers: list[str], rejected_rows: list[tuple[dict[str | None, str], str]]
) -> Path | None:
    if not rejected_rows:
        return None

    REJECTED_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    rejected_path = REJECTED_DIR / f"equity_master_rejected_{stamp}.csv"
    output_headers = [*original_headers, "IMPORT_ERROR"]

    with rejected_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=output_headers, extrasaction="ignore")
        writer.writeheader()
        for raw_row, error in rejected_rows:
            output = dict(raw_row)
            output["IMPORT_ERROR"] = error
            writer.writerow(output)

    return rejected_path


def import_rows(
    csv_path: Path,
    original_headers: list[str],
    raw_rows: list[dict[str | None, str]],
    source_id: int,
    run_id: int,
) -> tuple[int, int, int, int, Path | None]:
    inserted = 0
    updated = 0
    skipped = 0
    rejected: list[tuple[dict[str | None, str], str]] = []

    try:
        with SessionLocal() as session:
            run = session.get(IngestionRun, run_id)
            if run is None:
                raise RuntimeError(f"Ingestion run {run_id} could not be found.")

            companies = session.scalars(select(Company)).all()
            companies_by_name: dict[str, Company] = {}
            companies_by_id: dict[int, Company] = {}
            for company in companies:
                companies_by_name.setdefault(normalized_name(company.name), company)
                companies_by_id[company.id] = company

            existing_instruments = session.scalars(select(Instrument)).all()
            instruments_by_key: dict[tuple[str, str, str], Instrument] = {}
            for instrument in existing_instruments:
                key = (
                    instrument.exchange.strip().upper(),
                    instrument.symbol.strip().upper(),
                    instrument.series.strip().upper(),
                )
                instruments_by_key[key] = instrument

            for raw in raw_rows:
                row = normalized_row(raw)
                try:
                    symbol = row.get("SYMBOL", "").upper()
                    company_name = row.get("NAME OF COMPANY", "").strip()
                    series = row.get("SERIES", "").upper() or "UNSPECIFIED"
                    isin_value = row.get("ISIN NUMBER", "").upper() or None

                    if not symbol:
                        raise ValueError("Missing SYMBOL")
                    if not company_name:
                        raise ValueError("Missing NAME OF COMPANY")
                    if len(symbol) > 64:
                        raise ValueError("SYMBOL exceeds 64 characters")
                    if len(company_name) > 255:
                        raise ValueError("NAME OF COMPANY exceeds 255 characters")
                    if len(series) > 16:
                        raise ValueError("SERIES exceeds 16 characters")
                    if isin_value and len(isin_value) > 12:
                        raise ValueError("ISIN NUMBER exceeds 12 characters")

                    values = {
                        "exchange": "NSE",
                        "symbol": symbol,
                        "series": series,
                        "instrument_type": "EQUITY",
                        "isin": isin_value,
                        "listing_date": parse_date(
                            row.get("DATE OF LISTING", ""), "DATE OF LISTING"
                        ),
                        "paid_up_value": parse_decimal(
                            row.get("PAID UP VALUE", ""), "PAID UP VALUE"
                        ),
                        "market_lot": parse_integer(
                            row.get("MARKET LOT", ""), "MARKET LOT"
                        ),
                        "face_value": parse_decimal(
                            row.get("FACE VALUE", ""), "FACE VALUE"
                        ),
                    }
                except (ValueError, InvalidOperation) as exc:
                    rejected.append((raw, str(exc)))
                    continue

                company_key = normalized_name(company_name)
                instrument_key = ("NSE", symbol, series)
                instrument = instruments_by_key.get(instrument_key)

                if instrument is None:
                    company = companies_by_name.get(company_key)
                    if company is None:
                        company = Company(name=company_name)
                        session.add(company)
                        session.flush()  # Obtain the generated company ID.
                        companies_by_name[company_key] = company
                        companies_by_id[company.id] = company

                    instrument = Instrument(company_id=company.id, **values)
                    session.add(instrument)
                    instruments_by_key[instrument_key] = instrument
                    inserted += 1
                    continue

                # Preserve the company link of an existing instrument. Update its
                # linked company name when the master file reflects a name change.
                company = companies_by_id.get(instrument.company_id)
                if company is None:
                    company = session.get(Company, instrument.company_id)
                    if company is None:
                        raise RuntimeError(
                            f"Instrument {symbol}/{series} references a missing company."
                        )
                    companies_by_id[company.id] = company

                row_changed = False
                old_company_key = normalized_name(company.name)
                if company.name != company_name:
                    company.name = company_name
                    if companies_by_name.get(old_company_key) is company:
                        companies_by_name.pop(old_company_key, None)
                    companies_by_name[company_key] = company
                    row_changed = True

                for field, new_value in values.items():
                    if getattr(instrument, field) != new_value:
                        setattr(instrument, field, new_value)
                        row_changed = True

                if row_changed:
                    updated += 1
                else:
                    skipped += 1

            rejected_path = write_rejected_rows(original_headers, rejected)

            run.records_read = len(raw_rows)
            run.records_inserted = inserted
            run.records_updated = updated
            run.records_skipped = skipped
            run.records_failed = len(rejected)
            run.completed_at = utc_naive_now()
            run.status = "partial" if rejected else "completed"
            if rejected_path is not None:
                run.error_summary = (
                    f"{len(rejected)} row(s) rejected. Review: "
                    f"{rejected_path.relative_to(PROJECT_ROOT)}"
                )
            else:
                run.error_summary = None

            session.commit()

        return len(raw_rows), inserted, updated, skipped, rejected_path

    except Exception as exc:
        # The data transaction rolls back on fatal errors. Mark the separately
        # committed ingestion-run record failed so it does not stay 'running'.
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
        original_headers, raw_rows = read_input(csv_path)
        if not raw_rows:
            raise ValueError("The CSV contains no data rows.")

        source_id = get_source_id()
        run_id = create_ingestion_run(source_id)
        read, inserted, updated, skipped, rejected_path = import_rows(
            csv_path, original_headers, raw_rows, source_id, run_id
        )

        print("\nEquity master import finished.")
        print(f"Source file:       {csv_path}")
        print(f"Ingestion run ID:  {run_id}")
        print(f"Rows read:         {read}")
        print(f"Instruments added: {inserted}")
        print(f"Instruments updated: {updated}")
        print(f"Unchanged rows:    {skipped}")
        print(f"Rejected rows:     {read - inserted - updated - skipped}")
        if rejected_path is not None:
            print(f"Rejected row file: {rejected_path}")
        return 0
    except Exception as exc:
        print(f"Import failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
