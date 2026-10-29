"""Analytics module: Authoritative financial calculations, market cap services, unit conversions, and domain constants."""
from __future__ import annotations

from app.analytics.calculations import (
    apply_bonus_adjustment,
    apply_consolidation_adjustment,
    apply_shares_delta,
    apply_split_adjustment,
    calculate_market_cap_crores,
    calculate_percentage_change,
    calculate_price_divergence,
    is_divergence_material,
)
from app.analytics.constants import (
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
)
from app.analytics.service import (
    MarketCapResult,
    MarketCapService,
)
from app.analytics.units import (
    CRORE_DENOMINATOR,
    LAKH_DENOMINATOR,
    MARKET_CAP_PRECISION,
    convert_turnover_to_crores,
    convert_volume_to_lakhs,
)

__all__ = [
    # Services
    "MarketCapService",
    "MarketCapResult",
    # Calculations
    "calculate_market_cap_crores",
    "calculate_percentage_change",
    "calculate_price_divergence",
    "is_divergence_material",
    "apply_bonus_adjustment",
    "apply_split_adjustment",
    "apply_consolidation_adjustment",
    "apply_shares_delta",
    # Units
    "convert_volume_to_lakhs",
    "convert_turnover_to_crores",
    "LAKH_DENOMINATOR",
    "CRORE_DENOMINATOR",
    "MARKET_CAP_PRECISION",
    # Constants
    "STALE_SHARE_COUNT_THRESHOLD_DAYS",
    "STALE_SNAPSHOT_THRESHOLD_DAYS",
    "PRICE_DIVERGENCE_THRESHOLD",
    "SOURCE_TEJHQ",
    "SOURCE_TEJHQ_EOD",
    "SOURCE_TEJHQ_HISTORICAL",
    "SOURCE_TEJHQ_CORPORATE_ACTIONS",
    "SOURCE_0XRAMM",
    "SOURCE_NSE_FILING",
    "SOURCE_MANUAL",
    "RUN_STATUS_COMPLETED",
    "RUN_STATUS_PARTIAL",
    "RUN_STATUS_FAILED",
    "RUN_STATUS_SKIPPED",
]
