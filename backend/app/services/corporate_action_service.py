from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from app.providers.base import NormalizedCorporateAction
from app.providers.tejhq import TejHQProvider

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CorporateActionAdjustment:
    symbol: str
    from_date: date
    to_date: date
    factor: Decimal
    details: list[str]
    is_verified: bool
    error_message: str | None = None


class CorporateActionService:
    """Service to compute point-in-time corporate action adjustments (splits, bonuses)

    between an earlier disclosure date and a valuation date.
    """

    def __init__(self, provider: Any | None = None) -> None:
        self.provider = provider or TejHQProvider()

    def get_adjustment_factor(
        self,
        symbol: str,
        from_date: date,
        to_date: date,
    ) -> CorporateActionAdjustment:
        """Calculate cumulative share count adjustment factor for events occurring in (from_date, to_date].

        Point-in-time rule:
        Events with ex_date <= from_date are already reflected in the share count as of from_date.
        Events with ex_date > to_date have not occurred yet as of valuation date to_date.
        Only events where from_date < ex_date <= to_date affect the valuation date share count.
        """
        clean_symbol = symbol.strip().upper()
        if from_date >= to_date:
            return CorporateActionAdjustment(
                symbol=clean_symbol,
                from_date=from_date,
                to_date=to_date,
                factor=Decimal("1.0"),
                details=[],
                is_verified=True,
            )

        try:
            actions = self.provider.get_actions(clean_symbol)
        except Exception as exc:
            logger.warning(
                "Could not fetch corporate actions for %s between %s and %s: %s",
                clean_symbol,
                from_date,
                to_date,
                exc,
            )
            return CorporateActionAdjustment(
                symbol=clean_symbol,
                from_date=from_date,
                to_date=to_date,
                factor=Decimal("1.0"),
                details=[],
                is_verified=False,
                error_message=f"Corporate action lookup failed: {exc}",
            )

        relevant = [
            a
            for a in actions
            if from_date < a.ex_date <= to_date and a.action_type in ("bonus", "split")
        ]

        if not relevant:
            return CorporateActionAdjustment(
                symbol=clean_symbol,
                from_date=from_date,
                to_date=to_date,
                factor=Decimal("1.0"),
                details=[],
                is_verified=True,
            )

        relevant.sort(key=lambda a: a.ex_date)
        details: list[str] = []
        factor = Decimal("1.0")

        for a in relevant:
            if (
                a.action_type == "bonus"
                and a.ratio_num is not None
                and a.ratio_den is not None
                and a.ratio_den > 0
            ):
                bonus_factor = Decimal(a.ratio_num + a.ratio_den) / Decimal(a.ratio_den)
                factor *= bonus_factor
                details.append(f"Bonus {a.ratio_num}:{a.ratio_den} on {a.ex_date}")
            elif (
                a.action_type == "split"
                and a.face_value_from
                and a.face_value_to
                and a.face_value_to > 0
            ):
                split_factor = a.face_value_from / a.face_value_to
                factor *= split_factor
                details.append(f"Split {a.face_value_from}->{a.face_value_to} on {a.ex_date}")
            elif (
                a.action_type == "split"
                and a.ratio_num
                and a.ratio_den
                and a.ratio_den > 0
            ):
                split_factor = Decimal(a.ratio_num) / Decimal(a.ratio_den)
                factor *= split_factor
                details.append(f"Split {a.ratio_num}:{a.ratio_den} on {a.ex_date}")
            else:
                details.append(
                    f"{a.action_type.capitalize()} on {a.ex_date} ({a.raw_subject or 'unparsed'})"
                )

        return CorporateActionAdjustment(
            symbol=clean_symbol,
            from_date=from_date,
            to_date=to_date,
            factor=factor,
            details=details,
            is_verified=True,
        )
