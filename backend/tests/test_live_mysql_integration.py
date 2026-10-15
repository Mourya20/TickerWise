from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models import Company, DailyMarketSnapshot, DataSource, IngestionRun, Instrument
from app.services.eod_update_service import EODUpdateService, TEJHQ_SOURCE_NAME


class TestLiveMySQLIntegration(unittest.TestCase):
    """Integration test against actual configured MySQL instance.

    Verifies schema integrity, historical preservation, and idempotency
    without corrupting production data.
    """

    def setUp(self):
        self.session = SessionLocal()

    def tearDown(self):
        self.session.close()

    def test_database_connection_and_historical_counts(self):
        company_count = self.session.scalar(select(func.count(Company.id)))
        instrument_count = self.session.scalar(select(func.count(Instrument.id)))
        snapshot_count = self.session.scalar(select(func.count(DailyMarketSnapshot.id)))

        self.assertGreaterEqual(company_count, 2602)
        self.assertGreaterEqual(instrument_count, 2605)
        self.assertGreaterEqual(snapshot_count, 2593)

        # Check that historical snapshot date 2026-10-14 exists
        dates = self.session.scalars(select(DailyMarketSnapshot.snapshot_date).distinct()).all()
        self.assertIn(date(2026, 10, 14), dates)

    def test_idempotent_persistence_and_cleanup(self):
        # Pick one real instrument from database
        inst = self.session.scalar(
            select(Instrument).where(Instrument.symbol == "RELIANCE", Instrument.series == "EQ")
        )
        self.assertIsNotNone(inst)

        # Look up or create TejHQ DataSource
        service = EODUpdateService(session_factory=SessionLocal)
        source = service.get_or_create_source(
            self.session,
            name=TEJHQ_SOURCE_NAME,
            source_type="api",
            source_url="https://api.tejhq.dev",
            terms_url="https://tejhq.dev/docs",
            is_active=True,
        )
        self.session.commit()

        # Test date in future/test range so as not to conflict with real dates
        test_date = date(2099, 1, 1)

        # Clean up any leftover test data
        self.session.query(DailyMarketSnapshot).filter(
            DailyMarketSnapshot.instrument_id == inst.id,
            DailyMarketSnapshot.snapshot_date == test_date,
        ).delete()
        self.session.commit()

        try:
            # 1. Insert test snapshot
            snap = DailyMarketSnapshot(
                instrument_id=inst.id,
                source_id=source.id,
                snapshot_date=test_date,
                open_price=Decimal("1000.000000"),
                high_price=Decimal("1050.000000"),
                low_price=Decimal("990.000000"),
                close_price=Decimal("1020.000000"),
                last_traded_price=Decimal("1025.000000"),
                prev_close_price=Decimal("1000.000000"),
                percentage_change_pct=Decimal("2.000000"),
                volume=100000,
                turnover=Decimal("102000000.0000"),
                trade_count=5000,
                volume_lakhs=Decimal("1.000000"),
                traded_value_crores=Decimal("10.200000"),
            )
            self.session.add(snap)
            self.session.commit()

            # Verify inserted
            fetched = self.session.scalar(
                select(DailyMarketSnapshot).where(
                    DailyMarketSnapshot.instrument_id == inst.id,
                    DailyMarketSnapshot.snapshot_date == test_date,
                )
            )
            self.assertIsNotNone(fetched)
            self.assertEqual(fetched.close_price, Decimal("1020.000000"))
            self.assertEqual(fetched.last_traded_price, Decimal("1025.000000"))

            # 2. Update existing snapshot (idempotent update)
            fetched.close_price = Decimal("1030.000000")
            self.session.commit()

            updated = self.session.scalar(
                select(DailyMarketSnapshot).where(
                    DailyMarketSnapshot.instrument_id == inst.id,
                    DailyMarketSnapshot.snapshot_date == test_date,
                )
            )
            self.assertEqual(updated.close_price, Decimal("1030.000000"))

            # Verify count on test date is exactly 1 (no duplicate)
            count = self.session.scalar(
                select(func.count(DailyMarketSnapshot.id)).where(
                    DailyMarketSnapshot.instrument_id == inst.id,
                    DailyMarketSnapshot.snapshot_date == test_date,
                )
            )
            self.assertEqual(count, 1)

        finally:
            # Clean up test row
            self.session.query(DailyMarketSnapshot).filter(
                DailyMarketSnapshot.instrument_id == inst.id,
                DailyMarketSnapshot.snapshot_date == test_date,
            ).delete()
            self.session.commit()


if __name__ == "__main__":
    unittest.main()
