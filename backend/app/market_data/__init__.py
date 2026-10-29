"""Market Data domain module.

Owns daily market snapshots, historical OHLCV data, bar validation, and backfills.
"""
from __future__ import annotations

from app.market_data.backfill import BackfillAudit, HistoricalBackfillService
from app.market_data.fallback import FallbackValidationGate, FallbackValidationResult
from app.market_data.freshness import (
    PublicationReadiness,
    ReadinessAssessment,
    assess_target_date_readiness,
    is_trading_day,
    poll_for_eod_publication,
)
from app.market_data.latency import (
    ObservedLatencyMetrics,
    get_market_close_datetime,
    measure_observed_latency,
)
from app.market_data.service import validate_ohlcv_bar

__all__ = [
    "validate_ohlcv_bar",
    "HistoricalBackfillService",
    "BackfillAudit",
    "FallbackValidationGate",
    "FallbackValidationResult",
    "PublicationReadiness",
    "ReadinessAssessment",
    "assess_target_date_readiness",
    "poll_for_eod_publication",
    "is_trading_day",
    "measure_observed_latency",
    "get_market_close_datetime",
    "ObservedLatencyMetrics",
]
