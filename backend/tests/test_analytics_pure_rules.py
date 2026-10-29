"""Targeted unit tests for app.analytics pure financial rules, calculations, and conversions."""
from __future__ import annotations

import unittest
from decimal import Decimal

from app.analytics import (
    CRORE_DENOMINATOR,
    LAKH_DENOMINATOR,
    MARKET_CAP_PRECISION,
    PRICE_DIVERGENCE_THRESHOLD,
    RUN_STATUS_COMPLETED,
    RUN_STATUS_FAILED,
    RUN_STATUS_PARTIAL,
    RUN_STATUS_SKIPPED,
    SOURCE_0XRAMM,
    SOURCE_MANUAL,
    SOURCE_NSE_FILING,
    SOURCE_TEJHQ,
    SOURCE_TEJHQ_CORPORATE_ACTIONS,
    SOURCE_TEJHQ_EOD,
    SOURCE_TEJHQ_HISTORICAL,
    STALE_SHARE_COUNT_THRESHOLD_DAYS,
    STALE_SNAPSHOT_THRESHOLD_DAYS,
    apply_bonus_adjustment,
    apply_consolidation_adjustment,
    apply_shares_delta,
    apply_split_adjustment,
    calculate_market_cap_crores,
    calculate_percentage_change,
    calculate_price_divergence,
    convert_turnover_to_crores,
    convert_volume_to_lakhs,
    is_divergence_material,
)


