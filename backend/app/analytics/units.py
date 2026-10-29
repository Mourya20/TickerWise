"""Authoritative financial unit conversions and precision factors."""
from __future__ import annotations

from decimal import Decimal

LAKH_DENOMINATOR: Decimal = Decimal("100000")
CRORE_DENOMINATOR: Decimal = Decimal("10000000")
MARKET_CAP_PRECISION: Decimal = Decimal("0.000001")


def convert_volume_to_lakhs(volume: int | Decimal | float | None) -> Decimal | None:
    """Convert raw equity share trade volume to Lakhs (1 Lakh = 100,000 shares).

    Returns None if volume is None.
    """
    if volume is None:
        return None
    return Decimal(volume) / LAKH_DENOMINATOR


def convert_turnover_to_crores(turnover: Decimal | float | int | None) -> Decimal | None:
    """Convert raw trading value in Indian Rupees (INR) to ₹ Crores (1 Crore = 10,000,000 INR).

    Returns None if turnover is None.
    """
    if turnover is None:
        return None
    return Decimal(str(turnover)) / CRORE_DENOMINATOR
