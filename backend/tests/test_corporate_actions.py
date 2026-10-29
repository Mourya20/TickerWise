from __future__ import annotations

import unittest
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import Company, CorporateAction, DailyMarketSnapshot, DataSource, Instrument, InstrumentShareCount
from app.models.ingestion_run import IngestionRun
from app.providers.base import NormalizedCorporateAction
from app.providers.date_parser import parse_provider_event_date, parse_optional_provider_event_date
from app.providers.tejhq import TejHQProvider
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

    def test_resolve_instrument_by_isin(self):
        svc = CorporateActionService()
        with self.TestingSessionLocal() as session:
            inst, status = svc.resolve_instrument(session, symbol="RELIANCE", isin="INE002A01018")
            self.assertIsNotNone(inst)
            self.assertEqual(inst.id, 101)
            self.assertEqual(inst.isin, "INE002A01018")
            self.assertEqual(status, "matched_isin")

    def test_resolve_instrument_by_symbol_and_exchange(self):
        svc = CorporateActionService()
        with self.TestingSessionLocal() as session:
            inst, status = svc.resolve_instrument(session, symbol="RELIANCE", exchange="NSE")
            self.assertIsNotNone(inst)
            self.assertEqual(inst.id, 101)
            self.assertEqual(inst.symbol, "RELIANCE")
            self.assertEqual(status, "matched_symbol")

    def test_resolve_instrument_quarantines_ambiguous_multi_series(self):
        svc = CorporateActionService()
        with self.TestingSessionLocal() as session:
            comp2 = Company(id=2, name="Tata Motors Limited")
            session.add(comp2)
            session.flush()

            inst_eq = Instrument(
                id=201,
                company_id=2,
                exchange="NSE",
                symbol="TATAMOTORS",
                series="EQ",
                isin="INE155A01022",
                is_active=True,
            )
            inst_dvr = Instrument(
                id=202,
                company_id=2,
                exchange="NSE",
                symbol="TATAMOTORS",
                series="DVR",
                isin="IN9155A01020",
                is_active=True,
            )
            session.add_all([inst_eq, inst_dvr])
            session.commit()

            resolved, status = svc.resolve_instrument(session, symbol="TATAMOTORS", exchange="NSE")
            self.assertIsNone(resolved)
            self.assertEqual(status, "ambiguous")

            resolved_dvr, status_dvr = svc.resolve_instrument(session, symbol="TATAMOTORS", isin="IN9155A01020")
            self.assertIsNotNone(resolved_dvr)
            self.assertEqual(resolved_dvr.id, 202)
            self.assertEqual(status_dvr, "matched_isin")

    def test_resolve_instrument_never_creates_duplicate_entities(self):
        svc = CorporateActionService()
        with self.TestingSessionLocal() as session:
            count_before_inst = session.query(Instrument).count()
            count_before_comp = session.query(Company).count()

            resolved, status = svc.resolve_instrument(session, symbol="UNKNOWNCO", exchange="NSE")
            self.assertIsNone(resolved)
            self.assertEqual(status, "unmatched")

            count_after_inst = session.query(Instrument).count()
            count_after_comp = session.query(Company).count()

            self.assertEqual(count_before_inst, count_after_inst)
            self.assertEqual(count_before_comp, count_after_comp)

    def test_intra_batch_deduplication_in_memory(self):
        svc = CorporateActionService()
        with self.TestingSessionLocal() as session:
            batch_data = [
                {
                    "symbol": "RELIANCE",
                    "exchange": "NSE",
                    "event_type": "dividend",
                    "ex_date": date(2026, 9, 20),
                    "cash_amount": Decimal("10.0"),
                    "status": "completed",
                    "notes": "First occurrence in batch",
                },
                {
                    "symbol": "RELIANCE",
                    "exchange": "NSE",
                    "event_type": "dividend",
                    "ex_date": date(2026, 9, 20),
                    "cash_amount": Decimal("10.0"),
                    "status": "completed",
                    "notes": "Duplicate occurrence in batch",
                },
            ]

            result = svc.ingest_actions(session, batch_data, source_id=1)
            session.commit()

            # Both entries reconcile onto the single entity in-memory and database
            self.assertIs(result[0], result[1])
            persisted = session.query(CorporateAction).filter_by(
                symbol="RELIANCE",
                event_type="dividend",
                ex_date=date(2026, 9, 20),
            ).all()
            self.assertEqual(len(persisted), 1)

    def test_get_adjustment_factor_reads_from_database_pure_query(self):
        svc = CorporateActionService()
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
                    validation_status="valid",
                )
            )
            session.commit()

            # Calling get_adjustment_factor should compute factor 2.0 (share count doubles) without any remote HTTP calls
            adj = svc.get_adjustment_factor("RELIANCE", date(2026, 7, 1), date(2026, 9, 1), session=session)
            self.assertEqual(adj.factor, Decimal("2.0"))

            # Factor for dates after ex-date is 1.0
            adj_post = svc.get_adjustment_factor("RELIANCE", date(2026, 8, 5), date(2026, 9, 1), session=session)
            self.assertEqual(adj_post.factor, Decimal("1.000000"))

    def test_record_and_get_sync_status(self):
        svc = CorporateActionService()
        with self.TestingSessionLocal() as session:
            # 1. Initially unsynced
            status_init = svc.get_sync_status(session, "RELIANCE")
            self.assertEqual(status_init["status"], "not_synced")
            self.assertEqual(status_init["events_count"], 0)

            # 2. Record successful sync with 2 events
            svc.record_sync_status(
                session,
                symbol="RELIANCE",
                status="completed",
                records_read=2,
                records_inserted=2,
            )
            session.commit()

            status_synced = svc.get_sync_status(session, "RELIANCE")
            self.assertEqual(status_synced["status"], "synced")
            self.assertEqual(status_synced["events_count"], 2)
            self.assertIsNotNone(status_synced["last_success_at"])

            # 3. Record verified empty check
            svc.record_sync_status(
                session,
                symbol="RELIANCE",
                status="empty",
                records_read=0,
            )
            session.commit()

            status_empty = svc.get_sync_status(session, "RELIANCE")
            self.assertEqual(status_empty["status"], "empty")
            self.assertEqual(status_empty["events_count"], 0)

            # 4. Record failure
            svc.record_sync_status(
                session,
                symbol="RELIANCE",
                status="failed",
                error_summary="HTTP 502 Bad Gateway",
            )
            session.commit()

            status_failed = svc.get_sync_status(session, "RELIANCE")
            self.assertEqual(status_failed["status"], "failed")
            self.assertEqual(status_failed["error_message"], "HTTP 502 Bad Gateway")

    def test_corporate_actions_status_endpoint(self):
        svc = CorporateActionService()
        with self.TestingSessionLocal() as session:
            svc.record_sync_status(
                session,
                symbol="RELIANCE",
                status="completed",
                records_read=5,
                records_inserted=5,
            )
            session.commit()

        response = self.client.get("/api/v1/instruments/101/corporate-actions/status")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["instrument_id"], 101)
        self.assertEqual(data["symbol"], "RELIANCE")
        self.assertEqual(data["status"], "synced")
        self.assertEqual(data["events_count"], 5)
        self.assertEqual(data["provider_name"], "TejHQ")

    def test_corporate_actions_get_endpoint_is_strictly_read_only(self):
        # Verify that GET endpoint makes zero database writes and does not invoke provider
        with self.TestingSessionLocal() as session:
            actions_before = session.query(CorporateAction).count()
            runs_before = session.query(IngestionRun).count()

        with patch("app.providers.tejhq.TejHQProvider.get_actions") as mock_get_actions:
            response = self.client.get("/api/v1/instruments/101/corporate-actions")
            self.assertEqual(response.status_code, 200)
            mock_get_actions.assert_not_called()

        with self.TestingSessionLocal() as session:
            actions_after = session.query(CorporateAction).count()
            runs_after = session.query(IngestionRun).count()

        self.assertEqual(actions_before, actions_after)
        self.assertEqual(runs_before, runs_after)


