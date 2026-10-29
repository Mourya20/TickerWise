"""Automated discovery and onboarding of newly listed NSE equity instruments.

Owns validation of equity candidates, deduplication, company linkage, and idempotent instrument creation.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.company import Company
from app.models.instrument import Instrument
from app.providers.base import NormalizedMarketSnapshot

logger = logging.getLogger(__name__)

# Supported NSE Equity Series policy
# EQ: Normal Rolling Settlement Equity
# BE: Book Entry / Trade-for-Trade Equity
# BZ: Scrip-level surveillance / Z-group Equity
# SM: SME Platform Normal Settlement Equity
# ST: SME Platform Trade-for-Trade Equity
SUPPORTED_EQUITY_SERIES: frozenset[str] = frozenset({"EQ", "BE", "BZ", "SM", "ST"})

# Valid Indian Equity ISIN pattern:
# Starts with INE (Equity) or IN9 (Partly paid equity/rights), followed by 9 alphanumeric chars.
# Rejects INF (Mutual Funds / ETFs) and non-equity patterns.
ISIN_EQUITY_REGEX = re.compile(r"^IN[E9][A-Z0-9]{9}[0-9]$")
ISIN_GENERAL_REGEX = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")
SYMBOL_REGEX = re.compile(r"^[A-Z0-9\-&]{1,64}$")


def normalize_company_name(name: str) -> str:
    """Normalize company name for case-insensitive, whitespace-collapsed matching."""
    return " ".join(name.casefold().split())


@dataclass(frozen=True)
class DiscoverySummary:
    candidates_evaluated: int = 0
    discovered: int = 0
    reused_company: int = 0
    skipped_existing: int = 0
    invalid_identity: int = 0
    unsupported_series: int = 0
    ambiguous_entries: int = 0
    audit_notes: list[str] = field(default_factory=list)


@dataclass
class DiscoveryResult:
    summary: DiscoverySummary
    new_instruments: list[Instrument] = field(default_factory=list)


class InstrumentDiscoveryService:
    """Discovers and onboards newly listed NSE equity instruments from EOD market snapshots."""

    @classmethod
    def is_supported_series(cls, series: str | None) -> bool:
        if not series:
            return False
        return series.strip().upper() in SUPPORTED_EQUITY_SERIES

    @classmethod
    def validate_candidate(
        cls,
        symbol: str | None,
        series: str | None,
        name: str | None,
        isin: str | None,
    ) -> tuple[bool, str | None, str]:
        """Validate candidate identity fields.

        Returns:
            (is_valid, error_reason, category)
            category is one of: "valid", "unsupported_series", "invalid_identity"
        """
        if not symbol or not symbol.strip():
            return False, "Missing or blank symbol", "invalid_identity"

        clean_symbol = symbol.strip().upper()
        if not SYMBOL_REGEX.match(clean_symbol):
            return False, f"Malformed symbol '{clean_symbol}'", "invalid_identity"

        if not series or not series.strip():
            return False, "Missing series", "invalid_identity"

        clean_series = series.strip().upper()
        if clean_series not in SUPPORTED_EQUITY_SERIES:
            return (
                False,
                f"Series '{clean_series}' is not an authorized equity series",
                "unsupported_series",
            )

        if not name or not name.strip():
            return False, "Missing company name", "invalid_identity"

        if isin is not None and isin.strip():
            clean_isin = isin.strip().upper()
            if clean_isin.startswith("INF"):
                return False, f"Non-equity fund ISIN '{clean_isin}'", "unsupported_series"
            if len(clean_isin) != 12:
                return (
                    False,
                    f"ISIN '{clean_isin}' length {len(clean_isin)} != 12",
                    "invalid_identity",
                )
            if not ISIN_GENERAL_REGEX.match(clean_isin):
                return False, f"Malformed ISIN '{clean_isin}'", "invalid_identity"

        return True, None, "valid"

    def discover_and_onboard(
        self,
        session: Session,
        snapshot_rows: Sequence[NormalizedMarketSnapshot],
        snapshot_date: date,
        exchange: str = "NSE",
    ) -> DiscoveryResult:
        """Scan snapshot rows for unknown equity instruments and onboard them idempotently.

        Enforces Workstream 2 constraints:
        1. Only processes authorized NSE equity series (EQ, BE, BZ, SM, ST).
        2. Validates symbol, series, company name and ISIN format.
        3. Reuses existing company by ISIN or normalized company name.
        4. Never modifies existing instrument identity or existing company links.
        5. Sets first_seen_date = snapshot_date, listing_date = None (no invented listing date).
        6. Keeps comprehensive audit counters for all evaluations.
        """
        clean_exchange = exchange.strip().upper()

        # Load existing instruments for this exchange
        existing_instruments = session.scalars(
            select(Instrument).where(Instrument.exchange == clean_exchange)
        ).all()

        instruments_by_key: dict[tuple[str, str, str], Instrument] = {}
        instruments_by_isin: dict[str, list[Instrument]] = {}
        for inst in existing_instruments:
            key = (clean_exchange, inst.symbol.strip().upper(), inst.series.strip().upper())
            instruments_by_key[key] = inst
            if inst.isin:
                instruments_by_isin.setdefault(inst.isin.strip().upper(), []).append(inst)

        # Load existing companies
        existing_companies = session.scalars(select(Company)).all()
        companies_by_norm_name: dict[str, Company] = {}
        companies_by_id: dict[int, Company] = {}
        for comp in existing_companies:
            companies_by_norm_name.setdefault(normalize_company_name(comp.name), comp)
            companies_by_id[int(comp.id)] = comp

        candidates_evaluated = 0
        discovered = 0
        reused_company = 0
        skipped_existing = 0
        invalid_identity = 0
        unsupported_series = 0
        ambiguous_entries = 0
        audit_notes: list[str] = []
        new_instruments: list[Instrument] = []

        for row in snapshot_rows:
            candidates_evaluated += 1

            raw_symbol = row.symbol
            raw_series = row.series
            raw_name = row.name
            raw_isin = row.isin

            clean_symbol = raw_symbol.strip().upper() if raw_symbol else ""
            clean_series = raw_series.strip().upper() if raw_series else ""

            # Check if this instrument is already known
            if clean_symbol and clean_series:
                inst_key = (clean_exchange, clean_symbol, clean_series)
                if inst_key in instruments_by_key:
                    skipped_existing += 1
                    continue

            # Validate the candidate
            is_valid, reason, category = self.validate_candidate(
                raw_symbol, raw_series, raw_name, raw_isin
            )
            if not is_valid:
                if category == "unsupported_series":
                    unsupported_series += 1
                else:
                    invalid_identity += 1
                audit_notes.append(f"Symbol {raw_symbol or '<empty>'}: {reason}")
                continue

            clean_name = raw_name.strip() if raw_name else ""
            clean_isin = raw_isin.strip().upper() if raw_isin else None
            inst_key = (clean_exchange, clean_symbol, clean_series)

            # Re-check key in case duplicate candidate occurs within the same batch
            if inst_key in instruments_by_key:
                skipped_existing += 1
                continue

            # Resolve Company linkage
            target_company: Company | None = None
            is_company_reused = False

            # Strategy 1: Check existing instrument by ISIN
            if clean_isin and clean_isin in instruments_by_isin:
                matching_insts = instruments_by_isin[clean_isin]
                if matching_insts:
                    linked_comp_id = matching_insts[0].company_id
                    target_company = companies_by_id.get(int(linked_comp_id))
                    if target_company is not None:
                        is_company_reused = True
                        logger.info(
                            "Reusing company '%s' (id=%d) for new instrument %s/%s via ISIN %s",
                            target_company.name,
                            target_company.id,
                            clean_symbol,
                            clean_series,
                            clean_isin,
                        )

            # Strategy 2: Check existing company by normalized name
            if target_company is None and clean_name:
                norm_name = normalize_company_name(clean_name)
                target_company = companies_by_norm_name.get(norm_name)
                if target_company is not None:
                    is_company_reused = True
                    logger.info(
                        "Reusing company '%s' (id=%d) for new instrument %s/%s via name match",
                        target_company.name,
                        target_company.id,
                        clean_symbol,
                        clean_series,
                    )

            # Strategy 3: Create new Company record
            if target_company is None:
                target_company = Company(name=clean_name)
                session.add(target_company)
                session.flush()
                companies_by_norm_name[normalize_company_name(clean_name)] = target_company
                companies_by_id[int(target_company.id)] = target_company

            if is_company_reused:
                reused_company += 1

            # Create new Instrument
            new_instrument = Instrument(
                company_id=int(target_company.id),
                exchange=clean_exchange,
                symbol=clean_symbol,
                series=clean_series,
                instrument_type="EQUITY",
                isin=clean_isin,
                listing_date=None,  # Do not invent official listing date
                first_seen_date=snapshot_date,
                is_active=True,
            )
            session.add(new_instrument)
            session.flush()

            # Update cache to maintain idempotency within the batch
            instruments_by_key[inst_key] = new_instrument
            if clean_isin:
                instruments_by_isin.setdefault(clean_isin, []).append(new_instrument)

            new_instruments.append(new_instrument)
            discovered += 1
            audit_notes.append(
                f"Onboarded new instrument {clean_symbol}/{clean_series} "
                f"({clean_name}, company_id={target_company.id}, first_seen={snapshot_date})"
            )

        summary = DiscoverySummary(
            candidates_evaluated=candidates_evaluated,
            discovered=discovered,
            reused_company=reused_company,
            skipped_existing=skipped_existing,
            invalid_identity=invalid_identity,
            unsupported_series=unsupported_series,
            ambiguous_entries=ambiguous_entries,
            audit_notes=audit_notes,
        )

        return DiscoveryResult(summary=summary, new_instruments=new_instruments)


__all__ = [
    "InstrumentDiscoveryService",
    "DiscoveryResult",
    "DiscoverySummary",
    "SUPPORTED_EQUITY_SERIES",
    "ISIN_EQUITY_REGEX",
    "ISIN_GENERAL_REGEX",
    "SYMBOL_REGEX",
    "normalize_company_name",
]
