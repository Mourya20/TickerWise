"""Ingestion layer for Stock Intelligence Workbench.

Owns data ingestion workflows, CSV importers, and audit runs across market data,
equity instruments, and shareholding patterns.
"""
from __future__ import annotations

from app.ingestion.eod_service import (
    EODUpdateResult,
    EODUpdateService,
    ReconciledQuote,
)
from app.ingestion.equity_master_importer import (
    EquityMasterImportResult,
    import_equity_master,
)
from app.ingestion.market_snapshot_importer import (
    ImportResult as MarketSnapshotImportResult,
    import_market_snapshot,
)
from app.ingestion.shareholding_importer import (
    NSEPermissionStatus,
    NSEShareholdingIngestionService,
    NSEShareholdingParser,
    ParsedShareCount,
)

__all__ = [
    # EOD Market Data
    "EODUpdateService",
    "EODUpdateResult",
    "ReconciledQuote",
    # Equity Master
    "import_equity_master",
    "EquityMasterImportResult",
    # Market Snapshot
    "import_market_snapshot",
    "MarketSnapshotImportResult",
    # Shareholding Pattern
    "NSEShareholdingIngestionService",
    "NSEShareholdingParser",
    "NSEPermissionStatus",
    "ParsedShareCount",
]
