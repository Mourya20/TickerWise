"""Authoritative Market Capitalization analytics service.

Owns the single authoritative implementation for calculating dated, defensible equity market cap:
Market Capitalization in ₹ Crores = (LTP × Applicable Outstanding Shares) / 10,000,000
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics.calculations import calculate_market_cap_crores
from app.analytics.constants import STALE_SHARE_COUNT_THRESHOLD_DAYS
from app.models import DailyMarketSnapshot, DataSource, Instrument, InstrumentShareCount

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MarketCapResult:
    market_cap_crores: Decimal | None
    currency: str
    unit: str
    price_used: Decimal | None
    price_date: date | None
    price_type: str  # "LTP" or "close"
    share_count: int | None
    share_count_date: date | None
    share_count_source: str | None
    share_count_method: str | None  # "directly_reported" or "derived"
    share_count_status: str  # "fresh", "stale", "unavailable"
    is_stale: bool
    status: str  # "calculated", "unavailable"
    explanation: str | None
    calculated_at: datetime


class MarketCapService:
    """Calculates defensible, dated equity market capitalization.

    Formula:
    Market Capitalization in ₹ Crores = (LTP × Applicable Outstanding Shares) / 10,000,000
    """

    @classmethod
    def calculate_for_instrument(
        cls,
        instrument_id: int,
        db: Session,
        as_of_date: date | None = None,
        price_basis: str = "LTP",
    ) -> MarketCapResult:
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)

        instrument = db.get(Instrument, instrument_id)
        if instrument is None:
            return MarketCapResult(
                market_cap_crores=None,
                currency="INR",
                unit="₹ Crores",
                price_used=None,
                price_date=None,
                price_type=price_basis,
                share_count=None,
                share_count_date=None,
                share_count_source=None,
                share_count_method=None,
                share_count_status="unavailable",
                is_stale=True,
                status="unavailable",
                explanation="Instrument not found.",
                calculated_at=now_utc,
            )

        # 1. Select price from snapshot
        snapshot_stmt = (
            select(DailyMarketSnapshot)
            .where(DailyMarketSnapshot.instrument_id == instrument_id)
        )
        if as_of_date:
            snapshot_stmt = snapshot_stmt.where(DailyMarketSnapshot.snapshot_date <= as_of_date)
        snapshot_stmt = snapshot_stmt.order_by(DailyMarketSnapshot.snapshot_date.desc()).limit(1)

        snapshot = db.scalar(snapshot_stmt)
        if snapshot is None:
            return MarketCapResult(
                market_cap_crores=None,
                currency="INR",
                unit="₹ Crores",
                price_used=None,
                price_date=None,
                price_type=price_basis,
                share_count=None,
                share_count_date=None,
                share_count_source=None,
                share_count_method=None,
                share_count_status="unavailable",
                is_stale=True,
                status="unavailable",
                explanation="No market price snapshot found for instrument.",
                calculated_at=now_utc,
            )

        price: Decimal | None = None
        price_type = price_basis
        if price_basis.upper() == "LTP" and snapshot.last_traded_price is not None:
            price = snapshot.last_traded_price
            price_type = "LTP"
        elif snapshot.close_price is not None:
            price = snapshot.close_price
            price_type = "close"
        elif snapshot.last_traded_price is not None:
            price = snapshot.last_traded_price
            price_type = "LTP"

        if price is None or price <= 0:
            return MarketCapResult(
                market_cap_crores=None,
                currency="INR",
                unit="₹ Crores",
                price_used=None,
                price_date=snapshot.snapshot_date,
                price_type=price_type,
                share_count=None,
                share_count_date=None,
                share_count_source=None,
                share_count_method=None,
                share_count_status="unavailable",
                is_stale=True,
                status="unavailable",
                explanation=f"Valid market price missing on snapshot date {snapshot.snapshot_date}.",
                calculated_at=now_utc,
            )

        price_date = snapshot.snapshot_date

        # 2. Select applicable share count with point-in-time corporate action resolution
        from app.services.corporate_action_service import CorporateActionService
        ca_service = CorporateActionService()
        share_res = ca_service.resolve_applicable_share_count(db, instrument_id, price_date)

        if share_res.share_count is None:
            return MarketCapResult(
                market_cap_crores=None,
                currency="INR",
                unit="₹ Crores",
                price_used=price,
                price_date=price_date,
                price_type=price_type,
                share_count=None,
                share_count_date=share_res.base_reporting_date,
                share_count_source=share_res.data_source,
                share_count_method=share_res.extraction_method,
                share_count_status="unavailable",
                is_stale=True,
                status="unavailable",
                explanation=share_res.explanation or f"No official NSE shareholding pattern disclosure found on or before price date {price_date}.",
                calculated_at=now_utc,
            )

        effective_share_count = share_res.share_count
        share_count_date = share_res.base_reporting_date
        share_source = share_res.data_source or "NSE Disclosure"
        share_method = share_res.extraction_method
        share_status = share_res.status
        is_stale = share_res.is_stale

        # 3. Deterministic computation: (price * effective_shares) / 10,000,000
        mcap_crores = calculate_market_cap_crores(price, effective_share_count)

        return MarketCapResult(
            market_cap_crores=mcap_crores,
            currency="INR",
            unit="₹ Crores",
            price_used=price,
            price_date=price_date,
            price_type=price_type,
            share_count=effective_share_count,
            share_count_date=share_count_date,
            share_count_source=share_source,
            share_count_method=share_method,
            share_count_status=share_status,
            is_stale=is_stale,
            status="calculated",
            explanation=share_res.explanation,
            calculated_at=now_utc,
        )
