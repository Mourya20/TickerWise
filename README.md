# TickerWise

Reliable automated End-of-Day (EOD) market data workbench for Indian equities (NSE & BSE).

## Market Data Providers

1. **TejHQ API (Primary EOD Provider)**:
   - Historical EOD OHLCV, bhavcopy, and full-market daily snapshots.
   - Endpoints: `/v1/status`, `/v1/snapshot/nse?date=YYYY-MM-DD`, `/v1/ohlcv/nse/{SYMBOL}?from=...&to=...`.
   - Distinct semantic mapping: LTP (`last`), official close (`close`), previous close (`prev_close`), underlying volume (shares), turnover (INR), and trades.

2. **0xramm / Indian-Stock-Market-API (Supplementary Provider Candidate)**:
   - Lightweight quote wrapper around Yahoo Finance for company metrics (`market_cap`, `pe_ratio`, `dividend_yield`, `sector`).
   - **Permission Gate**: Disabled by default (`TICKERWISE_0XRAMM_ENABLED=false`, `TICKERWISE_0XRAMM_AUTOMATION_PERMISSION_CONFIRMED=false`). Fails closed in production until express data-use permissions for upstream Yahoo Finance are confirmed and a dedicated self-hosted service URL is configured.

## EOD Update Workflow

```bash
# Check provider pipeline status
python scripts/run_eod_update.py --check-status

# Dry-run validation (no DB changes)
python scripts/run_eod_update.py --dry-run

# Run daily EOD update (idempotent, skips if already processed)
python scripts/run_eod_update.py

# Force re-ingestion for a specific trading date
python scripts/run_eod_update.py --date 2026-10-14 --force

# Backfill historical OHLCV for a symbol
python scripts/run_eod_update.py --backfill-symbol RELIANCE --from-date 2026-10-01 --to-date 2026-10-14
```

## Windows Task Scheduler

Automated recurring updates are configured to run at **21:00 IST (UTC+5:30)** on trading days (Monday–Friday) via PowerShell:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "D:\TickerWise\scripts\run_eod_scheduled.ps1"
```

Detailed setup instructions and XML configurations are in [docs/windows_task_scheduler_setup.md](docs/windows_task_scheduler_setup.md).

## Running Tests

```bash
cd backend
.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
```


