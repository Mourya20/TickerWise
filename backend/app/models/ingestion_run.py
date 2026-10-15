from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.data_source import DataSource


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    source_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("data_sources.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    dataset_name: Mapped[str] = mapped_column(
        String(100), nullable=False
    )
    trading_date: Mapped[date | None] = mapped_column(
        Date, nullable=True, index=True
    )
    source_status: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'running'")
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    records_read: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )

    records_inserted: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    records_updated: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    records_skipped: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    records_failed: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    records_unmatched: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    error_summary: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )

    source: Mapped["DataSource"] = relationship()