import csv
import importlib.util
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "import_market_snapshot.py"
SPEC = importlib.util.spec_from_file_location("import_market_snapshot", SCRIPT_PATH)
IMPORTER = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules["import_market_snapshot"] = IMPORTER
SPEC.loader.exec_module(IMPORTER)


class MarketSnapshotImporterTests(unittest.TestCase):
    def test_read_input_normalizes_bom_and_padded_headers(self):
        headers = [
            "SYMBOL ",
            "SERIES ",
            "LTP ",
            "%CHANGE ",
            "MARKET CAPITAL (₹ Crores)",
            "VOLUME (Lakhs)",
            "VALUE (₹ Crores)",
        ]
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="", suffix=".csv", delete=False
        ) as handle:
            writer = csv.writer(handle)
            writer.writerow(headers)
            writer.writerow(["ABC", "EQ", "10.5", "-2.25", "100", "1.5", "20"])
            csv_path = Path(handle.name)

        try:
            original_headers, rows = IMPORTER.read_input(csv_path)
        finally:
            csv_path.unlink()

        self.assertEqual(original_headers, headers)
        self.assertEqual(rows[0]["SYMBOL "], "ABC")
        self.assertEqual(
            IMPORTER.normalized_row(rows[0])[IMPORTER.HEADER_CHANGE], "-2.25"
        )

    def test_missing_headers_are_reported_exactly(self):
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="", suffix=".csv", delete=False
        ) as handle:
            handle.write("SYMBOL, SERIES\nABC, EQ\n")
            csv_path = Path(handle.name)

        try:
            with self.assertRaisesRegex(ValueError, "CSV is missing required column") as error:
                IMPORTER.read_input(csv_path)
        finally:
            csv_path.unlink()

        self.assertIn("LTP", str(error.exception))
        self.assertIn("VALUE (₹ CRORES)", str(error.exception))

    def test_numeric_parsing_preserves_missing_and_negative_values(self):
        row = {
            IMPORTER.HEADER_LTP: "",
            IMPORTER.HEADER_CHANGE: "-5.85",
            IMPORTER.HEADER_MARKET_CAP: "10415.75",
            IMPORTER.HEADER_VOLUME: "690.07",
            IMPORTER.HEADER_VALUE: "2413.19",
        }
        values = IMPORTER.parse_market_values(row)
        self.assertIsNone(values[0])
        self.assertEqual(values[1], Decimal("-5.85"))
        self.assertEqual(values[3], Decimal("690.07"))

        with self.assertRaises(ValueError):
            IMPORTER.parse_decimal("NaN", "LTP")
        with self.assertRaises(ValueError):
            IMPORTER.parse_decimal("not-a-number", "LTP")

    def test_snapshot_date_requires_explicit_iso_date(self):
        self.assertEqual(
            IMPORTER.parse_snapshot_date("2026-10-14"), date(2026, 10, 14)
        )
        with self.assertRaises(ValueError):
            IMPORTER.parse_snapshot_date("14-10-2026")

    def test_matching_exact_series_and_unambiguous_fallback(self):
        eq = SimpleNamespace(id=1, exchange="NSE", symbol="ABC", series="EQ")
        exact = {("NSE", "ABC", "EQ"): eq}
        by_symbol = {("NSE", "ABC"): [eq]}

        match, reason = IMPORTER.resolve_instrument("ABC", "EQ", exact, by_symbol)
        self.assertIs(match, eq)
        self.assertIsNone(reason)

        match, reason = IMPORTER.resolve_instrument("ABC", None, exact, by_symbol)
        self.assertIs(match, eq)
        self.assertIsNone(reason)

    def test_matching_rejects_ambiguous_and_unmatched_symbols(self):
        eq = SimpleNamespace(id=1, exchange="NSE", symbol="ABC", series="EQ")
        be = SimpleNamespace(id=2, exchange="NSE", symbol="ABC", series="BE")
        exact = {("NSE", "ABC", "EQ"): eq, ("NSE", "ABC", "BE"): be}
        by_symbol = {("NSE", "ABC"): [eq, be]}

        match, reason = IMPORTER.resolve_instrument("ABC", None, exact, by_symbol)
        self.assertIsNone(match)
        self.assertIn("2 candidates", reason or "")

        match, reason = IMPORTER.resolve_instrument("MISSING", "EQ", exact, by_symbol)
        self.assertIsNone(match)
        self.assertIn("No instrument matched", reason or "")

    def test_duplicate_input_rows_are_skipped_or_failed(self):
        values = (Decimal("10"), Decimal("1"), None, Decimal("2"), Decimal("3"))
        self.assertEqual(IMPORTER.classify_duplicate(None, values), None)
        self.assertEqual(IMPORTER.classify_duplicate(values, values), "skipped")
        self.assertEqual(
            IMPORTER.classify_duplicate(values, (*values[:1], Decimal("2"), *values[2:])),
            "failed",
        )

    def test_fatal_database_error_marks_run_failed(self):
        class FakeSession:
            def __init__(self, run):
                self.run = run
                self.exited = False
                self.committed = False

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                self.exited = True
                return False

            def get(self, model, run_id):
                return self.run

            def scalars(self, statement):
                raise RuntimeError("simulated database failure")

            def commit(self):
                self.committed = True

        run = SimpleNamespace(status="running", completed_at=None, error_summary=None)
        failing_session = FakeSession(run)
        error_session = FakeSession(run)

        with patch.object(
            IMPORTER,
            "SessionLocal",
            side_effect=[failing_session, error_session],
        ):
            with self.assertRaisesRegex(RuntimeError, "simulated database failure"):
                IMPORTER.import_rows(
                    [],
                    [],
                    source_id=1,
                    run_id=1,
                    snapshot_date=date(2026, 10, 14),
                )

        self.assertTrue(failing_session.exited)
        self.assertEqual(run.status, "failed")
        self.assertTrue(error_session.committed)


if __name__ == "__main__":
    unittest.main()
