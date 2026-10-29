from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal


class ProviderError(Exception):
    """Base exception for all market data provider errors."""


class ProviderNetworkError(ProviderError):
    """Network connection, timeout or DNS error occurred while reaching provider."""


class ProviderResponseError(ProviderError):
    """Provider returned an unexpected HTTP error or invalid payload structure."""


class ProviderPermissionError(ProviderError):
    """Provider access or automated collection is prohibited / unauthorized."""


class ProviderConfigurationError(ProviderError):
    """Provider is misconfigured or required endpoint URL is missing."""


class ProviderDataValidationError(ProviderError):
    """Provider payload contains data that failed numeric/unit validation."""


@dataclass(frozen=True)
class NormalizedMarketSnapshot:
    """Canonical provider-independent representation of an EOD market snapshot row."""

    symbol: str
    series: str | None
    isin: str | None
    name: str | None
    exchange: str
    snapshot_date: date
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal | None
    last_price: Decimal | None
    prev_close: Decimal | None
    volume: int | None
    turnover: Decimal | None
    trades: int | None
    percentage_change_pct: Decimal | None
    is_calculated_change: bool
    provider_name: str
    retrieved_at: datetime


@dataclass(frozen=True)
class NormalizedOHLCV:
    """Canonical provider-independent representation of historical OHLCV row."""

    symbol: str
    exchange: str
    date: date
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal | None
    last_price: Decimal | None
    prev_close: Decimal | None
    volume: int | None
    turnover: Decimal | None
    trades: int | None


@dataclass(frozen=True)
class NormalizedCompanyMetric:
    """Canonical representation of a supplementary company or instrument metric."""

    symbol: str
    exchange: str
    metric_name: str
    numeric_value: Decimal | None
    text_value: str | None
    metric_unit: str | None
    as_of_date: date
    provider_name: str
    retrieved_at: datetime
    validation_status: str = "valid"


@dataclass(frozen=True)
class NormalizedQuote:
    """Canonical representation of a quote from a supplementary market provider."""

    symbol: str
    exchange: str
    price: Decimal | None
    percentage_change_pct: Decimal | None
    volume: int | None
    market_cap: Decimal | None
    pe_ratio: Decimal | None
    dividend_yield: Decimal | None
    sector: str | None
    as_of_date: date
    provider_name: str
    retrieved_at: datetime


@dataclass(frozen=True)
class ProviderStatus:
    """Provider health and pipeline status information."""

    provider_name: str
    trading_date: date | None
    stage: str | None
    prices_published_at: datetime | None
    derived_published_at: datetime | None
    is_fresh: bool
    run_url: str | None = None
    raw_metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class NormalizedCorporateAction:
    """Canonical representation of an exchange corporate action (split, bonus, dividend, etc.)."""

    symbol: str
    exchange: str
    isin: str | None
    company_name: str | None
    ex_date: date
    record_date: date | None
    action_type: str  # dividend, split, bonus, rights, etc.
    ratio_num: int | None = None
    ratio_den: int | None = None
    cash_amount: Decimal | None = None
    face_value_from: Decimal | None = None
    face_value_to: Decimal | None = None
    raw_subject: str | None = None


class IEODSnapshotProvider(ABC):
    """Capability interface for End-of-Day (EOD) market snapshot providers."""

    @abstractmethod
    def get_status(self) -> ProviderStatus:
        """Fetch provider operational status and latest published trading session."""
        raise NotImplementedError

    @abstractmethod
    def get_daily_snapshot(
        self, snapshot_date: date, exchange: str = "NSE"
    ) -> list[NormalizedMarketSnapshot]:
        """Fetch complete market snapshot for a specified trading date."""
        raise NotImplementedError


class IHistoricalOHLCVProvider(ABC):
    """Capability interface for historical daily OHLCV price providers."""

    @abstractmethod
    def get_historical_ohlcv(
        self, symbol: str, from_date: date, to_date: date, exchange: str = "NSE"
    ) -> list[NormalizedOHLCV]:
        """Fetch historical daily OHLCV rows for a single symbol over a date range."""
        raise NotImplementedError


class ICorporateActionsProvider(ABC):
    """Capability interface for corporate actions (splits, bonuses, dividends)."""

    @abstractmethod
    def get_actions(self, symbol: str) -> list[NormalizedCorporateAction]:
        """Fetch corporate actions for a single symbol."""
        raise NotImplementedError


class IInstrumentMasterProvider(ABC):
    """Capability interface for instrument and company master discovery providers."""

    @abstractmethod
    def get_instrument_master(
        self, exchange: str = "NSE"
    ) -> list[NormalizedMarketSnapshot]:
        """Fetch security definitions and master metadata."""
        raise NotImplementedError


class IFundamentalDisclosuresProvider(ABC):
    """Capability interface for fundamental disclosures (e.g. SEBI shareholding patterns)."""

    @abstractmethod
    def get_disclosures(
        self, symbol: str
    ) -> list[object]:
        """Fetch official fundamental filings or disclosures for a symbol."""
        raise NotImplementedError


class BaseMarketDataProvider(IEODSnapshotProvider, IHistoricalOHLCVProvider, ICorporateActionsProvider, ABC):
    """Consolidated market data provider interface implementing core market capabilities."""

    def get_actions(self, symbol: str) -> list[NormalizedCorporateAction]:
        """Default corporate actions implementation."""
        return []

