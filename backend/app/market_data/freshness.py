"""Market Data Freshness Assessment and Bounded Polling.

Distinguishes between valid non-trading sessions (weekends/holidays), pending publications
awaiting upstream processing, and fully published/derived sessions. Prevents treating
an unpublished session as a valid empty dataset.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Sequence

from app.providers.base import IEODSnapshotProvider, ProviderError, ProviderStatus

logger = logging.getLogger("app.market_data.freshness")


class PublicationReadiness(str, Enum):
    READY = "ready"
    PENDING_PUBLICATION = "pending_publication"
    NON_TRADING_SESSION = "non_trading_session"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class ReadinessAssessment:
    """Formal assessment of provider publication status for a target trading date."""

    readiness: PublicationReadiness
    target_date: date
    provider_name: str
    latest_published_date: date | None
    pipeline_stage: str | None
    is_weekend: bool
    is_holiday: bool
    message: str


# Canonical standard NSE holidays for reference (expandable via exchange master)
KNOWN_NSE_HOLIDAYS_2026: set[date] = {
    date(2026, 1, 26),  # Republic Day
    date(2026, 3, 3),   # Holi
    date(2026, 3, 20),  # Id-Ul-Fitr
    date(2026, 4, 3),   # Good Friday
    date(2026, 4, 14),  # Dr. Baba Saheb Ambedkar Jayanti
    date(2026, 5, 1),   # Maharashtra Day
    date(2026, 5, 27),  # Bakri Id
    date(2026, 8, 15),  # Independence Day
    date(2026, 10, 2),  # Mahatma Gandhi Jayanti
    date(2026, 10, 20), # Dussehra
    date(2026, 11, 8),  # Diwali Laxmi Pujan
    date(2026, 11, 10), # Diwali Balipratipada
    date(2026, 11, 24), # Gurunanak Jayanti
    date(2026, 12, 25), # Christmas
}


def is_trading_day(target_date: date) -> bool:
    """Return True if target date is a weekday and not an official NSE exchange holiday."""
    if target_date.weekday() >= 5:  # 5=Saturday, 6=Sunday
        return False
    if target_date in KNOWN_NSE_HOLIDAYS_2026:
        return False
    return True


def assess_target_date_readiness(
    provider: IEODSnapshotProvider,
    target_date: date,
) -> ReadinessAssessment:
    """Assess whether a specific date has been published or is still pending upstream release."""
    provider_name = getattr(provider, "provider_name", "TejHQ")
    is_weekend = target_date.weekday() >= 5
    is_holiday = target_date in KNOWN_NSE_HOLIDAYS_2026

    if is_weekend or is_holiday:
        reason = "weekend" if is_weekend else "official NSE exchange holiday"
        return ReadinessAssessment(
            readiness=PublicationReadiness.NON_TRADING_SESSION,
            target_date=target_date,
            provider_name=provider_name,
            latest_published_date=None,
            pipeline_stage=None,
            is_weekend=is_weekend,
            is_holiday=is_holiday,
            message=f"{target_date} is a non-trading session ({reason}). No EOD data expected.",
        )

    try:
        status = provider.get_status()
    except ProviderError as exc:
        return ReadinessAssessment(
            readiness=PublicationReadiness.UNAVAILABLE,
            target_date=target_date,
            provider_name=provider_name,
            latest_published_date=None,
            pipeline_stage=None,
            is_weekend=False,
            is_holiday=False,
            message=f"Provider {provider_name} status check failed: {exc}",
        )

    latest_date = status.trading_date
    stage = status.stage

    if latest_date is None or latest_date < target_date:
        return ReadinessAssessment(
            readiness=PublicationReadiness.PENDING_PUBLICATION,
            target_date=target_date,
            provider_name=provider_name,
            latest_published_date=latest_date,
            pipeline_stage=stage,
            is_weekend=False,
            is_holiday=False,
            message=(
                f"Target trading date {target_date} has NOT yet been published by {provider_name} "
                f"(latest available is {latest_date or 'none'}, stage='{stage}'). Data is pending publication."
            ),
        )

    # Provider has reached or passed the target date
    if latest_date >= target_date:
        # Check if derived stage is ready if required
        if stage and stage not in ("derived", "completed", "active"):
            return ReadinessAssessment(
                readiness=PublicationReadiness.PENDING_PUBLICATION,
                target_date=target_date,
                provider_name=provider_name,
                latest_published_date=latest_date,
                pipeline_stage=stage,
                is_weekend=False,
                is_holiday=False,
                message=(
                    f"Target trading date {target_date} is in preliminary stage '{stage}' "
                    f"by {provider_name}. Derived EOD pipeline not yet finalized."
                ),
            )

        return ReadinessAssessment(
            readiness=PublicationReadiness.READY,
            target_date=target_date,
            provider_name=provider_name,
            latest_published_date=latest_date,
            pipeline_stage=stage,
            is_weekend=False,
            is_holiday=False,
            message=f"EOD snapshot for {target_date} is ready for ingestion (stage='{stage}').",
        )

    return ReadinessAssessment(
        readiness=PublicationReadiness.PENDING_PUBLICATION,
        target_date=target_date,
        provider_name=provider_name,
        latest_published_date=latest_date,
        pipeline_stage=stage,
        is_weekend=False,
        is_holiday=False,
        message=f"Awaiting publication for {target_date}.",
    )


def poll_for_eod_publication(
    provider: IEODSnapshotProvider,
    target_date: date,
    max_attempts: int = 3,
    poll_interval_seconds: float = 2.0,
) -> ReadinessAssessment:
    """Execute bounded polling with backoff waiting for provider publication."""
    provider_name = getattr(provider, "provider_name", "TejHQ")
    logger.info(
        "Starting bounded polling for %s publication of %s (max_attempts=%d, interval=%.1fs)...",
        provider_name,
        target_date,
        max_attempts,
        poll_interval_seconds,
    )

    assessment = assess_target_date_readiness(provider, target_date)
    if assessment.readiness in (PublicationReadiness.READY, PublicationReadiness.NON_TRADING_SESSION):
        return assessment

    for attempt in range(1, max_attempts + 1):
        logger.info(
            "Polling attempt %d/%d: %s status for %s is '%s'",
            attempt,
            max_attempts,
            provider_name,
            target_date,
            assessment.readiness.value,
        )
        if attempt < max_attempts:
            time.sleep(poll_interval_seconds)
            assessment = assess_target_date_readiness(provider, target_date)
            if assessment.readiness == PublicationReadiness.READY:
                logger.info("Session %s became ready on attempt %d!", target_date, attempt + 1)
                return assessment

    logger.warning(
        "Bounded polling exhausted (%d attempts). Target session %s is still '%s'.",
        max_attempts,
        target_date,
        assessment.readiness.value,
    )
    return assessment
