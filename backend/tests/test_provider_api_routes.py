from __future__ import annotations

import unittest
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import BigInteger, Integer, create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

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
from app.providers.base import ProviderStatus


class TestProviderApiRoutes(unittest.TestCase):
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
        cls.session_factory = sessionmaker(bind=cls.engine)

        with cls.session_factory() as session:
            company = Company(name="RELIANCE INDUSTRIES LIMITED")
            session.add(company)
            session.flush()

            source = DataSource(
                name="TejHQ EOD Market Data",
                source_type="api",
                source_url="https://api.tejhq.dev",
                terms_url="https://tejhq.dev/docs",
                is_active=True,
            )
            session.add(source)
            session.flush()

            inst = Instrument(
                company_id=company.id,
                exchange="NSE",
                symbol="RELIANCE",
                series="EQ",
                instrument_type="EQUITY",
                isin="INE002A01018",
                is_active=True,
            )
            session.add(inst)
            session.flush()

            snapshot = DailyMarketSnapshot(
                instrument_id=inst.id,
                source_id=source.id,
                snapshot_date=date(2026, 10, 14),
                open_price=Decimal("1167.000000"),
                high_price=Decimal("1188.000000"),
                low_price=Decimal("1162.700000"),
                close_price=Decimal("1174.600000"),
                last_traded_price=Decimal("1174.600000"),
                prev_close_price=Decimal("1166.700000"),
                percentage_change_pct=Decimal("0.677123"),
                is_calculated_change=True,
                volume=10938195,
                turnover=Decimal("12880776743.5000"),
                trade_count=233442,
                volume_lakhs=Decimal("109.381950"),
                traded_value_crores=Decimal("1288.077674"),
            )
            session.add(snapshot)

            run = IngestionRun(
                source_id=source.id,
                dataset_name="tejhq_eod_snapshot_2026-10-14",
                trading_date=date(2026, 10, 14),
                source_status="derived",
                status="completed",
                records_read=2944,
                records_inserted=2593,
                records_updated=0,
                records_skipped=0,
                records_failed=0,
                records_unmatched=351,
            )
            session.add(run)
            session.commit()
            cls.test_inst_id = inst.id

        def override_get_db():
            with cls.session_factory() as session:
                yield session

        app.dependency_overrides[get_db] = override_get_db
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()
        Base.metadata.drop_all(cls.engine)
        cls.engine.dispose()

    def test_provider_status_endpoint(self):
        with patch("app.api.routes.TejHQProvider.get_status") as mock_status:
            mock_status.return_value = ProviderStatus(
                provider_name="TejHQ",
                trading_date=date(2026, 10, 14),
                stage="derived",
                prices_published_at=datetime(2026, 10, 14, 20, 3, 33),
                derived_published_at=datetime(2026, 10, 14, 20, 11, 22),
                is_fresh=True,
            )
            res = self.client.get("/api/v1/providers/status")
            self.assertEqual(res.status_code, 200)
            data = res.json()

            self.assertEqual(data["primary_provider"], "TejHQ")
            self.assertEqual(data["latest_published_trading_date"], "2026-10-14")
            self.assertEqual(data["pipeline_stage"], "derived")
            self.assertTrue(data["is_fresh"])
            self.assertEqual(data["last_local_ingestion_date"], "2026-10-14")
            self.assertEqual(data["last_local_ingestion_status"], "completed")
            self.assertFalse(data["is_local_stale"])

            # Verify providers list
            provider_names = [p["name"] for p in data["providers"]]
            self.assertIn("TejHQ EOD Market Data", provider_names)

    def test_instrument_detail_extended_snapshot_fields(self):
        res = self.client.get(f"/api/v1/instruments/{self.test_inst_id}")
        self.assertEqual(res.status_code, 200)
        data = res.json()

        self.assertEqual(data["symbol"], "RELIANCE")
        snap = data["snapshot"]
        self.assertIsNotNone(snap)

        # Distinct LTP and close fields
        self.assertEqual(Decimal(str(snap["ltp"])), Decimal("1174.6"))
        self.assertEqual(Decimal(str(snap["close"])), Decimal("1174.6"))
        self.assertEqual(Decimal(str(snap["open"])), Decimal("1167.0"))
        self.assertEqual(Decimal(str(snap["high"])), Decimal("1188.0"))
        self.assertEqual(Decimal(str(snap["low"])), Decimal("1162.7"))
        self.assertEqual(Decimal(str(snap["prev_close"])), Decimal("1166.7"))

        # Raw units
        self.assertEqual(snap["volume"], 10938195)
        self.assertEqual(Decimal(str(snap["turnover"])), Decimal("12880776743.5"))
        self.assertEqual(snap["trade_count"], 233442)

        # Existing units backward-compatibility
        self.assertEqual(Decimal(str(snap["volume_lakhs"])), Decimal("109.38195"))
        self.assertEqual(Decimal(str(snap["traded_value_crores"])), Decimal("1288.077674"))

        # Provenance and metadata
        self.assertEqual(snap["source_name"], "TejHQ EOD Market Data")
        self.assertIsNotNone(snap["last_ingested_at"])
        self.assertFalse(snap["is_stale"])
        self.assertEqual(snap["freshness_status"], "fresh")

    def test_provider_status_filters_eod_datasets_and_distinguishes_attempted_vs_successful(self):
        """Phase C: Ensure EOD status filters EOD dataset/source, distinguishes attempted from successful,

        and does not report a partial run as fully successful or pick up unrelated runs.
        """
        with self.session_factory() as session:
            # Add an unrelated master data run (completed)
            master_source = DataSource(
                name="NSE Equity Master",
                source_type="master_data",
                is_active=True,
            )
            session.add(master_source)
            session.flush()

            unrelated_run = IngestionRun(
                source_id=master_source.id,
                dataset_name="equity_master",
                trading_date=None,
                status="completed",
                started_at=datetime(2026, 10, 16, 9, 0, 0),
                completed_at=datetime(2026, 10, 16, 9, 5, 0),
                records_read=2605,
                records_inserted=2605,
            )
            session.add(unrelated_run)

            # Add an EOD partial run for 2026-10-15
            eod_source = session.query(DataSource).filter_by(name="TejHQ EOD Market Data").first()
            partial_eod_run = IngestionRun(
                source_id=eod_source.id,
                dataset_name="tejhq_eod_snapshot_2026-10-15",
                trading_date=date(2026, 10, 15),
                source_status="derived",
                status="partial",
                started_at=datetime(2026, 10, 15, 20, 0, 0),
                completed_at=datetime(2026, 10, 15, 20, 10, 0),
                records_read=2944,
                records_inserted=2592,
                records_unmatched=352,
            )
            session.add(partial_eod_run)
            session.commit()

            try:
                with patch("app.api.routes.TejHQProvider.get_status") as mock_status:
                    mock_status.return_value = ProviderStatus(
                        provider_name="TejHQ",
                        trading_date=date(2026, 10, 15),
                        stage="derived",
                        prices_published_at=datetime(2026, 10, 15, 20, 3, 33),
                        derived_published_at=datetime(2026, 10, 15, 20, 11, 22),
                        is_fresh=True,
                    )
                    res = self.client.get("/api/v1/providers/status")
                    self.assertEqual(res.status_code, 200)
                    data = res.json()

                    # The latest attempted EOD run is for 2026-10-15 with status 'partial'
                    self.assertEqual(data["last_run_status"], "partial")
                    self.assertEqual(data["last_local_ingestion_date"], "2026-10-15")
                    self.assertEqual(data["last_local_ingestion_status"], "partial")
                    self.assertTrue(data["incomplete_coverage"])

                    # The last SUCCESSFUL run must be 'completed' only (from 2026-10-14),
                    # not the partial run on 2026-10-15 and NOT the unrelated equity_master run!
                    self.assertEqual(data["last_successful_ingestion_date"], "2026-10-14")
                    self.assertEqual(data["provider_availability"], "available")
            finally:
                session.delete(partial_eod_run)
                session.delete(unrelated_run)
                session.delete(master_source)
                session.commit()

    def test_provider_status_external_provider_unavailable(self):
        """Phase C: When external provider fails/times out, reports 'unavailable' without crashing or leaking traces."""
        with patch("app.api.routes.TejHQProvider.get_status") as mock_status:
            mock_status.side_effect = Exception("Connection timed out to upstream server")
            res = self.client.get("/api/v1/providers/status")
            self.assertEqual(res.status_code, 200)
            data = res.json()

            self.assertEqual(data["provider_availability"], "unavailable")
            self.assertEqual(data["pipeline_stage"], "unavailable")
            self.assertFalse(data["is_fresh"])
            self.assertIsNone(data["latest_published_trading_date"])

    def test_snapshot_staleness_and_freshness_status(self):
        """Phase D: An older snapshot is marked is_stale=True when a newer EOD date exists in system."""
        with self.session_factory() as session:
            eod_source = session.query(DataSource).filter_by(name="TejHQ EOD Market Data").first()
            new_eod_run = IngestionRun(
                source_id=eod_source.id,
                dataset_name="tejhq_eod_snapshot_2026-10-15",
                trading_date=date(2026, 10, 15),
                status="partial",
                started_at=datetime(2026, 10, 15, 20, 0, 0),
                records_unmatched=5,
            )
            session.add(new_eod_run)
            session.commit()

            try:
                # Our test instrument only has snapshot for 2026-10-14, which is now older than system's 2026-10-15 date
                res = self.client.get(f"/api/v1/instruments/{self.test_inst_id}")
                self.assertEqual(res.status_code, 200)
                data = res.json()
                snap = data["snapshot"]
                self.assertEqual(snap["snapshot_date"], "2026-10-14")
                self.assertTrue(snap["is_stale"])
                self.assertEqual(snap["freshness_status"], "stale")

                # Now add a snapshot for 2026-10-15 with partial status
                snap_15 = DailyMarketSnapshot(
                    instrument_id=self.test_inst_id,
                    source_id=eod_source.id,
                    snapshot_date=date(2026, 10, 15),
                    last_traded_price=Decimal("1180.000000"),
                    close_price=Decimal("1180.000000"),
                )
                session.add(snap_15)
                session.commit()

                res_15 = self.client.get(f"/api/v1/instruments/{self.test_inst_id}")
                self.assertEqual(res_15.status_code, 200)
                data_15 = res_15.json()
                snap_res = data_15["snapshot"]
                self.assertEqual(snap_res["snapshot_date"], "2026-10-15")
                self.assertFalse(snap_res["is_stale"])
                self.assertEqual(snap_res["freshness_status"], "incomplete")

                session.delete(snap_15)
                session.commit()
            finally:
                session.delete(new_eod_run)
                session.commit()

    def test_market_cap_not_copied_from_older_snapshot(self):
        """Phase E: Missing latest market-cap must return None (null in JSON) and NOT copy from an older date."""
        with self.session_factory() as session:
            eod_source = session.query(DataSource).filter_by(name="TejHQ EOD Market Data").first()

            # Set an older market cap on the 2026-10-14 snapshot
            old_snap = (
                session.query(DailyMarketSnapshot)
                .filter_by(instrument_id=self.test_inst_id, snapshot_date=date(2026, 10, 14))
                .first()
            )
            old_snap.market_capitalization_crores = Decimal("1550000.75")
            session.flush()

            # Create a newer snapshot for 2026-10-15 that DOES NOT have market cap
            new_snap = DailyMarketSnapshot(
                instrument_id=self.test_inst_id,
                source_id=eod_source.id,
                snapshot_date=date(2026, 10, 15),
                last_traded_price=Decimal("1185.000000"),
                close_price=Decimal("1185.000000"),
                market_capitalization_crores=None,  # Missing in TejHQ feed
            )
            session.add(new_snap)
            session.commit()

            try:
                res = self.client.get(f"/api/v1/instruments/{self.test_inst_id}")
                self.assertEqual(res.status_code, 200)
                data = res.json()
                snap = data["snapshot"]
                self.assertEqual(snap["snapshot_date"], "2026-10-15")
                # Must be None, not silently copied from 2026-10-14!
                self.assertIsNone(snap["market_capitalization_crores"])
            finally:
                session.delete(new_snap)
                old_snap.market_capitalization_crores = None
                session.commit()

    def test_last_ingested_at_associated_with_run(self):
        """Phase F: Ingestion timestamp reflects associated IngestionRun.completed_at."""
        with self.session_factory() as session:
            run = (
                session.query(IngestionRun)
                .filter_by(dataset_name="tejhq_eod_snapshot_2026-10-14")
                .first()
            )
            expected_time = datetime(2026, 10, 14, 21, 45, 10)
            run.completed_at = expected_time
            session.commit()

            try:
                res = self.client.get(f"/api/v1/instruments/{self.test_inst_id}")
                self.assertEqual(res.status_code, 200)
                snap = res.json()["snapshot"]
                self.assertEqual(snap["last_ingested_at"], "2026-10-14T21:45:10")
            finally:
                run.completed_at = None
                session.commit()


if __name__ == "__main__":
    unittest.main()
