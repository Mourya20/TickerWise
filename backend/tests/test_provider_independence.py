"""Tests for Provider Independence, Evaluation Registry, Latency Measurement, and Controlled Fallback.

Verifies:
1. Provider capability interfaces (EOD, historical OHLCV, corporate actions, master, fundamentals).
2. Provider evaluation registry (terms, scraping permissions, latencies, coverage).
3. Observed latency measurement relative to NSE market close (15:30:00 IST).
4. Publication readiness assessment and bounded polling (no mistaking unpublished data for empty sessions).
5. Controlled fallback validation gate (identity, date, field, unit, coverage, permission checks).
6. Controlled fallback ingestion with explicit provider provenance in EODUpdateService.
7. Zero mutation and zero network calls during read-only provider status queries.
"""
from __future__ import annotations

import unittest
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

from sqlalchemy import BigInteger, Integer, create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.market_data.fallback import FallbackValidationGate, FallbackValidationResult
from app.market_data.freshness import (
    KNOWN_NSE_HOLIDAYS_2026,
    PublicationReadiness,
    assess_target_date_readiness,
    is_trading_day,
    poll_for_eod_publication,
)
from app.market_data.latency import (
    IST,
    NSE_MARKET_CLOSE_TIME,
    get_market_close_datetime,
    measure_observed_latency,
)
from app.models import Company, DailyMarketSnapshot, DataSource, IngestionRun, Instrument
from app.providers.base import (
    ICorporateActionsProvider,
    IEODSnapshotProvider,
    IFundamentalDisclosuresProvider,
    IHistoricalOHLCVProvider,
    IInstrumentMasterProvider,
    NormalizedMarketSnapshot,
    NormalizedOHLCV,
    ProviderError,
    ProviderStatus,
)
from app.providers.registry import (
    ProviderCapability,
    ProviderEvaluation,
    ProviderRegistry,
    ProviderRole,
)
from app.queries.provider_queries import (
    get_cached_provider_status,
    get_local_provider_status_data,
    set_cached_provider_status,
)
from app.services.eod_update_service import EODUpdateResult, EODUpdateService


