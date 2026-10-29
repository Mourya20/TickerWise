from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal

from app.providers.base import ProviderNetworkError
from app.providers.tejhq import TejHQProvider


class TestLiveTejHQHttp(unittest.TestCase):
    """Live read-only test suite against public TejHQ API.

    Verifies actual live availability and response schema without
    modifying any database records.
    """

    def setUp(self):
        self.provider = TejHQProvider()

    def test_live_status_endpoint(self):
        try:
            status = self.provider.get_status()
        except ProviderNetworkError as exc:
            self.skipTest(f"Live TejHQ network endpoint unavailable: {exc}")
        self.assertEqual(status.provider_name, "TejHQ")
        self.assertIsNotNone(status.trading_date)
        self.assertIn(status.stage, ("prices", "derived"))
        self.assertTrue(status.is_fresh)
        print(f"\n[LIVE TEST] TejHQ Status: trading_date={status.trading_date}, stage={status.stage}")

    def test_live_ohlcv_endpoint(self):
        # Fetch OHLCV history for RELIANCE
        try:
            rows = self.provider.get_historical_ohlcv(
                "RELIANCE", date(2026, 10, 10), date(2026, 10, 14)
            )
        except ProviderNetworkError as exc:
            self.skipTest(f"Live TejHQ network endpoint unavailable: {exc}")
        self.assertGreater(len(rows), 0)
        sample = rows[0]
        self.assertEqual(sample.symbol, "RELIANCE")
        self.assertIsInstance(sample.date, date)
        self.assertIsInstance(sample.open, Decimal)
        self.assertIsInstance(sample.close, Decimal)
        self.assertIsInstance(sample.last_price, Decimal)
        self.assertIsInstance(sample.volume, int)
        print(f"\n[LIVE TEST] TejHQ OHLCV for RELIANCE ({sample.date}): Close={sample.close}, Volume={sample.volume}")


if __name__ == "__main__":
    unittest.main()
