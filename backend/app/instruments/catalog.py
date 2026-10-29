"""Instrument catalog and identity management.

Owns company entity resolution, canonical security resolution, and symbol/series validation.
"""
from __future__ import annotations

import logging
import re
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.company import Company
from app.models.instrument import Instrument

logger = logging.getLogger(__name__)

# Valid Indian Equity ISIN pattern:
# Starts with INE (Equity) or IN9 (Partly paid equity/rights), followed by 8 alphanumeric chars and 1 check digit (total 12).
ISIN_EQUITY_REGEX = re.compile(r"^IN[E9][A-Z0-9]{8}[0-9]$")
SYMBOL_REGEX = re.compile(r"^[A-Z0-9\-&]{1,64}$")
SUPPORTED_EQUITY_SERIES: frozenset[str] = frozenset({"EQ", "BE", "BZ", "SM", "ST"})


def normalize_company_name(name: str) -> str:
    """Normalize company name for case-insensitive, whitespace-collapsed matching."""
    return " ".join(name.casefold().split())


def validate_equity_isin(isin: str | None) -> bool:
    """Return True if ISIN matches valid Indian equity structure (INE... or IN9...)."""
    if not isin:
        return False
    return bool(ISIN_EQUITY_REGEX.match(isin.strip().upper()))


def resolve_or_create_company(
    session: Session,
    name: str,
    companies_by_name: dict[str, Company] | None = None,
) -> Company:
    """Find existing company by normalized name or create a new one."""
    clean_name = " ".join(name.split())
    norm_key = normalize_company_name(clean_name)

    if companies_by_name is not None and norm_key in companies_by_name:
        return companies_by_name[norm_key]

    from sqlalchemy import func
    existing = session.scalar(
        select(Company).where(func.lower(Company.name) == clean_name.lower())
    )
    if existing is not None:
        if companies_by_name is not None:
            companies_by_name[norm_key] = existing
        return existing

    company = Company(name=clean_name)
    session.add(company)
    session.flush()

    if companies_by_name is not None:
        companies_by_name[norm_key] = company
    return company
