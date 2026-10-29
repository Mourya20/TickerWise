"""Authoritative financial constants and threshold definitions."""
from __future__ import annotations

from decimal import Decimal

# Market capitalization and share capital thresholds
STALE_SHARE_COUNT_THRESHOLD_DAYS: int = 120
STALE_SNAPSHOT_THRESHOLD_DAYS: int = 4

# Reconciliation and divergence thresholds
PRICE_DIVERGENCE_THRESHOLD: Decimal = Decimal("0.05")  # 5.0%
MAX_ALLOWABLE_PRICE_DIVERGENCE_PCT: Decimal = Decimal("5.0")
MAX_SHARE_COUNT_AGE_DAYS: int = 120

# Canonical provider and data source identifiers
SOURCE_TEJHQ = "TejHQ"
SOURCE_TEJHQ_EOD = "TejHQ EOD Market"
SOURCE_TEJHQ_HISTORICAL = "TejHQ Historical"
SOURCE_TEJHQ_CORPORATE_ACTIONS = "TejHQ Corporate Actions"
SOURCE_0XRAMM = "0xramm"
SOURCE_NSE_FILING = "NSE Shareholding Pattern"
SOURCE_MANUAL = "Manual Override"

# Ingestion run statuses
RUN_STATUS_COMPLETED = "completed"
RUN_STATUS_PARTIAL = "partial"
RUN_STATUS_FAILED = "failed"
RUN_STATUS_SKIPPED = "skipped"
