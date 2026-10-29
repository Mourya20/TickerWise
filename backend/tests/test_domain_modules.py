"""Targeted unit tests for business domain modules:

- app.instruments
- app.market_data
- app.fundamentals
- app.corporate_actions
- app.analytics
"""
from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal

from sqlalchemy import BigInteger, Integer, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.analytics import MarketCapResult, MarketCapService
from app.corporate_actions import CorporateActionService, generate_dedup_key
from app.db.base import Base
from app.fundamentals import get_latest_reported_shares, is_share_count_stale
from app.instruments import (
    DiscoveryResult,
    InstrumentDiscoveryService,
    normalize_company_name,
    resolve_or_create_company,
    validate_equity_isin,
)
from app.market_data import (
    BackfillAudit,
    HistoricalBackfillService,
    validate_ohlcv_bar,
)
from app.models import (
    Company,
    DailyMarketSnapshot,
    DataSource,
    Instrument,
    InstrumentShareCount,
)


class TestDomainModules(unittest.TestCase):
    """Test domain modules structure, business rules, and integration."""

    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(Base.metadata, "before_create", once=True)
        def fix_sqlite_pks(target, connection, **kw):
            if connection.dialect.name == "sqlite":
                for table in target.tables.values():
                    for col in table.primary_key.columns:
                        if isinstance(col.type, BigInteger):
                            col.type = Integer()

        Base.metadata.create_all(cls.engine)
        cls.SessionLocal = sessionmaker(bind=cls.engine)

    @classmethod
    def tearDownClass(cls):
        Base.metadata.drop_all(cls.engine)

    def setUp(self):
        self.db: Session = self.SessionLocal()

    def tearDown(self):
        self.db.rollback()
        self.db.query(DailyMarketSnapshot).delete()
        self.db.query(InstrumentShareCount).delete()
        self.db.query(Instrument).delete()
        self.db.query(DataSource).delete()
        self.db.query(Company).delete()
        self.db.commit()
        self.db.close()

    # --- 1. Instruments Domain ---
    def test_instruments_normalize_company_name(self):
        self.assertEqual(normalize_company_name("  TATA   MOTORS   LTD  "), "tata motors ltd")

    def test_instruments_validate_equity_isin(self):
        self.assertTrue(validate_equity_isin("INE002A01018"))
        self.assertTrue(validate_equity_isin("IN9002A01019"))
        self.assertFalse(validate_equity_isin("INF204KB14I2"))  # Mutual fund
        self.assertFalse(validate_equity_isin("US0378331005"))  # Foreign
        self.assertFalse(validate_equity_isin(""))
        self.assertFalse(validate_equity_isin(None))

    def test_instruments_resolve_or_create_company(self):
        c1 = resolve_or_create_company(self.db, "Tata Consultancy Services")
        self.assertIsNotNone(c1.id)
        self.assertEqual(c1.name, "Tata Consultancy Services")

        # Resolves existing
        c2 = resolve_or_create_company(self.db, "  Tata   Consultancy   Services  ")
        self.assertEqual(c1.id, c2.id)

    def test_instruments_discovery_service_export(self):
        self.assertTrue(hasattr(InstrumentDiscoveryService, "discover_and_onboard"))
        self.assertTrue(issubclass(DiscoveryResult, object))

    # --- 2. Market Data Domain ---
    def test_market_data_validate_ohlcv_bar(self):
        # Valid bar
        errors = validate_ohlcv_bar(
            open_price=Decimal("100"),
            high_price=Decimal("110"),
            low_price=Decimal("95"),
            close_price=Decimal("105"),
        )
        self.assertEqual(len(errors), 0)

        # High lower than Open
        errs2 = validate_ohlcv_bar(
            open_price=Decimal("120"),
            high_price=Decimal("110"),
            low_price=Decimal("95"),
            close_price=Decimal("105"),
        )
        self.assertTrue(any("High (110) < Open (120)" in e for e in errs2))

        # Low higher than Close
        errs3 = validate_ohlcv_bar(
            open_price=Decimal("100"),
            high_price=Decimal("110"),
            low_price=Decimal("108"),
            close_price=Decimal("105"),
        )
        self.assertTrue(any("Low (108) > Close (105)" in e for e in errs3))

    def test_market_data_backfill_service_export(self):
        self.assertTrue(hasattr(HistoricalBackfillService, "backfill_instruments"))
        self.assertTrue(issubclass(BackfillAudit, object))

    # --- 3. Fundamentals Domain ---
    def test_fundamentals_is_share_count_stale(self):
        today = date(2026, 10, 29)
        # Fresh (within 120 days)
        self.assertFalse(is_share_count_stale(date(2026, 9, 30), today))
        # Stale (> 120 days)
        self.assertTrue(is_share_count_stale(date(2026, 5, 1), today))
        # Future date is invalid / stale
        self.assertTrue(is_share_count_stale(date(2026, 11, 1), today))
        # None reporting date
        self.assertTrue(is_share_count_stale(None, today))

    def test_fundamentals_get_latest_reported_shares(self):
        source = DataSource(name="NSE Shareholding Pattern", source_type="api", source_url="https://nseindia.com", is_active=True)
        self.db.add(source)
        self.db.flush()

        company = Company(name="Infosys Limited")
        self.db.add(company)
        self.db.flush()

        inst = Instrument(company_id=company.id, exchange="NSE", symbol="INFY", series="EQ", instrument_type="equity", is_active=True)
        self.db.add(inst)
        self.db.flush()

        sc1 = InstrumentShareCount(
            instrument_id=inst.id, source_id=source.id, symbol="INFY", series="EQ", share_class="EQUITY",
            reported_share_count=4000000000, reporting_date=date(2026, 6, 30), is_active=True
        )
        sc2 = InstrumentShareCount(
            instrument_id=inst.id, source_id=source.id, symbol="INFY", series="EQ", share_class="EQUITY",
            reported_share_count=4150000000, reporting_date=date(2026, 9, 30), is_active=True
        )
        self.db.add_all([sc1, sc2])
        self.db.commit()

        # As of October -> returns September 30 filing
        latest = get_latest_reported_shares(self.db, inst.id, date(2026, 10, 15))
        self.assertIsNotNone(latest)
        self.assertEqual(latest.reported_share_count, 4150000000)

        # As of August -> returns June 30 filing
        older = get_latest_reported_shares(self.db, inst.id, date(2026, 8, 15))
        self.assertIsNotNone(older)
        self.assertEqual(older.reported_share_count, 4000000000)

    # --- 4. Corporate Actions Domain ---
    def test_corporate_actions_generate_dedup_key(self):
        key = generate_dedup_key(
            exchange="NSE",
            symbol="RELIANCE",
            event_type="bonus",
            event_date=date(2026, 10, 15),
            ratio_num=1,
            ratio_den=1,
        )
        self.assertEqual(key, "NSE:RELIANCE:bonus:2026-10-15:R1_1")

    # --- 5. Analytics Domain ---
    def test_analytics_market_cap_service(self):
        company = Company(name="Wipro Limited")
        self.db.add(company)
        self.db.flush()

        inst = Instrument(company_id=company.id, exchange="NSE", symbol="WIPRO", series="EQ", instrument_type="equity", is_active=True)
        self.db.add(inst)
        self.db.flush()

        src = DataSource(name="TejHQ EOD Market Data", source_type="api", source_url="https://tejhq.dev", terms_url="https://tejhq.dev/docs", is_active=True)
        self.db.add(src)
        self.db.flush()

        snap = DailyMarketSnapshot(
            instrument_id=inst.id, source_id=src.id, snapshot_date=date(2026, 10, 20),
            close_price=Decimal("500.00"), last_traded_price=Decimal("505.00"),
        )
        sc = InstrumentShareCount(
            instrument_id=inst.id, source_id=src.id, symbol="WIPRO", series="EQ", share_class="EQUITY",
            reported_share_count=5000000000, reporting_date=date(2026, 9, 30), is_active=True,
        )
        self.db.add_all([snap, sc])
        self.db.commit()

        # Calculate using authoritative Analytics MarketCapService
        res: MarketCapResult = MarketCapService.calculate_for_instrument(inst.id, self.db, price_basis="LTP")
        self.assertEqual(res.status, "calculated")
        # 505.00 * 5,000,000,000 / 10,000,000 = 252,500.000000 ₹ Crores
        self.assertEqual(res.market_cap_crores, Decimal("252500.000000"))
        self.assertEqual(res.price_used, Decimal("505.00"))
        self.assertFalse(res.is_stale)


if __name__ == "__main__":
    unittest.main()
