from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.core.config import settings
from app.providers.base import (
    BaseMarketDataProvider,
    NormalizedCompanyMetric,
    NormalizedMarketSnapshot,
    NormalizedOHLCV,
    NormalizedQuote,
    ProviderConfigurationError,
    ProviderDataValidationError,
    ProviderNetworkError,
    ProviderPermissionError,
    ProviderResponseError,
    ProviderStatus,
)

logger = logging.getLogger(__name__)

PROVIDER_NAME = "0xramm / Indian-Stock-Market-API"


def _parse_decimal(value: Any, field_name: str) -> Decimal | None:
    if value is None or value == "":
        return None
    # If the response used res=val, it might be a dict like {"value": 28.45, "unit": "x"}
    if isinstance(value, dict) and "value" in value:
        value = value.get("value")
        if value is None or value == "":
            return None
    try:
        dec = Decimal(str(value))
        if not dec.is_finite():
            raise ProviderDataValidationError(f"Invalid non-finite number for {field_name}: {value}")
        return dec
    except (InvalidOperation, ValueError) as exc:
        raise ProviderDataValidationError(f"Invalid decimal for {field_name}: {value}") from exc


def _parse_int(value: Any, field_name: str) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, dict) and "value" in value:
        value = value.get("value")
        if value is None or value == "":
            return None
    try:
        return int(value)
    except (ValueError, TypeError) as exc:
        raise ProviderDataValidationError(f"Invalid integer for {field_name}: {value}") from exc


