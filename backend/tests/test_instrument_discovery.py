from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add backend directory to path
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import unittest

from fastapi.testclient import TestClient
from sqlalchemy import BigInteger, Integer, create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes import router
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import (
    Company,
    DailyMarketSnapshot,
    DataSource,
    IngestionRun,
    Instrument,
)
from app.providers.base import NormalizedMarketSnapshot, ProviderStatus
from app.services.eod_update_service import EODUpdateService
from app.services.instrument_discovery_service import (
    DiscoveryResult,
    InstrumentDiscoveryService,
    normalize_company_name,
)


class TestInstrumentDiscovery(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
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

        Base.metadata.create_all(self.engine)
        self.SessionFactory = sessionmaker(bind=self.engine)

        def override_get_db():
            db = self.SessionFactory()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

        # Seed initial data: DataSource, Company, Instrument (RELIANCE EQ)
        with self.SessionFactory() as session:
            self.source = DataSource(
                name="TejHQ EOD Market Data",
                source_type="api",
                source_url="https://api.tejhq.dev",
                is_active=True,
            )
            session.add(self.source)
            session.flush()

            self.company_rel = Company(name="Reliance Industries Limited")
            session.add(self.company_rel)
            session.flush()

            self.inst_rel = Instrument(
                company_id=self.company_rel.id,
                exchange="NSE",
                symbol="RELIANCE",
                series="EQ",
                instrument_type="EQUITY",
                isin="INE002A01018",
                listing_date=date(1995, 11, 29),
                first_seen_date=None,
                is_active=True,
            )
            session.add(self.inst_rel)
            session.commit()

            self.source_id = int(self.source.id)
            self.company_rel_id = int(self.company_rel.id)
            self.inst_rel_id = int(self.inst_rel.id)

    def tearDown(self):
        app.dependency_overrides.clear()
        Base.metadata.drop_all(self.engine)

    def test_unknown_valid_ipo_equity_discovery(self):
        """1. An unknown, valid IPO equity appearing in provider snapshot is discovered and onboarded."""
        discovery = InstrumentDiscoveryService()
        snapshot_date = date(2026, 10, 27)

        rows = [
            NormalizedMarketSnapshot(
                symbol="SWIGGY",
                series="EQ",
                isin="INE00V501019",
                name="Swiggy Limited",
                exchange="NSE",
                snapshot_date=snapshot_date,
                open=Decimal("390.00"),
                high=Decimal("415.00"),
                low=Decimal("388.00"),
                close=Decimal("410.50"),
                last_price=Decimal("411.00"),
                prev_close=Decimal("390.00"),
                volume=15000000,
                turnover=Decimal("6000000000"),
                trades=120000,
                percentage_change_pct=Decimal("5.25"),
                is_calculated_change=True,
                provider_name="TejHQ",
                retrieved_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
        ]

        with self.SessionFactory() as session:
            result = discovery.discover_and_onboard(
                session=session,
                snapshot_rows=rows,
                snapshot_date=snapshot_date,
                exchange="NSE",
            )
            session.commit()

            self.assertEqual(result.summary.discovered, 1)
            self.assertEqual(result.summary.reused_company, 0)
            self.assertEqual(len(result.new_instruments), 1)

            # Verify in DB
            inst = session.scalar(
                select(Instrument).where(Instrument.symbol == "SWIGGY", Instrument.series == "EQ")
            )
            self.assertIsNotNone(inst)
            self.assertEqual(inst.symbol, "SWIGGY")
            self.assertEqual(inst.series, "EQ")
            self.assertEqual(inst.isin, "INE00V501019")
            self.assertIsNone(inst.listing_date)  # Do not invent official listing date
            self.assertEqual(inst.first_seen_date, snapshot_date)
            self.assertTrue(inst.is_active)

            comp = session.get(Company, inst.company_id)
            self.assertIsNotNone(comp)
            self.assertEqual(comp.name, "Swiggy Limited")

    def test_repeat_ingestion_idempotency(self):
        """2. Repeat ingestion of the same listing is idempotent with no duplicates."""
        discovery = InstrumentDiscoveryService()
        snapshot_date = date(2026, 10, 27)

        row = NormalizedMarketSnapshot(
            symbol="ZOMATO",
            series="EQ",
            isin="INE758T01015",
            name="Zomato Limited",
            exchange="NSE",
            snapshot_date=snapshot_date,
            open=Decimal("260.00"),
            high=Decimal("270.00"),
            low=Decimal("258.00"),
            close=Decimal("265.00"),
            last_price=Decimal("265.00"),
            prev_close=Decimal("259.00"),
            volume=5000000,
            turnover=Decimal("1325000000"),
            trades=50000,
            percentage_change_pct=Decimal("2.31"),
            is_calculated_change=True,
            provider_name="TejHQ",
            retrieved_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )

        with self.SessionFactory() as session:
            # First ingestion
            res1 = discovery.discover_and_onboard(session, [row], snapshot_date)
            session.commit()
            self.assertEqual(res1.summary.discovered, 1)

            # Second repeat ingestion of identical row
            res2 = discovery.discover_and_onboard(session, [row], snapshot_date)
            session.commit()
            self.assertEqual(res2.summary.discovered, 0)
            self.assertEqual(res2.summary.skipped_existing, 1)

            # Check that only 1 instrument and 1 company exist
            insts = session.scalars(select(Instrument).where(Instrument.symbol == "ZOMATO")).all()
            self.assertEqual(len(insts), 1)

            comps = session.scalars(select(Company).where(Company.name == "Zomato Limited")).all()
            self.assertEqual(len(comps), 1)

    def test_existing_instrument_discovered_again(self):
        """3. An already existing instrument in DB is recognized and skipped without alteration."""
        discovery = InstrumentDiscoveryService()
        snapshot_date = date(2026, 10, 27)

        row = NormalizedMarketSnapshot(
            symbol="RELIANCE",
            series="EQ",
            isin="INE002A01018",
            name="Reliance Industries Limited",
            exchange="NSE",
            snapshot_date=snapshot_date,
            open=Decimal("2700.00"),
            high=Decimal("2750.00"),
            low=Decimal("2690.00"),
            close=Decimal("2740.00"),
            last_price=Decimal("2742.00"),
            prev_close=Decimal("2710.00"),
            volume=4000000,
            turnover=Decimal("10960000000"),
            trades=80000,
            percentage_change_pct=Decimal("1.10"),
            is_calculated_change=True,
            provider_name="TejHQ",
            retrieved_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )

        with self.SessionFactory() as session:
            res = discovery.discover_and_onboard(session, [row], snapshot_date)
            session.commit()

            self.assertEqual(res.summary.discovered, 0)
            self.assertEqual(res.summary.skipped_existing, 1)

            # RELIANCE identity remains untouched
            inst = session.get(Instrument, self.inst_rel_id)
            self.assertEqual(inst.symbol, "RELIANCE")
            self.assertEqual(inst.listing_date, date(1995, 11, 29))
            self.assertIsNone(inst.first_seen_date)

    def test_name_changes_preserves_existing_identity(self):
        """4. Name changes in snapshot do not break or re-link existing instrument identity."""
        discovery = InstrumentDiscoveryService()
        snapshot_date = date(2026, 10, 27)

        row = NormalizedMarketSnapshot(
            symbol="RELIANCE",
            series="EQ",
            isin="INE002A01018",
            name="Reliance Industries Limited - New Brand Name",
            exchange="NSE",
            snapshot_date=snapshot_date,
            open=Decimal("2700.00"),
            high=Decimal("2750.00"),
            low=Decimal("2690.00"),
            close=Decimal("2740.00"),
            last_price=Decimal("2742.00"),
            prev_close=Decimal("2710.00"),
            volume=4000000,
            turnover=Decimal("10960000000"),
            trades=80000,
            percentage_change_pct=Decimal("1.10"),
            is_calculated_change=True,
            provider_name="TejHQ",
            retrieved_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )

        with self.SessionFactory() as session:
            res = discovery.discover_and_onboard(session, [row], snapshot_date)
            session.commit()

            self.assertEqual(res.summary.discovered, 0)
            self.assertEqual(res.summary.skipped_existing, 1)

            # Existing company name must not be changed merely due to snapshot text
            comp = session.get(Company, self.company_rel_id)
            self.assertEqual(comp.name, "Reliance Industries Limited")

    def test_isin_matches_to_existing_company(self):
        """5. New series with matching ISIN correctly links to the existing company."""
        discovery = InstrumentDiscoveryService()
        snapshot_date = date(2026, 10, 27)

        # Candidate has same ISIN as RELIANCE (INE002A01018), but series BE
        row = NormalizedMarketSnapshot(
            symbol="RELIANCE",
            series="BE",
            isin="INE002A01018",
            name="Reliance Industries Ltd",
            exchange="NSE",
            snapshot_date=snapshot_date,
            open=Decimal("2700.00"),
            high=Decimal("2720.00"),
            low=Decimal("2695.00"),
            close=Decimal("2710.00"),
            last_price=Decimal("2710.00"),
            prev_close=Decimal("2700.00"),
            volume=10000,
            turnover=Decimal("27100000"),
            trades=500,
            percentage_change_pct=Decimal("0.37"),
            is_calculated_change=True,
            provider_name="TejHQ",
            retrieved_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )

        with self.SessionFactory() as session:
            res = discovery.discover_and_onboard(session, [row], snapshot_date)
            session.commit()

            self.assertEqual(res.summary.discovered, 1)
            self.assertEqual(res.summary.reused_company, 1)

            new_inst = session.scalar(
                select(Instrument).where(Instrument.symbol == "RELIANCE", Instrument.series == "BE")
            )
            self.assertIsNotNone(new_inst)
            # Must reuse existing company ID!
            self.assertEqual(new_inst.company_id, self.company_rel_id)
            self.assertEqual(new_inst.first_seen_date, snapshot_date)

    def test_multi_series_under_same_symbol(self):
        """6. Multiple equity series under the same symbol (e.g. EQ and SM) coexist cleanly."""
        discovery = InstrumentDiscoveryService()
        snapshot_date = date(2026, 10, 27)

        rows = [
            NormalizedMarketSnapshot(
                symbol="ALPHACORP",
                series="EQ",
                isin="INE111A01011",
                name="Alpha Corp Limited",
                exchange="NSE",
                snapshot_date=snapshot_date,
                open=Decimal("100"),
                high=Decimal("105"),
                low=Decimal("99"),
                close=Decimal("104"),
                last_price=Decimal("104"),
                prev_close=Decimal("100"),
                volume=10000,
                turnover=Decimal("1040000"),
                trades=100,
                percentage_change_pct=Decimal("4.0"),
                is_calculated_change=True,
                provider_name="TejHQ",
                retrieved_at=datetime.now(timezone.utc).replace(tzinfo=None),
            ),
            NormalizedMarketSnapshot(
                symbol="ALPHACORP",
                series="SM",
                isin="INE111A01011",
                name="Alpha Corp Limited",
                exchange="NSE",
                snapshot_date=snapshot_date,
                open=Decimal("102"),
                high=Decimal("106"),
                low=Decimal("100"),
                close=Decimal("105"),
                last_price=Decimal("105"),
                prev_close=Decimal("101"),
                volume=5000,
                turnover=Decimal("525000"),
                trades=50,
                percentage_change_pct=Decimal("3.96"),
                is_calculated_change=True,
                provider_name="TejHQ",
                retrieved_at=datetime.now(timezone.utc).replace(tzinfo=None),
            ),
        ]

        with self.SessionFactory() as session:
            res = discovery.discover_and_onboard(session, rows, snapshot_date)
            session.commit()

            self.assertEqual(res.summary.discovered, 2)
            self.assertEqual(res.summary.reused_company, 1)  # 2nd row reuses company from 1st

            inst_eq = session.scalar(
                select(Instrument).where(Instrument.symbol == "ALPHACORP", Instrument.series == "EQ")
            )
            inst_sm = session.scalar(
                select(Instrument).where(Instrument.symbol == "ALPHACORP", Instrument.series == "SM")
            )
            self.assertIsNotNone(inst_eq)
            self.assertIsNotNone(inst_sm)
            self.assertEqual(inst_eq.company_id, inst_sm.company_id)

    def test_missing_or_malformed_identity_fields(self):
        """7. Candidates with missing or malformed identity fields are rejected."""
        discovery = InstrumentDiscoveryService()
        snapshot_date = date(2026, 10, 27)

        rows = [
            # Blank symbol
            NormalizedMarketSnapshot(
                symbol="",
                series="EQ",
                isin="INE222A01011",
                name="Bad Symbol Ltd",
                exchange="NSE",
                snapshot_date=snapshot_date,
                open=Decimal("10"),
                high=Decimal("10"),
                low=Decimal("10"),
                close=Decimal("10"),
                last_price=Decimal("10"),
                prev_close=Decimal("10"),
                volume=10,
                turnover=Decimal("100"),
                trades=1,
                percentage_change_pct=Decimal("0"),
                is_calculated_change=False,
                provider_name="TejHQ",
                retrieved_at=datetime.now(timezone.utc).replace(tzinfo=None),
            ),
            # Missing company name
            NormalizedMarketSnapshot(
                symbol="NONAME",
                series="EQ",
                isin="INE333A01011",
                name="",
                exchange="NSE",
                snapshot_date=snapshot_date,
                open=Decimal("10"),
                high=Decimal("10"),
                low=Decimal("10"),
                close=Decimal("10"),
                last_price=Decimal("10"),
                prev_close=Decimal("10"),
                volume=10,
                turnover=Decimal("100"),
                trades=1,
                percentage_change_pct=Decimal("0"),
                is_calculated_change=False,
                provider_name="TejHQ",
                retrieved_at=datetime.now(timezone.utc).replace(tzinfo=None),
            ),
            # Malformed ISIN (length != 12)
            NormalizedMarketSnapshot(
                symbol="BADISIN",
                series="EQ",
                isin="SHORT",
                name="Bad ISIN Corp",
                exchange="NSE",
                snapshot_date=snapshot_date,
                open=Decimal("10"),
                high=Decimal("10"),
                low=Decimal("10"),
                close=Decimal("10"),
                last_price=Decimal("10"),
                prev_close=Decimal("10"),
                volume=10,
                turnover=Decimal("100"),
                trades=1,
                percentage_change_pct=Decimal("0"),
                is_calculated_change=False,
                provider_name="TejHQ",
                retrieved_at=datetime.now(timezone.utc).replace(tzinfo=None),
            ),
        ]

        with self.SessionFactory() as session:
            res = discovery.discover_and_onboard(session, rows, snapshot_date)
            session.commit()

            self.assertEqual(res.summary.discovered, 0)
            self.assertEqual(res.summary.invalid_identity, 3)

    def test_unsupported_instrument_types_ignored(self):
        """8. Unsupported instrument types (bonds, gold bonds, funds, warrants, preference) are skipped."""
        discovery = InstrumentDiscoveryService()
        snapshot_date = date(2026, 10, 27)

        rows = [
            # Debenture / Bond series N1
            NormalizedMarketSnapshot(
                symbol="TATADEB",
                series="N1",
                isin="INE155A07010",
                name="Tata Debentures",
                exchange="NSE",
                snapshot_date=snapshot_date,
                open=Decimal("1000"),
                high=Decimal("1000"),
                low=Decimal("1000"),
                close=Decimal("1000"),
                last_price=Decimal("1000"),
                prev_close=Decimal("1000"),
                volume=10,
                turnover=Decimal("10000"),
                trades=1,
                percentage_change_pct=Decimal("0"),
                is_calculated_change=False,
                provider_name="TejHQ",
                retrieved_at=datetime.now(timezone.utc).replace(tzinfo=None),
            ),
            # Sovereign Gold Bond GB
            NormalizedMarketSnapshot(
                symbol="SGBMAY29",
                series="GB",
                isin="IN0020190101",
                name="Sovereign Gold Bond 2029",
                exchange="NSE",
                snapshot_date=snapshot_date,
                open=Decimal("5000"),
                high=Decimal("5000"),
                low=Decimal("5000"),
                close=Decimal("5000"),
                last_price=Decimal("5000"),
                prev_close=Decimal("5000"),
                volume=10,
                turnover=Decimal("50000"),
                trades=1,
                percentage_change_pct=Decimal("0"),
                is_calculated_change=False,
                provider_name="TejHQ",
                retrieved_at=datetime.now(timezone.utc).replace(tzinfo=None),
            ),
            # Mutual fund / ETF starting with INF
            NormalizedMarketSnapshot(
                symbol="NIFTYBEES",
                series="EQ",
                isin="INF204KB14I2",
                name="Nippon India ETF Nifty BeES",
                exchange="NSE",
                snapshot_date=snapshot_date,
                open=Decimal("250"),
                high=Decimal("252"),
                low=Decimal("249"),
                close=Decimal("251"),
                last_price=Decimal("251"),
                prev_close=Decimal("250"),
                volume=500000,
                turnover=Decimal("125500000"),
                trades=15000,
                percentage_change_pct=Decimal("0.4"),
                is_calculated_change=True,
                provider_name="TejHQ",
                retrieved_at=datetime.now(timezone.utc).replace(tzinfo=None),
            ),
            # Preference shares P1
            NormalizedMarketSnapshot(
                symbol="PREFSHR",
                series="P1",
                isin="INE999A04011",
                name="Preference Shares Co",
                exchange="NSE",
                snapshot_date=snapshot_date,
                open=Decimal("100"),
                high=Decimal("100"),
                low=Decimal("100"),
                close=Decimal("100"),
                last_price=Decimal("100"),
                prev_close=Decimal("100"),
                volume=10,
                turnover=Decimal("1000"),
                trades=1,
                percentage_change_pct=Decimal("0"),
                is_calculated_change=False,
                provider_name="TejHQ",
                retrieved_at=datetime.now(timezone.utc).replace(tzinfo=None),
            ),
        ]

        with self.SessionFactory() as session:
            res = discovery.discover_and_onboard(session, rows, snapshot_date)
            session.commit()

            self.assertEqual(res.summary.discovered, 0)
            self.assertEqual(res.summary.unsupported_series, 4)

    def test_eod_pipeline_end_to_end_discovery_and_snapshot(self):
        """Integration: EODUpdateService discovers new IPO, assigns snapshot in the same run, and is searchable."""
        snapshot_date = date(2026, 10, 27)

        # Mock TejHQ provider returning RELIANCE (existing) and NEWIPO (new listing)
        mock_tejhq = MagicMock()
        mock_tejhq.get_status.return_value = ProviderStatus(
            provider_name="TejHQ",
            trading_date=snapshot_date,
            stage="prices",
            prices_published_at=datetime(2026, 10, 27, 18, 0),
            derived_published_at=None,
            is_fresh=True,
        )
        mock_tejhq.get_daily_snapshot.return_value = [
            NormalizedMarketSnapshot(
                symbol="RELIANCE",
                series="EQ",
                isin="INE002A01018",
                name="Reliance Industries Limited",
                exchange="NSE",
                snapshot_date=snapshot_date,
                open=Decimal("2700.00"),
                high=Decimal("2750.00"),
                low=Decimal("2690.00"),
                close=Decimal("2740.00"),
                last_price=Decimal("2742.00"),
                prev_close=Decimal("2710.00"),
                volume=4000000,
                turnover=Decimal("10960000000"),
                trades=80000,
                percentage_change_pct=Decimal("1.10"),
                is_calculated_change=True,
                provider_name="TejHQ",
                retrieved_at=datetime.now(timezone.utc).replace(tzinfo=None),
            ),
            NormalizedMarketSnapshot(
                symbol="NEWIPO",
                series="EQ",
                isin="INE999V01019",
                name="New Tech IPO Limited",
                exchange="NSE",
                snapshot_date=snapshot_date,
                open=Decimal("500.00"),
                high=Decimal("550.00"),
                low=Decimal("490.00"),
                close=Decimal("540.00"),
                last_price=Decimal("542.00"),
                prev_close=Decimal("500.00"),
                volume=2000000,
                turnover=Decimal("1080000000"),
                trades=30000,
                percentage_change_pct=Decimal("8.00"),
                is_calculated_change=True,
                provider_name="TejHQ",
                retrieved_at=datetime.now(timezone.utc).replace(tzinfo=None),
            ),
        ]

        service = EODUpdateService(
            tejhq_provider=mock_tejhq,
            session_factory=self.SessionFactory,
        )

        update_res = service.run_update(target_date=snapshot_date)
        self.assertEqual(update_res.status, "completed")
        self.assertEqual(update_res.instruments_discovered, 1)
        self.assertEqual(update_res.records_inserted, 2)  # Both RELIANCE and NEWIPO snapshots inserted!

        # Verify NEWIPO is immediately searchable via API
        response = self.client.get("/api/v1/instruments?query=NEWIPO")
        self.assertEqual(response.status_code, 200)
        items = response.json()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["symbol"], "NEWIPO")
        self.assertEqual(items[0]["company_name"], "New Tech IPO Limited")
        new_inst_id = items[0]["instrument_id"]

        # Verify Instrument Detail endpoint
        detail_resp = self.client.get(f"/api/v1/instruments/{new_inst_id}")
        self.assertEqual(detail_resp.status_code, 200)
        detail = detail_resp.json()
        self.assertEqual(detail["symbol"], "NEWIPO")
        self.assertIsNone(detail["listing_date"])
        self.assertEqual(detail["first_seen_date"], "2026-10-27")
        self.assertIsNotNone(detail["snapshot"])
        self.assertEqual(Decimal(str(detail["snapshot"]["close"])), Decimal("540.00"))
        self.assertEqual(Decimal(str(detail["snapshot"]["ltp"])), Decimal("542.00"))

    def test_failed_database_transaction_rollback(self):
        """9. Fatal DB error during ingestion causes complete rollback and marks run as failed."""
        snapshot_date = date(2026, 10, 27)

        mock_tejhq = MagicMock()
        mock_tejhq.get_status.return_value = ProviderStatus(
            provider_name="TejHQ",
            trading_date=snapshot_date,
            stage="prices",
            prices_published_at=datetime(2026, 10, 27, 18, 0),
            derived_published_at=None,
            is_fresh=True,
        )
        mock_tejhq.get_daily_snapshot.return_value = [
            NormalizedMarketSnapshot(
                symbol="FAILIPO",
                series="EQ",
                isin="INE888V01019",
                name="Fail IPO Limited",
                exchange="NSE",
                snapshot_date=snapshot_date,
                open=Decimal("100"),
                high=Decimal("100"),
                low=Decimal("100"),
                close=Decimal("100"),
                last_price=Decimal("100"),
                prev_close=Decimal("100"),
                volume=100,
                turnover=Decimal("10000"),
                trades=1,
                percentage_change_pct=Decimal("0"),
                is_calculated_change=False,
                provider_name="TejHQ",
                retrieved_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
        ]

        service = EODUpdateService(
            tejhq_provider=mock_tejhq,
            session_factory=self.SessionFactory,
        )

        orig_commit = Session.commit
        commit_count = 0

        def flaky_commit(session_self):
            nonlocal commit_count
            commit_count += 1
            if commit_count == 3:
                raise RuntimeError("Simulated DB Crash")
            return orig_commit(session_self)

        with patch.object(Session, "commit", side_effect=flaky_commit, autospec=True):
            update_res = service.run_update(target_date=snapshot_date)
            self.assertEqual(update_res.status, "failed")

        # Verify FAILIPO was NOT persisted
        with self.SessionFactory() as session:
            inst = session.scalar(select(Instrument).where(Instrument.symbol == "FAILIPO"))
            self.assertIsNone(inst)

    def test_dry_run_does_not_persist(self):
        """10. Dry run mode performs discovery in memory but rolls back without saving to DB."""
        snapshot_date = date(2026, 10, 27)

        mock_tejhq = MagicMock()
        mock_tejhq.get_daily_snapshot.return_value = [
            NormalizedMarketSnapshot(
                symbol="DRYIPO",
                series="EQ",
                isin="INE777V01019",
                name="Dry Run IPO Limited",
                exchange="NSE",
                snapshot_date=snapshot_date,
                open=Decimal("100"),
                high=Decimal("100"),
                low=Decimal("100"),
                close=Decimal("100"),
                last_price=Decimal("100"),
                prev_close=Decimal("100"),
                volume=100,
                turnover=Decimal("10000"),
                trades=1,
                percentage_change_pct=Decimal("0"),
                is_calculated_change=False,
                provider_name="TejHQ",
                retrieved_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
        ]

        service = EODUpdateService(
            tejhq_provider=mock_tejhq,
            session_factory=self.SessionFactory,
        )

        update_res = service.run_update(target_date=snapshot_date, dry_run=True)
        self.assertIn("[DRY RUN]", update_res.message)

        # Verify DRYIPO was rolled back
        with self.SessionFactory() as session:
            inst = session.scalar(select(Instrument).where(Instrument.symbol == "DRYIPO"))
            self.assertIsNone(inst)


if __name__ == "__main__":
    unittest.main()
