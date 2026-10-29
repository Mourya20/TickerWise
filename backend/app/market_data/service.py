"""Market data domain services.

Owns daily market snapshots, historical OHLCV queries, and price semantic validation.
"""
from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.daily_market_snapshot import DailyMarketSnapshot
from app.models.instrument import Instrument

logger = logging.getLogger(__name__)


def validate_ohlcv_bar(
    open_price: Decimal | None,
    high_price: Decimal | None,
    low_price: Decimal | None,
    close_price: Decimal | None,
) -> list[str]:
    """Validate internal financial integrity of an OHLC bar.

    Rules:
    - High must be >= Open, Low, Close (when present).
    - Low must be <= Open, High, Close (when present).
    """
    errors: list[str] = []
    prices = [p for p in (open_price, high_price, low_price, close_price) if p is not None]
    if not prices:
        return errors

    if high_price is not None:
        if open_price is not None and high_price < open_price:
            errors.append(f"High ({high_price}) < Open ({open_price})")
        if low_price is not None and high_price < low_price:
            errors.append(f"High ({high_price}) < Low ({low_price})")
        if close_price is not None and high_price < close_price:
            errors.append(f"High ({high_price}) < Close ({close_price})")

    if low_price is not None:
        if open_price is not None and low_price > open_price:
            errors.append(f"Low ({low_price}) > Open ({open_price})")
        if close_price is not None and low_price > close_price:
            errors.append(f"Low ({low_price}) > Close ({close_price})")

    return errors