class TestAnalyticsPureRules(unittest.TestCase):
    """Test pure financial formulas, unit conversions, and domain constants."""

    def test_calculate_market_cap_crores_valid(self):
        """Standard market cap calculation with 6-decimal quantization."""
        # 1,000 INR price * 10,000,000 shares = 10,000,000,000 INR = 1,000.000000 Cr
        mcap = calculate_market_cap_crores(Decimal("1000.00"), 10000000)
        self.assertEqual(mcap, Decimal("1000.000000"))

        # Fractional example: 1,234.56 price * 5,432,100 shares / 10,000,000 = 670.6253376 -> 670.625338
        mcap2 = calculate_market_cap_crores(Decimal("1234.56"), 5432100)
        self.assertEqual(mcap2, Decimal("670.625338"))

    def test_calculate_market_cap_crores_invalid_or_missing(self):
        """Missing or non-positive inputs safely return None without crashing or fabricating."""
        self.assertIsNone(calculate_market_cap_crores(None, 1000000))
        self.assertIsNone(calculate_market_cap_crores(Decimal("100.0"), None))
        self.assertIsNone(calculate_market_cap_crores(None, None))
        self.assertIsNone(calculate_market_cap_crores(Decimal("0.0"), 1000000))
        self.assertIsNone(calculate_market_cap_crores(Decimal("-50.0"), 1000000))
        self.assertIsNone(calculate_market_cap_crores(Decimal("100.0"), 0))
        self.assertIsNone(calculate_market_cap_crores(Decimal("100.0"), -500))

    def test_calculate_percentage_change(self):
        """Price percentage change calculation relative to previous day close."""
        # Upward: 100 -> 105 (+5%)
        pct, is_calc = calculate_percentage_change(Decimal("105.0"), Decimal("100.0"))
        self.assertTrue(is_calc)
        self.assertEqual(pct, Decimal("5.0"))

        # Downward: 200 -> 190 (-5%)
        pct, is_calc = calculate_percentage_change(Decimal("190.0"), Decimal("200.0"))
        self.assertTrue(is_calc)
        self.assertEqual(pct, Decimal("-5.0"))

        # Flat: 100 -> 100 (0%)
        pct, is_calc = calculate_percentage_change(Decimal("100.0"), Decimal("100.0"))
        self.assertTrue(is_calc)
        self.assertEqual(pct, Decimal("0.0"))

        # Zero or invalid prev_close
        pct, is_calc = calculate_percentage_change(Decimal("100.0"), Decimal("0.0"))
        self.assertFalse(is_calc)
        self.assertIsNone(pct)

        # Missing values
        pct, is_calc = calculate_percentage_change(None, Decimal("100.0"))
        self.assertFalse(is_calc)
        self.assertIsNone(pct)

        pct, is_calc = calculate_percentage_change(Decimal("100.0"), None)
        self.assertFalse(is_calc)
        self.assertIsNone(pct)

    def test_price_divergence_and_materiality(self):
        """Check feed-to-feed price divergence calculation and materiality threshold."""
        # 100 vs 103 -> 3% divergence (within 5% threshold)
        diff = calculate_price_divergence(Decimal("100.0"), Decimal("103.0"))
        self.assertEqual(diff, Decimal("0.03"))
        is_mat, pct = is_divergence_material(Decimal("100.0"), Decimal("103.0"))
        self.assertFalse(is_mat)
        self.assertEqual(pct, Decimal("0.03"))

        # 100 vs 110 -> 10% divergence (exceeds 5% threshold)
        is_mat, pct = is_divergence_material(Decimal("100.0"), Decimal("110.0"))
        self.assertTrue(is_mat)
        self.assertEqual(pct, Decimal("0.10"))

        # Missing or non-positive canonical price
        self.assertIsNone(calculate_price_divergence(None, Decimal("100.0")))
        self.assertIsNone(calculate_price_divergence(Decimal("0.0"), Decimal("100.0")))
        is_mat, pct = is_divergence_material(None, Decimal("100.0"))
        self.assertFalse(is_mat)
        self.assertIsNone(pct)

    def test_apply_bonus_adjustment(self):
        """Post-bonus equity shares calculation."""
        # 1:1 Bonus on 1,000,000 shares -> factor 2.0 -> 2,000,000 shares
        shares, factor = apply_bonus_adjustment(1000000, ratio_num=1, ratio_den=1)
        self.assertEqual(factor, Decimal("2"))
        self.assertEqual(shares, 2000000)

        # 1:2 Bonus (1 new for every 2 held) -> factor 1.5 -> 1,500,000 shares
        shares, factor = apply_bonus_adjustment(1000000, ratio_num=1, ratio_den=2)
        self.assertEqual(factor, Decimal("1.5"))
        self.assertEqual(shares, 1500000)

        # Invalid ratio
        with self.assertRaises(ValueError):
            apply_bonus_adjustment(1000000, ratio_num=1, ratio_den=0)

    def test_apply_split_adjustment(self):
        """Post-split equity shares calculation via face value or ratio."""
        # Face value split: 10 -> 2 (factor 5)
        shares, factor = apply_split_adjustment(
            1000000,
            face_value_from=Decimal("10"),
            face_value_to=Decimal("2"),
        )
        self.assertEqual(factor, Decimal("5"))
        self.assertEqual(shares, 5000000)

        # Ratio split: 2:1 (factor 2)
        shares, factor = apply_split_adjustment(1000000, ratio_num=2, ratio_den=1)
        self.assertEqual(factor, Decimal("2"))
        self.assertEqual(shares, 2000000)

        # Missing parameters
        with self.assertRaises(ValueError):
            apply_split_adjustment(1000000)

        # Invalid face value
        with self.assertRaises(ValueError):
            apply_split_adjustment(1000000, face_value_from=10, face_value_to=0)

    def test_apply_consolidation_adjustment(self):
        """Reverse stock split (consolidation)."""
        # 1:5 consolidation on 5,000,000 shares -> factor 0.2 -> 1,000,000 shares
        shares, factor = apply_consolidation_adjustment(5000000, ratio_num=1, ratio_den=5)
        self.assertEqual(factor, Decimal("0.2"))
        self.assertEqual(shares, 1000000)

        with self.assertRaises(ValueError):
            apply_consolidation_adjustment(5000000, ratio_num=0, ratio_den=5)

    def test_apply_shares_delta(self):
        """Additive share count updates (capital raise or buyback extinguishment)."""
        # Allotment +100,000
        new_shares = apply_shares_delta(1000000, 100000)
        self.assertEqual(new_shares, 1100000)

        # Buyback cancellation -50,000
        new_shares = apply_shares_delta(1000000, -50000)
        self.assertEqual(new_shares, 950000)

        # Over-cancellation bounded at 0
        new_shares = apply_shares_delta(100, -500)
        self.assertEqual(new_shares, 0)

    def test_unit_conversions(self):
        """Volume in Lakhs and Turnover in Crores unit conversions."""
        # Volume
        self.assertEqual(convert_volume_to_lakhs(100000), Decimal("1"))
        self.assertEqual(convert_volume_to_lakhs(250000), Decimal("2.5"))
        self.assertEqual(convert_volume_to_lakhs(0), Decimal("0"))
        self.assertIsNone(convert_volume_to_lakhs(None))

        # Turnover
        self.assertEqual(convert_turnover_to_crores(10000000), Decimal("1"))
        self.assertEqual(convert_turnover_to_crores("25000000.50"), Decimal("2.50000005"))
        self.assertIsNone(convert_turnover_to_crores(None))

    def test_constants_and_source_identifiers(self):
        """Domain constants and standard source names match canonical specifications."""
        self.assertEqual(STALE_SHARE_COUNT_THRESHOLD_DAYS, 120)
        self.assertEqual(STALE_SNAPSHOT_THRESHOLD_DAYS, 4)
        self.assertEqual(PRICE_DIVERGENCE_THRESHOLD, Decimal("0.05"))
        self.assertEqual(LAKH_DENOMINATOR, Decimal("100000"))
        self.assertEqual(CRORE_DENOMINATOR, Decimal("10000000"))
        self.assertEqual(MARKET_CAP_PRECISION, Decimal("0.000001"))

        self.assertEqual(SOURCE_TEJHQ, "TejHQ")
        self.assertEqual(SOURCE_TEJHQ_EOD, "TejHQ EOD Market")
        self.assertEqual(SOURCE_TEJHQ_HISTORICAL, "TejHQ Historical")
        self.assertEqual(SOURCE_TEJHQ_CORPORATE_ACTIONS, "TejHQ Corporate Actions")
        self.assertEqual(SOURCE_0XRAMM, "0xramm")
        self.assertEqual(SOURCE_NSE_FILING, "NSE Shareholding Pattern")
        self.assertEqual(SOURCE_MANUAL, "Manual Override")

        self.assertEqual(RUN_STATUS_COMPLETED, "completed")
        self.assertEqual(RUN_STATUS_PARTIAL, "partial")
        self.assertEqual(RUN_STATUS_FAILED, "failed")
        self.assertEqual(RUN_STATUS_SKIPPED, "skipped")


if __name__ == "__main__":
    unittest.main()
