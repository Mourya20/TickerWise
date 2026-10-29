"""Observed Market Data Publication Latency Measurement.

Measures actual observed upstream provider publication latency and end-to-end ingestion
timings relative to the canonical NSE regular market close (15:30:00 IST).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

# Canonical Indian Market Timings (NSE)
# Fixed offset UTC+05:30 (Indian Standard Time) - pure standard library without external tzdata
IST = timezone(timedelta(hours=5, minutes=30), name="IST")
NSE_MARKET_CLOSE_TIME = time(15, 30, 0)  # 15:30 IST / 10:00 UTC
TYPICAL_EOD_WINDOW_START = time(18, 30, 0)  # 18:30 IST
TYPICAL_EOD_WINDOW_END = time(22, 30, 0)    # 22:30 IST


@dataclass(frozen=True)
class ObservedLatencyMetrics:
    """Formal measurement of observed provider and pipeline delivery timing."""

    trading_date: date
    market_close_dt: datetime
    prices_published_at: datetime | None
    derived_published_at: datetime | None
    retrieval_started_at: datetime
    ingestion_completed_at: datetime | None

    # Computed delays in seconds
    upstream_price_latency_seconds: float | None
    upstream_derived_latency_seconds: float | None
    retrieval_delay_seconds: float
    total_end_to_end_seconds: float | None

    is_delayed: bool
    human_summary: str


def get_market_close_datetime(trading_date: date) -> datetime:
    """Return timezone-aware 15:30 IST datetime for a given trading date."""
    return datetime.combine(trading_date, NSE_MARKET_CLOSE_TIME, tzinfo=IST)


def measure_observed_latency(
    trading_date: date,
    retrieval_started_at: datetime,
    prices_published_at: datetime | None = None,
    derived_published_at: datetime | None = None,
    ingestion_completed_at: datetime | None = None,
    expected_threshold_hours: float = 6.0,
) -> ObservedLatencyMetrics:
    """Measure exact elapsed time between NSE market close and observed milestones."""
    market_close = get_market_close_datetime(trading_date)

    # Normalize retrieval and completion to IST aware if naive
    def to_ist(dt: datetime | None) -> datetime | None:
        if dt is None:
            return None
        if dt.tzinfo is None:
            # Assume UTC naive from database, convert to IST
            return dt.replace(tzinfo=timezone.utc).astimezone(IST)
        return dt.astimezone(IST)

    retrieval_ist = to_ist(retrieval_started_at)
    assert retrieval_ist is not None
    completed_ist = to_ist(ingestion_completed_at)
    prices_pub_ist = to_ist(prices_published_at)
    derived_pub_ist = to_ist(derived_published_at)

    retrieval_delay = (retrieval_ist - market_close).total_seconds()

    upstream_price_lat = None
    if prices_pub_ist:
        upstream_price_lat = (prices_pub_ist - market_close).total_seconds()

    upstream_derived_lat = None
    if derived_pub_ist:
        upstream_derived_lat = (derived_pub_ist - market_close).total_seconds()

    total_e2e = None
    if completed_ist:
        total_e2e = (completed_ist - market_close).total_seconds()

    # Determine if delayed beyond expected threshold (e.g. > 6 hours after close)
    benchmark_delay = upstream_derived_lat if upstream_derived_lat is not None else retrieval_delay
    is_delayed = benchmark_delay > (expected_threshold_hours * 3600)

    # Format human-readable summary
    def fmt_duration(seconds: float) -> str:
        sign = "-" if seconds < 0 else ""
        abs_sec = abs(seconds)
        hours = int(abs_sec // 3600)
        minutes = int((abs_sec % 3600) // 60)
        return f"{sign}{hours}h {minutes:02d}m"

    parts = [f"Trading Date: {trading_date}"]
    if upstream_derived_lat is not None:
        parts.append(f"Provider Derived Published: +{fmt_duration(upstream_derived_lat)} post-close")
    elif upstream_price_lat is not None:
        parts.append(f"Provider Prices Published: +{fmt_duration(upstream_price_lat)} post-close")

    if total_e2e is not None:
        parts.append(f"Pipeline Ingested: +{fmt_duration(total_e2e)} post-close")
    else:
        parts.append(f"Retrieval Started: +{fmt_duration(retrieval_delay)} post-close")

    if is_delayed:
        parts.append("(DELAYED)")

    summary = " | ".join(parts)

    return ObservedLatencyMetrics(
        trading_date=trading_date,
        market_close_dt=market_close,
        prices_published_at=prices_pub_ist,
        derived_published_at=derived_pub_ist,
        retrieval_started_at=retrieval_ist,
        ingestion_completed_at=completed_ist,
        upstream_price_latency_seconds=upstream_price_lat,
        upstream_derived_latency_seconds=upstream_derived_lat,
        retrieval_delay_seconds=retrieval_delay,
        total_end_to_end_seconds=total_e2e,
        is_delayed=is_delayed,
        human_summary=summary,
    )
