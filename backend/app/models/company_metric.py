from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
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
    from app.models.company import Company
    from app.models.data_source import DataSource
    from app.models.instrument import Instrument


class CompanyMetric(Base):
    __tablename__ = "company_metrics"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "metric_name",
            "as_of_date",
            "source_id",
            name="uq_company_metrics_comp_metric_date_source",
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
    instrument_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("instruments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("data_sources.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    metric_name: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )
    numeric_value: Mapped[Decimal | None] = mapped_column(
        Numeric(24, 6), nullable=True
    )
    text_value: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    metric_unit: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )
    as_of_date: Mapped[date] = mapped_column(
        Date, nullable=False, index=True
    )
    retrieved_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
    )
    validation_status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'valid'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
    )

    company: Mapped["Company"] = relationship()
    instrument: Mapped["Instrument | None"] = relationship()
    source: Mapped["DataSource"] = relationship()
