"""Robust, timezone-safe calendar date parser for market data and corporate action provider payloads."""
from __future__ import annotations

from datetime import date, datetime
import re
from typing import Any

# Regex to extract YYYY-MM-DD from the start of an ISO date or timestamp string
_DATE_PREFIX_REGEX = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")


def parse_provider_event_date(val: Any) -> date:
    """Parse a provider event date into a calendar date without timezone date shifting.

    Exchange event dates (such as ex-date, record-date, allotment-date) represent calendar
    trading days. Timezone shifting (e.g. converting UTC midnight 00:00:00Z to a negative UTC
    offset) would incorrectly shift the calendar event date backwards by one day. This parser
    preserves the exact calendar date expressed by the provider.

    Accepts:
      - 'YYYY-MM-DD' (e.g. '2024-10-28')
      - ISO-8601 strings ending with 'Z' (e.g. '2010-05-10T00:00:00Z')
      - ISO-8601 strings with timezone offset (e.g. '2010-05-10T00:00:00+05:30', '2010-05-10T00:00:00-04:00')
      - ISO-8601 timestamp with space (e.g. '2010-05-10 00:00:00')
      - datetime or date instances

    Raises:
      ValueError: If val is None, empty, malformed, or represents an invalid calendar date.
    """
    if val is None:
        raise ValueError("Event date cannot be None")

    if isinstance(val, datetime):
        return val.date()

    if isinstance(val, date):
        return val

    if not isinstance(val, str):
        raise ValueError(f"Unsupported event date type: {type(val).__name__}")

    cleaned = val.strip()
    if not cleaned:
        raise ValueError("Event date string is empty")

    match = _DATE_PREFIX_REGEX.match(cleaned)
    if not match:
        raise ValueError(f"Invalid event date format (expected YYYY-MM-DD prefix): '{val}'")

    date_str = match.group(0)
    try:
        # date.fromisoformat validates year, month (1-12), day (1-31) and leap years
        return date.fromisoformat(date_str)
    except ValueError as exc:
        raise ValueError(f"Invalid calendar date in '{val}': {exc}") from exc


def parse_optional_provider_event_date(val: Any) -> date | None:
    """Parse an optional provider event date. Returns None if value is None, empty string, or invalid."""
    if val is None:
        return None
    if isinstance(val, str) and not val.strip():
        return None
    try:
        return parse_provider_event_date(val)
    except (ValueError, TypeError):
        return None


