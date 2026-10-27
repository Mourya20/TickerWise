from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class InstrumentSearchResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    instrument_id: int
    company_name: str
    exchange: str
    symbol: str
    series: str
    isin: str | None
    is_active: bool


class MarketSnapshotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    snapshot_date: date
    ltp: Decimal | None = None
    close: Decimal | None = None
    open: Decimal | None = None
    high: Decimal | None = None
    low: Decimal | None = None
    prev_close: Decimal | None = None
    percentage_change_pct: Decimal | None = None
    is_calculated_change: bool = False
    market_capitalization_crores: Decimal | None = None
    market_cap_price_basis: str | None = "LTP"
    market_cap_price_date: date | None = None
    share_count: int | None = None
    share_count_date: date | None = None
    share_count_source: str | None = None
    share_count_method: str | None = None
    share_count_status: str | None = None
    market_cap_explanation: str | None = None
    volume_lakhs: Decimal | None = None
    traded_value_crores: Decimal | None = None
    volume: int | None = None
    turnover: Decimal | None = None
    trade_count: int | None = None
    source_name: str | None = None
    last_ingested_at: datetime | None = None
    is_stale: bool = False
    freshness_status: str = "fresh"


class PriceBarResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    trading_date: date
    open: Decimal | None = None
    high: Decimal | None = None
    low: Decimal | None = None
    close: Decimal | None = None
    ltp: Decimal | None = None
    prev_close: Decimal | None = None
    volume: int | None = None
    volume_lakhs: Decimal | None = None
    turnover: Decimal | None = None
    traded_value_crores: Decimal | None = None
    percentage_change_pct: Decimal | None = None
    trade_count: int | None = None
    source_name: str | None = None


class ShareCountHistoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    instrument_id: int
    symbol: str
    series: str
    share_class: str
    reported_share_count: int
    fully_paid_shares: int | None = None
    partly_paid_shares: int | None = None
    source_capital_amount: Decimal | None = None
    face_value: Decimal | None = None
    reporting_date: date
    filing_date: date | None = None
    retrieved_at: datetime
    source_name: str | None = None
    extraction_method: str
    validation_status: str
    corporate_action_adjusted: bool = False
    corporate_action_details: str | None = None


class InstrumentDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    instrument_id: int
    company_id: int
    company_name: str
    exchange: str
    symbol: str
    series: str
    instrument_type: str
    isin: str | None
    listing_date: date | None
    paid_up_value: Decimal | None
    market_lot: int | None
    face_value: Decimal | None
    is_active: bool
    snapshot: MarketSnapshotResponse | None
