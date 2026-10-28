from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.models.corporate_action import CorporateAction
from app.models.data_source import DataSource
from app.models.instrument import Instrument
from app.models.instrument_share_count import InstrumentShareCount
from app.providers.base import NormalizedCorporateAction
from app.providers.tejhq import TejHQProvider

logger = logging.getLogger(__name__)

STALE_SHARE_COUNT_THRESHOLD_DAYS = 120
DEFAULT_SOURCE_NAME = "TejHQ Corporate Actions"


@dataclass(frozen=True)
class CorporateActionAdjustment:
    symbol: str
    from_date: date
    to_date: date
    factor: Decimal
    details: list[str]
    is_verified: bool
    error_message: str | None = None


@dataclass(frozen=True)
class ApplicableShareCountResult:
    instrument_id: int
    symbol: str
    share_count: int | None
    base_share_count: int | None
    base_reporting_date: date | None
    valuation_date: date
    actions_applied: list[str]
    has_unquantified_action: bool
    unquantified_reasons: list[str]
    is_verified: bool
    data_source: str | None
    extraction_method: str | None
    is_stale: bool
    status: str  # "fresh", "stale", "unverified", "stale_unverified", "unavailable"
    explanation: str | None


def generate_dedup_key(
    exchange: str,
    symbol: str,
    event_type: str,
    event_date: date | None,
    ratio_num: int | None = None,
    ratio_den: int | None = None,
    face_value_from: Decimal | None = None,
    face_value_to: Decimal | None = None,
    cash_amount: Decimal | None = None,
    shares: int | None = None,
) -> str:
    """Generate a deterministic deduplication key for a corporate action."""
    ex = (exchange or "NSE").strip().upper()
    sym = (symbol or "").strip().upper()
    et = (event_type or "other").strip().lower()
    dt = event_date.isoformat() if event_date else "NODATE"

    parts = [ex, sym, et, dt]
    if ratio_num is not None or ratio_den is not None:
        parts.append(f"R{ratio_num}_{ratio_den}")
    elif face_value_from is not None or face_value_to is not None:
        parts.append(f"FV{face_value_from}_{face_value_to}")
    if cash_amount is not None:
        parts.append(f"C{cash_amount}")
    if shares is not None:
        parts.append(f"S{shares}")

    key = ":".join(parts)
    if len(key) > 120:
        h = hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
        return f"{key[:95]}:{h}"
    return key


def get_action_effective_date(action: CorporateAction) -> date | None:
    """Determine the date on which the corporate action takes effect on trading/share capital."""
    return (
        action.effective_date
        or action.allotment_date
        or action.completion_date
        or action.ex_date
        or action.record_date
        or action.announcement_date
    )


