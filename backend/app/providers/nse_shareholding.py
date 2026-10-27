from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.models import DataSource, Instrument, InstrumentShareCount
from app.providers.base import NormalizedCorporateAction
from app.providers.tejhq import TejHQProvider
from app.services.corporate_action_service import CorporateActionService

logger = logging.getLogger(__name__)

NSE_SOURCE_NAME = "NSE Shareholding Pattern Disclosure"
NSE_SOURCE_TYPE = "filing"
NSE_SOURCE_URL = "https://www.nseindia.com/companies-listing/corporate-filings-shareholding-pattern"
NSE_TERMS_URL = "https://www.nseindia.com/static/nse-terms-of-use"


@dataclass(frozen=True)
class ParsedShareCount:
    symbol: str
    series: str
    share_class: str
    reported_share_count: int
    fully_paid_shares: int | None
    partly_paid_shares: int | None
    underlying_dr_shares: int | None
    source_capital_amount: Decimal | None
    face_value: Decimal | None
    reporting_date: date
    filing_date: date | None
    extraction_method: str  # "directly_reported" or "derived"
    source_reference: str | None
    file_checksum: str | None
    validation_status: str = "valid"
    notes: str | None = None


class NSEPermissionStatus:
    """Documents NSE terms-of-use and automated collection feasibility."""

    TERMS_SUMMARY = (
        "NSE Terms of Use (https://www.nseindia.com/static/nse-terms-of-use) explicitly state: "
        "'User is prohibited to conduct any systematic or automated data collection activities "
        "(including scraping, data mining, data extraction and data harvesting) on or in relation "
        "to our Website / Mobile Application.' Additionally, automated requests are intercepted by "
        "Akamai Bot Manager. Automated bulk scraping is blocked and legally restricted without prior written consent."
    )

    @classmethod
    def is_automated_scraping_permitted(cls) -> bool:
        # Strict enforcement: automated scraping from nseindia.com is not authorized
        return False

    @classmethod
    def get_status_report(cls) -> dict[str, Any]:
        return {
            "automated_scraping_permitted": cls.is_automated_scraping_permitted(),
            "authorized_modes": ["authorized_downloaded_filing", "offline_xbrl_archive", "manual_upload"],
            "legal_limitation": cls.TERMS_SUMMARY,
            "technical_restriction": "Akamai WAF bot challenge protection",
        }


