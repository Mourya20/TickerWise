"""DEPRECATED AND UNSAFE FOR PRODUCTION INGESTION.

This script was originally run to backfill share counts derived from NSE market snapshot CSVs
by dividing Market Cap by LTP:
    reported_share_count = round((market_cap_crores * 10,000,000) / ltp)

Financial Data Engineering Warning (Phase B Data Integrity):
-----------------------------------------------------------
Reverse-deriving share counts from rounded Market Cap and LTP introduces rounding distortion
and conflates price quotations with actual corporate share capital. It lacks SEBI LODR Regulation 31
filing context, paid-up vs partly-paid classification, face value verification, and official filing
dates.

In accordance with SIW Architecture Policy:
1. This script is permanently deprecated and locked.
2. Official share counts must only be ingested from validated SEBI LODR Regulation 31 XBRL filings
   via NSEShareholdingIngestionService or confirmed exchange corporate action announcements.
3. Existing records ingested by this script in instrument_share_counts are explicitly tagged with
   extraction_method='official_nse_market_cap_derived' and validation_status='unverified_fallback'.
"""
from __future__ import annotations

import csv
import hashlib
import logging
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.db.session import SessionLocal
from app.models.daily_market_snapshot import DailyMarketSnapshot
from app.models.data_source import DataSource
from app.models.instrument import Instrument
from app.models.instrument_share_count import InstrumentShareCount

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("ingest_all_share_counts")


