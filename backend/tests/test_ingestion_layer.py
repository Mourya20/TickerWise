"""Targeted unit tests for app.ingestion workflows and importers."""
from __future__ import annotations

import csv
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from app.ingestion import (
    EquityMasterImportResult,
    MarketSnapshotImportResult,
    NSEPermissionStatus,
    NSEShareholdingIngestionService,
    NSEShareholdingParser,
    import_equity_master,
    import_market_snapshot,
)
from app.ingestion.equity_master_importer import (
    normalized_name,
    parse_date,
    parse_decimal as parse_em_decimal,
    parse_integer,
    read_input as read_em_input,
)
from app.ingestion.market_snapshot_importer import (
    HEADER_CHANGE,
    HEADER_LTP,
    HEADER_MARKET_CAP,
    HEADER_VOLUME,
    classify_duplicate,
    normalized_header,
    normalized_row,
    parse_decimal as parse_ms_decimal,
    parse_market_values,
    parse_snapshot_date,
    read_input as read_ms_input,
    resolve_instrument,
)


class TestIngestionLayer(unittest.TestCase):
    """Test ingestion layer workflows, parsing logic, and deduplication rules."""

    def test_equity_master_parsing_helpers(self):
        """Parse equity master fields: date, decimal, whole-number integer."""
        # Date parsing
        self.assertEqual(parse_date("06-OCT-2008", "DATE OF LISTING"), date(2008, 10, 6))
        self.assertIsNone(parse_date("", "DATE OF LISTING"))
        with self.assertRaises(ValueError):
            parse_date("invalid-date", "DATE OF LISTING")

        # Decimal parsing
        self.assertEqual(parse_em_decimal("10.50", "PAID UP VALUE"), Decimal("10.50"))
        self.assertEqual(parse_em_decimal("1,000.50", "PAID UP VALUE"), Decimal("1000.50"))
        self.assertIsNone(parse_em_decimal("", "PAID UP VALUE"))
        with self.assertRaises(ValueError):
            parse_em_decimal("NaN", "PAID UP VALUE")

        # Integer parsing (market lot)
        self.assertEqual(parse_integer("50", "MARKET LOT"), 50)
        self.assertIsNone(parse_integer("", "MARKET LOT"))
        with self.assertRaises(ValueError):
            parse_integer("50.5", "MARKET LOT")

    def test_equity_master_name_normalization(self):
        """Company names are normalized by lowercase and single-spacing."""
        self.assertEqual(normalized_name("  Reliance   Industries   Limited  "), "reliance industries limited")
        self.assertEqual(normalized_name("TCS  LIMITED"), "tcs limited")

    def test_equity_master_read_input_validation(self):
        """Missing required headers raises ValueError."""
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="", suffix=".csv", delete=False) as f:
            f.write("SYMBOL,NAME OF COMPANY\nTCS,Tata Consultancy Services\n")
            temp_path = Path(f.name)

        try:
            with self.assertRaises(ValueError) as ctx:
                read_em_input(temp_path)
            self.assertIn("CSV is missing required column", str(ctx.exception))
        finally:
            temp_path.unlink()

    def test_market_snapshot_parsing_helpers(self):
        """Parse market snapshot row values preserving None and negative values."""
        row = {
            HEADER_LTP: "",
            HEADER_CHANGE: "-3.50",
            HEADER_MARKET_CAP: "50000.00",
            HEADER_VOLUME: "100.25",
            "VALUE (₹ CRORES)": "250.75",
        }
        values = parse_market_values(row)
        self.assertIsNone(values[0])  # LTP is None
        self.assertEqual(values[1], Decimal("-3.50"))
        self.assertEqual(values[2], Decimal("50000.00"))
        self.assertEqual(values[3], Decimal("100.25"))
        self.assertEqual(values[4], Decimal("250.75"))

    def test_market_snapshot_duplicate_classification(self):
        """Classify duplicate rows within snapshot input batch."""
        values = (Decimal("100.0"), Decimal("1.5"), Decimal("5000"), Decimal("10"), Decimal("20"))
        self.assertIsNone(classify_duplicate(None, values))
        self.assertEqual(classify_duplicate(values, values), "skipped")

        conflicting_values = (Decimal("105.0"), Decimal("1.5"), Decimal("5000"), Decimal("10"), Decimal("20"))
        self.assertEqual(classify_duplicate(values, conflicting_values), "failed")

    def test_market_snapshot_instrument_resolution(self):
        """Resolve instrument by exact (exchange, symbol, series) and unambiguous fallback."""
        eq = SimpleNamespace(id=1, exchange="NSE", symbol="INFY", series="EQ")
        be = SimpleNamespace(id=2, exchange="NSE", symbol="INFY", series="BE")
        exact = {("NSE", "INFY", "EQ"): eq, ("NSE", "INFY", "BE"): be}
        by_symbol = {("NSE", "INFY"): [eq, be]}

        # Exact match
        inst, err = resolve_instrument("INFY", "EQ", exact, by_symbol)
        self.assertIs(inst, eq)
        self.assertIsNone(err)

        # Ambiguous series without explicit series
        inst, err = resolve_instrument("INFY", None, exact, by_symbol)
        self.assertIsNone(inst)
        self.assertIn("2 candidates", err or "")

        # Unmatched symbol
        inst, err = resolve_instrument("UNKNOWN", "EQ", exact, by_symbol)
        self.assertIsNone(inst)
        self.assertIn("No instrument matched", err or "")

    def test_shareholding_importer_exports(self):
        """Verify that shareholding ingestion services are properly exposed in app.ingestion."""
        self.assertTrue(hasattr(NSEShareholdingParser, "parse_csv"))
        self.assertTrue(hasattr(NSEShareholdingParser, "parse_xbrl"))
        self.assertTrue(hasattr(NSEShareholdingParser, "parse_json"))
        self.assertTrue(hasattr(NSEShareholdingIngestionService, "ingest_records"))
        report = NSEPermissionStatus.get_status_report()
        self.assertIn("automated_scraping_permitted", report)
        self.assertFalse(report["automated_scraping_permitted"])


if __name__ == "__main__":
    unittest.main()
