"""Targeted unit tests for app.queries read-only query layer."""
from __future__ import annotations

import unittest
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.models import (
    Company,
    CorporateAction,
    DailyMarketSnapshot,
    DataSource,
    IngestionRun,
    Instrument,
    InstrumentShareCount,
)
from app.queries import (
    compute_snapshot_freshness,
    get_associated_ingestion_run,
    get_corporate_actions,
    get_instrument_with_company,
    get_latest_snapshot_with_source,
    get_price_history,
    get_share_counts,
    search_instruments,
)


class TestReadOnlyQueryLayer(unittest.TestCase):
    """Test read-only database query functions and zero-mutation guarantees."""

    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(cls.engine)
        cls.SessionLocal = sessionmaker(bind=cls.engine)

    @classmethod
    def tearDownClass(cls):
        Base.metadata.drop_all(cls.engine)

    def setUp(self):
        self.db: Session = self.SessionLocal()

        # Seed minimal test data
        self.company = Company(
            id=1,
            name="Reliance Industries Limited",
        )
        self.instrument = Instrument(
            id=101,
            company_id=1,
            exchange="NSE",
            symbol="RELIANCE",
            series="EQ",
            instrument_type="equity",
            isin="INE002A01018",
            is_active=True,
        )
        self.source = DataSource(
            id=201,
            name="TejHQ EOD Market Data",
            source_type="api",
            source_url="https://api.tejhq.dev",
            terms_url="https://tejhq.dev/docs",
            is_active=True,
        )
        self.snap1 = DailyMarketSnapshot(
            id=301,
            instrument_id=101,
            source_id=201,
            snapshot_date=date(2026, 10, 20),
            open_price=Decimal("1100.0"),
            high_price=Decimal("1120.0"),
            low_price=Decimal("1090.0"),
            close_price=Decimal("1110.0"),
            last_traded_price=Decimal("1112.0"),
            prev_close_price=Decimal("1100.0"),
            percentage_change_pct=Decimal("0.909091"),
            volume=500000,
            volume_lakhs=Decimal("5.0"),
            turnover=Decimal("555000000"),
            traded_value_crores=Decimal("55.5"),
        )
        self.snap2 = DailyMarketSnapshot(
            id=302,
            instrument_id=101,
            source_id=201,
            snapshot_date=date(2026, 10, 21),
            open_price=Decimal("1110.0"),
            high_price=Decimal("1130.0"),
            low_price=Decimal("1105.0"),
            close_price=Decimal("1125.0"),
            last_traded_price=Decimal("1128.0"),
            prev_close_price=Decimal("1110.0"),
            percentage_change_pct=Decimal("1.351351"),
            volume=600000,
            volume_lakhs=Decimal("6.0"),
            turnover=Decimal("675000000"),
            traded_value_crores=Decimal("67.5"),
        )
        self.run = IngestionRun(
            id=401,
            source_id=201,
            dataset_name="tejhq_eod_snapshot_20261021",
            trading_date=date(2026, 10, 21),
            status="completed",
            started_at=datetime(2026, 10, 21, 16, 0, 0),
            completed_at=datetime(2026, 10, 21, 16, 5, 0),
            records_read=1,
            records_inserted=1,
        )
        self.ca = CorporateAction(
            id=501,
            instrument_id=101,
            source_id=201,
            exchange="NSE",
            symbol="RELIANCE",
            event_type="bonus",
            dedup_key="NSE:RELIANCE:BONUS:2026-10-15",
            ex_date=date(2026, 10, 15),
            ratio_num=1,
            ratio_den=1,
            status="completed",
        )
        self.sc = InstrumentShareCount(
            id=601,
            instrument_id=101,
            source_id=201,
            symbol="RELIANCE",
            series="EQ",
            share_class="EQUITY",
            reported_share_count=6765000000,
            reporting_date=date(2026, 9, 30),
            is_active=True,
        )

        self.db.add_all([self.company, self.instrument, self.source, self.snap1, self.snap2, self.run, self.ca, self.sc])
        self.db.commit()

    def tearDown(self):
        self.db.query(CorporateAction).delete()
        self.db.query(InstrumentShareCount).delete()
        self.db.query(DailyMarketSnapshot).delete()
        self.db.query(IngestionRun).delete()
        self.db.query(Instrument).delete()
        self.db.query(DataSource).delete()
        self.db.query(Company).delete()
        self.db.commit()
        self.db.close()

    def test_search_instruments_query(self):
        """Search instruments by exact or partial symbol/name."""
        results = search_instruments(self.db, "RELIANCE")
        self.assertEqual(len(results), 1)
        inst, comp = results[0]
        self.assertEqual(inst.symbol, "RELIANCE")
        self.assertEqual(comp.name, "Reliance Industries Limited")

        # Prefix search
        prefix_res = search_instruments(self.db, "reli")
        self.assertEqual(len(prefix_res), 1)

        # Empty match
        nomatch_res = search_instruments(self.db, "NONEXISTENT")
        self.assertEqual(len(nomatch_res), 0)

    def test_get_instrument_with_company(self):
        """Fetch single instrument with joined company."""
        res = get_instrument_with_company(self.db, 101)
        self.assertIsNotNone(res)
        inst, comp = res
        self.assertEqual(inst.id, 101)
        self.assertEqual(comp.name, "Reliance Industries Limited")

        # Missing instrument
        missing = get_instrument_with_company(self.db, 99999)
        self.assertIsNone(missing)

    def test_get_latest_snapshot_with_source(self):
        """Fetch latest market snapshot and outerjoined source."""
        res = get_latest_snapshot_with_source(self.db, 101)
        self.assertIsNotNone(res)
        snap, src = res
        self.assertEqual(snap.snapshot_date, date(2026, 10, 21))
        self.assertEqual(snap.close_price, Decimal("1125.0"))
        self.assertIsNotNone(src)
        self.assertEqual(src.name, "TejHQ EOD Market Data")

    def test_get_associated_ingestion_run(self):
        """Find associated ingestion run by source_id and date."""
        run = get_associated_ingestion_run(self.db, 201, date(2026, 10, 21))
        self.assertIsNotNone(run)
        self.assertEqual(run.id, 401)
        self.assertEqual(run.status, "completed")

        missing = get_associated_ingestion_run(self.db, 201, date(2026, 1, 1))
        self.assertIsNone(missing)

    def test_get_price_history_query(self):
        """Fetch historical bars in ascending chronological order."""
        bars = get_price_history(self.db, 101, limit=10)
        self.assertEqual(len(bars), 2)
        # Chronological order
        self.assertEqual(bars[0][0].snapshot_date, date(2026, 10, 20))
        self.assertEqual(bars[1][0].snapshot_date, date(2026, 10, 21))

        # Filter by from_date
        filtered = get_price_history(self.db, 101, from_date=date(2026, 10, 21))
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0][0].snapshot_date, date(2026, 10, 21))

    def test_get_corporate_actions_query(self):
        """Fetch corporate actions for instrument."""
        actions = get_corporate_actions(self.db, 101)
        self.assertEqual(len(actions), 1)
        act, src = actions[0]
        self.assertEqual(act.event_type, "bonus")
        self.assertEqual(act.ratio_num, 1)
        self.assertEqual(act.ratio_den, 1)

    def test_get_share_counts_query(self):
        """Fetch reported share counts for instrument."""
        counts = get_share_counts(self.db, 101)
        self.assertEqual(len(counts), 1)
        sc, src = counts[0]
        self.assertEqual(sc.reported_share_count, 6765000000)
        self.assertEqual(sc.reporting_date, date(2026, 9, 30))

    def test_compute_snapshot_freshness_query(self):
        """Compute snapshot freshness without network or clock assumptions."""
        # Date matches max db snapshot date (2026-10-21) and completed ingestion run
        is_stale, status = compute_snapshot_freshness(date(2026, 10, 21), self.db)
        self.assertFalse(is_stale)
        self.assertEqual(status, "fresh")

        # Older date is stale
        is_stale, status = compute_snapshot_freshness(date(2026, 10, 19), self.db)
        self.assertTrue(is_stale)
        self.assertEqual(status, "stale")

    def test_strictly_zero_mutations(self):
        """Assert that running every query function causes ZERO database mutations."""
        tables = [Company, Instrument, DataSource, DailyMarketSnapshot, IngestionRun, CorporateAction, InstrumentShareCount]
        before_counts = {t.__name__: self.db.scalar(select(func.count(t.id))) for t in tables}

        # Execute every query function
        _ = search_instruments(self.db, "RELIANCE")
        _ = get_instrument_with_company(self.db, 101)
        _ = get_latest_snapshot_with_source(self.db, 101)
        _ = get_associated_ingestion_run(self.db, 201, date(2026, 10, 21))
        _ = get_price_history(self.db, 101)
        _ = get_corporate_actions(self.db, 101)
        _ = get_share_counts(self.db, 101)
        _ = compute_snapshot_freshness(date(2026, 10, 21), self.db)

        after_counts = {t.__name__: self.db.scalar(select(func.count(t.id))) for t in tables}
        self.assertEqual(before_counts, after_counts, "Queries must strictly NOT modify database records!")


if __name__ == "__main__":
    unittest.main()
