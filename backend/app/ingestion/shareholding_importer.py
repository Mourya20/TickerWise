"""Shareholding pattern disclosure ingestion workflow.

Coordinates parsing of SEBI LODR Regulation 31 XBRL/JSON/CSV filings,
deduplication, point-in-time share capital resolution, and database persistence.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.corporate_actions.service import CorporateActionService
from app.db.session import SessionLocal
from app.models import DataSource, Instrument, InstrumentShareCount
from app.providers.nse_shareholding import (
    NSE_SOURCE_NAME,
    NSE_SOURCE_TYPE,
    NSE_SOURCE_URL,
    NSE_TERMS_URL,
    NSEPermissionStatus,
    NSEShareholdingParser,
    ParsedShareCount,
)
from app.providers.tejhq import TejHQProvider

logger = logging.getLogger(__name__)


class NSEShareholdingIngestionService:
    """Service to ingest parsed shareholding disclosures with corporate-action awareness.
    
    Owns database persistence, source management, instrument resolution, and deduplication
    for equity shareholding pattern records.
    """

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


__all__ = [
    "NSEShareholdingIngestionService",
    "NSEShareholdingParser",
    "NSEPermissionStatus",
    "ParsedShareCount",
]
