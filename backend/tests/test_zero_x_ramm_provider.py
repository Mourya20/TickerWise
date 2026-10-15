from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal

import httpx

from app.providers.base import (
    ProviderConfigurationError,
    ProviderPermissionError,
    ProviderResponseError,
)
from app.providers.zero_x_ramm import ZeroXRammProvider


class TestZeroXRammProvider(unittest.TestCase):
    def test_disabled_by_default_raises_permission_error(self):
        # Default initialization should fail closed
        provider = ZeroXRammProvider(enabled=False, permission_confirmed=False)
        with self.assertRaises(ProviderPermissionError) as ctx:
            provider.get_status()
        self.assertIn("disabled by configuration", str(ctx.exception))

    def test_unverified_automation_permission_fails_closed(self):
        # Even if enabled is set, without permission confirmation it fails closed
        provider = ZeroXRammProvider(
            enabled=True,
            permission_confirmed=False,
            base_url="http://localhost:5000",
        )
        with self.assertRaises(ProviderPermissionError) as ctx:
            provider.get_stock_quote("RELIANCE")
        self.assertIn("permission for upstream Yahoo Finance has not been verified", str(ctx.exception))

    def test_missing_base_url_raises_configuration_error(self):
        # When enabled and permission confirmed, but base URL missing
        provider = ZeroXRammProvider(
            enabled=True,
            permission_confirmed=True,
            base_url="",
        )
        with self.assertRaises(ProviderConfigurationError) as ctx:
            provider.get_stock_quote("RELIANCE")
        self.assertIn("base URL is not configured", str(ctx.exception))

    def test_quote_parsing_with_res_num(self):
        def handler(request: httpx.Request):
            self.assertEqual(request.url.path, "/stock")
            self.assertEqual(request.url.params.get("symbol"), "RELIANCE.NS")
            self.assertEqual(request.url.params.get("res"), "num")
            return httpx.Response(
                200,
                json={
                    "symbol": "RELIANCE.NS",
                    "price": 2500.50,
                    "change_pct": 1.25,
                    "volume": 4500000,
                    "market_cap": 16900000000000,
                    "pe_ratio": 28.4,
                    "dividend_yield": 0.35,
                    "sector": "Energy",
                },
            )

        client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://localhost:5000")
        provider = ZeroXRammProvider(
            enabled=True,
            permission_confirmed=True,
            base_url="http://localhost:5000",
            client=client,
        )

        quote = provider.get_stock_quote("RELIANCE")
        self.assertEqual(quote.symbol, "RELIANCE")
        self.assertEqual(quote.exchange, "NSE")
        self.assertEqual(quote.price, Decimal("2500.50"))
        self.assertEqual(quote.percentage_change_pct, Decimal("1.25"))
        self.assertEqual(quote.volume, 4500000)
        self.assertEqual(quote.market_cap, Decimal("16900000000000"))
        self.assertEqual(quote.pe_ratio, Decimal("28.4"))
        self.assertEqual(quote.dividend_yield, Decimal("0.35"))
        self.assertEqual(quote.sector, "Energy")
        self.assertIn("0xramm", quote.provider_name)

    def test_quote_parsing_with_res_val_structures(self):
        def handler(request: httpx.Request):
            return httpx.Response(
                200,
                json={
                    "symbol": "INFY.NS",
                    "price": {"value": 1500.0, "unit": "INR"},
                    "pe_ratio": {"value": 24.5, "unit": "x"},
                    "market_cap": {"value": 620000000000, "unit": "INR"},
                    "volume": {"value": 2000000, "unit": "shares"},
                },
            )

        client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://localhost:5000")
        provider = ZeroXRammProvider(
            enabled=True,
            permission_confirmed=True,
            base_url="http://localhost:5000",
            client=client,
        )

        quote = provider.get_stock_quote("INFY")
        self.assertEqual(quote.price, Decimal("1500.0"))
        self.assertEqual(quote.pe_ratio, Decimal("24.5"))
        self.assertEqual(quote.market_cap, Decimal("620000000000"))
        self.assertEqual(quote.volume, 2000000)

    def test_missing_fields_never_fabricated(self):
        def handler(request: httpx.Request):
            return httpx.Response(
                200,
                json={
                    "symbol": "SMALLCAP.NS",
                    "price": 50.0,
                    # market_cap, pe_ratio, dividend_yield, sector missing
                },
            )

        client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://localhost:5000")
        provider = ZeroXRammProvider(
            enabled=True,
            permission_confirmed=True,
            base_url="http://localhost:5000",
            client=client,
        )

        quote = provider.get_stock_quote("SMALLCAP")
        self.assertEqual(quote.price, Decimal("50.0"))
        self.assertIsNone(quote.market_cap)
        self.assertIsNone(quote.pe_ratio)
        self.assertIsNone(quote.dividend_yield)
        self.assertIsNone(quote.sector)

    def test_metrics_extraction(self):
        def handler(request: httpx.Request):
            return httpx.Response(
                200,
                json={
                    "symbol": "TCS.NS",
                    "price": 3500.0,
                    "market_cap": 12800000000000,
                    "pe_ratio": 29.5,
                    "dividend_yield": 1.2,
                    "sector": "Information Technology",
                },
            )

        client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://localhost:5000")
        provider = ZeroXRammProvider(
            enabled=True,
            permission_confirmed=True,
            base_url="http://localhost:5000",
            client=client,
        )

        metrics = provider.get_stock_metrics("TCS")
        self.assertEqual(len(metrics), 4)

        metric_dict = {m.metric_name: m for m in metrics}
        self.assertIn("market_cap", metric_dict)
        self.assertEqual(metric_dict["market_cap"].numeric_value, Decimal("12800000000000"))
        self.assertEqual(metric_dict["market_cap"].metric_unit, "INR")

        self.assertIn("pe_ratio", metric_dict)
        self.assertEqual(metric_dict["pe_ratio"].numeric_value, Decimal("29.5"))
        self.assertEqual(metric_dict["pe_ratio"].metric_unit, "ratio")

        self.assertIn("dividend_yield", metric_dict)
        self.assertEqual(metric_dict["dividend_yield"].numeric_value, Decimal("1.2"))
        self.assertEqual(metric_dict["dividend_yield"].metric_unit, "pct")

        self.assertIn("sector", metric_dict)
        self.assertEqual(metric_dict["sector"].text_value, "Information Technology")
        self.assertEqual(metric_dict["sector"].metric_unit, "text")

    def test_unsupported_methods_raise_not_implemented(self):
        provider = ZeroXRammProvider(
            enabled=True,
            permission_confirmed=True,
            base_url="http://localhost:5000",
        )
        with self.assertRaises(NotImplementedError):
            provider.get_daily_snapshot(date(2026, 10, 14))

        with self.assertRaises(NotImplementedError):
            provider.get_historical_ohlcv("RELIANCE", date(2026, 10, 10), date(2026, 10, 14))


if __name__ == "__main__":
    unittest.main()
