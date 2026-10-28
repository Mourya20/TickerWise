from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Instrument(Base):
    __tablename__ = "instruments"

    __table_args__ = (
        UniqueConstraint(
            "exchange",
            "symbol",
            "series",
            name="uq_instruments_exchange_symbol_series",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )

    company_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("companies.id", ondelete="RESTRICT"),
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
    )

    series: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default=text("'UNSPECIFIED'"),
    )

    instrument_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default=text("'EQUITY'"),
    )

    isin: Mapped[str | None] = mapped_column(
        String(12),
        nullable=True,
    )

    listing_date: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
    )

    first_seen_date: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
    )

    paid_up_value: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4),
        nullable=True,
    )

    market_lot: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    face_value: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4),
        nullable=True,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("1"),
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
    )

    company: Mapped["Company"] = relationship(
        back_populates="instruments"
    )