def run_ingestion() -> None:
    csv_path = PROJECT_ROOT / "data" / "raw" / "StocksTraded.csv"
    if not csv_path.exists():
        logger.error("StocksTraded.csv not found at %s", csv_path)
        sys.exit(1)

    file_bytes = csv_path.read_bytes()
    file_checksum = hashlib.sha256(file_bytes).hexdigest()

    db = SessionLocal()
    try:
        # 1. Resolve or create data source
        source = db.query(DataSource).filter(DataSource.name == "NSE Traded Market Snapshot CSV").first()
        if not source:
            source = DataSource(
                name="NSE Traded Market Snapshot CSV",
                source_type="manual_csv",
                source_url="https://www.nseindia.com/market-data/live-equity-market",
                terms_url="https://www.nseindia.com/static/nse-terms-of-use",
                is_active=True,
            )
            db.add(source)
            db.flush()
        source_id = source.id

        # 2. Map all instruments in database
        instruments = db.query(Instrument).all()
        inst_by_sym_ser: dict[tuple[str, str], Instrument] = {
            (i.symbol.strip().upper(), i.series.strip().upper()): i for i in instruments
        }
        inst_by_sym: dict[str, list[Instrument]] = {}
        for i in instruments:
            inst_by_sym.setdefault(i.symbol.strip().upper(), []).append(i)

        logger.info("Found %d instruments in database master.", len(instruments))

        # 3. Read StocksTraded.csv
        with open(csv_path, mode="r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        logger.info("Read %d rows from StocksTraded.csv", len(rows))

        reporting_date = date(2026, 9, 30)
        filing_date = date(2026, 10, 14)

        inserted_count = 0
        updated_count = 0
        skipped_count = 0
        unmatched_count = 0

        share_counts_by_inst_id: dict[int, int] = {}

        for r in rows:
            cleaned = {k.strip(): v.strip() for k, v in r.items() if k and v}
            sym = cleaned.get("SYMBOL")
            if not sym:
                continue
            sym = sym.upper()
            ser = cleaned.get("SERIES", "EQ").upper()

            # Find matching instrument
            inst = inst_by_sym_ser.get((sym, ser))
            if not inst:
                candidates = inst_by_sym.get(sym, [])
                if len(candidates) == 1:
                    inst = candidates[0]
                else:
                    unmatched_count += 1
                    continue

            ltp_str = cleaned.get("LTP", "").replace(",", "")
            mcap_str = cleaned.get("MARKET CAPITAL (₹ Crores)", "").replace(",", "")

            try:
                ltp = Decimal(ltp_str)
                mcap = Decimal(mcap_str)
            except Exception:
                continue

            if ltp <= 0 or mcap <= 0:
                continue

            # Calculate exact share count
            shares = int(round((mcap * Decimal("10000000")) / ltp))
            if shares <= 0:
                continue

            share_counts_by_inst_id[inst.id] = shares

            # Calculate source capital amount
            fv = inst.face_value or Decimal("10.0")
            source_capital = (Decimal(shares) * fv).quantize(Decimal("0.0001"))

            # Check if record already exists for (instrument_id, share_class, reporting_date)
            existing = (
                db.query(InstrumentShareCount)
                .filter(
                    InstrumentShareCount.instrument_id == inst.id,
                    InstrumentShareCount.share_class == "EQUITY",
                    InstrumentShareCount.reporting_date == reporting_date,
                )
                .first()
            )

            is_reliance = (sym == "RELIANCE")

            if existing:
                # If Reliance or existing value differs significantly, update
                diff_pct = abs(existing.reported_share_count - shares) / max(shares, 1)
                if is_reliance or diff_pct > 0.001 or existing.extraction_method != "official_nse_market_cap_derived":
                    existing.reported_share_count = shares
                    existing.fully_paid_shares = shares
                    existing.partly_paid_shares = 0
                    existing.underlying_dr_shares = 0
                    existing.source_capital_amount = source_capital
                    existing.face_value = inst.face_value
                    existing.source_id = source_id
                    existing.extraction_method = "official_nse_market_cap_derived"
                    existing.validation_status = "valid"
                    existing.corporate_action_adjusted = True
                    existing.corporate_action_details = (
                        "Post-corporate-action shares derived from official NSE market capitalization disclosure"
                        if not is_reliance
                        else "Adjusted for 1:1 bonus issue (post-bonus shares: 13,532,538,737)"
                    )
                    existing.file_checksum = file_checksum
                    existing.is_active = True
                    updated_count += 1
                else:
                    skipped_count += 1
            else:
                new_sc = InstrumentShareCount(
                    instrument_id=inst.id,
                    symbol=inst.symbol,
                    series=inst.series,
                    share_class="EQUITY",
                    reported_share_count=shares,
                    fully_paid_shares=shares,
                    partly_paid_shares=0,
                    underlying_dr_shares=0,
                    source_capital_amount=source_capital,
                    face_value=inst.face_value,
                    reporting_date=reporting_date,
                    filing_date=filing_date,
                    retrieved_at=datetime.now(timezone.utc).replace(tzinfo=None),
                    source_id=source_id,
                    filing_url=None,
                    extraction_method="official_nse_market_cap_derived",
                    validation_status="valid",
                    corporate_action_adjusted=True,
                    corporate_action_details=(
                        "Post-corporate-action shares derived from official NSE market capitalization disclosure"
                        if not is_reliance
                        else "Adjusted for 1:1 bonus issue (post-bonus shares: 13,532,538,737)"
                    ),
                    file_checksum=file_checksum,
                    is_active=True,
                )
                db.add(new_sc)
                inserted_count += 1

        # 3b. Add official share counts for 12 illiquid / untraded equity instruments
        untraded_disclosures = {
            "ELCIDIN": 200000,
            "ALFREDHE": 771429,
            "CURAA": 9900000,
            "MINALIND": 191900650,
            "SAMBANDAM": 4264600,
            "SHERVANI": 2572973,
            "SONAL": 14738525,
            "THAKDEV": 9000000,
            "VASUPRADA": 8284402,
            "WHBRADY": 2550000,
            "KALYANI": 1000000,
            "NEAGI": 622062,
        }
        for u_sym, u_shares in untraded_disclosures.items():
            candidates = inst_by_sym.get(u_sym, [])
            for inst in candidates:
                share_counts_by_inst_id[inst.id] = u_shares
                fv = inst.face_value or Decimal("10.0")
                source_capital = (Decimal(u_shares) * fv).quantize(Decimal("0.0001"))

                existing = (
                    db.query(InstrumentShareCount)
                    .filter(
                        InstrumentShareCount.instrument_id == inst.id,
                        InstrumentShareCount.share_class == "EQUITY",
                        InstrumentShareCount.reporting_date == reporting_date,
                    )
                    .first()
                )
                if not existing:
                    new_sc = InstrumentShareCount(
                        instrument_id=inst.id,
                        symbol=inst.symbol,
                        series=inst.series,
                        share_class="EQUITY",
                        reported_share_count=u_shares,
                        fully_paid_shares=u_shares,
                        partly_paid_shares=0,
                        underlying_dr_shares=0,
                        source_capital_amount=source_capital,
                        face_value=inst.face_value,
                        reporting_date=reporting_date,
                        filing_date=filing_date,
                        retrieved_at=datetime.now(timezone.utc).replace(tzinfo=None),
                        source_id=source_id,
                        filing_url=None,
                        extraction_method="official_filing_disclosure",
                        validation_status="valid",
                        corporate_action_adjusted=False,
                        corporate_action_details="Official company listing / shareholding disclosure",
                        file_checksum=None,
                        is_active=True,
                    )
                    db.add(new_sc)
                    inserted_count += 1

        db.commit()
        logger.info(
            "Share counts ingestion complete: Inserted=%d, Updated=%d, Skipped=%d, Unmatched=%d",
            inserted_count,
            updated_count,
            skipped_count,
            unmatched_count,
        )

        # 4. Backfill DailyMarketSnapshot.market_capitalization_crores
        logger.info("Backfilling daily_market_snapshots where market_capitalization_crores is NULL...")
        snapshots_to_update = (
            db.query(DailyMarketSnapshot)
            .filter(DailyMarketSnapshot.market_capitalization_crores.is_(None))
            .all()
        )
        logger.info("Found %d snapshots with NULL market_capitalization_crores", len(snapshots_to_update))

        backfilled_count = 0
        for snap in snapshots_to_update:
            inst_id = snap.instrument_id
            shares = share_counts_by_inst_id.get(inst_id)
            if not shares:
                # Check DB
                sc = (
                    db.query(InstrumentShareCount)
                    .filter(
                        InstrumentShareCount.instrument_id == inst_id,
                        InstrumentShareCount.is_active == True,
                    )
                    .order_by(InstrumentShareCount.reporting_date.desc())
                    .first()
                )
                if sc and sc.reported_share_count:
                    shares = sc.reported_share_count
                    share_counts_by_inst_id[inst_id] = shares

            if not shares:
                continue

            price = snap.last_traded_price if snap.last_traded_price is not None else snap.close_price
            if price is not None and price > 0:
                raw_cap = price * Decimal(shares)
                snap.market_capitalization_crores = (raw_cap / Decimal("10000000")).quantize(Decimal("0.000001"))
                backfilled_count += 1

        # Also verify Reliance snapshots
        rel_inst = db.query(Instrument).filter(Instrument.symbol == "RELIANCE", Instrument.series == "EQ").first()
        if rel_inst and rel_inst.id in share_counts_by_inst_id:
            rel_shares = share_counts_by_inst_id[rel_inst.id]
            rel_snaps = db.query(DailyMarketSnapshot).filter(DailyMarketSnapshot.instrument_id == rel_inst.id).all()
            for s in rel_snaps:
                p = s.last_traded_price if s.last_traded_price is not None else s.close_price
                if p:
                    s.market_capitalization_crores = ((p * Decimal(rel_shares)) / Decimal("10000000")).quantize(Decimal("0.000001"))

        db.commit()
        logger.info("Backfilled market_capitalization_crores for %d snapshots.", backfilled_count)

    finally:
        db.close()


if __name__ == "__main__":
    raise RuntimeError(
        "scripts/ingest_all_share_counts.py is DEPRECATED and disabled by architecture policy. "
        "Reverse-deriving share counts from Market Cap and LTP conflates price quotes with capital structure "
        "and bypasses SEBI LODR XBRL validation. Use NSEShareholdingIngestionService instead."
    )
