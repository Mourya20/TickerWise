from __future__ import annotations

import json
import sys
from pathlib import Path

# Add backend directory to path
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

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
    Instrument,
)
from app.providers.base import NormalizedOHLCV, ProviderNetworkError
from app.services.historical_backfill_service import (
    CHECKPOINT_FILE,
    HistoricalBackfillService,
)


class TestHistoricalPriceAndChart(unittest.TestCase):
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

        with self.SessionFactory() as session:
            source = DataSource(
                name="TejHQ EOD Market Data",
                source_type="api",
                source_url="https://api.tejhq.dev",
                is_active=True,
            )
            company = Company(name="RELIANCE INDUSTRIES LTD")
            session.add_all([source, company])
            session.flush()

            self.source_id = source.id
            self.company_id = company.id

            self.inst_rel = Instrument(
                company_id=company.id,
                exchange="NSE",
                symbol="RELIANCE",
                series="EQ",
                isin="INE002A01018",
                is_active=True,
            )
            session.add(self.inst_rel)

            # Instrument with ambiguous multi-series (DVR and EQ)
            comp_tm = Company(name="TATA MOTORS LTD")
            session.add(comp_tm)
            session.flush()

            self.inst_tm_eq = Instrument(
                company_id=comp_tm.id,
                exchange="NSE",
                symbol="TATAMOTORS",
                series="EQ",
                isin="INE155A01022",
                is_active=True,
            )
            self.inst_tm_dvr = Instrument(
                company_id=comp_tm.id,
                exchange="NSE",
                symbol="TATAMOTORS",
                series="DVR",
                isin="IN9155A01020",
                is_active=True,
            )

            # Instrument with multiple non-EQ ambiguous series
            comp_ambig = Company(name="AMBIGUOUS TEST LTD")
            session.add(comp_ambig)
            session.flush()
            self.inst_amb1 = Instrument(
                company_id=comp_ambig.id,
                exchange="NSE",
                symbol="AMBIG",
                series="BE",
                isin="INEXXX0001",
                is_active=True,
            )
            self.inst_amb2 = Instrument(
                company_id=comp_ambig.id,
                exchange="NSE",
                symbol="AMBIG",
                series="BZ",
                isin="INEXXX0002",
                is_active=True,
            )

            session.add_all([
                self.inst_tm_eq,
                self.inst_tm_dvr,
                self.inst_amb1,
                self.inst_amb2,
            ])
            session.commit()
            self.rel_id = int(self.inst_rel.id)
            self.tm_eq_id = int(self.inst_tm_eq.id)
            self.tm_dvr_id = int(self.inst_tm_dvr.id)

    def tearDown(self):
        app.dependency_overrides.clear()
        Base.metadata.drop_all(self.engine)

    def test_api_pagination_more_than_1000_bars(self):
        """Seed 1,250 bars and verify API pagination with offset and limit."""
        with self.SessionFactory() as session:
            # Seed 1,250 daily bars starting from 2021-01-01
            start_ord = date(2021, 1, 1).toordinal()
            snapshots = []
            for i in range(1250):
                d = date.fromordinal(start_ord + i)
                snapshots.append(
                    DailyMarketSnapshot(
                        instrument_id=self.rel_id,
                        source_id=self.source_id,
                        snapshot_date=d,
                        open_price=Decimal("1000.00"),
                        high_price=Decimal("1020.00"),
                        low_price=Decimal("990.00"),
                        close_price=Decimal("1010.00"),
                        last_traded_price=Decimal("1010.00"),
                        prev_close_price=Decimal("1000.00"),
                        volume=50000,
                        volume_lakhs=Decimal("0.50"),
                        traded_value_crores=Decimal("5.05"),
                    )
                )
            session.add_all(snapshots)
            session.commit()

        # Page 0 (latest 1,000 bars, chronological)
        r0 = self.client.get(f"/api/v1/instruments/{self.rel_id}/prices?limit=1000&offset=0")
        self.assertEqual(r0.status_code, 200)
        p0 = r0.json()
        self.assertEqual(len(p0), 1000)

        # Page 1 (older 250 bars, chronological)
        r1 = self.client.get(f"/api/v1/instruments/{self.rel_id}/prices?limit=1000&offset=1000")
        self.assertEqual(r1.status_code, 200)
        p1 = r1.json()
        self.assertEqual(len(p1), 250)

        # Check unique dates and no overlap between pages
        dates0 = set(b["trading_date"] for b in p0)
        dates1 = set(b["trading_date"] for b in p1)
        self.assertEqual(len(dates0.intersection(dates1)), 0)
        self.assertEqual(len(dates0) + len(dates1), 1250)

        # Check chronological ascending order in both
        for p in (p0, p1):
            dates_list = [b["trading_date"] for b in p]
            self.assertEqual(dates_list, sorted(dates_list))

        # Check that page 1 dates are strictly older than page 0 dates
        self.assertLess(max(dates1), min(dates0))

    def test_complete_all_range_query(self):
        """Without from/to, returns chronological bars up to requested limit."""
        with self.SessionFactory() as session:
            for day in range(1, 11):
                session.add(
                    DailyMarketSnapshot(
                        instrument_id=self.rel_id,
                        source_id=self.source_id,
                        snapshot_date=date(2026, 10, day),
                        open_price=Decimal("2000"),
                        high_price=Decimal("2050"),
                        low_price=Decimal("1990"),
                        close_price=Decimal("2010"),
                        volume=10000,
                    )
                )
            session.commit()

        res = self.client.get(f"/api/v1/instruments/{self.rel_id}/prices")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(len(data), 10)
        self.assertEqual(data[0]["trading_date"], "2026-10-01")
        self.assertEqual(data[-1]["trading_date"], "2026-10-10")

    def test_backfill_checkpoint_mismatch_resets_completed(self):
        """A checkpoint for date range A must not skip work for date range B."""
        svc = HistoricalBackfillService(session_factory=self.SessionFactory)

        mock_checkpoint = {
            "exchange": "NSE",
            "provider": "TejHQ",
            "instrument_selection_policy": "primary_equity_series",
            "from_date": "2024-01-01",
            "to_date": "2024-06-01",
            "completed_symbols": ["RELIANCE"],
        }
        with patch.object(svc, "load_checkpoint", return_value=mock_checkpoint):
            # Request different range: 2025-01-01 to 2025-06-01
            mock_provider = MagicMock()
            mock_provider.provider_name = "TejHQ"
            mock_provider.get_historical_ohlcv.return_value = [
                NormalizedOHLCV(
                    symbol="RELIANCE",
                    exchange="NSE",
                    date=date(2025, 1, 15),
                    open=Decimal("1500"),
                    high=Decimal("1520"),
                    low=Decimal("1490"),
                    close=Decimal("1510"),
                    last_price=Decimal("1510"),
                    prev_close=Decimal("1500"),
                    volume=50000,
                    turnover=Decimal("75500000"),
                    trades=1000,
                )
            ]
            svc.provider = mock_provider

            with patch.object(svc, "save_checkpoint") as mock_save:
                audit = svc.backfill_instruments(
                    symbols=["RELIANCE"],
                    from_date=date(2025, 1, 1),
                    to_date=date(2025, 6, 1),
                    resume=True,
                    delay_seconds=0,
                )
                # Must NOT skip RELIANCE because the date range mismatched!
                self.assertEqual(audit.symbols_completed, 1)
                self.assertEqual(audit.bars_inserted, 1)
                mock_provider.get_historical_ohlcv.assert_called_once()
                mock_save.assert_called()

    def test_backfill_resume_after_interruption(self):
        """When checkpoint matches exactly, already completed symbols are skipped."""
        svc = HistoricalBackfillService(session_factory=self.SessionFactory)

        matching_cp = {
            "exchange": "NSE",
            "provider": "TejHQ",
            "instrument_selection_policy": "primary_equity_series",
            "from_date": "2025-01-01",
            "to_date": "2025-06-01",
            "completed_symbols": ["RELIANCE"],
            "empty_history_symbols": [],
        }
        with patch.object(svc, "load_checkpoint", return_value=matching_cp):
            mock_provider = MagicMock()
            mock_provider.provider_name = "TejHQ"
            svc.provider = mock_provider

            audit = svc.backfill_instruments(
                symbols=["RELIANCE", "TATAMOTORS"],
                from_date=date(2025, 1, 1),
                to_date=date(2025, 6, 1),
                resume=True,
                delay_seconds=0,
            )
            # RELIANCE was in checkpoint, so provider should NOT be called for RELIANCE
            calls = [c[0][0] for c in mock_provider.get_historical_ohlcv.call_args_list]
            self.assertNotIn("RELIANCE", calls)

    def test_backfill_empty_vs_failed_provider_results(self):
        """Distinguish 0-bar empty responses from network/fetch failures."""
        svc = HistoricalBackfillService(session_factory=self.SessionFactory)
        mock_provider = MagicMock()
        mock_provider.provider_name = "TejHQ"

        # RELIANCE returns 0 bars (empty history)
        # TATAMOTORS raises network error
        def side_effect(sym, f, t):
            if sym == "RELIANCE":
                return []
            raise ProviderNetworkError("Connection timed out")

        mock_provider.get_historical_ohlcv.side_effect = side_effect
        svc.provider = mock_provider

        with patch.object(svc, "save_checkpoint"):
            audit = svc.backfill_instruments(
                symbols=["RELIANCE", "TATAMOTORS"],
                from_date=date(2025, 1, 1),
                to_date=date(2025, 6, 1),
                resume=False,
                delay_seconds=0,
            )

        self.assertEqual(audit.symbols_empty, 1)
        self.assertEqual(audit.symbols_failed, 1)
        self.assertEqual(audit.bars_read, 0)
        self.assertTrue(any("0 historical bars returned" in f for f in audit.failures))
        self.assertTrue(any("Connection timed out" in f for f in audit.failures))

    def test_instrument_ambiguity_and_quarantine(self):
        """Multi-series symbol with EQ maps to EQ; multi-series without EQ is quarantined."""
        svc = HistoricalBackfillService(session_factory=self.SessionFactory)
        mock_provider = MagicMock()
        mock_provider.provider_name = "TejHQ"
        mock_provider.get_historical_ohlcv.return_value = [
            NormalizedOHLCV(
                symbol="TATAMOTORS",
                exchange="NSE",
                date=date(2025, 1, 10),
                open=Decimal("800"),
                high=Decimal("810"),
                low=Decimal("795"),
                close=Decimal("805"),
                last_price=Decimal("805"),
                prev_close=Decimal("800"),
                volume=10000,
                turnover=Decimal("8050000"),
                trades=500,
            )
        ]
        svc.provider = mock_provider

        with patch.object(svc, "save_checkpoint"):
            # TATAMOTORS has EQ and DVR -> resolves to EQ
            audit = svc.backfill_instruments(
                symbols=["TATAMOTORS", "AMBIG"],
                from_date=date(2025, 1, 1),
                to_date=date(2025, 1, 31),
                resume=False,
                delay_seconds=0,
            )

        # TATAMOTORS completed (mapped to EQ)
        self.assertEqual(audit.symbols_completed, 1)
        # AMBIG has only BE and BZ -> quarantined
        self.assertEqual(audit.symbols_quarantined, 1)
        self.assertTrue(any("quarantined" in f.lower() for f in audit.failures))

        # Check DB: TATAMOTORS EQ received the snapshot, DVR did NOT receive it
        with self.SessionFactory() as session:
            eq_snaps = session.scalars(
                select(DailyMarketSnapshot).where(DailyMarketSnapshot.instrument_id == self.tm_eq_id)
            ).all()
            dvr_snaps = session.scalars(
                select(DailyMarketSnapshot).where(DailyMarketSnapshot.instrument_id == self.tm_dvr_id)
            ).all()
            self.assertEqual(len(eq_snaps), 1)
            self.assertEqual(len(dvr_snaps), 0)

    def test_backfill_idempotency_insert_skip_update(self):
        """Re-running backfill skips identical bars and updates changed bars without duplicates."""
        svc = HistoricalBackfillService(session_factory=self.SessionFactory)
        mock_provider = MagicMock()
        mock_provider.provider_name = "TejHQ"

        bar1 = NormalizedOHLCV(
            symbol="RELIANCE",
            exchange="NSE",
            date=date(2025, 1, 10),
            open=Decimal("1200"),
            high=Decimal("1210"),
            low=Decimal("1190"),
            close=Decimal("1205"),
            last_price=Decimal("1205"),
            prev_close=Decimal("1200"),
            volume=1000,
            turnover=Decimal("1205000"),
            trades=100,
        )
        mock_provider.get_historical_ohlcv.return_value = [bar1]
        svc.provider = mock_provider

        with patch.object(svc, "save_checkpoint"):
            # Run 1: insert
            audit1 = svc.backfill_instruments(
                symbols=["RELIANCE"],
                from_date=date(2025, 1, 1),
                to_date=date(2025, 1, 31),
                resume=False,
                delay_seconds=0,
            )
            self.assertEqual(audit1.bars_inserted, 1)
            self.assertEqual(audit1.bars_updated, 0)
            self.assertEqual(audit1.bars_skipped, 0)

            # Run 2: same data -> skipped
            audit2 = svc.backfill_instruments(
                symbols=["RELIANCE"],
                from_date=date(2025, 1, 1),
                to_date=date(2025, 1, 31),
                resume=False,
                delay_seconds=0,
            )
            self.assertEqual(audit2.bars_inserted, 0)
            self.assertEqual(audit2.bars_skipped, 1)
            self.assertEqual(audit2.bars_updated, 0)

            # Run 3: updated close price -> updated
            bar1_changed = NormalizedOHLCV(
                symbol="RELIANCE",
                exchange="NSE",
                date=date(2025, 1, 10),
                open=Decimal("1200"),
                high=Decimal("1210"),
                low=Decimal("1190"),
                close=Decimal("1208"),  # changed
                last_price=Decimal("1208"),
                prev_close=Decimal("1200"),
                volume=1000,
                turnover=Decimal("1208000"),
                trades=100,
            )
            mock_provider.get_historical_ohlcv.return_value = [bar1_changed]
            audit3 = svc.backfill_instruments(
                symbols=["RELIANCE"],
                from_date=date(2025, 1, 1),
                to_date=date(2025, 1, 31),
                resume=False,
                delay_seconds=0,
            )
            self.assertEqual(audit3.bars_inserted, 0)
            self.assertEqual(audit3.bars_updated, 1)
            self.assertEqual(audit3.bars_skipped, 0)

        # Total snapshots for this instrument remains exactly 1 (no duplicate rows)
        with self.SessionFactory() as session:
            snaps = session.scalars(
                select(DailyMarketSnapshot).where(DailyMarketSnapshot.instrument_id == self.rel_id)
            ).all()
            self.assertEqual(len(snaps), 1)
            self.assertEqual(snaps[0].close_price, Decimal("1208.000000"))

    def test_missing_volume_and_ohlc_validation(self):
        """Preserves None for missing volume; rejects invalid negative prices."""
        valid_bar_missing_vol = NormalizedOHLCV(
            symbol="RELIANCE",
            exchange="NSE",
            date=date(2025, 1, 10),
            open=Decimal("100"),
            high=Decimal("105"),
            low=Decimal("95"),
            close=Decimal("102"),
            last_price=Decimal("102"),
            prev_close=Decimal("100"),
            volume=None,  # missing volume
            turnover=None,
            trades=None,
        )
        self.assertEqual(HistoricalBackfillService.validate_bar(valid_bar_missing_vol), [])

        negative_vol_bar = NormalizedOHLCV(
            symbol="RELIANCE",
            exchange="NSE",
            date=date(2025, 1, 10),
            open=Decimal("100"),
            high=Decimal("105"),
            low=Decimal("95"),
            close=Decimal("102"),
            last_price=Decimal("102"),
            prev_close=Decimal("100"),
            volume=-5,  # invalid negative
            turnover=None,
            trades=None,
        )
        errs = HistoricalBackfillService.validate_bar(negative_vol_bar)
        self.assertTrue(any("Negative volume" in e for e in errs))

    def test_prices_endpoint_is_strictly_read_only(self):
        """Phase I: GET /prices is strictly read-only and never triggers backfill or writes."""
        with patch.object(
            HistoricalBackfillService,
            "backfill_single_instrument",
            return_value=(1, 1, 0, 0, 0, []),
        ) as mock_bf:
            # Standard query: mock must never be called
            res_no_bf = self.client.get(f"/api/v1/instruments/{self.rel_id}/prices")
            self.assertEqual(res_no_bf.status_code, 200)
            mock_bf.assert_not_called()

            # Even if a client passes auto_backfill=true, the endpoint ignores it and does not write
            res_bf = self.client.get(f"/api/v1/instruments/{self.rel_id}/prices?auto_backfill=true")
            self.assertEqual(res_bf.status_code, 200)
            mock_bf.assert_not_called()

    def test_empty_price_history_returns_200_empty_list(self):
        """Instruments with no snapshots return an empty array with 200 OK (never 404 or 500)."""
        res = self.client.get(f"/api/v1/instruments/{self.tm_dvr_id}/prices")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), [])

    def test_api_date_filtering_from_and_to_bounds(self):
        """API properly respects from and to parameters, returning matching date bounds chronologically."""
        with self.SessionFactory() as session:
            for day in range(1, 21):
                session.add(
                    DailyMarketSnapshot(
                        instrument_id=self.rel_id,
                        source_id=self.source_id,
                        snapshot_date=date(2026, 10, day),
                        open_price=Decimal("2000"),
                        high_price=Decimal("2050"),
                        low_price=Decimal("1990"),
                        close_price=Decimal("2010"),
                        volume=10000,
                    )
                )
            session.commit()

        # Query bounded range: 2026-10-05 to 2026-10-15
        res = self.client.get(f"/api/v1/instruments/{self.rel_id}/prices?from=2026-10-05&to=2026-10-15")
        self.assertEqual(res.status_code, 200)
        bars = res.json()
        self.assertEqual(len(bars), 11)
        self.assertEqual(bars[0]["trading_date"], "2026-10-05")
        self.assertEqual(bars[-1]["trading_date"], "2026-10-15")

    def test_invalid_date_range_and_nonexistent_instrument(self):
        """Invalid date ranges produce 400 Bad Request; unknown instruments produce 404 Not Found."""
        # from > to -> 400
        res_bad = self.client.get(f"/api/v1/instruments/{self.rel_id}/prices?from=2026-10-20&to=2026-10-10")
        self.assertEqual(res_bad.status_code, 400)
        self.assertIn("Invalid date range", res_bad.json()["detail"])

        # non-existent instrument -> 404
        res_404 = self.client.get("/api/v1/instruments/999999/prices")
        self.assertEqual(res_404.status_code, 404)
        self.assertIn("Instrument not found", res_404.json()["detail"])


if __name__ == "__main__":
    unittest.main()
