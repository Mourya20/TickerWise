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
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.data_source import DataSource
    from app.models.instrument import Instrument


class DailyMarketSnapshot(Base):
    __tablename__ = "daily_market_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "instrument_id",
            "snapshot_date",
            name="uq_daily_market_snapshots_instrument_date",
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
    source_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("data_sources.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    snapshot_date: Mapped[date] = mapped_column(
        Date, nullable=False, index=True
    )
    open_price: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 6), nullable=True
    )
    high_price: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 6), nullable=True
    )
    low_price: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 6), nullable=True
    )
    close_price: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 6), nullable=True
    )
    last_traded_price: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 6), nullable=True
    )
    prev_close_price: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 6), nullable=True
    )
    percentage_change_pct: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 6), nullable=True
    )
    is_calculated_change: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("0")
    )
    market_capitalization_crores: Mapped[Decimal | None] = mapped_column(
        Numeric(24, 6), nullable=True
    )
    volume_lakhs: Mapped[Decimal | None] = mapped_column(
        Numeric(24, 6), nullable=True
    )
    traded_value_crores: Mapped[Decimal | None] = mapped_column(
        Numeric(24, 6), nullable=True
    )
    volume: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True
    )
    turnover: Mapped[Decimal | None] = mapped_column(
        Numeric(24, 4), nullable=True
    )
    trade_count: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
    )

    instrument: Mapped["Instrument"] = relationship()
    source: Mapped["DataSource"] = relationship()

