"""Authoritative pure financial calculation formulas.

All functions are deterministic, side-effect free, and have zero database dependencies.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Tuple

from app.analytics.constants import PRICE_DIVERGENCE_THRESHOLD
from app.analytics.units import CRORE_DENOMINATOR, MARKET_CAP_PRECISION


def calculate_market_cap_crores(
    price: Decimal | float | None,
    share_count: int | None,
) -> Decimal | None:
    """Calculate point-in-time Market Capitalization in INR Crores.

    Formula:
        Market Capitalization (₹ Crores) = (Price × Applicable Outstanding Shares) / 10,000,000

    Rules:
    - Returns None if price is None, <= 0, or share_count is None, <= 0.
    - Result is quantized to 6 decimal places (0.000001 ₹ Cr).
    """
    if price is None or share_count is None:
        return None
    dec_price = Decimal(str(price))
    if dec_price <= 0 or share_count <= 0:
        return None

    raw_cap = dec_price * Decimal(share_count)
    return (raw_cap / CRORE_DENOMINATOR).quantize(MARKET_CAP_PRECISION)


def calculate_percentage_change(
    current_price: Decimal | float | None,
    prev_close: Decimal | float | None,
) -> Tuple[Decimal | None, bool]:
    """Calculate session price percentage change relative to previous day close.

    Formula:
        ((Current Price - Previous Close) / Previous Close) * 100

    Returns:
        (percentage_change_pct, is_calculated)
        Returns (None, False) if either price is missing or prev_close <= 0.
    """
    if current_price is None or prev_close is None:
        return None, False

    dec_curr = Decimal(str(current_price))
    dec_prev = Decimal(str(prev_close))

    if dec_prev <= 0:
        return None, False

    pct_change = ((dec_curr - dec_prev) / dec_prev) * Decimal("100")
    return pct_change, True


def calculate_price_divergence(
    canonical_price: Decimal | float | None,
    candidate_price: Decimal | float | None,
) -> Decimal | None:
    """Calculate relative divergence between candidate price and canonical price.

    Formula:
        abs(candidate_price - canonical_price) / canonical_price

    Returns:
        Relative difference as Decimal (e.g., 0.05 for 5%), or None if either price is invalid.
    """
    if canonical_price is None or candidate_price is None:
        return None

    dec_canonical = Decimal(str(canonical_price))
    dec_candidate = Decimal(str(candidate_price))

    if dec_canonical <= 0:
        return None

    return abs(dec_candidate - dec_canonical) / dec_canonical


def is_divergence_material(
    canonical_price: Decimal | float | None,
    candidate_price: Decimal | float | None,
    threshold: Decimal = PRICE_DIVERGENCE_THRESHOLD,
) -> Tuple[bool, Decimal | None]:
    """Check if the price divergence between two feeds exceeds an allowed tolerance threshold.

    Returns:
        (is_material, diff_pct)
    """
    diff_pct = calculate_price_divergence(canonical_price, candidate_price)
    if diff_pct is None:
        return False, None

    return diff_pct > threshold, diff_pct


def apply_bonus_adjustment(
    shares: Decimal | int,
    ratio_num: int,
    ratio_den: int,
) -> Tuple[int, Decimal]:
    """Calculate post-bonus equity shares count given ratio (e.g., 1:1 or 2:1).

    Formula:
        factor = 1 + (ratio_num / ratio_den)
        adjusted_shares = int(shares * factor)

    Returns:
        (adjusted_shares, factor)
    """
    if ratio_den <= 0 or ratio_num < 0:
        raise ValueError(f"Invalid bonus ratio: {ratio_num}:{ratio_den}")

    factor = Decimal(1) + (Decimal(ratio_num) / Decimal(ratio_den))
    adjusted_shares = int(Decimal(shares) * factor)
    return adjusted_shares, factor


def apply_split_adjustment(
    shares: Decimal | int,
    ratio_num: int | None = None,
    ratio_den: int | None = None,
    face_value_from: Decimal | float | None = None,
    face_value_to: Decimal | float | None = None,
) -> Tuple[int, Decimal]:
    """Calculate post-split equity shares count from face value change or split ratio.

    Rules:
    - If face values provided (e.g. 10 -> 2): factor = face_value_from / face_value_to.
    - If ratio provided (e.g. 2:1): factor = ratio_num / ratio_den.

    Returns:
        (adjusted_shares, split_factor)
    """
    if face_value_from is not None and face_value_to is not None:
        dec_fv_from = Decimal(str(face_value_from))
        dec_fv_to = Decimal(str(face_value_to))
        if dec_fv_to <= 0:
            raise ValueError(f"Invalid face_value_to: {face_value_to}")
        split_factor = dec_fv_from / dec_fv_to
    elif ratio_num is not None and ratio_den is not None:
        if ratio_den <= 0:
            raise ValueError(f"Invalid split ratio denominator: {ratio_den}")
        split_factor = Decimal(ratio_num) / Decimal(ratio_den)
    else:
        raise ValueError("Either face values or split ratio must be provided.")

    adjusted_shares = int(Decimal(shares) * split_factor)
    return adjusted_shares, split_factor


def apply_consolidation_adjustment(
    shares: Decimal | int,
    ratio_num: int,
    ratio_den: int,
) -> Tuple[int, Decimal]:
    """Calculate post-consolidation (reverse split) equity shares count.

    Formula:
        factor = ratio_num / ratio_den
        adjusted_shares = int(shares * factor)

    Returns:
        (adjusted_shares, factor)
    """
    if ratio_den <= 0 or ratio_num <= 0:
        raise ValueError(f"Invalid consolidation ratio: {ratio_num}:{ratio_den}")

    factor = Decimal(ratio_num) / Decimal(ratio_den)
    adjusted_shares = int(Decimal(shares) * factor)
    return adjusted_shares, factor


def apply_shares_delta(shares: Decimal | int, delta: int) -> int:
    """Apply an additive share count delta (e.g. QIP/rights issue addition or buyback cancellation).

    Returns:
        new_shares as integer (minimum 0).
    """
    result = int(Decimal(shares) + Decimal(delta))
    return max(0, result)
