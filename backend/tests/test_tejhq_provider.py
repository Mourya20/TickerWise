from __future__ import annotations

import unittest
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch

import httpx

from app.providers.base import (
    NormalizedMarketSnapshot,
    ProviderDataValidationError,
    ProviderNetworkError,
    ProviderResponseError,
)
from app.providers.tejhq import TejHQProvider


class TestTejHQProvider(unittest.TestCase):
    def test_status_parsing_success(self):
        def handler(request: httpx.Request):
            return httpx.Response(
                200,
                json={
                    "trading_date": "2026-10-14",
                    "stage": "derived",
                    "prices_published_at": "2026-10-14T20:03:33Z",
                    "derived_published_at": "2026-10-14T20:11:22Z",
                    "run_url": "https://github.com/tejhq/tej-bazaar/actions/runs/38628636275",
                    "generated_at": "2026-10-14T20:11:22Z",
                },
            )

        client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.tejhq.dev")
        provider = TejHQProvider(client=client)

        status = provider.get_status()
        self.assertEqual(status.provider_name, "TejHQ")
        self.assertEqual(status.trading_date, date(2026, 10, 14))
        self.assertEqual(status.stage, "derived")
        self.assertTrue(status.is_fresh)
        self.assertEqual(status.prices_published_at, datetime(2026, 10, 14, 20, 3, 33))
        self.assertEqual(status.derived_published_at, datetime(2026, 10, 14, 20, 11, 22))

    def test_status_invalid_date(self):
        def handler(request: httpx.Request):
            return httpx.Response(200, json={"trading_date": "invalid-date", "stage": "prices"})

        client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.tejhq.dev")
        provider = TejHQProvider(client=client)
        with self.assertRaises(ProviderResponseError):
            provider.get_status()

    def test_snapshot_parsing_and_semantic_distinctions(self):
        def handler(request: httpx.Request):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "symbol": "RELIANCE",
                            "series": "EQ",
                            "isin": "INE002A01018",
                            "name": "RELIANCE INDUSTRIES LTD",
                            "open": 1167.0,
                            "high": 1188.0,
                            "low": 1162.7,
                            "close": 1174.6,
                            "last": 1175.0,
                            "prev_close": 1166.7,
                            "volume": 10938195,
                            "turnover": 12880776743.5,
                            "trades": 233442,
                        }
                    ],
                    "meta": {
                        "count": 1,
                        "date": "2026-10-14",
                        "exchange": "NSE",
                    },
                },
            )

        client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.tejhq.dev")
        provider = TejHQProvider(client=client)

        snapshots = provider.get_daily_snapshot(date(2026, 10, 14))
        self.assertEqual(len(snapshots), 1)
        snap: NormalizedMarketSnapshot = snapshots[0]

        self.assertEqual(snap.symbol, "RELIANCE")
        self.assertEqual(snap.series, "EQ")
        self.assertEqual(snap.isin, "INE002A01018")
        self.assertEqual(snap.name, "RELIANCE INDUSTRIES LTD")
        self.assertEqual(snap.open, Decimal("1167.0"))
        self.assertEqual(snap.high, Decimal("1188.0"))
        self.assertEqual(snap.low, Decimal("1162.7"))
        # Verify strict distinction: LTP is last, close is close!
        self.assertEqual(snap.close, Decimal("1174.6"))
        self.assertEqual(snap.last_price, Decimal("1175.0"))
        self.assertNotEqual(snap.close, snap.last_price)
        self.assertEqual(snap.prev_close, Decimal("1166.7"))
        self.assertEqual(snap.volume, 10938195)
        self.assertEqual(snap.turnover, Decimal("12880776743.5"))
        self.assertEqual(snap.trades, 233442)
        # Percentage change calculated from (close - prev_close)/prev_close * 100
        expected_change = ((Decimal("1174.6") - Decimal("1166.7")) / Decimal("1166.7")) * Decimal("100")
        self.assertEqual(snap.percentage_change_pct, expected_change)
        self.assertTrue(snap.is_calculated_change)

    def test_snapshot_missing_close_never_mapped_to_ltp(self):
        def handler(request: httpx.Request):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "symbol": "TCS",
                            "series": "EQ",
                            "isin": "INE467B01029",
                            "open": 3500.0,
                            "high": 3550.0,
                            "low": 3490.0,
                            "close": None,  # Missing close
                            "last": 3520.0,  # LTP
                            "prev_close": 3500.0,
                            "volume": 500000,
                            "turnover": 1760000000.0,
                            "trades": 50000,
                        }
                    ],
                    "meta": {"count": 1, "date": "2026-10-14"},
                },
            )

        client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.tejhq.dev")
        provider = TejHQProvider(client=client)

        snapshots = provider.get_daily_snapshot(date(2026, 10, 14))
        self.assertEqual(len(snapshots), 1)
        snap = snapshots[0]
        # Never map LTP to close or treat missing close as LTP
        self.assertIsNone(snap.close)
        self.assertEqual(snap.last_price, Decimal("3520.0"))

    def test_snapshot_mismatched_date_rejected(self):
        def handler(request: httpx.Request):
            return httpx.Response(
                200,
                json={
                    "data": [],
                    "meta": {"date": "2026-10-13"},  # Mismatched with requested 2026-10-14
                },
            )

        client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.tejhq.dev")
        provider = TejHQProvider(client=client)

        with self.assertRaises(ProviderResponseError) as ctx:
            provider.get_daily_snapshot(date(2026, 10, 14))
        self.assertIn("mismatched", str(ctx.exception))

    def test_snapshot_invalid_numeric_values_rejected(self):
        def handler(request: httpx.Request):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "symbol": "TEST",
                            "open": "not-a-number",
                            "close": 100.0,
                        }
                    ],
                    "meta": {"date": "2026-10-14"},
                },
            )

        client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.tejhq.dev")
        provider = TejHQProvider(client=client)

        with self.assertRaises(ProviderDataValidationError):
            provider.get_daily_snapshot(date(2026, 10, 14))

    def test_transient_error_retry(self):
        calls = 0

        def handler(request: httpx.Request):
            nonlocal calls
            calls += 1
            if calls == 1:
                return httpx.Response(503, json={"error": "service unavailable"})
            return httpx.Response(200, json={"trading_date": "2026-10-14", "stage": "prices"})

        client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.tejhq.dev")
        provider = TejHQProvider(client=client, max_retries=2)

        with patch("time.sleep"):  # don't wait in tests
            status = provider.get_status()
        self.assertEqual(calls, 2)
        self.assertEqual(status.trading_date, date(2026, 10, 14))

    def test_non_transient_error_raises_immediately(self):
        def handler(request: httpx.Request):
            return httpx.Response(404, json={"error": "not_found", "message": "no data"})

        client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.tejhq.dev")
        provider = TejHQProvider(client=client, max_retries=3)

        with self.assertRaises(ProviderResponseError):
            provider.get_status()

    def test_historical_ohlcv_parsing(self):
        def handler(request: httpx.Request):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "date": "2026-10-14",
                            "open": 1167.0,
                            "high": 1188.0,
                            "low": 1162.7,
                            "close": 1174.6,
                            "last": 1174.6,
                            "prev_close": 1166.7,
                            "volume": 10938195,
                            "turnover": 12880776743.5,
                            "trades": 233442,
                        }
                    ],
                    "meta": {"symbol": "RELIANCE", "exchange": "NSE"},
                },
            )

        client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.tejhq.dev")
        provider = TejHQProvider(client=client)

        rows = provider.get_historical_ohlcv("RELIANCE", date(2026, 10, 10), date(2026, 10, 14))
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r.symbol, "RELIANCE")
        self.assertEqual(r.date, date(2026, 10, 14))
        self.assertEqual(r.open, Decimal("1167.0"))
        self.assertEqual(r.close, Decimal("1174.6"))
        self.assertEqual(r.volume, 10938195)


if __name__ == "__main__":
    unittest.main()