class NSEShareholdingParser:
    """Parser for official NSE Shareholding Pattern Disclosures (XBRL/XML, JSON, CSV)."""

    @staticmethod
    def _clean_tag(tag: str) -> str:
        """Strip XML namespace."""
        return re.sub(r"\{.*\}", "", tag)

    @staticmethod
    def _parse_date(date_str: str | None) -> date | None:
        if not date_str:
            return None
        clean = str(date_str).strip()
        for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d-%m-%Y", "%d/%m/%Y", "%Y%m%d"):
            try:
                return datetime.strptime(clean, fmt).date()
            except ValueError:
                continue
        return None

    @classmethod
    def parse_xbrl(cls, content: str, source_ref: str | None = None) -> list[ParsedShareCount]:
        """Parse SEBI LODR Regulation 31 XBRL XML shareholding disclosure.

        Explicitly processes XBRL contexts, dimensions, units and scale attributes
        without heuristic magnitude guessing.
        """
        checksum = hashlib.sha256(content.encode("utf-8")).hexdigest()
        root = ET.fromstring(content)

        # 1. Parse XBRL contexts to identify non-segmented (overall entity) instant contexts
        # Segmented contexts represent sub-categories (Promoter, Public, etc.)
        entity_contexts: set[str] = set()
        context_dates: dict[str, date] = {}

        for elem in root.iter():
            clean_tag = cls._clean_tag(elem.tag).lower()
            if clean_tag == "context":
                context_id = elem.attrib.get("id") or elem.attrib.get("Id") or ""
                # Check if it has segments / dimensions
                has_segment = any("segment" in cls._clean_tag(c.tag).lower() for c in elem.iter())
                if not has_segment:
                    entity_contexts.add(context_id)
                # Check instant date
                for child in elem.iter():
                    if cls._clean_tag(child.tag).lower() == "instant" and child.text:
                        parsed_d = cls._parse_date(child.text)
                        if parsed_d:
                            context_dates[context_id] = parsed_d

        # 2. Extract facts prioritizing non-segmented (entity-level) contexts
        facts_by_tag: dict[str, list[tuple[str, dict[str, str]]]] = {}
        for elem in root.iter():
            clean_tag = cls._clean_tag(elem.tag).lower()
            text = (elem.text or "").strip()
            if text:
                facts_by_tag.setdefault(clean_tag, []).append((text, elem.attrib))

        def get_fact_value(tags: tuple[str, ...], is_numeric: bool = False) -> tuple[Any | None, dict[str, str]]:
            for tag in tags:
                if tag in facts_by_tag:
                    candidates = facts_by_tag[tag]
                    # If entity_contexts were identified, check them first
                    if entity_contexts:
                        for text, attrs in candidates:
                            ctx = attrs.get("contextRef") or attrs.get("contextref")
                            if ctx and ctx in entity_contexts:
                                if is_numeric:
                                    try:
                                        return Decimal(text), attrs
                                    except (InvalidOperation, ValueError):
                                        continue
                                return text, attrs
                    # Fallback to candidate facts
                    for text, attrs in candidates:
                        if is_numeric:
                            try:
                                return Decimal(text), attrs
                            except (InvalidOperation, ValueError):
                                continue
                        return text, attrs
            return None, {}

        def parse_scaled_number(tags: tuple[str, ...]) -> tuple[Decimal | None, dict[str, str]]:
            val, attrs = get_fact_value(tags, is_numeric=True)
            if val is None or not isinstance(val, Decimal):
                return None, attrs
            scale_attr = attrs.get("scale")
            if scale_attr:
                try:
                    val = val * (Decimal(10) ** int(scale_attr))
                except Exception:
                    pass
            unit_ref = (attrs.get("unitRef") or attrs.get("unitref") or "").lower()
            if "crore" in unit_ref:
                val = val * Decimal("10000000")
            elif "lakh" in unit_ref:
                val = val * Decimal("100000")
            return val, attrs

        # Symbol / Scrip Code
        symbol_val, _ = get_fact_value(("symbol", "scripcode", "nsesymbol", "nse_symbol", "companysymbol"))
        symbol = str(symbol_val).upper().strip() if symbol_val else None

        if not symbol:
            # Check attribute or specific tags
            for elem in root.iter():
                clean_tag = cls._clean_tag(elem.tag).lower()
                if "symbol" in clean_tag and elem.text:
                    symbol = elem.text.strip().upper()
                    break

        if not symbol:
            raise ValueError("Could not extract stock symbol from XBRL disclosure.")

        # Reporting date (Quarter ended)
        reporting_date = None
        date_val, _ = get_fact_value(("quarterended", "reportingdate", "asondate", "dateofreport", "periodended"))
        if date_val:
            reporting_date = cls._parse_date(str(date_val))

        if not reporting_date and entity_contexts:
            for ctx_id in entity_contexts:
                if ctx_id in context_dates:
                    reporting_date = context_dates[ctx_id]
                    break

        if not reporting_date:
            raise ValueError(f"Could not extract reporting date from XBRL disclosure for symbol {symbol}.")

        # Filing date
        filing_date = None
        fdate_val, _ = get_fact_value(("dateoffiling", "filingdate", "submissiondate"))
        if fdate_val:
            filing_date = cls._parse_date(str(fdate_val))

        # Share counts
        total_shares_dec, _ = parse_scaled_number((
            "totalnumberofshares",
            "totalnoofsharesheld",
            "totalsharesheld",
            "shareholdingstatementtotalshares",
            "totalnumberofequityshares",
            "numberofequityshares",
        ))
        direct_total_shares = int(total_shares_dec) if total_shares_dec is not None else None

        fully_paid_dec, _ = parse_scaled_number((
            "nooffullypaidupequitysharesheld",
            "numberoffullypaidupequityshares",
            "fullypaidupcapitalshares",
            "fullypaidshares",
        ))
        fully_paid = int(fully_paid_dec) if fully_paid_dec is not None else None

        partly_paid_dec, _ = parse_scaled_number((
            "noofpartlypaidupequitysharesheld",
            "numberofpartlypaidupshares",
            "partlypaidshares",
        ))
        partly_paid = int(partly_paid_dec) if partly_paid_dec is not None else None

        dr_shares_dec, _ = parse_scaled_number((
            "noofsharesunderlyingdepositoryreceipts",
            "sharesunderlyingdr",
            "sharesunderlyingdepositoryreceipts",
        ))
        dr_shares = int(dr_shares_dec) if dr_shares_dec is not None else None

        # Paid-up capital and face value
        paid_up_capital, _ = parse_scaled_number((
            "paidupequitysharecapital",
            "paidupcapital",
            "paidupcapitalamount",
            "totalequitycapital",
        ))
        face_value, _ = parse_scaled_number((
            "facevalue",
            "facevaluepershare",
            "nominalvalue",
        ))

        # Extraction method & final share count
        final_count: int | None = None
        extraction_method = "directly_reported"

        if direct_total_shares and direct_total_shares > 0:
            final_count = direct_total_shares
            extraction_method = "directly_reported"
        elif fully_paid and fully_paid > 0:
            final_count = fully_paid + (partly_paid or 0)
            extraction_method = "directly_reported"
        elif paid_up_capital is not None and face_value is not None and face_value > 0:
            shares_derived = paid_up_capital / face_value
            final_count = int(shares_derived)
            extraction_method = "derived"

        if not final_count or final_count <= 0:
            raise ValueError(f"Failed to extract valid equity share count for symbol {symbol}.")

        return [
            ParsedShareCount(
                symbol=symbol,
                series="EQ",
                share_class="EQUITY",
                reported_share_count=final_count,
                fully_paid_shares=fully_paid,
                partly_paid_shares=partly_paid,
                underlying_dr_shares=dr_shares,
                source_capital_amount=paid_up_capital,
                face_value=face_value,
                reporting_date=reporting_date,
                filing_date=filing_date,
                extraction_method=extraction_method,
                source_reference=source_ref or "NSE_XBRL_Filing",
                file_checksum=checksum,
                validation_status="valid",
            )
        ]

    @classmethod
    def parse_json(cls, content: str, source_ref: str | None = None) -> list[ParsedShareCount]:
        """Parse structured JSON shareholding pattern disclosure."""
        checksum = hashlib.sha256(content.encode("utf-8")).hexdigest()
        data = json.loads(content)
        records = data if isinstance(data, list) else [data]

        results: list[ParsedShareCount] = []
        for r in records:
            symbol = str(r.get("symbol") or r.get("SYMBOL") or "").strip().upper()
            if not symbol:
                continue

            reporting_date = cls._parse_date(
                r.get("reporting_date") or r.get("quarter_ended") or r.get("as_of_date")
            )
            if not reporting_date:
                continue

            filing_date = cls._parse_date(r.get("filing_date") or r.get("submission_date"))

            total_shares = None
            for key in ("total_shares", "reported_share_count", "TOTAL_SHARES", "total_equity_shares"):
                if key in r and r[key] is not None:
                    try:
                        total_shares = int(Decimal(str(r[key])))
                        break
                    except (ValueError, InvalidOperation):
                        continue

            fully_paid = None
            if "fully_paid_shares" in r and r["fully_paid_shares"] is not None:
                try:
                    fully_paid = int(Decimal(str(r["fully_paid_shares"])))
                except (ValueError, InvalidOperation):
                    pass

            partly_paid = None
            if "partly_paid_shares" in r and r["partly_paid_shares"] is not None:
                try:
                    partly_paid = int(Decimal(str(r["partly_paid_shares"])))
                except (ValueError, InvalidOperation):
                    pass

            dr_shares = None
            if "underlying_dr_shares" in r and r["underlying_dr_shares"] is not None:
                try:
                    dr_shares = int(Decimal(str(r["underlying_dr_shares"])))
                except (ValueError, InvalidOperation):
                    pass

            paid_up_capital = None
            for key in ("paid_up_capital", "source_capital_amount", "PAID_UP_CAPITAL"):
                if key in r and r[key] is not None:
                    try:
                        paid_up_capital = Decimal(str(r[key]))
                        break
                    except (ValueError, InvalidOperation):
                        pass

            face_value = None
            for key in ("face_value", "FACE_VALUE"):
                if key in r and r[key] is not None:
                    try:
                        face_value = Decimal(str(r[key]))
                        break
                    except (ValueError, InvalidOperation):
                        pass

            extraction_method = "directly_reported"
            if not total_shares or total_shares <= 0:
                if paid_up_capital and face_value and face_value > 0:
                    if paid_up_capital < Decimal("100000"):
                        total_shares = int((paid_up_capital * Decimal("10000000")) / face_value)
                    else:
                        total_shares = int(paid_up_capital / face_value)
                    extraction_method = "derived"

            if not total_shares or total_shares <= 0:
                continue

            results.append(
                ParsedShareCount(
                    symbol=symbol,
                    series=str(r.get("series", "EQ")).strip().upper(),
                    share_class=str(r.get("share_class", "EQUITY")).strip().upper(),
                    reported_share_count=total_shares,
                    fully_paid_shares=fully_paid,
                    partly_paid_shares=partly_paid,
                    underlying_dr_shares=dr_shares,
                    source_capital_amount=paid_up_capital,
                    face_value=face_value,
                    reporting_date=reporting_date,
                    filing_date=filing_date,
                    extraction_method=extraction_method,
                    source_reference=source_ref or r.get("source_reference", "NSE_JSON_Disclosure"),
                    file_checksum=checksum,
                    validation_status="valid",
                )
            )

        return results

    @classmethod
    def parse_csv(cls, content: str, source_ref: str | None = None) -> list[ParsedShareCount]:
        """Parse CSV format shareholding summary disclosure."""
        checksum = hashlib.sha256(content.encode("utf-8")).hexdigest()
        reader = csv.DictReader(io.StringIO(content))
        results: list[ParsedShareCount] = []

        for row in reader:
            clean_row = {k.strip().upper(): v.strip() for k, v in row.items() if k and v}
            symbol = clean_row.get("SYMBOL") or clean_row.get("SCRIP_CODE")
            if not symbol:
                continue

            reporting_date = cls._parse_date(
                clean_row.get("REPORTING_DATE") or clean_row.get("QUARTER_ENDED") or clean_row.get("AS_OF_DATE")
            )
            if not reporting_date:
                continue

            filing_date = cls._parse_date(clean_row.get("FILING_DATE") or clean_row.get("SUBMISSION_DATE"))

            total_shares_val = clean_row.get("TOTAL_SHARES") or clean_row.get("REPORTED_SHARES")
            paid_up_cap_val = clean_row.get("PAID_UP_CAPITAL") or clean_row.get("PAID_UP_VALUE")
            face_val = clean_row.get("FACE_VALUE")

            total_shares = None
            if total_shares_val:
                try:
                    total_shares = int(Decimal(total_shares_val))
                except (ValueError, InvalidOperation):
                    pass

            paid_up_capital = None
            if paid_up_cap_val:
                try:
                    paid_up_capital = Decimal(paid_up_cap_val)
                except (ValueError, InvalidOperation):
                    pass

            face_value = None
            if face_val:
                try:
                    face_value = Decimal(face_val)
                except (ValueError, InvalidOperation):
                    pass

            extraction_method = "directly_reported"
            if not total_shares or total_shares <= 0:
                if paid_up_capital and face_value and face_value > 0:
                    if paid_up_capital < Decimal("100000"):
                        total_shares = int((paid_up_capital * Decimal("10000000")) / face_value)
                    else:
                        total_shares = int(paid_up_capital / face_value)
                    extraction_method = "derived"

            if not total_shares or total_shares <= 0:
                continue

            results.append(
                ParsedShareCount(
                    symbol=symbol.strip().upper(),
                    series=clean_row.get("SERIES", "EQ").strip().upper(),
                    share_class=clean_row.get("SHARE_CLASS", "EQUITY").strip().upper(),
                    reported_share_count=total_shares,
                    fully_paid_shares=None,
                    partly_paid_shares=None,
                    underlying_dr_shares=None,
                    source_capital_amount=paid_up_capital,
                    face_value=face_value,
                    reporting_date=reporting_date,
                    filing_date=filing_date,
                    extraction_method=extraction_method,
                    source_reference=source_ref or "NSE_CSV_Disclosure",
                    file_checksum=checksum,
                    validation_status="valid",
                )
            )

        return results