class TestDateParser(unittest.TestCase):
    def test_parse_date_only_format(self):
        self.assertEqual(parse_provider_event_date("2026-10-15"), date(2026, 10, 15))

    def test_parse_iso_zulu_timestamp(self):
        self.assertEqual(parse_provider_event_date("2026-10-15T00:00:00Z"), date(2026, 10, 15))
        self.assertEqual(parse_provider_event_date("2026-10-15T23:59:59Z"), date(2026, 10, 15))

    def test_parse_iso_fractional_seconds_zulu(self):
        self.assertEqual(parse_provider_event_date("2026-10-15T05:30:00.123456Z"), date(2026, 10, 15))

    def test_parse_iso_with_offsets(self):
        self.assertEqual(parse_provider_event_date("2026-10-15T05:30:00+05:30"), date(2026, 10, 15))
        self.assertEqual(parse_provider_event_date("2026-10-15T23:00:00-04:00"), date(2026, 10, 15))

    def test_parse_space_separated(self):
        self.assertEqual(parse_provider_event_date("2026-10-15 12:30:00"), date(2026, 10, 15))

    def test_parse_date_and_datetime_objects(self):
        self.assertEqual(parse_provider_event_date(date(2026, 10, 15)), date(2026, 10, 15))
        self.assertEqual(parse_provider_event_date(datetime(2026, 10, 15, 18, 45)), date(2026, 10, 15))

    def test_parse_preserves_stated_calendar_day(self):
        # A stated calendar event date of 2026-10-15 with late UTC time must remain 2026-10-15
        self.assertEqual(parse_provider_event_date("2026-10-15T23:59:59Z"), date(2026, 10, 15))

    def test_parse_invalid_raises_value_error(self):
        with self.assertRaises(ValueError):
            parse_provider_event_date("not-a-date")
        with self.assertRaises(ValueError):
            parse_provider_event_date("")
        with self.assertRaises(ValueError):
            parse_provider_event_date(None)
        with self.assertRaises(ValueError):
            parse_provider_event_date("2026/10/15")

    def test_parse_optional_provider_event_date(self):
        self.assertIsNone(parse_optional_provider_event_date(None))
        self.assertIsNone(parse_optional_provider_event_date(""))
        self.assertIsNone(parse_optional_provider_event_date("invalid"))
        self.assertEqual(parse_optional_provider_event_date("2026-10-15T00:00:00Z"), date(2026, 10, 15))


