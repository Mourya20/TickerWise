from __future__ import annotations

import unittest
from datetime import date, datetime
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import Company, DailyMarketSnapshot, DataSource, Instrument, InstrumentShareCount
from app.providers.base import NormalizedCorporateAction, NormalizedOHLCV
from app.providers.nse_shareholding import (
    NSEPermissionStatus,
    NSEShareholdingIngestionService,
    NSEShareholdingParser,
    ParsedShareCount,
)
from app.services.historical_backfill_service import HistoricalBackfillService
from app.services.market_cap_service import MarketCapService


class DummyTejHQForTest:
    def __init__(self, actions=None):
        self._actions = actions or []

    def get_actions(self, symbol: str):
        return self._actions


class TestStage2Core(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.TestingSessionLocal = sessionmaker(
            autocommit=False, autoflush=False, bind=self.engine
        )
        Base.metadata.create_all(bind=self.engine)

        # Seed data source
        with self.TestingSessionLocal() as session:
            ds_tejhq = DataSource(id=1, name="TejHQ EOD Market Data", source_type="api", is_active=True)
            ds_nse = DataSource(id=2, name="NSE Shareholding Pattern Disclosure", source_type="filing", is_active=True)
            session.add_all([ds_tejhq, ds_nse])

            comp = Company(id=1, name="Tata Consultancy Services Limited")
            session.add(comp)
            session.flush()

            inst = Instrument(
                id=101,
                company_id=1,
                exchange="NSE",
                symbol="TCS",
                series="EQ",
                isin="INE467B01029",
                face_value=Decimal("1.0"),
                is_active=True,
            )
            session.add(inst)
            session.flush()

            # Seed snapshots
            snap1 = DailyMarketSnapshot(
                id=1,
                instrument_id=101,
                source_id=1,
                snapshot_date=date(2026, 10, 14),
                open_price=Decimal("2300.0"),
                high_price=Decimal("2350.0"),
                low_price=Decimal("2290.0"),
                close_price=Decimal("2340.0"),
                last_traded_price=Decimal("2345.0"),
                prev_close_price=Decimal("2295.0"),
                volume=1200000,
                turnover=Decimal("2808000000"),
                volume_lakhs=Decimal("12.0"),
                traded_value_crores=Decimal("280.8"),
                percentage_change_pct=Decimal("1.96"),
                is_calculated_change=True,
                trade_count=45000,
            )
            snap2 = DailyMarketSnapshot(
                id=2,
                instrument_id=101,
                source_id=1,
                snapshot_date=date(2026, 10, 15),
                open_price=Decimal("2345.0"),
                high_price=Decimal("2360.0"),
                low_price=Decimal("2330.0"),
                close_price=Decimal("2350.0"),
                last_traded_price=Decimal("2355.0"),
                prev_close_price=Decimal("2340.0"),
                volume=1500000,
                turnover=Decimal("3525000000"),
                volume_lakhs=Decimal("15.0"),
                traded_value_crores=Decimal("352.5"),
                percentage_change_pct=Decimal("0.427"),
                is_calculated_change=True,
                trade_count=52000,
            )
            session.add_all([snap1, snap2])

            # Seed share count
            sc = InstrumentShareCount(
                id=1,
                instrument_id=101,
                symbol="TCS",
                series="EQ",
                share_class="EQUITY",
                reported_share_count=3618087518,
                fully_paid_shares=3618087518,
                face_value=Decimal("1.0"),
                source_capital_amount=Decimal("3618087518"),
                reporting_date=date(2026, 9, 30),
                filing_date=date(2026, 10, 12),
                source_id=2,
                extraction_method="directly_reported",
                validation_status="valid",
            )
            session.add(sc)
            session.commit()

            self.tcs_id = 101

        def override_get_db():
            db = self.TestingSessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=self.engine)

    def test_get_instrument_prices_chronological(self):
        response = self.client.get(f"/api/v1/instruments/{self.tcs_id}/prices")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 2)
        # Verify chronological order
        self.assertEqual(data[0]["trading_date"], "2026-10-14")
        self.assertEqual(data[1]["trading_date"], "2026-10-15")
        # Check volume and turnover unit fields
        self.assertEqual(float(data[0]["open"]), 2300.0)
        self.assertEqual(float(data[0]["volume_lakhs"]), 12.0)
        self.assertEqual(float(data[0]["traded_value_crores"]), 280.8)
        self.assertEqual(data[0]["source_name"], "TejHQ EOD Market Data")

    def test_get_instrument_prices_date_filters(self):
        response = self.client.get(
            f"/api/v1/instruments/{self.tcs_id}/prices?from=2026-10-15&to=2026-10-15"
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["trading_date"], "2026-10-15")

    def test_get_instrument_prices_invalid_range_400(self):
        response = self.client.get(
            f"/api/v1/instruments/{self.tcs_id}/prices?from=2026-10-20&to=2026-10-10"
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("cannot be after", response.json()["detail"])

    def test_get_instrument_prices_not_found_404(self):
        response = self.client.get("/api/v1/instruments/999999/prices")
        self.assertEqual(response.status_code, 404)

    def test_get_instrument_detail_market_cap_calculated(self):
        response = self.client.get(f"/api/v1/instruments/{self.tcs_id}")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        snapshot = data["snapshot"]
        self.assertIsNotNone(snapshot)
        # Expected market cap = (2355.0 * 3618087518) / 10,000,000 = 852059.610489
        self.assertIsNotNone(snapshot["market_capitalization_crores"])
        mcap = float(snapshot["market_capitalization_crores"])
        self.assertAlmostEqual(mcap, 852059.610489, places=2)
        self.assertEqual(snapshot["market_cap_price_basis"], "LTP")
        self.assertEqual(snapshot["market_cap_price_date"], "2026-10-15")
        self.assertEqual(snapshot["share_count"], 3618087518)
        self.assertEqual(snapshot["share_count_date"], "2026-09-30")
        self.assertEqual(snapshot["share_count_status"], "fresh")

    def test_get_share_counts_history(self):
        response = self.client.get(f"/api/v1/instruments/{self.tcs_id}/share-counts")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["symbol"], "TCS")
        self.assertEqual(data[0]["reported_share_count"], 3618087518)
        self.assertEqual(data[0]["reporting_date"], "2026-09-30")
        self.assertEqual(data[0]["extraction_method"], "directly_reported")

    def test_market_cap_service_stale_flag(self):
        with self.TestingSessionLocal() as session:
            # Create old share count dated > 120 days ago
            sc = session.query(InstrumentShareCount).filter_by(symbol="TCS").first()
            sc.reporting_date = date(2026, 1, 1)
            session.commit()

            res = MarketCapService.calculate_for_instrument(self.tcs_id, session)
            self.assertTrue(res.is_stale)
            self.assertEqual(res.share_count_status, "stale")
            self.assertIn("days prior", res.explanation)

    def test_market_cap_missing_share_count(self):
        with self.TestingSessionLocal() as session:
            comp = Company(id=2, name="Missing Company")
            session.add(comp)
            session.flush()
            inst = Instrument(
                id=102,
                company_id=2,
                exchange="NSE",
                symbol="MISSING",
                series="EQ",
                face_value=Decimal("10"),
            )
            session.add(inst)
            session.flush()
            snap = DailyMarketSnapshot(
                id=3,
                instrument_id=102,
                source_id=1,
                snapshot_date=date(2026, 10, 15),
                last_traded_price=Decimal("100"),
            )
            session.add(snap)
            session.commit()

            res = MarketCapService.calculate_for_instrument(102, session)
            self.assertIsNone(res.market_cap_crores)
            self.assertEqual(res.status, "unavailable")
            self.assertIn("No official NSE shareholding", res.explanation)

    def test_nse_shareholding_xbrl_parser(self):
        xml_content = """<?xml version="1.0" encoding="utf-8"?>
        <xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance">
          <Symbol>INFY</Symbol>
          <QuarterEnded>2026-09-30</QuarterEnded>
          <DateOfFiling>2026-10-14</DateOfFiling>
          <TotalNumberOfShares>4151800000</TotalNumberOfShares>
          <NumberOfFullyPaidUpEquityShares>4151800000</NumberOfFullyPaidUpEquityShares>
          <FaceValuePerShare>5.0</FaceValuePerShare>
          <PaidUpEquityShareCapital>20759000000.0</PaidUpEquityShareCapital>
        </xbrli:xbrl>"""
        parsed = NSEShareholdingParser.parse_xbrl(xml_content, source_ref="test_xbrl.xml")
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].symbol, "INFY")
        self.assertEqual(parsed[0].reported_share_count, 4151800000)
        self.assertEqual(parsed[0].reporting_date, date(2026, 9, 30))
        self.assertEqual(parsed[0].extraction_method, "directly_reported")

    def test_nse_shareholding_derived_fallback(self):
        xml_content = """<?xml version="1.0" encoding="utf-8"?>
        <xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance">
          <Symbol>TCS</Symbol>
          <QuarterEnded>2026-09-30</QuarterEnded>
          <FaceValuePerShare>1.0</FaceValuePerShare>
          <PaidUpEquityShareCapital>3618087518.0</PaidUpEquityShareCapital>
        </xbrli:xbrl>"""
        parsed = NSEShareholdingParser.parse_xbrl(xml_content, source_ref="test_derived.xml")
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].symbol, "TCS")
        self.assertEqual(parsed[0].reported_share_count, 3618087518)
        self.assertEqual(parsed[0].extraction_method, "derived")

    def test_nse_shareholding_corporate_action_awareness(self):
        # Suppose a 1:1 bonus occurred on 2026-10-01, after the 2026-09-30 filing
        dummy_actions = [
            NormalizedCorporateAction(
                symbol="TCS",
                exchange="NSE",
                isin="INE467B01029",
                company_name="TCS",
                ex_date=date(2026, 10, 1),
                record_date=date(2026, 10, 1),
                action_type="bonus",
                ratio_num=1,
                ratio_den=1,
                raw_subject="Bonus 1:1",
            )
        ]
        svc = NSEShareholdingIngestionService(
            session_factory=self.TestingSessionLocal,
            tejhq_provider=DummyTejHQForTest(actions=dummy_actions),
        )

        has_ca, ca_details, ca_factor = svc.check_corporate_actions("TCS", date(2026, 9, 30))
        self.assertTrue(has_ca)
        self.assertEqual(ca_factor, Decimal("2.0"))
        self.assertIn("Bonus 1:1", ca_details)

    def test_nse_permission_report(self):
        report = NSEPermissionStatus.get_status_report()
        self.assertFalse(report["automated_scraping_permitted"])
        self.assertIn("prohibited", report["legal_limitation"].lower())

    def test_backfill_validation_bar(self):
        # Valid bar
        valid_bar = NormalizedOHLCV(
            symbol="TCS",
            exchange="NSE",
            date=date(2026, 10, 20),
            open=Decimal("2300"),
            high=Decimal("2350"),
            low=Decimal("2290"),
            close=Decimal("2340"),
            last_price=Decimal("2340"),
            prev_close=Decimal("2290"),
            volume=100000,
            turnover=Decimal("234000000"),
            trades=5000,
        )
        self.assertEqual(HistoricalBackfillService.validate_bar(valid_bar), [])

        # Invalid bar: High < Low
        invalid_bar = NormalizedOHLCV(
            symbol="TCS",
            exchange="NSE",
            date=date(2026, 10, 20),
            open=Decimal("2300"),
            high=Decimal("2280"),  # high < low!
            low=Decimal("2290"),
            close=Decimal("2300"),
            last_price=Decimal("2300"),
            prev_close=Decimal("2290"),
            volume=100000,
            turnover=Decimal("234000000"),
            trades=5000,
        )
        errs = HistoricalBackfillService.validate_bar(invalid_bar)
        self.assertTrue(any("High (2280) < Low (2290)" in e for e in errs))

    def test_nse_shareholding_xbrl_context_and_dimensions(self):
        """Verify XBRL parser preserves entity context and does not overwrite with dimensional segments."""
        xml_content = """<?xml version="1.0" encoding="utf-8"?>
        <xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance">
          <xbrli:context id="I_2026_Promoter">
            <xbrli:entity>
              <xbrli:identifier scheme="http://www.nseindia.com">RELIANCE</xbrli:identifier>
              <xbrli:segment>
                <PromoterMember>PromoterAndPromoterGroupMember</PromoterMember>
              </xbrli:segment>
            </xbrli:entity>
            <xbrli:period>
              <xbrli:instant>2026-09-30</xbrli:instant>
            </xbrli:period>
          </xbrli:context>
          <xbrli:context id="I_2026_Total">
            <xbrli:entity>
              <xbrli:identifier scheme="http://www.nseindia.com">RELIANCE</xbrli:identifier>
            </xbrli:entity>
            <xbrli:period>
              <xbrli:instant>2026-09-30</xbrli:instant>
            </xbrli:period>
          </xbrli:context>
          <Symbol contextRef="I_2026_Total">RELIANCE</Symbol>
          <QuarterEnded contextRef="I_2026_Total">2026-09-30</QuarterEnded>
          <TotalNumberOfShares contextRef="I_2026_Total">13532538737</TotalNumberOfShares>
          <!-- Segmented promoter tag appearing later in the document must NOT overwrite the entity total -->
          <TotalNumberOfShares contextRef="I_2026_Promoter">6766269368</TotalNumberOfShares>
        </xbrli:xbrl>"""
        parsed = NSEShareholdingParser.parse_xbrl(xml_content, source_ref="test_dimensions.xml")
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].symbol, "RELIANCE")
        self.assertEqual(parsed[0].reported_share_count, 13532538737)
        self.assertEqual(parsed[0].reporting_date, date(2026, 9, 30))

    def test_market_cap_point_in_time_no_future_fallback(self):
        """Verify MarketCapService strictly respects point-in-time and does NOT fall back to future share counts."""
        with self.TestingSessionLocal() as session:
            # Instrument with a share count dated in the FUTURE relative to snapshot
            comp = Company(id=3, name="Future Cap Co")
            session.add(comp)
            session.flush()
            inst = Instrument(id=103, company_id=3, exchange="NSE", symbol="FUTURECO", series="EQ")
            session.add(inst)
            session.flush()

            # Price snapshot on Oct 10
            snap = DailyMarketSnapshot(
                id=4,
                instrument_id=103,
                source_id=1,
                snapshot_date=date(2026, 10, 10),
                last_traded_price=Decimal("100.0"),
            )
            # Share count dated Oct 20 (future relative to snapshot)
            sc = InstrumentShareCount(
                id=2,
                instrument_id=103,
                symbol="FUTURECO",
                series="EQ",
                share_class="EQUITY",
                reported_share_count=10000000,
                reporting_date=date(2026, 10, 20),
                source_id=2,
                extraction_method="directly_reported",
                validation_status="valid",
            )
            session.add_all([snap, sc])
            session.commit()

            res = MarketCapService.calculate_for_instrument(103, session)
            # Must be unavailable because no filing existed on or before 2026-10-10
            self.assertIsNone(res.market_cap_crores)
            self.assertEqual(res.status, "unavailable")
            self.assertIn("No official NSE shareholding", res.explanation)

    def test_representative_sebi_lodr_xbrl_fixture(self):
        """Verify parsing against a real representative SEBI LODR Regulation 31 filing fixture."""
        from pathlib import Path
        fixture_path = Path(__file__).parent / "fixtures" / "tcs_sebi_lodr_reg31.xml"
        self.assertTrue(fixture_path.exists(), f"Fixture file missing: {fixture_path}")
        content = fixture_path.read_text(encoding="utf-8")

        parsed_list = NSEShareholdingParser.parse_xbrl(content, source_ref=str(fixture_path))
        self.assertEqual(len(parsed_list), 1)
        rec = parsed_list[0]

        # Verify exact metadata and share count
        self.assertEqual(rec.symbol, "TCS")
        self.assertEqual(rec.reporting_date, date(2026, 9, 30))
        self.assertEqual(rec.filing_date, date(2026, 10, 12))
        self.assertEqual(rec.reported_share_count, 3618087518)
        self.assertEqual(rec.fully_paid_shares, 3618087518)
        self.assertEqual(rec.extraction_method, "directly_reported")
        self.assertEqual(rec.face_value, Decimal("1.00"))
        self.assertEqual(rec.source_capital_amount, Decimal("3618087518"))


if __name__ == "__main__":
    unittest.main()
