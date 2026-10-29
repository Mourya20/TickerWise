"""Background workers and scheduled pipeline entrypoints.

Encapsulates long-running background tasks, historical data backfilling, and
scheduled EOD pipelines away from HTTP request/response lifecycles.
"""
from __future__ import annotations

from app.workers.backfill_worker import run_backfill_worker
from app.workers.corporate_action_worker import run_corporate_action_worker
from app.workers.eod_worker import (
    check_provider_status,
    run_catchup_worker,
    run_eod_worker,
)
from app.workers.shareholding_worker import (
    check_nse_permissions,
    parse_filing_file,
    run_shareholding_worker,
)

__all__ = [
    "run_eod_worker",
    "run_catchup_worker",
    "check_provider_status",
    "run_backfill_worker",
    "run_shareholding_worker",
    "check_nse_permissions",
    "parse_filing_file",
    "run_corporate_action_worker",
]