class TestTejHQCorporateActionsProvider(unittest.TestCase):
    @patch.object(TejHQProvider, "_request_with_retry")
    def test_provider_normalizes_and_skips_malformed(self, mock_req):
        mock_req.return_value = {
            "data": [
                {
                    "symbol": "RELIANCE",
                    "purpose": "Dividend - Rs 10 per share",
                    "action_type": "DIVIDEND",
                    "ex_date": "2026-08-15T00:00:00Z",
                    "record_date": "2026-08-16T00:00:00Z",
                    "amount": 10.0,
                },
                {
                    "symbol": "RELIANCE",
                    "purpose": "Corrupted date row",
                    "action_type": "SPLIT",
                    "ex_date": "invalid-date-format",
                },
                {
                    "symbol": "RELIANCE",
                    "purpose": "Stock Split from 10 to 2",
                    "action_type": "SPLIT",
                    "ex_date": "2026-09-01",
                    "from_face_value": 10,
                    "to_face_value": 2,
                },
            ]
        }

        provider = TejHQProvider()
        actions = provider.get_actions("RELIANCE")

        # Row 2 was skipped because of malformed date; rows 1 and 3 are parsed
        self.assertEqual(len(actions), 2)
        self.assertEqual(actions[0].action_type, "dividend")
        self.assertEqual(actions[0].ex_date, date(2026, 8, 15))
        self.assertEqual(actions[0].cash_amount, Decimal("10.0"))
        self.assertEqual(actions[1].action_type, "split")
        self.assertEqual(actions[1].ex_date, date(2026, 9, 1))

    @patch.object(TejHQProvider, "_request_with_retry")
    def test_provider_empty_list(self, mock_req):
        mock_req.return_value = {"data": []}

        provider = TejHQProvider()
        actions = provider.get_actions("TCS")
        self.assertEqual(actions, [])