class ZeroXRammProvider(BaseMarketDataProvider):
    """Supplementary provider adapter for 0xramm/Indian-Stock-Market-API.

    MANDATORY ACCESS GATE:
    This adapter is disabled by default. Upstream data source is Yahoo Finance,
    whose terms prohibit automated data collection without express prior permission.
    Fails closed unless TICKERWISE_0XRAMM_ENABLED and
    TICKERWISE_0XRAMM_AUTOMATION_PERMISSION_CONFIRMED are explicitly set to True
    and a valid self-hosted base URL is configured.
    """

    def __init__(
        self,
        base_url: str | None = None,
        enabled: bool | None = None,
        permission_confirmed: bool | None = None,
        timeout_seconds: float | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.enabled = enabled if enabled is not None else settings.TICKERWISE_0XRAMM_ENABLED
        self.permission_confirmed = (
            permission_confirmed
            if permission_confirmed is not None
            else settings.TICKERWISE_0XRAMM_AUTOMATION_PERMISSION_CONFIRMED
        )
        self.base_url = (base_url or settings.TICKERWISE_0XRAMM_BASE_URL or "").rstrip("/")
        self.timeout_seconds = (
            timeout_seconds
            if timeout_seconds is not None
            else settings.TICKERWISE_0XRAMM_TIMEOUT_SECONDS
        )
        self._custom_client = client

    def _verify_permission_and_config(self) -> None:
        """Fail closed if provider is disabled or automated permission is unconfirmed."""
        if not self.enabled:
            raise ProviderPermissionError(
                "0xramm provider is disabled by configuration (TICKERWISE_0XRAMM_ENABLED=False). "
                "Do not use in production without authorization."
            )
        if not self.permission_confirmed:
            raise ProviderPermissionError(
                "0xramm automated data collection permission for upstream Yahoo Finance has not "
                "been verified (TICKERWISE_0XRAMM_AUTOMATION_PERMISSION_CONFIRMED=False). "
                "Automated collection is prohibited. Application fails closed."
            )
        if not self.base_url:
            raise ProviderConfigurationError(
                "0xramm base URL is not configured (TICKERWISE_0XRAMM_BASE_URL is empty). "
                "The 0xramm project does not provide an official public hosted API; a verified self-hosted "
                "instance URL is required."
            )

    def _get_client(self) -> httpx.Client:
        if self._custom_client is not None:
            return self._custom_client
        return httpx.Client(
            base_url=self.base_url,
            timeout=self.timeout_seconds,
            headers={
                "User-Agent": "TickerWise/1.0 (Research Workbench)",
                "Accept": "application/json",
            },
        )

    def get_status(self) -> ProviderStatus:
        """Check provider operational status. Fails closed if unauthorized."""
        self._verify_permission_and_config()
        client = self._get_client()
        should_close = self._custom_client is None
        try:
            response = client.get("/")
            if response.status_code != 200:
                raise ProviderResponseError(
                    f"0xramm status check returned HTTP {response.status_code}: {response.text[:200]}"
                )
            payload = response.json()
            return ProviderStatus(
                provider_name=PROVIDER_NAME,
                trading_date=None,
                stage="active",
                prices_published_at=None,
                derived_published_at=None,
                is_fresh=True,
                run_url=None,
                raw_metadata=payload,
            )
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            raise ProviderNetworkError(f"Network error contacting 0xramm service: {exc}") from exc
        finally:
            if should_close:
                client.close()

    def get_stock_quote(self, symbol: str, exchange: str = "NSE") -> NormalizedQuote:
        """Fetch real-time stock quote from 0xramm endpoint.

        Calls GET /stock?symbol={SYMBOL}.NS&res=num
        """
        self._verify_permission_and_config()
        clean_symbol = symbol.strip().upper()
        # 0xramm uses .NS for NSE and .BO for BSE
        formatted_symbol = f"{clean_symbol}.NS" if exchange.upper() == "NSE" else f"{clean_symbol}.BO"

        client = self._get_client()
        should_close = self._custom_client is None
        try:
            response = client.get(
                "/stock",
                params={"symbol": formatted_symbol, "res": "num"},
            )
            if response.status_code != 200:
                raise ProviderResponseError(
                    f"0xramm quote failed with HTTP {response.status_code} for {formatted_symbol}: {response.text[:200]}"
                )
            data = response.json()
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            raise ProviderNetworkError(f"Network error contacting 0xramm for quote: {exc}") from exc
        finally:
            if should_close:
                client.close()

        retrieved_at = datetime.now(timezone.utc).replace(tzinfo=None)
        today = retrieved_at.date()

        # Parse fields from 0xramm payload
        price = _parse_decimal(data.get("price") or data.get("current_price"), "price")
        change_pct = _parse_decimal(
            data.get("change_pct") or data.get("percentage_change") or data.get("change_percent"),
            "change_pct",
        )
        volume = _parse_int(data.get("volume"), "volume")
        market_cap = _parse_decimal(data.get("market_cap") or data.get("market_capitalization"), "market_cap")
        pe_ratio = _parse_decimal(data.get("pe_ratio") or data.get("pe"), "pe_ratio")
        dividend_yield = _parse_decimal(
            data.get("dividend_yield") or data.get("dividend"), "dividend_yield"
        )
        sector = str(data.get("sector") or "").strip() or None

        return NormalizedQuote(
            symbol=clean_symbol,
            exchange=exchange.upper(),
            price=price,
            percentage_change_pct=change_pct,
            volume=volume,
            market_cap=market_cap,
            pe_ratio=pe_ratio,
            dividend_yield=dividend_yield,
            sector=sector,
            as_of_date=today,
            provider_name=PROVIDER_NAME,
            retrieved_at=retrieved_at,
        )

    def get_stock_metrics(self, symbol: str, exchange: str = "NSE") -> list[NormalizedCompanyMetric]:
        """Extract supplementary company metrics (market_cap, pe_ratio, dividend_yield, sector)."""
        quote = self.get_stock_quote(symbol, exchange)
        metrics: list[NormalizedCompanyMetric] = []

        if quote.market_cap is not None:
            metrics.append(
                NormalizedCompanyMetric(
                    symbol=quote.symbol,
                    exchange=quote.exchange,
                    metric_name="market_cap",
                    numeric_value=quote.market_cap,
                    text_value=None,
                    metric_unit="INR",
                    as_of_date=quote.as_of_date,
                    provider_name=PROVIDER_NAME,
                    retrieved_at=quote.retrieved_at,
                )
            )

        if quote.pe_ratio is not None:
            metrics.append(
                NormalizedCompanyMetric(
                    symbol=quote.symbol,
                    exchange=quote.exchange,
                    metric_name="pe_ratio",
                    numeric_value=quote.pe_ratio,
                    text_value=None,
                    metric_unit="ratio",
                    as_of_date=quote.as_of_date,
                    provider_name=PROVIDER_NAME,
                    retrieved_at=quote.retrieved_at,
                )
            )

        if quote.dividend_yield is not None:
            metrics.append(
                NormalizedCompanyMetric(
                    symbol=quote.symbol,
                    exchange=quote.exchange,
                    metric_name="dividend_yield",
                    numeric_value=quote.dividend_yield,
                    text_value=None,
                    metric_unit="pct",
                    as_of_date=quote.as_of_date,
                    provider_name=PROVIDER_NAME,
                    retrieved_at=quote.retrieved_at,
                )
            )

        if quote.sector is not None:
            metrics.append(
                NormalizedCompanyMetric(
                    symbol=quote.symbol,
                    exchange=quote.exchange,
                    metric_name="sector",
                    numeric_value=None,
                    text_value=quote.sector,
                    metric_unit="text",
                    as_of_date=quote.as_of_date,
                    provider_name=PROVIDER_NAME,
                    retrieved_at=quote.retrieved_at,
                )
            )

        return metrics

    def get_daily_snapshot(
        self, snapshot_date: date, exchange: str = "NSE"
    ) -> list[NormalizedMarketSnapshot]:
        """0xramm is a quote and company metric wrapper; it does not provide full-market bhavcopy."""
        raise NotImplementedError(
            "0xramm provider does not provide full-market EOD snapshots. Use TejHQ for EOD snapshots."
        )

    def get_historical_ohlcv(
        self, symbol: str, from_date: date, to_date: date, exchange: str = "NSE"
    ) -> list[NormalizedOHLCV]:
        """Historical EOD OHLCV must be sourced from TejHQ."""
        raise NotImplementedError(
            "0xramm provider does not provide historical EOD OHLCV. Use TejHQ as primary provider."
        )
