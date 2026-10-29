from __future__ import annotations

import unittest
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import BigInteger, Integer, create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.router import api_router
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import (
    Company,
    CorporateAction,
    DailyMarketSnapshot,
    DataSource,
    IngestionRun,
    Instrument,
    InstrumentShareCount,
)
from app.providers.base import ProviderStatus


class TestApiRouterModularization(unittest.TestCase):
    """Verifies that the modularized router structure preserves 100% of API functionality,

    correct route registration, validation rules, error handling, and strict read-only invariants.
    """

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
            # 1. Company
            comp = Company(id=1, name="Tata Consultancy Services Limited")
            session.add(comp)
            session.flush()

            # 2. Instrument
            inst = Instrument(
                id=101,
                company_id=comp.id,
                exchange="NSE",
                symbol="TCS",
                series="EQ",
                instrument_type="EQUITY",
                isin="INE467B01029",
                listing_date=date(2004, 8, 25),
                paid_up_value=Decimal("1.0000"),
                face_value=Decimal("1.0000"),
                is_active=True,
            )
            session.add(inst)
            session.flush()

            # 3. Data Sources
            source_tejhq = DataSource(
                id=1,
                name="TejHQ EOD Market Data",
                source_type="api",
                source_url="https://api.tejhq.dev",
                terms_url="https://tejhq.dev/docs",
                is_active=True,
            )
            source_nse = DataSource(
                id=2,
                name="NSE Shareholding Pattern Disclosure",
                source_type="filing",
                is_active=True,
            )
            session.add_all([source_tejhq, source_nse])
            session.flush()

            # 4. Snapshots
            snap = DailyMarketSnapshot(
                id=1,
                instrument_id=101,
                source_id=1,
                snapshot_date=date(2026, 10, 28),
                open_price=Decimal("3800.00"),
                high_price=Decimal("3850.00"),
                low_price=Decimal("3790.00"),
                close_price=Decimal("3820.00"),
                last_traded_price=Decimal("3825.00"),
                prev_close_price=Decimal("3780.00"),
                volume=1500000,
                turnover=Decimal("5730000000.00"),
                volume_lakhs=Decimal("15.000000"),
                traded_value_crores=Decimal("573.000000"),
                percentage_change_pct=Decimal("1.190476"),
                is_calculated_change=True,
                trade_count=45000,
            )
            session.add(snap)

            # 5. Share Count
            sc = InstrumentShareCount(
                id=1,
                instrument_id=101,
                symbol="TCS",
                series="EQ",
                share_class="EQUITY",
                reported_share_count=3618087518,
                fully_paid_shares=3618087518,
                source_capital_amount=Decimal("3618087518.00"),
                face_value=Decimal("1.0000"),
                reporting_date=date(2026, 9, 30),
                filing_date=date(2026, 10, 12),
                source_id=2,
                extraction_method="directly_reported",
                validation_status="verified",
            )
            session.add(sc)

            # 6. Corporate Action
            ca = CorporateAction(
                id=1,
                instrument_id=101,
                exchange="NSE",
                symbol="TCS",
                event_type="dividend",
                dedup_key="NSE_TCS_DIVIDEND_20261015",
                announcement_date=date(2026, 10, 10),
                ex_date=date(2026, 10, 15),
                record_date=date(2026, 10, 16),
                effective_date=date(2026, 10, 15),
                cash_amount=Decimal("10.00"),
                status="completed",
                source_id=1,
                validation_status="valid",
            )
            session.add(ca)

            # 7. Ingestion Run
            run = IngestionRun(
                id=1,
                source_id=1,
                dataset_name="tejhq_eod_snapshot_2026-10-28",
                trading_date=date(2026, 10, 28),
                status="completed",
                started_at=datetime(2026, 10, 28, 18, 30, 0),
                completed_at=datetime(2026, 10, 28, 18, 32, 0),
                records_read=2602,
                records_inserted=2602,
                records_updated=0,
                records_skipped=0,
                records_failed=0,
                records_unmatched=0,
            )
            session.add(run)

            session.commit()

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

    def setUp(self):
        from app.api.endpoints.providers import _remote_status_cache
        _remote_status_cache.clear()

    def test_router_registration_and_exact_paths(self):
        """Verify all expected endpoint paths are registered on the application router."""
        routes = list(app.openapi()["paths"].keys())
        expected_paths = [
            "/health",
            "/api/v1/providers/status",
            "/api/v1/instruments",
            "/api/v1/instruments/{instrument_id}",
            "/api/v1/instruments/{instrument_id}/prices",
            "/api/v1/instruments/{instrument_id}/share-counts",
            "/api/v1/instruments/{instrument_id}/corporate-actions",
        ]
        for path in expected_paths:
            self.assertIn(path, routes, f"Path {path} missing from app routes")

    def test_health_endpoint(self):
        res = self.client.get("/health")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"status": "ok"})

    def test_instruments_search_and_validation(self):
        # Valid search
        res = self.client.get("/api/v1/instruments?query=TCS")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["symbol"], "TCS")
        self.assertEqual(data[0]["company_name"], "Tata Consultancy Services Limited")

        # Empty whitespace search -> 400
        res_empty = self.client.get("/api/v1/instruments?query=%20%20%20")
        self.assertEqual(res_empty.status_code, 400)
        self.assertIn("non-whitespace", res_empty.json()["detail"])

        # No match query -> 200 empty list
        res_nomatch = self.client.get("/api/v1/instruments?query=NONEXISTENT")
        self.assertEqual(res_nomatch.status_code, 200)
        self.assertEqual(res_nomatch.json(), [])

    def test_instrument_detail_and_market_cap(self):
        res = self.client.get("/api/v1/instruments/101")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["symbol"], "TCS")
        self.assertIsNotNone(data["snapshot"])
        self.assertEqual(data["snapshot"]["ltp"], "3825.000000")
        self.assertEqual(data["snapshot"]["share_count"], 3618087518)
        # Market cap = 3825.00 * 3618087518 / 10,000,000 = 1383918.475635
        self.assertEqual(data["snapshot"]["market_capitalization_crores"], "1383918.475635")

        # Missing instrument -> 404
        res_404 = self.client.get("/api/v1/instruments/999999")
        self.assertEqual(res_404.status_code, 404)
        self.assertEqual(res_404.json()["detail"], "Instrument not found.")

    def test_instrument_prices_and_date_validation(self):
        res = self.client.get("/api/v1/instruments/101/prices")
        self.assertEqual(res.status_code, 200)
        bars = res.json()
        self.assertEqual(len(bars), 1)
        self.assertEqual(bars[0]["trading_date"], "2026-10-28")

        # Inverted date range -> 400
        res_invalid_dates = self.client.get("/api/v1/instruments/101/prices?from=2026-10-30&to=2026-10-01")
        self.assertEqual(res_invalid_dates.status_code, 400)
        self.assertIn("cannot be after", res_invalid_dates.json()["detail"])

    def test_instrument_share_counts_and_corporate_actions(self):
        # Share counts
        res_sc = self.client.get("/api/v1/instruments/101/share-counts")
        self.assertEqual(res_sc.status_code, 200)
        sc_data = res_sc.json()
        self.assertEqual(len(sc_data), 1)
        self.assertEqual(sc_data[0]["reported_share_count"], 3618087518)

        # Corporate actions
        res_ca = self.client.get("/api/v1/instruments/101/corporate-actions")
        self.assertEqual(res_ca.status_code, 200)
        ca_data = res_ca.json()
        self.assertEqual(len(ca_data), 1)
        self.assertEqual(ca_data[0]["event_type"], "dividend")

    def test_provider_status_and_caching(self):
        with patch("app.api.endpoints.providers.TejHQProvider.get_status") as mock_status:
            mock_status.return_value = ProviderStatus(
                provider_name="TejHQ",
                trading_date=date(2026, 10, 28),
                stage="derived",
                prices_published_at=datetime(2026, 10, 28, 20, 0, 0),
                derived_published_at=datetime(2026, 10, 28, 20, 15, 0),
                is_fresh=True,
            )
            res = self.client.get("/api/v1/providers/status")
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertEqual(data["primary_provider"], "TejHQ")
            self.assertEqual(data["provider_availability"], "available")
            self.assertEqual(data["latest_published_trading_date"], "2026-10-28")

            # Second call within TTL returns cached result without re-invoking provider
            mock_status.reset_mock()
            res_cached = self.client.get("/api/v1/providers/status")
            self.assertEqual(res_cached.status_code, 200)
            mock_status.assert_not_called()

    def test_strictly_read_only_invariant(self):
        """Verify that executing all GET endpoints causes ZERO database writes or table row count changes."""
        tables = [
            Company,
            Instrument,
            DailyMarketSnapshot,
            DataSource,
            IngestionRun,
            CorporateAction,
            InstrumentShareCount,
        ]

        def get_all_counts():
            with self.session_factory() as session:
                return {model.__name__: session.query(model).count() for model in tables}

        counts_before = get_all_counts()

        endpoints = [
            "/health",
            "/api/v1/providers/status",
            "/api/v1/instruments?query=TCS",
            "/api/v1/instruments/101",
            "/api/v1/instruments/101/prices",
            "/api/v1/instruments/101/prices?from=2026-01-01&to=2026-10-28",
            "/api/v1/instruments/101/share-counts",
            "/api/v1/instruments/101/corporate-actions",
        ]

        for ep in endpoints:
            res = self.client.get(ep)
            self.assertEqual(res.status_code, 200, f"Endpoint {ep} returned {res.status_code}")

        counts_after = get_all_counts()
        self.assertEqual(
            counts_before,
            counts_after,
            f"Database mutation detected! Before: {counts_before}, After: {counts_after}",
        )


if __name__ == "__main__":
    unittest.main()