class CorporateActionService:
    """Service to ingest, deduplicate, and resolve point-in-time corporate actions

    and effective outstanding share counts.
    """

    def __init__(self, provider: Any | None = None) -> None:
        self.provider = provider or TejHQProvider()

    def get_or_create_source(self, session: Session) -> DataSource:
        """Find or create the DataSource record for corporate actions."""
        source = session.scalar(
            select(DataSource).where(
                or_(
                    DataSource.name == DEFAULT_SOURCE_NAME,
                    DataSource.name == "TejHQ EOD Market Data",
                )
            ).order_by(DataSource.id.asc()).limit(1)
        )
        if source is None:
            source = DataSource(
                name=DEFAULT_SOURCE_NAME,
                source_type="api",
                source_url="https://tejhq.dev",
                terms_url="https://tejhq.dev/terms",
                is_active=True,
            )
            session.add(source)
            session.flush()
        return source

    def ingest_actions(
        self,
        session: Session,
        actions: list[NormalizedCorporateAction | dict[str, Any]],
        source_id: int | None = None,
    ) -> list[CorporateAction]:
        """Idempotently ingest and reconcile corporate actions with audit provenance."""
        if not actions:
            return []

        if source_id is None:
            source = self.get_or_create_source(session)
            source_id = source.id

        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        persisted: list[CorporateAction] = []

        # Cache instruments by symbol
        symbols = set()
        for a in actions:
            if isinstance(a, NormalizedCorporateAction):
                symbols.add(a.symbol.strip().upper())
            elif isinstance(a, dict):
                sym = str(a.get("symbol", "")).strip().upper()
                if sym:
                    symbols.add(sym)

        instruments = session.scalars(
            select(Instrument).where(
                Instrument.exchange == "NSE",
                Instrument.symbol.in_(list(symbols)),
            )
        ).all()
        inst_map = {inst.symbol: inst for inst in instruments}

        for item in actions:
            if isinstance(item, NormalizedCorporateAction):
                sym = item.symbol.strip().upper()
                exchange = item.exchange.strip().upper()
                event_type = item.action_type.strip().lower()
                ex_date = item.ex_date
                record_date = item.record_date
                announcement_date = None
                allotment_date = None
                completion_date = None
                effective_date = None
                ratio_num = item.ratio_num
                ratio_den = item.ratio_den
                face_value_from = item.face_value_from
                face_value_to = item.face_value_to
                cash_amount = item.cash_amount
                proposed_shares = None
                proposed_amount = None
                actual_shares = None
                actual_amount = None
                status = "completed"
                raw_subject = item.raw_subject
                raw_payload = None
                source_ref = "TejHQ API"
            elif isinstance(item, dict):
                sym = str(item.get("symbol", "")).strip().upper()
                exchange = str(item.get("exchange", "NSE")).strip().upper()
                event_type = str(item.get("event_type") or item.get("action_type") or "other").strip().lower()
                ex_date = item.get("ex_date")
                record_date = item.get("record_date")
                announcement_date = item.get("announcement_date")
                allotment_date = item.get("allotment_date")
                completion_date = item.get("completion_date")
                effective_date = item.get("effective_date")
                ratio_num = item.get("ratio_num")
                ratio_den = item.get("ratio_den")
                face_value_from = item.get("face_value_from")
                face_value_to = item.get("face_value_to")
                cash_amount = item.get("cash_amount")
                proposed_shares = item.get("proposed_shares")
                proposed_amount = item.get("proposed_amount")
                actual_shares = item.get("actual_shares")
                actual_amount = item.get("actual_amount")
                status = str(item.get("status", "completed")).strip().lower()
                raw_subject = item.get("raw_subject")
                raw_payload = json.dumps(item.get("raw_payload")) if isinstance(item.get("raw_payload"), (dict, list)) else item.get("raw_payload")
                source_ref = item.get("source_reference", "API Ingestion")
            else:
                continue

            inst = inst_map.get(sym)
            if inst is None:
                logger.warning("Skipping corporate action for unknown instrument symbol '%s'", sym)
                continue

            provided_key = item.get("dedup_key") if isinstance(item, dict) else None
            anchor_dt = announcement_date or ex_date or record_date or allotment_date or completion_date or effective_date
            dedup_key = provided_key or generate_dedup_key(
                exchange=exchange,
                symbol=sym,
                event_type=event_type,
                event_date=anchor_dt,
                ratio_num=ratio_num,
                ratio_den=ratio_den,
                face_value_from=face_value_from,
                face_value_to=face_value_to,
                cash_amount=cash_amount,
            )

            existing = session.scalar(
                select(CorporateAction).where(CorporateAction.dedup_key == dedup_key)
            )

            if existing is not None:
                # Reconcile updates (e.g. status transition from proposed -> allotted, actual shares confirmed)
                updated = False
                if status and existing.status != status:
                    existing.status = status
                    updated = True
                if actual_shares is not None and existing.actual_shares != actual_shares:
                    existing.actual_shares = actual_shares
                    updated = True
                if actual_amount is not None and existing.actual_amount != actual_amount:
                    existing.actual_amount = actual_amount
                    updated = True
                if allotment_date is not None and existing.allotment_date != allotment_date:
                    existing.allotment_date = allotment_date
                    updated = True
                if completion_date is not None and existing.completion_date != completion_date:
                    existing.completion_date = completion_date
                    updated = True
                if effective_date is not None and existing.effective_date != effective_date:
                    existing.effective_date = effective_date
                    updated = True
                if updated:
                    existing.updated_at = now_utc
                persisted.append(existing)
            else:
                new_action = CorporateAction(
                    instrument_id=inst.id,
                    exchange=exchange,
                    symbol=sym,
                    event_type=event_type,
                    dedup_key=dedup_key,
                    announcement_date=announcement_date,
                    record_date=record_date,
                    ex_date=ex_date,
                    issue_open_date=None,
                    issue_close_date=None,
                    allotment_date=allotment_date,
                    completion_date=completion_date,
                    effective_date=effective_date,
                    ratio_num=ratio_num,
                    ratio_den=ratio_den,
                    face_value_from=face_value_from,
                    face_value_to=face_value_to,
                    cash_amount=cash_amount,
                    proposed_shares=proposed_shares,
                    proposed_amount=proposed_amount,
                    actual_shares=actual_shares,
                    actual_amount=actual_amount,
                    status=status,
                    source_id=source_id,
                    source_reference=source_ref,
                    retrieved_at=now_utc,
                    raw_subject=raw_subject,
                    raw_payload=raw_payload,
                    validation_status="valid",
                    notes=None,
                )
                session.add(new_action)
                persisted.append(new_action)

        session.flush()
        return persisted

    def fetch_and_persist_for_symbol(
        self,
        session: Session,
        symbol: str,
        source_id: int | None = None,
    ) -> int:
        """Fetch corporate actions from provider for symbol and persist to database."""
        clean_symbol = symbol.strip().upper()
        if not hasattr(self.provider, "get_actions"):
            return 0
        try:
            actions = self.provider.get_actions(clean_symbol)
        except Exception as exc:
            logger.warning("Provider failed to fetch actions for %s: %s", clean_symbol, exc)
            return 0

        if not actions:
            return 0

        persisted = self.ingest_actions(session, actions, source_id=source_id)
        return len(persisted)

    def get_actions_for_instrument(
        self,
        session: Session,
        instrument_id: int,
        event_types: list[str] | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[CorporateAction]:
        """Query corporate actions for an instrument ordered chronologically descending."""
        stmt = select(CorporateAction).where(CorporateAction.instrument_id == instrument_id)

        if event_types:
            clean_types = [t.strip().lower() for t in event_types]
            stmt = stmt.where(CorporateAction.event_type.in_(clean_types))

        if from_date:
            date_col = func.coalesce(
                CorporateAction.effective_date,
                CorporateAction.ex_date,
                CorporateAction.allotment_date,
                CorporateAction.completion_date,
                CorporateAction.record_date,
                CorporateAction.announcement_date,
            )
            stmt = stmt.where(date_col >= from_date)

        if to_date:
            date_col = func.coalesce(
                CorporateAction.effective_date,
                CorporateAction.ex_date,
                CorporateAction.allotment_date,
                CorporateAction.completion_date,
                CorporateAction.record_date,
                CorporateAction.announcement_date,
            )
            stmt = stmt.where(date_col <= to_date)

        stmt = stmt.order_by(
            func.coalesce(
                CorporateAction.effective_date,
                CorporateAction.ex_date,
                CorporateAction.allotment_date,
                CorporateAction.completion_date,
                CorporateAction.record_date,
                CorporateAction.announcement_date,
            ).desc(),
            CorporateAction.id.desc(),
        )

        return list(session.scalars(stmt).all())

    def resolve_applicable_share_count(
        self,
        session: Session,
        instrument_id: int,
        valuation_date: date,
    ) -> ApplicableShareCountResult:
        """Resolve applicable point-in-time outstanding equity share count for an instrument.

        Mathematical and business rules:
        1. Select latest active equity share count reported on or before valuation_date.
        2. If no official disclosure exists on or before valuation_date: return unavailable.
        3. Identify window: (base_reporting_date, valuation_date].
        4. Query completed/allotted corporate actions with effective dates inside this window.
        5. Adjust share count sequentially:
           - Splits and Bonuses: multiply by confirmed ratio/face-value factor.
           - Capital raises (QIP, rights, preferential): if status in ('allotted', 'completed') and actual_shares confirmed, add to count. Proposed raises do NOT affect shares.
           - Buybacks / Reductions: if status in ('completed', 'allotted') and actual_shares confirmed, subtract from count. Proposed buybacks do NOT affect shares.
           - Cash dividends: do not change share count.
           - If any action in window cannot be quantified, flag unquantified without fabricating.
        6. Avoid double counting: any filing reported after an event already incorporates that event, so events <= base_reporting_date are never re-applied.
        """
        inst = session.get(Instrument, instrument_id)
        if inst is None:
            return ApplicableShareCountResult(
                instrument_id=instrument_id,
                symbol="UNKNOWN",
                share_count=None,
                base_share_count=None,
                base_reporting_date=None,
                valuation_date=valuation_date,
                actions_applied=[],
                has_unquantified_action=False,
                unquantified_reasons=[],
                is_verified=False,
                data_source=None,
                extraction_method=None,
                is_stale=True,
                status="unavailable",
                explanation="Instrument not found in database.",
            )

        symbol = inst.symbol

        # 1. Base share count from official filing <= valuation_date
        share_stmt = (
            select(InstrumentShareCount, DataSource)
            .outerjoin(DataSource, DataSource.id == InstrumentShareCount.source_id)
            .where(
                InstrumentShareCount.instrument_id == instrument_id,
                InstrumentShareCount.share_class == "EQUITY",
                InstrumentShareCount.is_active == True,
                InstrumentShareCount.reporting_date <= valuation_date,
            )
            .order_by(InstrumentShareCount.reporting_date.desc(), InstrumentShareCount.id.desc())
            .limit(1)
        )
        base_row = session.execute(share_stmt).first()

        if base_row is None:
            return ApplicableShareCountResult(
                instrument_id=instrument_id,
                symbol=symbol,
                share_count=None,
                base_share_count=None,
                base_reporting_date=None,
                valuation_date=valuation_date,
                actions_applied=[],
                has_unquantified_action=False,
                unquantified_reasons=[],
                is_verified=False,
                data_source=None,
                extraction_method=None,
                is_stale=True,
                status="unavailable",
                explanation=f"No official NSE shareholding pattern disclosure found on or before price date {valuation_date}.",
            )

        base_filing, data_source = base_row
        base_count = base_filing.reported_share_count
        base_date = base_filing.reporting_date
        source_name = data_source.name if data_source else "NSE Disclosure"
        extraction_method = base_filing.extraction_method

        if base_count is None or base_count <= 0:
            return ApplicableShareCountResult(
                instrument_id=instrument_id,
                symbol=symbol,
                share_count=None,
                base_share_count=base_count,
                base_reporting_date=base_date,
                valuation_date=valuation_date,
                actions_applied=[],
                has_unquantified_action=True,
                unquantified_reasons=["Reported share count in filing is zero or negative."],
                is_verified=False,
                data_source=source_name,
                extraction_method=extraction_method,
                is_stale=True,
                status="unavailable",
                explanation="Reported share count in official filing is invalid (zero or negative).",
            )

        # 2. Window for corporate actions: strictly (base_date, valuation_date]
        current_shares = Decimal(base_count)
        actions_applied: list[str] = []
        has_unquantified = False
        unquantified_reasons: list[str] = []

        if valuation_date > base_date:
            # Query corporate actions in DB
            date_expr = func.coalesce(
                CorporateAction.effective_date,
                CorporateAction.ex_date,
                CorporateAction.allotment_date,
                CorporateAction.completion_date,
                CorporateAction.record_date,
                CorporateAction.announcement_date,
            )
            actions_stmt = (
                select(CorporateAction)
                .where(
                    CorporateAction.instrument_id == instrument_id,
                    date_expr > base_date,
                    date_expr <= valuation_date,
                )
                .order_by(date_expr.asc(), CorporateAction.id.asc())
            )
            actions_in_window = list(session.scalars(actions_stmt).all())

            # If no actions found in DB, try fetching from provider if available
            if not actions_in_window and hasattr(self.provider, "get_actions"):
                total_in_db = session.scalar(
                    select(func.count(CorporateAction.id)).where(CorporateAction.instrument_id == instrument_id)
                )
                if not total_in_db:
                    try:
                        self.fetch_and_persist_for_symbol(session, symbol)
                        actions_in_window = list(session.scalars(actions_stmt).all())
                    except Exception as exc:
                        logger.warning("Corporate action provider fetch failed for %s: %s", symbol, exc)

            for act in actions_in_window:
                if act.validation_status == "rejected":
                    continue

                act_effective_dt = get_action_effective_date(act) or valuation_date
                etype = (act.event_type or "").lower()
                status = (act.status or "completed").lower()

                if status == "cancelled":
                    actions_applied.append(f"{act.event_type.upper()} on {act_effective_dt} cancelled")
                    continue

                # Splits
                if etype in ("split", "face_value_split", "stock_split"):
                    if act.face_value_from and act.face_value_to and act.face_value_to > 0:
                        split_factor = Decimal(act.face_value_from) / Decimal(act.face_value_to)
                        current_shares = int(current_shares * split_factor)
                        fv_from = f"{float(act.face_value_from):g}"
                        fv_to = f"{float(act.face_value_to):g}"
                        actions_applied.append(
                            f"Split {fv_from}->{fv_to} on {act_effective_dt} (factor {split_factor})"
                        )
                    elif act.ratio_num and act.ratio_den and act.ratio_den > 0:
                        split_factor = Decimal(act.ratio_num) / Decimal(act.ratio_den)
                        current_shares = int(current_shares * split_factor)
                        actions_applied.append(
                            f"Split {act.ratio_num}:{act.ratio_den} on {act_effective_dt} (factor {split_factor})"
                        )
                    else:
                        has_unquantified = True
                        unquantified_reasons.append(
                            f"Split on {act_effective_dt} missing valid ratio or face values"
                        )

                # Bonus issues
                elif etype in ("bonus", "bonus_issue"):
                    if act.ratio_num and act.ratio_den and act.ratio_den > 0:
                        bonus_factor = Decimal(act.ratio_num + act.ratio_den) / Decimal(act.ratio_den)
                        current_shares = int(current_shares * bonus_factor)
                        actions_applied.append(
                            f"Bonus {act.ratio_num}:{act.ratio_den} on {act_effective_dt} (factor {bonus_factor})"
                        )
                    else:
                        has_unquantified = True
                        unquantified_reasons.append(
                            f"Bonus on {act_effective_dt} missing valid ratio"
                        )

                # Capital raises: QIP, rights, preferential allotment, warrant conversion
                elif etype in ("qip", "rights", "rights_issue", "preferential_allotment", "warrant_conversion", "capital_issue"):
                    if status in ("allotted", "completed"):
                        if act.actual_shares is not None and act.actual_shares > 0:
                            current_shares += Decimal(act.actual_shares)
                            actions_applied.append(
                                f"{act.event_type.upper()} allotment of {act.actual_shares:,} shares on {act_effective_dt}"
                            )
                        else:
                            has_unquantified = True
                            unquantified_reasons.append(
                                f"{act.event_type.upper()} completed on {act_effective_dt} but actual_shares is not confirmed"
                            )
                    elif status in ("proposed", "approved", "active", "board_approved", "announced"):
                        # Proposed / announced event does not adjust share count until allotment
                        actions_applied.append(
                            f"{act.event_type.upper()} ({status}) on {act_effective_dt} - not allotted; shares unaffected"
                        )

                # Buybacks / Capital reduction
                elif etype in ("buyback", "capital_reduction", "share_cancellation"):
                    if status in ("completed", "allotted", "extinguished"):
                        if act.actual_shares is not None and act.actual_shares > 0:
                            current_shares = max(Decimal(0), current_shares - Decimal(act.actual_shares))
                            actions_applied.append(
                                f"Buyback extinguishment of {act.actual_shares:,} shares on {act_effective_dt}"
                            )
                        else:
                            has_unquantified = True
                            unquantified_reasons.append(
                                f"Buyback completed on {act_effective_dt} but extinguished share count is missing"
                            )
                    elif status in ("proposed", "approved", "active", "announced", "offer_open"):
                        # Proposed buyback has not extinguished shares yet
                        actions_applied.append(
                            f"Buyback ({status}) on {act_effective_dt} - not extinguished; shares unaffected"
                        )

                # Cash dividends
                elif etype in ("dividend", "interim_dividend", "final_dividend", "special_dividend"):
                    actions_applied.append(
                        f"Dividend ₹{act.cash_amount or 0} on {act_effective_dt} (no share count change)"
                    )

                # Other unrecognized actions
                else:
                    if act.actual_shares and status in ("allotted", "completed"):
                        current_shares += Decimal(act.actual_shares)
                        actions_applied.append(
                            f"Action '{act.event_type}' on {act_effective_dt}: {act.actual_shares:,} shares"
                        )
                    elif act.actual_shares is None and act.ratio_num is None:
                        has_unquantified = True
                        unquantified_reasons.append(
                            f"Unquantified corporate action '{act.event_type}' on {act_effective_dt}"
                        )

        # 3. Check staleness (>120 days)
        days_diff = (valuation_date - base_date).days
        is_stale = bool(days_diff > STALE_SHARE_COUNT_THRESHOLD_DAYS or days_diff < 0)

        if has_unquantified:
            status_str = "stale_unverified" if is_stale else "unverified"
        elif is_stale:
            status_str = "stale"
        else:
            status_str = "fresh"

        notes: list[str] = []
        if actions_applied:
            notes.append(f"Adjusted for corporate actions ({'; '.join(actions_applied)})")
        if unquantified_reasons:
            notes.append(f"Unquantified corporate events flagged: {'; '.join(unquantified_reasons)}")
        if is_stale:
            notes.append(
                f"Share count reporting date ({base_date}) is {days_diff} days prior to price snapshot date ({valuation_date}). Stale indicator flagged."
            )

        explanation = "; ".join(notes) if notes else None
        final_shares = int(current_shares) if current_shares > 0 else None

        return ApplicableShareCountResult(
            instrument_id=instrument_id,
            symbol=symbol,
            share_count=final_shares,
            base_share_count=base_count,
            base_reporting_date=base_date,
            valuation_date=valuation_date,
            actions_applied=actions_applied,
            has_unquantified_action=has_unquantified,
            unquantified_reasons=unquantified_reasons,
            is_verified=not has_unquantified,
            data_source=source_name,
            extraction_method=extraction_method,
            is_stale=is_stale,
            status=status_str,
            explanation=explanation,
        )

    def get_adjustment_factor(
        self,
        symbol: str,
        from_date: date,
        to_date: date,
    ) -> CorporateActionAdjustment:
        """Calculate cumulative share count adjustment factor for events occurring in (from_date, to_date].

        Maintained for backward compatibility.
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
