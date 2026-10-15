from __future__ import annotations

import unittest
from datetime import date, datetime, timezone

from decimal import Decimal
from unittest.mock import MagicMock

from sqlalchemy import BigInteger, Integer, create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models import (
    Company,
    DailyMarketSnapshot,
    DataSource,
    IngestionRun,
    Instrument,
)
from app.providers.base import (
    NormalizedMarketSnapshot,
    NormalizedQuote,
    ProviderStatus,
)
from app.services.eod_update_service import EODUpdateService, ReconciledQuote


class TestEODUpdateService(unittest.TestCase):
    def setUp(self):
        # Use in-memory SQLite with StaticPool for fast, isolated tests
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


        with self.SessionFactory() as session:
            # Seed company and instruments
            company = Company(name="RELIANCE INDUSTRIES LTD")
            session.add(company)
            session.flush()

            inst_eq = Instrument(
                company_id=company.id,
                exchange="NSE",
                symbol="RELIANCE",
                series="EQ",
                isin="INE002A01018",
                is_active=True,
            )
            session.add(inst_eq)

            # Another company with multiple series to test ambiguous matching
            comp2 = Company(name="TATA MOTORS LTD")
            session.add(comp2)
            session.flush()

            inst_tm_eq = Instrument(
                company_id=comp2.id,
                exchange="NSE",
                symbol="TATAMOTORS",
                series="EQ",
                isin="INE155A01022",
                is_active=True,
            )
            inst_tm_dvr = Instrument(
                company_id=comp2.id,
                exchange="NSE",
                symbol="TATAMOTORS",
                series="DVR",
                isin="IN9155A01020",
                is_active=True,
            )
            session.add_all([inst_tm_eq, inst_tm_dvr])

            # Seed a single-series instrument with distinct ISIN
            comp3 = Company(name="INFOSYS LTD")
            session.add(comp3)
            session.flush()

            inst_infy = Instrument(
                company_id=comp3.id,
                exchange="NSE",
                symbol="INFY",
                series="EQ",
                isin="INE009A01021",
                is_active=True,
            )
            session.add(inst_infy)

            # Seed an earlier snapshot to verify historical preservation
            source = DataSource(
                name="NSE Historical CSV",
                source_type="manual_csv",
                is_active=True,
            )
            session.add(source)
            session.flush()

            earlier_snapshot = DailyMarketSnapshot(
                instrument_id=inst_eq.id,
                source_id=source.id,
                snapshot_date=date(2026, 10, 10),
                last_traded_price=Decimal("1150.000000"),
                percentage_change_pct=Decimal("0.500000"),
                volume_lakhs=Decimal("10.000000"),
                traded_value_crores=Decimal("11.500000"),
            )
            session.add(earlier_snapshot)
            session.commit()

    def tearDown(self):
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_instrument_matching_strategies(self):
        with self.SessionFactory() as session:
            instruments = session.scalars(select(Instrument)).all()
            exact = {}
            isin_map = {}
            sym_map = {}
            for i in instruments:
                exact[(i.exchange, i.symbol, i.series)] = i
                sym_map.setdefault((i.exchange, i.symbol), []).append(i)
                if i.isin:
                    isin_map.setdefault(i.isin, []).append(i)

            # 1. Exact match
            inst, err = EODUpdateService.resolve_instrument(
                "RELIANCE", "EQ", "INE002A01018", exact, isin_map, sym_map
            )
            self.assertIsNotNone(inst)
            self.assertEqual(inst.symbol, "RELIANCE")
            self.assertEqual(inst.series, "EQ")
            self.assertIsNone(err)

            # 2. ISIN match when series is missing or different
            inst, err = EODUpdateService.resolve_instrument(
                "RELIANCE", None, "INE002A01018", exact, isin_map, sym_map
            )
            self.assertIsNotNone(inst)
            self.assertEqual(inst.symbol, "RELIANCE")

            # 3. Single candidate match when series is missing
            inst, err = EODUpdateService.resolve_instrument(
                "INFY", None, None, exact, isin_map, sym_map
            )
            self.assertIsNotNone(inst)
            self.assertEqual(inst.symbol, "INFY")

            # 4. Ambiguous match when multiple candidates exist and series/ISIN missing
            inst, err = EODUpdateService.resolve_instrument(
                "TATAMOTORS", None, None, exact, isin_map, sym_map
            )
            self.assertIsNone(inst)
            self.assertIn("Ambiguous", err)

            # 5. Unmatched
            inst, err = EODUpdateService.resolve_instrument(
                "NONEXISTENT", "EQ", None, exact, isin_map, sym_map
            )
            self.assertIsNone(inst)
            self.assertIn("No instrument found", err)

    def test_run_update_insertion_and_historical_preservation(self):
        mock_tejhq = MagicMock()
        mock_tejhq.get_status.return_value = ProviderStatus(
            provider_name="TejHQ",
            trading_date=date(2026, 10, 15),
            stage="derived",
            prices_published_at=datetime(2026, 10, 15, 20, 0, 0),
            derived_published_at=datetime(2026, 10, 15, 20, 10, 0),
            is_fresh=True,
        )

        sample_row = NormalizedMarketSnapshot(
            symbol="RELIANCE",
            series="EQ",
            isin="INE002A01018",
            name="RELIANCE INDUSTRIES LTD",
            exchange="NSE",
            snapshot_date=date(2026, 10, 15),
            open=Decimal("1160.0"),
            high=Decimal("1180.0"),
            low=Decimal("1155.0"),
            close=Decimal("1175.0"),
            last_price=Decimal("1174.5"),
            prev_close=Decimal("1150.0"),
            volume=5000000,
            turnover=Decimal("5875000000.0"),
            trades=100000,
            percentage_change_pct=Decimal("2.173913"),
            is_calculated_change=True,
            provider_name="TejHQ",
            retrieved_at=datetime.now(timezone.utc).replace(tzinfo=None),

        )
        mock_tejhq.get_daily_snapshot.return_value = [sample_row]

        service = EODUpdateService(tejhq_provider=mock_tejhq, session_factory=self.SessionFactory)
        result = service.run_update(target_date=date(2026, 10, 15))

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.records_read, 1)
        self.assertEqual(result.records_inserted, 1)
        self.assertEqual(result.records_updated, 0)
        self.assertEqual(result.records_skipped, 0)
        self.assertEqual(result.records_failed, 0)
        self.assertEqual(result.records_unmatched, 0)

        with self.SessionFactory() as session:
            # Check new snapshot row
            snaps = session.scalars(
                select(DailyMarketSnapshot).order_by(DailyMarketSnapshot.snapshot_date.asc())
            ).all()
            self.assertEqual(len(snaps), 2)  # 1 earlier + 1 newly inserted

            # Historical preservation check: earlier snapshot untouched!
            earlier = snaps[0]
            self.assertEqual(earlier.snapshot_date, date(2026, 10, 10))
            self.assertEqual(earlier.last_traded_price, Decimal("1150.000000"))

            # New snapshot verification
            new_snap = snaps[1]
            self.assertEqual(new_snap.snapshot_date, date(2026, 10, 15))
            self.assertEqual(new_snap.close_price, Decimal("1175.000000"))
            self.assertEqual(new_snap.last_traded_price, Decimal("1174.500000"))
            self.assertEqual(new_snap.volume, 5000000)
            self.assertEqual(new_snap.volume_lakhs, Decimal("50.000000"))  # 5,000,000 / 100,000
            self.assertEqual(new_snap.traded_value_crores, Decimal("587.500000"))  # 5,875,000,000 / 10,000,000

            # Ingestion run audit check
            run = session.get(IngestionRun, result.run_id)
            self.assertIsNotNone(run)
            self.assertEqual(run.status, "completed")
            self.assertEqual(run.trading_date, date(2026, 10, 15))
            self.assertEqual(run.records_inserted, 1)

    def test_run_update_idempotent_skip_and_update(self):
        mock_tejhq = MagicMock()
        mock_tejhq.get_status.return_value = ProviderStatus(
            provider_name="TejHQ",
            trading_date=date(2026, 10, 15),
            stage="derived",
            prices_published_at=None,
            derived_published_at=None,
            is_fresh=True,
        )

        sample_row = NormalizedMarketSnapshot(
            symbol="INFY",
            series="EQ",
            isin="INE009A01021",
            name="INFOSYS LTD",
            exchange="NSE",
            snapshot_date=date(2026, 10, 15),
            open=Decimal("1500.0"),
            high=Decimal("1520.0"),
            low=Decimal("1490.0"),
            close=Decimal("1510.0"),
            last_price=Decimal("1510.0"),
            prev_close=Decimal("1500.0"),
            volume=1000000,
            turnover=Decimal("1510000000.0"),
            trades=40000,
            percentage_change_pct=Decimal("0.666667"),
            is_calculated_change=True,
            provider_name="TejHQ",
            retrieved_at=datetime.now(timezone.utc).replace(tzinfo=None),

        )
        mock_tejhq.get_daily_snapshot.return_value = [sample_row]

        service = EODUpdateService(tejhq_provider=mock_tejhq, session_factory=self.SessionFactory)

        # 1. First run: inserted
        res1 = service.run_update(target_date=date(2026, 10, 15))
        self.assertEqual(res1.records_inserted, 1)

        # 2. Second run without force: should detect already ingested and skip
        res2 = service.run_update(target_date=date(2026, 10, 15), force=False)
        self.assertEqual(res2.status, "skipped")

        # 3. Third run with force and unchanged data: skipped count = 1
        res3 = service.run_update(target_date=date(2026, 10, 15), force=True)
        self.assertEqual(res3.records_skipped, 1)
        self.assertEqual(res3.records_updated, 0)
        self.assertEqual(res3.records_inserted, 0)

        # 4. Fourth run with modified close price: updated count = 1
        modified_row = NormalizedMarketSnapshot(
            symbol="INFY",
            series="EQ",
            isin="INE009A01021",
            name="INFOSYS LTD",
            exchange="NSE",
            snapshot_date=date(2026, 10, 15),
            open=Decimal("1500.0"),
            high=Decimal("1520.0"),
            low=Decimal("1490.0"),
            close=Decimal("1515.0"),  # changed from 1510 to 1515
            last_price=Decimal("1515.0"),
            prev_close=Decimal("1500.0"),
            volume=1000000,
            turnover=Decimal("1515000000.0"),
            trades=40000,
            percentage_change_pct=Decimal("1.000000"),
            is_calculated_change=True,
            provider_name="TejHQ",
            retrieved_at=datetime.now(timezone.utc).replace(tzinfo=None),

        )
        mock_tejhq.get_daily_snapshot.return_value = [modified_row]
        res4 = service.run_update(target_date=date(2026, 10, 15), force=True)
        self.assertEqual(res4.records_updated, 1)

        # Verify no duplicate rows were created
        with self.SessionFactory() as session:
            snaps = session.scalars(
                select(DailyMarketSnapshot).where(
                    DailyMarketSnapshot.snapshot_date == date(2026, 10, 15)
                )
            ).all()
            self.assertEqual(len(snaps), 1)
            self.assertEqual(snaps[0].close_price, Decimal("1515.000000"))

    def test_unmatched_and_failed_audit_counts(self):
        mock_tejhq = MagicMock()
        mock_tejhq.get_status.return_value = ProviderStatus(
            provider_name="TejHQ",
            trading_date=date(2026, 10, 15),
            stage="prices",
            prices_published_at=None,
            derived_published_at=None,
            is_fresh=True,
        )

        unmatched_row = NormalizedMarketSnapshot(
            symbol="UNKNOWN_CORP",
            series="EQ",
            isin="INE999999999",
            name="Unknown",
            exchange="NSE",
            snapshot_date=date(2026, 10, 15),
            open=Decimal("100.0"),
            high=Decimal("105.0"),
            low=Decimal("95.0"),
            close=Decimal("102.0"),
            last_price=Decimal("102.0"),
            prev_close=Decimal("100.0"),
            volume=1000,
            turnover=Decimal("102000.0"),
            trades=10,
            percentage_change_pct=Decimal("2.0"),
            is_calculated_change=True,
            provider_name="TejHQ",
            retrieved_at=datetime.now(timezone.utc).replace(tzinfo=None),

        )

        failed_row = NormalizedMarketSnapshot(
            symbol="RELIANCE",
            series="EQ",
            isin="INE002A01018",
            name="RELIANCE INDUSTRIES LTD",
            exchange="NSE",
            snapshot_date=date(2026, 10, 15),
            open=Decimal("1160.0"),
            high=Decimal("1180.0"),
            low=Decimal("1155.0"),
            close=None,  # Both close and LTP null -> invalid!
            last_price=None,
            prev_close=Decimal("1150.0"),
            volume=5000000,
            turnover=Decimal("5875000000.0"),
            trades=100000,
            percentage_change_pct=None,
            is_calculated_change=False,
            provider_name="TejHQ",
            retrieved_at=datetime.now(timezone.utc).replace(tzinfo=None),

        )

        mock_tejhq.get_daily_snapshot.return_value = [unmatched_row, failed_row]

        service = EODUpdateService(tejhq_provider=mock_tejhq, session_factory=self.SessionFactory)
        res = service.run_update(target_date=date(2026, 10, 15), force=True)

        self.assertEqual(res.status, "partial")
        self.assertEqual(res.records_unmatched, 1)
        self.assertEqual(res.records_failed, 1)
        self.assertEqual(res.records_inserted, 0)
        self.assertIsNotNone(res.review_path)

        with self.SessionFactory() as session:
            run = session.get(IngestionRun, res.run_id)
            self.assertEqual(run.status, "partial")
            self.assertEqual(run.records_unmatched, 1)
            self.assertEqual(run.records_failed, 1)
            self.assertIn("Review:", run.error_summary)

    def test_mandatory_coverage_check_failure(self):
        """Phase H #21: No successful status when mandatory coverage checks fail."""
        mock_tejhq = MagicMock()
        mock_tejhq.get_status.return_value = ProviderStatus(
            provider_name="TejHQ",
            trading_date=date(2026, 10, 15),
            stage="derived",
            prices_published_at=datetime.now(timezone.utc),
            derived_published_at=datetime.now(timezone.utc),
            is_fresh=True,
        )

        # Provider returns only 1 matched row, but mandatory threshold is 1500
        snap = NormalizedMarketSnapshot(
            symbol="RELIANCE",
            series="EQ",
            isin="INE002A01018",
            name="RELIANCE INDUSTRIES LTD",
            exchange="NSE",
            snapshot_date=date(2026, 10, 15),
            open=Decimal("1160.0"),
            high=Decimal("1180.0"),
            low=Decimal("1155.0"),
            close=Decimal("1175.0"),
            last_price=Decimal("1174.5"),
            prev_close=Decimal("1150.0"),
            volume=5000000,
            turnover=Decimal("5875000000.0"),
            trades=100000,
            percentage_change_pct=Decimal("2.17"),
            is_calculated_change=False,
            provider_name="TejHQ",
            retrieved_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        mock_tejhq.get_daily_snapshot.return_value = [snap]

        service = EODUpdateService(tejhq_provider=mock_tejhq, session_factory=self.SessionFactory)
        res = service.run_update(target_date=date(2026, 10, 15), min_coverage_threshold=1500)

        # Must fail with 'failed' status despite HTTP 200 and successful row processing
        self.assertEqual(res.status, "failed")
        self.assertIn("Mandatory coverage check failed", res.message)

        with self.SessionFactory() as session:
            run = session.get(IngestionRun, res.run_id)
            self.assertIsNotNone(run)
            self.assertEqual(run.status, "failed")
            self.assertIn("Mandatory coverage check failed", run.error_summary)

    def test_reconcile_quote_canonical_priority(self):
        """Phase E: Canonical daily market prices take precedence, never averaged or overwritten."""
        pri_snap = NormalizedMarketSnapshot(
            symbol="RELIANCE",
            series="EQ",
            isin="INE002A01018",
            name="RELIANCE INDUSTRIES LTD",
            exchange="NSE",
            snapshot_date=date(2026, 10, 15),
            open=Decimal("1160.0"),
            high=Decimal("1180.0"),
            low=Decimal("1155.0"),
            close=Decimal("1175.0"),
            last_price=Decimal("1174.5"),
            prev_close=Decimal("1150.0"),
            volume=5000000,
            turnover=Decimal("5875000000.0"),
            trades=100000,
            percentage_change_pct=Decimal("2.17"),
            is_calculated_change=False,
            provider_name="TejHQ",
            retrieved_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )

        sup_quote = NormalizedQuote(
            symbol="RELIANCE",
            exchange="NSE",
            price=Decimal("1176.0"),  # Slightly different real-time quote
            percentage_change_pct=Decimal("2.26"),
            volume=5100000,
            market_cap=Decimal("1950000.50"),
            pe_ratio=Decimal("24.8"),
            dividend_yield=Decimal("0.35"),
            sector="Refineries",
            as_of_date=date(2026, 10, 15),
            provider_name="0xramm",
            retrieved_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )

        reconciled = EODUpdateService.reconcile_quote(pri_snap, sup_quote)

        # Canonical prices MUST match primary (TejHQ), NOT supplementary or averaged
        self.assertEqual(reconciled.close, Decimal("1175.0"))
        self.assertEqual(reconciled.last_price, Decimal("1174.5"))
        self.assertEqual(reconciled.volume, 5000000)

        # Supplementary metrics are correctly populated
        self.assertEqual(reconciled.market_cap, Decimal("1950000.50"))
        self.assertEqual(reconciled.pe_ratio, Decimal("24.8"))
        self.assertEqual(reconciled.sector, "Refineries")

        # Provenance accurately tracked
        self.assertEqual(reconciled.provenance["close"], "TejHQ")
        self.assertEqual(reconciled.provenance["last_price"], "TejHQ")
        self.assertEqual(reconciled.provenance["market_cap"], "0xramm")
        self.assertEqual(reconciled.provenance["pe_ratio"], "0xramm")

    def test_reconcile_quote_differing_dates_rejected(self):
        """Phase E: Do not mix metrics from differing dates while presenting as synchronized."""
        pri_snap = NormalizedMarketSnapshot(
            symbol="RELIANCE",
            series="EQ",
            isin="INE002A01018",
            name="RELIANCE",
            exchange="NSE",
            snapshot_date=date(2026, 10, 15),
            open=Decimal("1160.0"),
            high=Decimal("1180.0"),
            low=Decimal("1155.0"),
            close=Decimal("1175.0"),
            last_price=Decimal("1174.5"),
            prev_close=Decimal("1150.0"),
            volume=5000000,
            turnover=Decimal("5875000000.0"),
            trades=100000,
            percentage_change_pct=Decimal("2.17"),
            is_calculated_change=False,
            provider_name="TejHQ",
            retrieved_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )

        # Supplementary quote has yesterday's as_of_date
        sup_quote = NormalizedQuote(
            symbol="RELIANCE",
            exchange="NSE",
            price=Decimal("1150.0"),
            percentage_change_pct=Decimal("1.0"),
            volume=4000000,
            market_cap=Decimal("1900000.0"),
            pe_ratio=Decimal("24.1"),
            dividend_yield=Decimal("0.35"),
            sector="Refineries",
            as_of_date=date(2026, 10, 14),  # As-of date differs!
            provider_name="0xramm",
            retrieved_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )

        reconciled = EODUpdateService.reconcile_quote(pri_snap, sup_quote)

        # Fundamental metrics must be rejected
        self.assertIsNone(reconciled.market_cap)
        self.assertIsNone(reconciled.pe_ratio)
        self.assertTrue(any("Date mismatch" in d for d in reconciled.discrepancies))

    def test_reconcile_quote_material_divergence_logged(self):
        """Phase E: Detect and record material price divergence (>5%) without corrupting canonical price."""
        pri_snap = NormalizedMarketSnapshot(
            symbol="RELIANCE",
            series="EQ",
            isin="INE002A01018",
            name="RELIANCE",
            exchange="NSE",
            snapshot_date=date(2026, 10, 15),
            open=Decimal("1160.0"),
            high=Decimal("1180.0"),
            low=Decimal("1155.0"),
            close=Decimal("1000.0"),
            last_price=Decimal("1000.0"),
            prev_close=Decimal("1000.0"),
            volume=5000000,
            turnover=Decimal("5000000000.0"),
            trades=100000,
            percentage_change_pct=Decimal("0.0"),
            is_calculated_change=False,
            provider_name="TejHQ",
            retrieved_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )

        # Supplementary price is 1100 (10% higher -> exceeds 5% threshold)
        sup_quote = NormalizedQuote(
            symbol="RELIANCE",
            exchange="NSE",
            price=Decimal("1100.0"),
            percentage_change_pct=Decimal("10.0"),
            volume=5000000,
            market_cap=None,
            pe_ratio=None,
            dividend_yield=None,
            sector=None,
            as_of_date=date(2026, 10, 15),
            provider_name="0xramm",
            retrieved_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )

        reconciled = EODUpdateService.reconcile_quote(pri_snap, sup_quote)

        # Canonical price is preserved, NOT changed to 1100 or 1050
        self.assertEqual(reconciled.close, Decimal("1000.0"))
        self.assertTrue(any("Material price divergence" in d for d in reconciled.discrepancies))

    def test_classify_review_categories(self):
        """Distinguish fund/ETF ISINs, ambiguous instruments, and missing equities."""
        # 1. Non-equity fund/ETF
        cat_fund = EODUpdateService.classify_review_category("INF209K01157", "Some reason")
        self.assertEqual(cat_fund, "unmatched_non_equity_fund")

        # 2. Ambiguous symbol
        cat_amb = EODUpdateService.classify_review_category(
            "INE123A01010", "Ambiguous instrument: symbol TATAMOTORS has 2 candidates"
        )
        self.assertEqual(cat_amb, "ambiguous")

        # 3. Missing equity
        cat_eq = EODUpdateService.classify_review_category("INE999999999", "No matching instrument")
        self.assertEqual(cat_eq, "unmatched_equity")


if __name__ == "__main__":
    unittest.main()

