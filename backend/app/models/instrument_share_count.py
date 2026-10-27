from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.data_source import DataSource
    from app.models.instrument import Instrument


class InstrumentShareCount(Base):
    __tablename__ = "instrument_share_counts"
    __table_args__ = (
        UniqueConstraint(
            "instrument_id",
            "share_class",
            "reporting_date",
            name="uq_instrument_share_counts_inst_class_date",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    instrument_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("instruments.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    symbol: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )
    series: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'EQ'")
    )
    share_class: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'EQUITY'")
    )
    reported_share_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False
    )
    fully_paid_shares: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True
    )
    partly_paid_shares: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True
    )
    underlying_dr_shares: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True
    )
    source_capital_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(24, 4), nullable=True
    )
    face_value: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4), nullable=True
    )
    reporting_date: Mapped[date] = mapped_column(
        Date, nullable=False, index=True
    )
    filing_date: Mapped[date | None] = mapped_column(
        Date, nullable=True
    )
    retrieved_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
    )
    source_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("data_sources.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    filing_url: Mapped[str | None] = mapped_column(
        String(1024), nullable=True
    )
    extraction_method: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'directly_reported'")
    )
    validation_status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'valid'")
    )
    corporate_action_adjusted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("0")
    )
    corporate_action_details: Mapped[str | None] = mapped_column(
        String(512), nullable=True
    )
    file_checksum: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("1")
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
