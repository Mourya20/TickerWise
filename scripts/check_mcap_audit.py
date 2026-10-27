import csv
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.db.session import SessionLocal
from app.models.company import Company
from app.models.instrument import Instrument
from app.models.daily_market_snapshot import DailyMarketSnapshot
from app.models.instrument_share_count import InstrumentShareCount

db = SessionLocal()

print("--- DB COUNTS ---")
total_instruments = db.query(Instrument).count()
total_snapshots = db.query(DailyMarketSnapshot).count()
total_share_counts = db.query(InstrumentShareCount).count()
print(f"Total Instruments: {total_instruments}")
print(f"Total Snapshots: {total_snapshots}")
print(f"Total Share Counts in DB: {total_share_counts}")

# Check snapshots by date
from sqlalchemy import func
date_counts = (
    db.query(DailyMarketSnapshot.snapshot_date, func.count(DailyMarketSnapshot.id), func.count(DailyMarketSnapshot.market_capitalization_crores))
    .group_by(DailyMarketSnapshot.snapshot_date)
    .order_by(DailyMarketSnapshot.snapshot_date.asc())
    .all()
)
print("\n--- SNAPSHOTS BY DATE (Date, Total, With MarketCap) ---")
for d, total, with_mcap in date_counts:
    print(f"Date {d}: Total {total}, With MarketCap {with_mcap}")

# Check sample instruments and their market caps
print("\n--- SAMPLE INSTRUMENTS MARKET CAP AUDIT ---")
sample_symbols = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "WIPRO", "ITC", "SBIN", "BHARTIARTL", "TATAMOTORS", "ZOMATO"]
for sym in sample_symbols:
    inst = db.query(Instrument).filter(Instrument.symbol == sym).first()
    if not inst:
        print(f"Symbol {sym}: NOT FOUND")
        continue
    # Latest snapshot
    snap = (
        db.query(DailyMarketSnapshot)
        .filter(DailyMarketSnapshot.instrument_id == inst.id)
        .order_by(DailyMarketSnapshot.snapshot_date.desc())
        .first()
    )
    # Share count
    sc = (
        db.query(InstrumentShareCount)
        .filter(InstrumentShareCount.instrument_id == inst.id)
        .order_by(InstrumentShareCount.reporting_date.desc())
        .first()
    )
    # Check 2026-10-14 snapshot (Stage 1)
    s1_snap = (
        db.query(DailyMarketSnapshot)
        .filter(DailyMarketSnapshot.instrument_id == inst.id, DailyMarketSnapshot.snapshot_date == "2026-10-14")
        .first()
    )
    s1_mcap = s1_snap.market_capitalization_crores if s1_snap else None
    s1_ltp = s1_snap.last_traded_price if s1_snap else None
    
    snap_mcap = snap.market_capitalization_crores if snap else None
    snap_ltp = snap.last_traded_price if snap else None
    snap_date = snap.snapshot_date if snap else None
    
    print(f"Symbol: {sym:12} | Latest Snap Date: {snap_date} | Latest LTP: {snap_ltp} | Latest Snap MCAP: {snap_mcap} | S1 MCAP (2026-10-14): {s1_mcap} (LTP: {s1_ltp}) | ShareCount: {sc.reported_share_count if sc else 'NONE'}")

db.close()
