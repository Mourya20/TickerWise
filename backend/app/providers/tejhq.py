from __future__ import annotations

import logging
import time
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.analytics import calculate_percentage_change
from app.core.config import settings
from app.providers.date_parser import (
    parse_optional_provider_event_date,
    parse_provider_event_date,
)
from app.providers.base import (
    BaseMarketDataProvider,
    NormalizedCorporateAction,
    NormalizedMarketSnapshot,
    NormalizedOHLCV,
    ProviderDataValidationError,
    ProviderNetworkError,
    ProviderResponseError,
    ProviderStatus,
)

logger = logging.getLogger(__name__)

PROVIDER_NAME = "TejHQ"
DEFAULT_EXCHANGE = "NSE"


def _parse_decimal(value: Any, field_name: str) -> Decimal | None:
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
    try:
        val = int(value)
        return val
    except (ValueError, TypeError) as exc:
        raise ProviderDataValidationError(f"Invalid integer for {field_name}: {value}") from exc


def _parse_iso_datetime(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        # Normalize trailing Z to +00:00
        normalized = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        # Store as naive UTC
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    except Exception:
        return None


class TejHQProvider(BaseMarketDataProvider):
    """Primary market data provider adapter for TejHQ EOD and full-market snapshot APIs."""

    def __init__(
        self,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
        max_retries: int | None = None,
        user_agent: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = (base_url or settings.TEJHQ_BASE_URL).rstrip("/")
        self.timeout_seconds = (
            timeout_seconds if timeout_seconds is not None else settings.TEJHQ_TIMEOUT_SECONDS
        )
        self.max_retries = max_retries if max_retries is not None else settings.TEJHQ_MAX_RETRIES
        self.user_agent = user_agent or settings.TEJHQ_USER_AGENT
        self._custom_client = client

    def _get_client(self) -> httpx.Client:
        if self._custom_client is not None:
            return self._custom_client
        return httpx.Client(
            base_url=self.base_url,
            timeout=self.timeout_seconds,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "application/json",
            },
        )

    def _request_with_retry(self, method: str, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Perform HTTP request with bounded exponential backoff for transient failures."""
        client = self._get_client()
        should_close = self._custom_client is None

        attempt = 0
        backoff = 0.5

        try:
            while True:
                attempt += 1
                try:
                    response = client.request(
                        method,
                        path,
                        params=params,
                        headers={
                            "User-Agent": self.user_agent,
                            "Accept": "application/json",
                        },
                    )

                    if response.status_code in (429, 500, 502, 503, 504) and attempt <= self.max_retries:
                        logger.warning(
                            "TejHQ request %s %s returned %s, retrying attempt %d/%d after %.1fs",
                            method,
                            path,
                            response.status_code,
                            attempt,
                            self.max_retries,
                            backoff,
                        )
                        time.sleep(backoff)
                        backoff = min(backoff * 2.0, 5.0)
                        continue

                    if response.status_code != 200:
                        raise ProviderResponseError(
                            f"TejHQ returned HTTP {response.status_code} for {path}: {response.text[:300]}"
                        )

                    try:
                        return response.json()
                    except Exception as exc:
                        raise ProviderResponseError(f"TejHQ returned non-JSON response for {path}") from exc

                except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as exc:
                    if attempt <= self.max_retries:
                        logger.warning(
                            "TejHQ network error for %s %s: %s, retrying attempt %d/%d after %.1fs",
                            method,
                            path,
                            exc,
                            attempt,
                            self.max_retries,
                            backoff,
                        )
                        time.sleep(backoff)
                        backoff = min(backoff * 2.0, 5.0)
                        continue
                    raise ProviderNetworkError(f"Network error communicating with TejHQ: {exc}") from exc
        finally:
            if should_close:
                client.close()

    def get_status(self) -> ProviderStatus:
        """Fetch provider operational status and latest published trading session."""
        data = self._request_with_retry("GET", "/v1/status")
        trading_date_str = data.get("trading_date")
        trading_date: date | None = None
        if trading_date_str:
            try:
                trading_date = datetime.strptime(trading_date_str, "%Y-%m-%d").date()
            except ValueError as exc:
                raise ProviderResponseError(f"Invalid trading_date format: {trading_date_str}") from exc

        stage = data.get("stage")
        prices_published = _parse_iso_datetime(data.get("prices_published_at"))
        derived_published = _parse_iso_datetime(data.get("derived_published_at"))
        is_fresh = bool(trading_date is not None and stage in ("prices", "derived"))

        return ProviderStatus(
            provider_name=PROVIDER_NAME,
            trading_date=trading_date,
            stage=stage,
            prices_published_at=prices_published,
            derived_published_at=derived_published,
            is_fresh=is_fresh,
            run_url=data.get("run_url"),
            raw_metadata=data,
        )

    def get_daily_snapshot(
        self, snapshot_date: date, exchange: str = DEFAULT_EXCHANGE
    ) -> list[NormalizedMarketSnapshot]:
        """Fetch complete market snapshot for a specified trading date."""
        exchange_code = exchange.strip().lower()
        date_str = snapshot_date.isoformat()
        payload = self._request_with_retry(
            "GET",
            f"/v1/snapshot/{exchange_code}",
            params={"date": date_str},
        )

        data_rows = payload.get("data")
        if not isinstance(data_rows, list):
            raise ProviderResponseError(
                f"TejHQ snapshot response missing 'data' list for {snapshot_date}"
            )

        meta = payload.get("meta") or {}
        meta_date = meta.get("date")
        if meta_date and meta_date != date_str:
            raise ProviderResponseError(
                f"TejHQ returned mismatched snapshot date: expected {date_str}, received {meta_date}"
            )

        retrieval_time = datetime.now(timezone.utc).replace(tzinfo=None)
        results: list[NormalizedMarketSnapshot] = []

        for row in data_rows:
            if not isinstance(row, dict):
                continue

            symbol = str(row.get("symbol", "")).strip().upper()
            if not symbol:
                continue

            series = row.get("series")
            series_str = str(series).strip().upper() if series else None
            isin = row.get("isin")
            isin_str = str(isin).strip().upper() if isin else None
            name = row.get("name")
            name_str = str(name).strip() if name else None

            open_price = _parse_decimal(row.get("open"), "open")
            high_price = _parse_decimal(row.get("high"), "high")
            low_price = _parse_decimal(row.get("low"), "low")
            close_price = _parse_decimal(row.get("close"), "close")
            last_price = _parse_decimal(row.get("last"), "last")
            prev_close_price = _parse_decimal(row.get("prev_close"), "prev_close")
            volume = _parse_int(row.get("volume"), "volume")
            turnover = _parse_decimal(row.get("turnover"), "turnover")
            trades = _parse_int(row.get("trades"), "trades")

            # Semantic validation:
            # - `last` is LTP (last traded price)
            # - `close` is provider reported closing price
            # - `prev_close` is previous day close
            # Never map LTP to close or treat missing close as LTP!
            # Percentage change calculation:
            target_price = close_price if close_price is not None else last_price
            pct_change, is_calculated = calculate_percentage_change(target_price, prev_close_price)

            results.append(
                NormalizedMarketSnapshot(
                    symbol=symbol,
                    series=series_str,
                    isin=isin_str,
                    name=name_str,
                    exchange=exchange.upper(),
                    snapshot_date=snapshot_date,
                    open=open_price,
                    high=high_price,
                    low=low_price,
                    close=close_price,
                    last_price=last_price,
                    prev_close=prev_close_price,
                    volume=volume,
                    turnover=turnover,
                    trades=trades,
                    percentage_change_pct=pct_change,
                    is_calculated_change=is_calculated,
                    provider_name=PROVIDER_NAME,
                    retrieved_at=retrieval_time,
                )
            )

        return results

    def get_historical_ohlcv(
        self, symbol: str, from_date: date, to_date: date, exchange: str = DEFAULT_EXCHANGE
    ) -> list[NormalizedOHLCV]:
        """Fetch historical daily OHLCV rows for a single symbol over a date range."""
        exchange_code = exchange.strip().lower()
        clean_symbol = symbol.strip().upper()
        payload = self._request_with_retry(
            "GET",
            f"/v1/ohlcv/{exchange_code}/{clean_symbol}",
            params={
                "from": from_date.isoformat(),
                "to": to_date.isoformat(),
            },
        )

        data_rows = payload.get("data")
        if not isinstance(data_rows, list):
            raise ProviderResponseError(
                f"TejHQ OHLCV response missing 'data' list for symbol {clean_symbol}"
            )

        results: list[NormalizedOHLCV] = []
        for row in data_rows:
            if not isinstance(row, dict):
                continue
            date_str = row.get("date")
            if not date_str:
                continue
            row_date = datetime.strptime(str(date_str), "%Y-%m-%d").date()

            open_price = _parse_decimal(row.get("open"), "open")
            high_price = _parse_decimal(row.get("high"), "high")
            low_price = _parse_decimal(row.get("low"), "low")
            close_price = _parse_decimal(row.get("close"), "close")
            last_price = _parse_decimal(row.get("last"), "last")
            prev_close_price = _parse_decimal(row.get("prev_close"), "prev_close")
            volume = _parse_int(row.get("volume"), "volume")
            turnover = _parse_decimal(row.get("turnover"), "turnover")
            trades = _parse_int(row.get("trades"), "trades")

            results.append(
                NormalizedOHLCV(
                    symbol=clean_symbol,
                    exchange=exchange.upper(),
                    date=row_date,
                    open=open_price,
                    high=high_price,
                    low=low_price,
                    close=close_price,
                    last_price=last_price,
                    prev_close=prev_close_price,
                    volume=volume,
                    turnover=turnover,
                    trades=trades,
                )
            )

        return results

    def get_actions(self, symbol: str) -> list[NormalizedCorporateAction]:
        """Fetch historical corporate actions for a single symbol."""
        clean_symbol = symbol.strip().upper()
        payload = self._request_with_retry(
            "GET",
            f"/v1/actions/{clean_symbol}",
        )

        data_rows = payload.get("data")
        if not isinstance(data_rows, list):
            raise ProviderResponseError(
                f"TejHQ actions response missing 'data' list for symbol {clean_symbol}"
            )

        results: list[NormalizedCorporateAction] = []
        malformed_count = 0

        for row in data_rows:
            if not isinstance(row, dict):
                malformed_count += 1
                logger.warning("TejHQ action row skipped (not a dictionary): %s", row)
                continue

            raw_ex_date = row.get("ex_date")
            try:
                ex_date = parse_provider_event_date(raw_ex_date)
            except ValueError as exc:
                malformed_count += 1
                logger.warning(
                    "TejHQ action row for %s skipped due to invalid ex_date '%s': %s",
                    clean_symbol,
                    raw_ex_date,
                    exc,
                )
                continue

            raw_rec_date = row.get("record_date")
            try:
                rec_date = parse_optional_provider_event_date(raw_rec_date)
            except ValueError as exc:
                logger.warning(
                    "TejHQ action row for %s has invalid record_date '%s', proceeding with None: %s",
                    clean_symbol,
                    raw_rec_date,
                    exc,
                )
                rec_date = None

            raw_action_type = str(row.get("type") or row.get("action_type") or "other").strip().lower()
            normalized_type = (
                "dividend" if "dividend" in raw_action_type
                else "split" if "split" in raw_action_type or "sub-division" in raw_action_type
                else "bonus" if "bonus" in raw_action_type
                else "rights" if "rights" in raw_action_type
                else "demerger" if "demerger" in raw_action_type
                else "buyback" if "buyback" in raw_action_type
                else raw_action_type
            )

            results.append(
                NormalizedCorporateAction(
                    symbol=str(row.get("symbol", clean_symbol)).strip().upper(),
                    exchange=str(row.get("exchange", "NSE")).strip().upper(),
                    isin=str(row.get("isin", "")).strip().upper() or None,
                    company_name=str(row.get("company", "")).strip() or None,
                    ex_date=ex_date,
                    record_date=rec_date,
                    action_type=normalized_type,
                    ratio_num=_parse_int(row.get("ratio_num"), "ratio_num"),
                    ratio_den=_parse_int(row.get("ratio_den"), "ratio_den"),
                    cash_amount=_parse_decimal(row.get("cash_amount") if row.get("cash_amount") is not None else row.get("amount"), "cash_amount"),
                    face_value_from=_parse_decimal(row.get("face_value_from"), "face_value_from"),
                    face_value_to=_parse_decimal(row.get("face_value_to"), "face_value_to"),
                    raw_subject=str(row.get("raw_subject", "")).strip() or None,
                )
            )

        if malformed_count > 0:
            logger.info("TejHQ get_actions for %s: %d valid actions returned, %d malformed rows skipped", clean_symbol, len(results), malformed_count)

        return results
