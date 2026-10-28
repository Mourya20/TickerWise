from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.data_source import DataSource
    from app.models.instrument import Instrument


class CorporateAction(Base):
    """Stores exchange corporate actions and capital events with full audit provenance."""

    __tablename__ = "corporate_actions"
    __table_args__ = (
        UniqueConstraint(
            "dedup_key",
            name="uq_corporate_actions_dedup_key",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )

    instrument_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("instruments.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    exchange: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default=text("'NSE'"),
    )

    symbol: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )

    event_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        index=True,
    )

    dedup_key: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        index=True,
    )

    announcement_date: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
    )

    record_date: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
    )

    ex_date: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
        index=True,
    )

    issue_open_date: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
    )

    issue_close_date: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
    )

    allotment_date: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
    )

    completion_date: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
    )

    effective_date: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
        index=True,
    )

    ratio_num: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    ratio_den: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    face_value_from: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4),
        nullable=True,
    )

    face_value_to: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4),
        nullable=True,
    )

    cash_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4),
        nullable=True,
    )

    proposed_shares: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )

    proposed_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(24, 4),
        nullable=True,
    )

    actual_shares: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )

    actual_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(24, 4),
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default=text("'completed'"),
    )

    source_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("data_sources.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    source_reference: Mapped[str | None] = mapped_column(
        String(512),
        nullable=True,
    )

    retrieved_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
    )

    raw_subject: Mapped[str | None] = mapped_column(
        String(1024),
        nullable=True,
    )

    raw_payload: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    validation_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default=text("'valid'"),
    )

    notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    instrument: Mapped["Instrument"] = relationship()
    source: Mapped["DataSource"] = relationship()
