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
from app.models import Company, CorporateAction, DailyMarketSnapshot, DataSource, Instrument, InstrumentShareCount
from app.providers.base import NormalizedCorporateAction
from app.services.corporate_action_service import (
    CorporateActionService,
    generate_dedup_key,
    get_action_effective_date,
)
from app.services.market_cap_service import MarketCapService


class DummyTejHQCorporateActionsProvider:
    def __init__(self, actions: list[NormalizedCorporateAction] | None = None) -> None:
        self._actions = actions or []

    def get_actions(self, symbol: str) -> list[NormalizedCorporateAction]:
        clean = symbol.strip().upper()
        return [a for a in self._actions if a.symbol.strip().upper() == clean]


class TestCorporateActionsAndShareCapital(unittest.TestCase):
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

        with self.TestingSessionLocal() as session:
            ds_tejhq = DataSource(id=1, name="TejHQ Corporate Actions", source_type="api", is_active=True)
            ds_nse = DataSource(id=2, name="NSE Shareholding Pattern Disclosure", source_type="filing", is_active=True)
            session.add_all([ds_tejhq, ds_nse])

            comp = Company(id=1, name="Reliance Industries Limited")
            session.add(comp)
            session.flush()

            inst = Instrument(
                id=101,
                company_id=1,
                exchange="NSE",
                symbol="RELIANCE",
                series="EQ",
                isin="INE002A01018",
                face_value=Decimal("10.0"),
                is_active=True,
            )
            session.add(inst)

            # Seed base filing: 100,000,000 shares on 2026-06-30
            sc = InstrumentShareCount(
                id=1,
                instrument_id=101,
                source_id=2,
                symbol="RELIANCE",
                series="EQ",
                share_class="EQUITY",
                reported_share_count=100000000,
                reporting_date=date(2026, 6, 30),
                extraction_method="directly_reported",
                validation_status="valid",
                is_active=True,
            )
            session.add(sc)

            # Seed price snapshot on 2026-10-15: LTP 1500.0
            snap = DailyMarketSnapshot(
                id=1,
                instrument_id=101,
                source_id=1,
                snapshot_date=date(2026, 10, 15),
                last_traded_price=Decimal("1500.0"),
                close_price=Decimal("1495.0"),
            )
            session.add(snap)
            session.commit()

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

    def test_dedup_key_deterministic(self):
        key1 = generate_dedup_key("NSE", "RELIANCE", "bonus", date(2026, 10, 28), ratio_num=1, ratio_den=1)
        key2 = generate_dedup_key("NSE", "RELIANCE", "bonus", date(2026, 10, 28), ratio_num=1, ratio_den=1)
        self.assertEqual(key1, key2)
        self.assertEqual(key1, "NSE:RELIANCE:bonus:2026-10-28:R1_1")

    def test_idempotent_ingestion_and_reconciliation(self):
        svc = CorporateActionService()
        with self.TestingSessionLocal() as session:
            # 1. Ingest proposed QIP
            actions_data = [
                {
                    "symbol": "RELIANCE",
                    "exchange": "NSE",
                    "event_type": "qip",
                    "announcement_date": date(2026, 7, 1),
                    "proposed_shares": 5000000,
                    "status": "proposed",
                    "notes": "Board approved QIP issue",
                }
            ]
            ingested = svc.ingest_actions(session, actions_data, source_id=1)
            session.commit()
            self.assertEqual(len(ingested), 1)
            self.assertEqual(ingested[0].status, "proposed")
            self.assertIsNone(ingested[0].actual_shares)
            action_id = ingested[0].id

            # 2. Ingest duplicate action - should reconcile and not duplicate
            ingested2 = svc.ingest_actions(session, actions_data, source_id=1)
            session.commit()
            self.assertEqual(len(ingested2), 1)
            self.assertEqual(ingested2[0].id, action_id)

            # Verify total count in DB remains 1
            total = session.query(CorporateAction).filter_by(symbol="RELIANCE").count()
            self.assertEqual(total, 1)

            # 3. Lifecycle transition: QIP allotted with actual shares confirmed
            updated_data = [
                {
                    "symbol": "RELIANCE",
                    "exchange": "NSE",
                    "event_type": "qip",
                    "announcement_date": date(2026, 7, 1),
                    "allotment_date": date(2026, 7, 15),
                    "proposed_shares": 5000000,
                    "actual_shares": 4950000,
                    "status": "allotted",
                    "notes": "QIP allotment completed",
                }
            ]
            reconciled = svc.ingest_actions(session, updated_data, source_id=1)
            session.commit()
            self.assertEqual(len(reconciled), 1)
            self.assertEqual(reconciled[0].id, action_id)
            self.assertEqual(reconciled[0].status, "allotted")
            self.assertEqual(reconciled[0].actual_shares, 4950000)

            total_after = session.query(CorporateAction).filter_by(symbol="RELIANCE").count()
            self.assertEqual(total_after, 1)

    def test_proposed_capital_raise_does_not_affect_shares(self):
        svc = CorporateActionService()
        with self.TestingSessionLocal() as session:
            # Add proposed rights issue on 2026-07-10 (between filing 2026-06-30 and price 2026-10-15)
            session.add(
                CorporateAction(
                    instrument_id=101,
                    exchange="NSE",
                    symbol="RELIANCE",
                    event_type="rights",
                    dedup_key="NSE:RELIANCE:rights:2026-07-10:R1_1",
                    announcement_date=date(2026, 7, 10),
                    proposed_shares=10000000,
                    status="proposed",
                    source_id=1,
                    validation_status="valid",
                )
            )
            session.commit()

            # Valuation on 2026-08-01: shares must NOT increase because rights issue is only proposed
            res = svc.resolve_applicable_share_count(session, 101, date(2026, 8, 1))
            self.assertEqual(res.share_count, 100000000)
            self.assertFalse(res.has_unquantified_action)
            self.assertTrue(any("not allotted; shares unaffected" in a for a in res.actions_applied))

    def test_allotted_capital_raise_increases_shares(self):
        svc = CorporateActionService()
        with self.TestingSessionLocal() as session:
            # Add completed QIP allotment on 2026-07-20
            session.add(
                CorporateAction(
                    instrument_id=101,
                    exchange="NSE",
                    symbol="RELIANCE",
                    event_type="qip",
                    dedup_key="NSE:RELIANCE:qip:2026-07-20:S5000000",
                    allotment_date=date(2026, 7, 20),
                    actual_shares=5000000,
                    status="allotted",
                    source_id=1,
                    validation_status="valid",
                )
            )
            session.commit()

            # Valuation on 2026-08-01: base 100,000,000 + 5,000,000 = 105,000,000
            res = svc.resolve_applicable_share_count(session, 101, date(2026, 8, 1))
            self.assertEqual(res.share_count, 105000000)
            self.assertTrue(any("5,000,000 shares" in a for a in res.actions_applied))

    def test_proposed_buyback_does_not_reduce_shares(self):
        svc = CorporateActionService()
        with self.TestingSessionLocal() as session:
            session.add(
                CorporateAction(
                    instrument_id=101,
                    exchange="NSE",
                    symbol="RELIANCE",
                    event_type="buyback",
                    dedup_key="NSE:RELIANCE:buyback:2026-07-05:S2000000",
                    announcement_date=date(2026, 7, 5),
                    proposed_shares=2000000,
                    status="proposed",
                    source_id=1,
                    validation_status="valid",
                )
            )
            session.commit()

            # Valuation on 2026-08-01: shares must NOT decrease because buyback has not completed
            res = svc.resolve_applicable_share_count(session, 101, date(2026, 8, 1))
            self.assertEqual(res.share_count, 100000000)
            self.assertTrue(any("not extinguished; shares unaffected" in a for a in res.actions_applied))

    def test_completed_buyback_reduces_shares(self):
        svc = CorporateActionService()
        with self.TestingSessionLocal() as session:
            session.add(
                CorporateAction(
                    instrument_id=101,
                    exchange="NSE",
                    symbol="RELIANCE",
                    event_type="buyback",
                    dedup_key="NSE:RELIANCE:buyback:2026-08-10:S2000000",
                    completion_date=date(2026, 8, 10),
                    actual_shares=2000000,
                    status="completed",
                    source_id=1,
                    validation_status="valid",
                )
            )
            session.commit()

            # Valuation on 2026-08-15: base 100,000,000 - 2,000,000 = 98,000,000
            res = svc.resolve_applicable_share_count(session, 101, date(2026, 8, 15))
            self.assertEqual(res.share_count, 98000000)
            self.assertTrue(any("Buyback extinguishment of 2,000,000 shares" in a for a in res.actions_applied))

    def test_bonus_issue_adjustment(self):
        svc = CorporateActionService()
        with self.TestingSessionLocal() as session:
            # 1:1 Bonus on 2026-08-01
            session.add(
                CorporateAction(
                    instrument_id=101,
                    exchange="NSE",
                    symbol="RELIANCE",
                    event_type="bonus",
                    dedup_key="NSE:RELIANCE:bonus:2026-08-01:R1_1",
                    ex_date=date(2026, 8, 1),
                    ratio_num=1,
                    ratio_den=1,
                    status="completed",
                    source_id=1,
                    validation_status="valid",
                )
            )
            session.commit()

            # Valuation on 2026-08-05: 100,000,000 * 2 = 200,000,000
            res = svc.resolve_applicable_share_count(session, 101, date(2026, 8, 5))
            self.assertEqual(res.share_count, 200000000)
            self.assertTrue(any("Bonus 1:1" in a for a in res.actions_applied))

    def test_stock_split_adjustment(self):
        svc = CorporateActionService()
        with self.TestingSessionLocal() as session:
            # Face value split 10 -> 2 (5-for-1 split) on 2026-08-10
            session.add(
                CorporateAction(
                    instrument_id=101,
                    exchange="NSE",
                    symbol="RELIANCE",
                    event_type="split",
                    dedup_key="NSE:RELIANCE:split:2026-08-10:FV10_2",
                    ex_date=date(2026, 8, 10),
                    face_value_from=Decimal("10.0"),
                    face_value_to=Decimal("2.0"),
                    status="completed",
                    source_id=1,
                    validation_status="valid",
                )
            )
            session.commit()

            # Valuation on 2026-08-15: 100,000,000 * 5 = 500,000,000
            res = svc.resolve_applicable_share_count(session, 101, date(2026, 8, 15))
            self.assertEqual(res.share_count, 500000000)
            self.assertTrue(any("Split 10->2" in a for a in res.actions_applied))

    def test_point_in_time_no_lookahead_and_no_double_counting(self):
        svc = CorporateActionService()
        with self.TestingSessionLocal() as session:
            # 1. Action 1: Bonus on 2026-07-15
            session.add(
                CorporateAction(
                    instrument_id=101,
                    exchange="NSE",
                    symbol="RELIANCE",
                    event_type="bonus",
                    dedup_key="NSE:RELIANCE:bonus:2026-07-15:R1_1",
                    ex_date=date(2026, 7, 15),
                    ratio_num=1,
                    ratio_den=1,
                    status="completed",
                    source_id=1,
                    validation_status="valid",
                )
            )
            # 2. Action 2: Future Split on 2026-11-01 (after snapshot date 2026-10-15)
            session.add(
                CorporateAction(
                    instrument_id=101,
                    exchange="NSE",
                    symbol="RELIANCE",
                    event_type="split",
                    dedup_key="NSE:RELIANCE:split:2026-11-01:R2_1",
                    ex_date=date(2026, 11, 1),
                    ratio_num=2,
                    ratio_den=1,
                    status="completed",
                    source_id=1,
                    validation_status="valid",
                )
            )
            session.commit()

            # Point-in-time check A: valuation on 2026-07-10 (before bonus)
            res_before = svc.resolve_applicable_share_count(session, 101, date(2026, 7, 10))
            self.assertEqual(res_before.share_count, 100000000)  # No bonus applied

            # Point-in-time check B: valuation on 2026-07-20 (after bonus, before split)
            res_mid = svc.resolve_applicable_share_count(session, 101, date(2026, 7, 20))
            self.assertEqual(res_mid.share_count, 200000000)  # Bonus applied, split not applied

            # Point-in-time check C: valuation on 2026-10-15 (after bonus, before split)
            res_oct = svc.resolve_applicable_share_count(session, 101, date(2026, 10, 15))
            self.assertEqual(res_oct.share_count, 200000000)  # Future split has NOT happened!

            # Double-counting check: Now suppose NSE filing for 2026-09-30 is ingested with 200,000,000 shares
            session.add(
                InstrumentShareCount(
                    id=2,
                    instrument_id=101,
                    source_id=2,
                    symbol="RELIANCE",
                    series="EQ",
                    share_class="EQUITY",
                    reported_share_count=200000000,
                    reporting_date=date(2026, 9, 30),
                    extraction_method="directly_reported",
                    validation_status="valid",
                    is_active=True,
                )
            )
            session.commit()

            # Valuation on 2026-10-15: base date is now 2026-09-30.
            # The bonus on 2026-07-15 is <= 2026-09-30, so it must NOT be applied again!
            res_recounted = svc.resolve_applicable_share_count(session, 101, date(2026, 10, 15))
            self.assertEqual(res_recounted.share_count, 200000000)
            self.assertEqual(res_recounted.base_reporting_date, date(2026, 9, 30))
            self.assertEqual(len(res_recounted.actions_applied), 0)  # Zero adjustments in (2026-09-30, 2026-10-15]

    def test_unquantified_action_handling(self):
        svc = CorporateActionService()
        with self.TestingSessionLocal() as session:
            # Split with missing ratio / face values
            session.add(
                CorporateAction(
                    instrument_id=101,
                    exchange="NSE",
                    symbol="RELIANCE",
                    event_type="split",
                    dedup_key="NSE:RELIANCE:split:2026-08-01:NODETAILS",
                    ex_date=date(2026, 8, 1),
                    ratio_num=None,
                    ratio_den=None,
                    status="completed",
                    source_id=1,
                    validation_status="valid",
                )
            )
            session.commit()

            res = svc.resolve_applicable_share_count(session, 101, date(2026, 8, 15))
            self.assertTrue(res.has_unquantified_action)
            self.assertIn("unverified", res.status)
            self.assertTrue(any("missing valid ratio" in r for r in res.unquantified_reasons))

    def test_market_cap_service_integration(self):
        with self.TestingSessionLocal() as session:
            # 1:1 Bonus on 2026-08-01
            session.add(
                CorporateAction(
                    instrument_id=101,
                    exchange="NSE",
                    symbol="RELIANCE",
                    event_type="bonus",
                    dedup_key="NSE:RELIANCE:bonus:2026-08-01:R1_1",
                    ex_date=date(2026, 8, 1),
                    ratio_num=1,
                    ratio_den=1,
                    status="completed",
                    source_id=1,
                    validation_status="valid",
                )
            )
            session.commit()

            mcap_res = MarketCapService.calculate_for_instrument(101, session)
            self.assertEqual(mcap_res.status, "calculated")
            self.assertEqual(mcap_res.share_count, 200000000)
            # Market cap = (1500.0 * 200,000,000) / 10,000,000 = 30,000 Crores
            self.assertEqual(mcap_res.market_cap_crores, Decimal("30000.000000"))
            self.assertIn("Bonus 1:1", mcap_res.explanation)

    def test_corporate_actions_api_endpoint(self):
        with self.TestingSessionLocal() as session:
            session.add(
                CorporateAction(
                    instrument_id=101,
                    exchange="NSE",
                    symbol="RELIANCE",
                    event_type="bonus",
                    dedup_key="NSE:RELIANCE:bonus:2026-08-01:R1_1",
                    ex_date=date(2026, 8, 1),
                    ratio_num=1,
                    ratio_den=1,
                    status="completed",
                    source_id=1,
                    raw_subject="Bonus 1:1 Issue",
                    validation_status="valid",
                )
            )
            session.commit()

        response = self.client.get("/api/v1/instruments/101/corporate-actions")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["symbol"], "RELIANCE")
        self.assertEqual(data[0]["event_type"], "bonus")
        self.assertEqual(data[0]["ratio_num"], 1)
        self.assertEqual(data[0]["ratio_den"], 1)
        self.assertEqual(data[0]["raw_subject"], "Bonus 1:1 Issue")
        self.assertEqual(data[0]["source_name"], "TejHQ Corporate Actions")

    def test_corporate_actions_api_404_for_missing_instrument(self):
        response = self.client.get("/api/v1/instruments/999999/corporate-actions")
        self.assertEqual(response.status_code, 404)
        self.assertIn("Instrument not found", response.json()["detail"])
