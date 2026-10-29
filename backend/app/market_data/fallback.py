"""Controlled Provider Fallback Validation Gate and Source Precedence Policy.

Ensures that alternative market data providers pass strict identity, date, field,
unit and quality checks before any record is accepted into persistent storage.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Sequence

from app.analytics import is_divergence_material
from app.analytics.constants import MAX_ALLOWABLE_PRICE_DIVERGENCE_PCT
from app.models.instrument import Instrument
from app.providers.base import NormalizedMarketSnapshot
from app.providers.registry import ProviderRegistry

logger = logging.getLogger("app.market_data.fallback")


@dataclass(frozen=True)
class FallbackValidationResult:
    """Outcome of running fallback data through the multi-stage validation gate."""

    is_accepted: bool
    provider_name: str
    target_date: date
    records_evaluated: int
    records_passed: int
    records_failed: int
    records_unmatched: int
    rejection_reasons: tuple[str, ...] = ()
    quarantined_samples: tuple[dict[str, Any], ...] = ()


class FallbackValidationGate:
    """Multi-layer validation barrier that an alternative/fallback provider payload must pass."""

    DEFAULT_MIN_COVERAGE = 1500

    @classmethod
    def validate_payload(
        cls,
        provider_id: str,
        target_date: date,
        rows: Sequence[NormalizedMarketSnapshot],
        registered_instruments: dict[tuple[str, str, str], Instrument],
        symbol_instruments: dict[tuple[str, str], list[Instrument]],
        min_coverage: int = DEFAULT_MIN_COVERAGE,
    ) -> FallbackValidationResult:
        """Execute validation pipeline over candidate fallback rows.

        Verifies:
        1. Legal authorization (local storage & display rights).
        2. Date consistency across all rows.
        3. Instrument identity and symbol resolution.
        4. Field constraints and OHLC price relationship validity.
        5. Unit consistency.
        6. Minimum coverage threshold.
        """
        rejection_reasons: list[str] = []
        quarantined: list[dict[str, Any]] = []

        # Gate 1: Provider Permission Verification
        perms = ProviderRegistry.verify_permissions(provider_id)
        if not perms.get("local_storage_permitted", False):
            rejection_reasons.append(
                f"Provider '{provider_id}' is not authorized for local storage."
            )
        if not perms.get("intended_display_permitted", False):
            rejection_reasons.append(
                f"Provider '{provider_id}' is not authorized for application display."
            )

        if not rows:
            rejection_reasons.append("Fallback payload is completely empty (0 rows).")
            return FallbackValidationResult(
                is_accepted=False,
                provider_name=provider_id,
                target_date=target_date,
                records_evaluated=0,
                records_passed=0,
                records_failed=0,
                records_unmatched=0,
                rejection_reasons=tuple(rejection_reasons),
            )

        passed = 0
        failed = 0
        unmatched = 0

        for r in rows:
            # Gate 2: Date consistency check
            if r.snapshot_date != target_date:
                failed += 1
                if len(quarantined) < 10:
                    quarantined.append({
                        "symbol": r.symbol,
                        "error": f"Date mismatch: expected {target_date}, row had {r.snapshot_date}",
                    })
                continue

            # Gate 3: Instrument identity resolution
            sym = r.symbol.strip().upper()
            ser = r.series.strip().upper() if r.series else "EQ"
            inst = registered_instruments.get(("NSE", sym, ser))
            if inst is None:
                candidates = symbol_instruments.get(("NSE", sym), [])
                if len(candidates) == 1:
                    inst = candidates[0]
                else:
                    unmatched += 1
                    if len(quarantined) < 10:
                        quarantined.append({
                            "symbol": sym,
                            "error": f"Unmatched symbol or ambiguous series: {len(candidates)} candidates",
                        })
                    continue

            # Gate 4: Numeric & OHLC relationship quality checks
            row_errors: list[str] = []
            if r.close is not None and r.close <= 0:
                row_errors.append("Non-positive close price")
            if r.last_price is not None and r.last_price <= 0:
                row_errors.append("Non-positive LTP")
            if r.volume is not None and r.volume < 0:
                row_errors.append("Negative volume")

            # OHLC hierarchy
            if r.high is not None and r.low is not None and r.high < r.low:
                row_errors.append(f"High ({r.high}) < Low ({r.low})")
            if r.high is not None and r.open is not None and r.high < r.open:
                row_errors.append(f"High ({r.high}) < Open ({r.open})")
            if r.high is not None and r.close is not None and r.high < r.close:
                row_errors.append(f"High ({r.high}) < Close ({r.close})")
            if r.low is not None and r.open is not None and r.low > r.open:
                row_errors.append(f"Low ({r.low}) > Open ({r.open})")
            if r.low is not None and r.close is not None and r.low > r.close:
                row_errors.append(f"Low ({r.low}) > Close ({r.close})")

            # Gate 5: Unit consistency (turnover order of magnitude vs volume * price)
            if r.turnover is not None and r.volume is not None and r.close is not None and r.volume > 0:
                min_approx_turnover = Decimal(r.volume) * (r.low or r.close) * Decimal("0.8")
                max_approx_turnover = Decimal(r.volume) * (r.high or r.close) * Decimal("1.2")
                # If turnover is in Lakhs instead of raw Rupees or completely out of bound
                if r.turnover < (min_approx_turnover * Decimal("0.001")) or r.turnover > (max_approx_turnover * Decimal("1000")):
                    row_errors.append(
                        f"Turnover magnitude anomaly ({r.turnover} vs approx bounds [{min_approx_turnover:.2f}, {max_approx_turnover:.2f}])"
                    )

            if row_errors:
                failed += 1
                if len(quarantined) < 10:
                    quarantined.append({
                        "symbol": sym,
                        "error": "; ".join(row_errors),
                    })
            else:
                passed += 1

        # Gate 6: Minimum coverage check
        if passed < min_coverage:
            rejection_reasons.append(
                f"Valid records passed ({passed}) below required minimum coverage threshold ({min_coverage})."
            )

        is_accepted = len(rejection_reasons) == 0

        logger.info(
            "Fallback validation for '%s' on %s: accepted=%s (passed=%d, failed=%d, unmatched=%d, reasons=%s)",
            provider_id,
            target_date,
            is_accepted,
            passed,
            failed,
            unmatched,
            rejection_reasons,
        )

        return FallbackValidationResult(
            is_accepted=is_accepted,
            provider_name=provider_id,
            target_date=target_date,
            records_evaluated=len(rows),
            records_passed=passed,
            records_failed=failed,
            records_unmatched=unmatched,
            rejection_reasons=tuple(rejection_reasons),
            quarantined_samples=tuple(quarantined),
        )
