"""Tests for background workers layer (app/workers/).

Verifies that workers execute correctly, handle options safely, and cleanly propagate results.
"""
from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.services.eod_update_service import EODUpdateResult
from app.services.historical_backfill_service import BackfillAudit
from app.workers.backfill_worker import run_backfill_worker
from app.workers.eod_worker import (
    check_provider_status,
    parse_date,
    run_catchup_worker,
    run_eod_worker,
)
from app.workers.corporate_action_worker import run_corporate_action_worker
from app.workers.shareholding_worker import (
    check_nse_permissions,
    run_shareholding_worker,
)


class TestWorkersLayer(unittest.TestCase):
    def test_eod_worker_parse_date(self):
        d = parse_date("2026-10-28")
        self.assertEqual(d, date(2026, 10, 28))

    def test_eod_worker_parse_date_invalid(self):
        with self.assertRaises(Exception):
            parse_date("invalid-date")

    @patch("app.workers.eod_worker.TejHQProvider")
    def test_check_provider_status(self, mock_provider_cls):
        mock_provider = mock_provider_cls.return_value
        mock_status = MagicMock()
        mock_status.provider_name = "TejHQ"
        mock_status.trading_date = date(2026, 10, 28)
        mock_status.stage = "derived"
        mock_status.prices_published_at = None
        mock_status.derived_published_at = None
        mock_status.is_fresh = True
        mock_status.run_url = "https://example.com"
        mock_provider.get_status.return_value = mock_status

        status = check_provider_status()
        self.assertEqual(status["provider_name"], "TejHQ")
        self.assertEqual(status["trading_date"], "2026-10-28")
        self.assertTrue(status["is_fresh"])

    @patch("app.workers.eod_worker.EODUpdateService")
    def test_run_eod_worker(self, mock_service_cls):
        mock_service = mock_service_cls.return_value
        dummy_result = EODUpdateResult(
            trading_date=date(2026, 10, 28),
            status="success",
            run_id=1,
            records_read=100,
            records_inserted=100,
            records_updated=0,
            records_skipped=0,
            records_failed=0,
            records_unmatched=0,
            instruments_discovered=0,
            review_path=None,
            message="OK",
        )
        mock_service.run_update.return_value = dummy_result

        res = run_eod_worker(target_date=date(2026, 10, 28), dry_run=True)
        self.assertEqual(res.status, "success")
        self.assertEqual(res.records_inserted, 100)
        mock_service.run_update.assert_called_once_with(
            target_date=date(2026, 10, 28),
            force=False,
            dry_run=True,
            min_coverage_threshold=1500,
        )

    @patch("app.workers.eod_worker.EODUpdateService")
    def test_run_catchup_worker(self, mock_service_cls):
        mock_service = mock_service_cls.return_value
        dummy_res = EODUpdateResult(
            trading_date=date(2026, 10, 28),
            status="success",
            run_id=2,
            records_read=50,
            records_inserted=50,
            records_updated=0,
            records_skipped=0,
            records_failed=0,
            records_unmatched=0,
            instruments_discovered=0,
            review_path=None,
            message="Catchup OK",
        )
        mock_service.run_catchup.return_value = [dummy_res]

        results = run_catchup_worker(dry_run=False)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, "success")

    @patch("app.workers.backfill_worker.HistoricalBackfillService")
    def test_run_backfill_worker(self, mock_service_cls):
        mock_service = mock_service_cls.return_value
        dummy_audit = BackfillAudit(
            symbols_requested=2,
            symbols_completed=2,
            symbols_failed=0,
            bars_read=100,
            bars_inserted=90,
            bars_updated=10,
            bars_skipped=0,
            bars_failed=0,
            failures=[],
        )
        mock_service.backfill_instruments.return_value = dummy_audit

        audit = run_backfill_worker(
            symbols=["RELIANCE", "TCS"],
            from_date=date(2025, 1, 1),
            to_date=date(2026, 1, 1),
            resume=True,
            dry_run=False,
        )
        self.assertEqual(audit.symbols_completed, 2)
        self.assertEqual(audit.bars_inserted, 90)

    def test_run_backfill_worker_empty_symbols(self):
        with self.assertRaises(ValueError):
            run_backfill_worker(symbols=[])

    def test_check_nse_permissions(self):
        rep = check_nse_permissions()
        self.assertIn("automated_scraping_permitted", rep)
        self.assertFalse(rep["automated_scraping_permitted"])

    def test_run_shareholding_worker_empty_files(self):
        with self.assertRaises(ValueError):
            run_shareholding_worker(files=[])

    @patch("app.workers.corporate_action_worker.TejHQProvider")
    @patch("app.workers.corporate_action_worker.CorporateActionService")
    @patch("app.workers.corporate_action_worker.SessionLocal")
    def test_run_corporate_action_worker(self, mock_session_factory, mock_service_cls, mock_provider_cls):
        mock_session = mock_session_factory.return_value
        mock_inst = MagicMock()
        mock_inst.symbol = "RELIANCE"
        mock_session.scalars.return_value.all.return_value = [mock_inst]

        mock_provider = mock_provider_cls.return_value
        mock_action = MagicMock()
        mock_provider.get_actions.return_value = [mock_action]

        mock_service = mock_service_cls.return_value
        mock_audit = MagicMock()
        mock_audit.actions_inserted = 1
        mock_audit.actions_updated = 0
        mock_service.ingest_actions.return_value = mock_audit

        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_checkpoint = Path(tmpdir) / "checkpoint.json"
            result = run_corporate_action_worker(
                symbols=["RELIANCE"],
                delay=0.0,
                resume=False,
                dry_run=False,
                checkpoint_path=tmp_checkpoint,
            )
            self.assertEqual(result["target_count"], 1)
            self.assertEqual(result["total_synced"], 1)
            self.assertEqual(result["total_actions_inserted"], 1)


if __name__ == "__main__":
    unittest.main()