class NSEShareholdingIngestionService:
    """Service to ingest parsed shareholding disclosures with corporate-action awareness."""

    def __init__(
        self,
        session_factory=SessionLocal,
        tejhq_provider: TejHQProvider | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.tejhq = tejhq_provider or TejHQProvider()

    def get_or_create_source(self, session: Session) -> DataSource:
        source = session.scalar(select(DataSource).where(DataSource.name == NSE_SOURCE_NAME))
        if source is None:
            source = DataSource(
                name=NSE_SOURCE_NAME,
                source_type=NSE_SOURCE_TYPE,
                source_url=NSE_SOURCE_URL,
                terms_url=NSE_TERMS_URL,
                is_active=True,
            )
            session.add(source)
            session.flush()
        return source

    def check_corporate_actions(
        self, symbol: str, after_date: date
    ) -> tuple[bool, str | None, Decimal]:
        """Check if stock split or bonus issue occurred after the shareholding reporting date.

        Returns (has_split_or_bonus, details, adjustment_factor).
        """
        ca_svc = CorporateActionService(provider=self.tejhq)
        adj = ca_svc.get_adjustment_factor(symbol, after_date, date.max)
        if adj.factor != Decimal("1.0"):
            return True, "; ".join(adj.details), adj.factor
        return False, None, Decimal("1.0")

    def ingest_records(
        self,
        records: list[ParsedShareCount],
        adjust_for_corporate_actions: bool = True,
    ) -> dict[str, Any]:
        """Persist parsed shareholding pattern records with corporate-action awareness.

        Idempotent:
        - If (instrument_id, share_class, reporting_date) does not exist: inserts.
        - If exists: updates if values or filing status differ; skips if identical.
        - Prior history is preserved.
        """
        inserted = 0
        updated = 0
        skipped = 0
        failed = 0
        unmatched = 0

        with self.session_factory() as session:
            source = self.get_or_create_source(session)
            source_id = int(source.id)

            for rec in records:
                # Match instrument in master
                instrument = session.scalar(
                    select(Instrument).where(
                        Instrument.symbol == rec.symbol,
                        Instrument.exchange == "NSE",
                    )
                )
                if instrument is None:
                    unmatched += 1
                    logger.warning("Unmatched instrument for share count: symbol=%s", rec.symbol)
                    continue

                inst_id = int(instrument.id)

                # Corporate actions check: record metadata without mutating reported_share_count
                corp_adjusted = False
                corp_details = None

                if adjust_for_corporate_actions:
                    has_ca, ca_details, ca_factor = self.check_corporate_actions(
                        rec.symbol, rec.reporting_date
                    )
                    if has_ca:
                        corp_adjusted = True
                        corp_details = f"Subsequent corporate actions noted ({ca_details}, factor {ca_factor})"

                # Raw reported share count remains authentic and immutable
                effective_share_count = rec.reported_share_count

                # Check existing record for same (instrument_id, share_class, reporting_date)
                existing = session.scalar(
                    select(InstrumentShareCount).where(
                        InstrumentShareCount.instrument_id == inst_id,
                        InstrumentShareCount.share_class == rec.share_class,
                        InstrumentShareCount.reporting_date == rec.reporting_date,
                    )
                )

                if existing is None:
                    new_record = InstrumentShareCount(
                        instrument_id=inst_id,
                        symbol=rec.symbol,
                        series=rec.series or instrument.series,
                        share_class=rec.share_class,
                        reported_share_count=effective_share_count,
                        fully_paid_shares=rec.fully_paid_shares,
                        partly_paid_shares=rec.partly_paid_shares,
                        underlying_dr_shares=rec.underlying_dr_shares,
                        source_capital_amount=rec.source_capital_amount,
                        face_value=rec.face_value or instrument.face_value,
                        reporting_date=rec.reporting_date,
                        filing_date=rec.filing_date,
                        retrieved_at=datetime.now(timezone.utc).replace(tzinfo=None),
                        source_id=source_id,
                        filing_url=rec.source_reference,
                        extraction_method=rec.extraction_method,
                        validation_status=rec.validation_status,
                        corporate_action_adjusted=corp_adjusted,
                        corporate_action_details=corp_details,
                        file_checksum=rec.file_checksum,
                        is_active=True,
                    )
                    session.add(new_record)
                    inserted += 1
                else:
                    # Check if changed
                    is_changed = (
                        existing.reported_share_count != effective_share_count
                        or existing.corporate_action_adjusted != corp_adjusted
                        or existing.file_checksum != rec.file_checksum
                        or existing.filing_date != rec.filing_date
                    )
                    if is_changed:
                        existing.reported_share_count = effective_share_count
                        existing.fully_paid_shares = rec.fully_paid_shares
                        existing.partly_paid_shares = rec.partly_paid_shares
                        existing.underlying_dr_shares = rec.underlying_dr_shares
                        existing.source_capital_amount = rec.source_capital_amount
                        existing.face_value = rec.face_value or instrument.face_value
                        existing.filing_date = rec.filing_date
                        existing.corporate_action_adjusted = corp_adjusted
                        existing.corporate_action_details = corp_details
                        existing.file_checksum = rec.file_checksum
                        existing.extraction_method = rec.extraction_method
                        existing.validation_status = rec.validation_status
                        existing.retrieved_at = datetime.now(timezone.utc).replace(tzinfo=None)
                        updated += 1
                    else:
                        skipped += 1

            session.commit()

        return {
            "total_read": len(records),
            "inserted": inserted,
            "updated": updated,
            "skipped": skipped,
            "failed": failed,
            "unmatched": unmatched,
        }