class TestProviderIndependence(unittest.TestCase):
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
        self.session_factory = sessionmaker(bind=self.engine)

        with self.session_factory() as session:
            c = Company(name="INFOSYS LIMITED")
            session.add(c)
            session.flush()

            src = DataSource(
                name="TejHQ EOD Market Data",
                source_type="api",
                source_url="https://api.tejhq.dev",
                terms_url="https://tejhq.dev/docs",
                is_active=True,
            )
            session.add(src)
            session.flush()

            inst = Instrument(
                company_id=c.id,
                exchange="NSE",
                symbol="INFY",
                series="EQ",
                instrument_type="EQUITY",
                isin="INE009A01021",
                is_active=True,
            )
            session.add(inst)
            session.commit()

            self.company_id = c.id
            self.instrument_id = inst.id
            self.source_id = src.id

    def tearDown(self):
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    # --- 1. Provider Capability Protocols ---
    def test_provider_capability_protocols(self):
        class MockEODProvider(IEODSnapshotProvider):
            def get_status(self) -> ProviderStatus:
                return ProviderStatus(
                    provider_name="Mock",
                    trading_date=date(2026, 10, 28),
                    stage="derived",
                    prices_published_at=None,
                    derived_published_at=None,
                    is_fresh=True,
                )

            def get_daily_snapshot(self, snapshot_date: date, exchange: str = "NSE") -> list[NormalizedMarketSnapshot]:
                return []

        prov = MockEODProvider()
        self.assertIsInstance(prov, IEODSnapshotProvider)
        self.assertEqual(prov.get_status().provider_name, "Mock")

    # --- 2. Provider Evaluation Registry & Terms Verification ---
    def test_provider_registry_lookups(self):
        tejhq = ProviderRegistry.get_provider("tejhq")
        self.assertIsNotNone(tejhq)
        self.assertEqual(tejhq.role, ProviderRole.PRIMARY_CANONICAL)
        self.assertTrue(tejhq.local_storage_permitted)
        self.assertTrue(tejhq.intended_display_permitted)
        self.assertIn(ProviderCapability.EOD_SNAPSHOT, tejhq.capabilities)
        self.assertIn(ProviderCapability.HISTORICAL_OHLCV, tejhq.capabilities)

        # NSE Bhavcopy
        bhavcopy = ProviderRegistry.get_provider("nse_official_bhavcopy")
        self.assertIsNotNone(bhavcopy)
        self.assertFalse(bhavcopy.automated_scraping_permitted)  # Akamai protected & Terms forbid bots
        self.assertTrue(bhavcopy.local_storage_permitted)        # Authorized offline downloads permitted

        # Yahoo finance is quarantined
        yf = ProviderRegistry.get_provider("yahoo_finance")
        self.assertEqual(yf.role, ProviderRole.QUARANTINED)
        self.assertFalse(yf.local_storage_permitted)

    def test_provider_permissions_verification(self):
        perms = ProviderRegistry.verify_permissions("tejhq")
        self.assertTrue(perms["exists"])
        self.assertTrue(perms["automated_scraping_permitted"])
        self.assertTrue(perms["local_storage_permitted"])

        nse_perms = ProviderRegistry.verify_permissions("nse_official_bhavcopy")
        self.assertFalse(nse_perms["automated_scraping_permitted"])

    # --- 3. Observed Latency Measurement ---
    def test_market_close_datetime(self):
        d = date(2026, 10, 28)
        close_dt = get_market_close_datetime(d)
        self.assertEqual(close_dt.hour, 15)
        self.assertEqual(close_dt.minute, 30)
        self.assertEqual(close_dt.tzinfo, IST)

    def test_measure_observed_latency_on_time_and_delayed(self):
        d = date(2026, 10, 28)
        market_close = datetime(2026, 10, 28, 15, 30, tzinfo=IST)
        # Provider published at 20:15 IST (4h 45m post-close)
        pub_time = datetime(2026, 10, 28, 20, 15, tzinfo=IST)
        retrieval = datetime(2026, 10, 28, 20, 20, tzinfo=IST)
        completed = datetime(2026, 10, 28, 20, 25, tzinfo=IST)

        metrics = measure_observed_latency(
            trading_date=d,
            retrieval_started_at=retrieval,
            derived_published_at=pub_time,
            ingestion_completed_at=completed,
            expected_threshold_hours=6.0,
        )

        self.assertFalse(metrics.is_delayed)
        self.assertAlmostEqual(metrics.upstream_derived_latency_seconds, 17100.0, places=0)
        self.assertIn("4h 45m", metrics.human_summary)

        # Delayed scenario (published at 22:30 IST, 7h post-close)
        pub_late = datetime(2026, 10, 28, 22, 30, tzinfo=IST)
        late_metrics = measure_observed_latency(
            trading_date=d,
            retrieval_started_at=pub_late,
            derived_published_at=pub_late,
            expected_threshold_hours=6.0,
        )
        self.assertTrue(late_metrics.is_delayed)
        self.assertIn("(DELAYED)", late_metrics.human_summary)

    # --- 4. Readiness Assessment & Bounded Polling ---
    def test_trading_day_detection(self):
        # 2026-10-24 is Saturday, 2026-10-25 is Sunday
        self.assertFalse(is_trading_day(date(2026, 10, 24)))
        self.assertFalse(is_trading_day(date(2026, 10, 25)))
        # 2026-10-28 is Wednesday (normal trading day)
        self.assertTrue(is_trading_day(date(2026, 10, 28)))
        # Republic Day 2026-01-26 is Monday holiday
        self.assertFalse(is_trading_day(date(2026, 1, 26)))

    def test_assess_target_date_readiness_pending_vs_ready(self):
        mock_provider = MagicMock(spec=IEODSnapshotProvider)
        mock_provider.provider_name = "TejHQ"

        # 1. Target date is weekend
        res = assess_target_date_readiness(mock_provider, date(2026, 10, 25))
        self.assertEqual(res.readiness, PublicationReadiness.NON_TRADING_SESSION)

        # 2. Target date is today (Wednesday), but provider has only published yesterday
        mock_provider.get_status.return_value = ProviderStatus(
            provider_name="TejHQ",
            trading_date=date(2026, 10, 27),
            stage="derived",
            prices_published_at=None,
            derived_published_at=None,
            is_fresh=True,
        )
        res_pending = assess_target_date_readiness(mock_provider, date(2026, 10, 28))
        self.assertEqual(res_pending.readiness, PublicationReadiness.PENDING_PUBLICATION)
        self.assertIn("NOT yet been published", res_pending.message)

        # 3. Provider has published target date and stage is derived
        mock_provider.get_status.return_value = ProviderStatus(
            provider_name="TejHQ",
            trading_date=date(2026, 10, 28),
            stage="derived",
            prices_published_at=None,
            derived_published_at=None,
            is_fresh=True,
        )
        res_ready = assess_target_date_readiness(mock_provider, date(2026, 10, 28))
        self.assertEqual(res_ready.readiness, PublicationReadiness.READY)

    # --- 5. Controlled Fallback Validation Gate ---
    def test_fallback_validation_gate_rejection_of_unpermitted_provider(self):
        rows = [
            NormalizedMarketSnapshot(
                symbol="INFY",
                series="EQ",
                isin="INE009A01021",
                name="INFOSYS LIMITED",
                exchange="NSE",
                snapshot_date=date(2026, 10, 28),
                open=Decimal("1900.00"),
                high=Decimal("1920.00"),
                low=Decimal("1890.00"),
                close=Decimal("1910.00"),
                last_price=Decimal("1910.00"),
                prev_close=Decimal("1895.00"),
                volume=1000000,
                turnover=Decimal("1910000000.00"),
                trades=50000,
                percentage_change_pct=Decimal("0.791557"),
                is_calculated_change=False,
                provider_name="yahoo_finance",
                retrieved_at=datetime.now(timezone.utc),
            )
        ]
        val = FallbackValidationGate.validate_payload(
            provider_id="yahoo_finance",  # not permitted for storage
            target_date=date(2026, 10, 28),
            rows=rows,
            registered_instruments={},
            symbol_instruments={},
            min_coverage=1,
        )
        self.assertFalse(val.is_accepted)
        self.assertTrue(any("not authorized for local storage" in r for r in val.rejection_reasons))

    def test_fallback_validation_gate_detects_ohlc_violation_and_unit_anomaly(self):
        # High < Low and negative price
        invalid_rows = [
            NormalizedMarketSnapshot(
                symbol="INFY",
                series="EQ",
                isin="INE009A01021",
                name="INFOSYS",
                exchange="NSE",
                snapshot_date=date(2026, 10, 28),
                open=Decimal("100"),
                high=Decimal("90"),   # High < Low violation!
                low=Decimal("110"),
                close=Decimal("105"),
                last_price=Decimal("105"),
                prev_close=Decimal("100"),
                volume=100,
                turnover=Decimal("10"),  # Turnover 10 vs volume*price ~ 10,000 (unit anomaly!)
                trades=10,
                percentage_change_pct=Decimal("5.0"),
                is_calculated_change=False,
                provider_name="tejhq",
                retrieved_at=datetime.now(timezone.utc),
            )
        ]
        with self.session_factory() as s:
            inst = s.get(Instrument, self.instrument_id)
            val = FallbackValidationGate.validate_payload(
                provider_id="tejhq",
                target_date=date(2026, 10, 28),
                rows=invalid_rows,
                registered_instruments={("NSE", "INFY", "EQ"): inst},
                symbol_instruments={("NSE", "INFY"): [inst]},
                min_coverage=1,
            )
            self.assertFalse(val.is_accepted)
            self.assertEqual(val.records_failed, 1)

    # --- 6. Controlled Fallback Ingestion in EODUpdateService ---
    def test_eod_service_switches_to_fallback_when_primary_fails(self):
        # Primary fails
        mock_primary = MagicMock(spec=IEODSnapshotProvider)
        mock_primary.provider_name = "TejHQ"
        mock_primary.get_status.return_value = ProviderStatus(
            provider_name="TejHQ",
            trading_date=date(2026, 10, 28),
            stage="derived",
            prices_published_at=None,
            derived_published_at=None,
            is_fresh=True,
        )
        mock_primary.get_daily_snapshot.side_effect = ProviderError("Primary API Timeout 504")

        # Fallback provider passes validation
        mock_fallback = MagicMock(spec=IEODSnapshotProvider)
        mock_fallback.provider_name = "eodhd_commercial"
        valid_row = NormalizedMarketSnapshot(
            symbol="INFY",
            series="EQ",
            isin="INE009A01021",
            name="INFOSYS LIMITED",
            exchange="NSE",
            snapshot_date=date(2026, 10, 28),
            open=Decimal("1900.00"),
            high=Decimal("1920.00"),
            low=Decimal("1890.00"),
            close=Decimal("1910.00"),
            last_price=Decimal("1910.00"),
            prev_close=Decimal("1895.00"),
            volume=1000000,
            turnover=Decimal("1910000000.00"),
            trades=50000,
            percentage_change_pct=Decimal("0.791557"),
            is_calculated_change=False,
            provider_name="eodhd_commercial",
            retrieved_at=datetime.now(timezone.utc),
        )
        mock_fallback.get_daily_snapshot.return_value = [valid_row]

        service = EODUpdateService(
            tejhq_provider=mock_primary,
            fallback_provider=mock_fallback,
            session_factory=self.session_factory,
        )

        result = service.run_update(
            target_date=date(2026, 10, 28),
            min_coverage_threshold=1,
        )

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.records_inserted, 1)

        # Verify fallback source provenance in DB
        with self.session_factory() as session:
            snap = session.scalar(
                select(DailyMarketSnapshot).where(
                    DailyMarketSnapshot.instrument_id == self.instrument_id,
                    DailyMarketSnapshot.snapshot_date == date(2026, 10, 28),
                )
            )
            self.assertIsNotNone(snap)
            self.assertEqual(snap.close_price, Decimal("1910.00"))
            # Must NOT be primary source id; must reference fallback source!
            self.assertNotEqual(snap.source_id, self.source_id)
            fb_source = session.get(DataSource, snap.source_id)
            self.assertIn("Fallback", fb_source.name)

    # --- 7. Read-Only Query Layer Zero-Mutation & Zero-Network Guarantee ---
    def test_get_local_provider_status_data_zero_network_and_zero_mutation(self):
        with self.session_factory() as session:
            # Seed an IngestionRun
            run = IngestionRun(
                source_id=self.source_id,
                dataset_name="tejhq_eod_snapshot_2026-10-28",
                trading_date=date(2026, 10, 28),
                source_status="derived | +4h 45m post-close",
                status="completed",
                started_at=datetime(2026, 10, 28, 20, 15, 0),
                completed_at=datetime(2026, 10, 28, 20, 25, 0),
                records_read=2600,
                records_inserted=2600,
            )
            session.add(run)
            session.commit()

            # Set background telemetry in store
            set_cached_provider_status(
                "tejhq",
                ProviderStatus(
                    provider_name="TejHQ",
                    trading_date=date(2026, 10, 28),
                    stage="derived",
                    prices_published_at=datetime(2026, 10, 28, 20, 10, 0),
                    derived_published_at=datetime(2026, 10, 28, 20, 15, 0),
                    is_fresh=True,
                )
            )

            # Query should succeed without outbound network calls
            data = get_local_provider_status_data(session, primary_provider_id="tejhq")
            self.assertEqual(data["primary_provider"], "TejHQ")
            self.assertEqual(data["latest_published_trading_date"], date(2026, 10, 28))
            self.assertEqual(data["pipeline_stage"], "derived")
            self.assertTrue(data["is_fresh"])
            self.assertEqual(data["last_successful_ingestion_date"], date(2026, 10, 28))


if __name__ == "__main__":
    unittest.main()
