# Windows Task Scheduler Setup: TickerWise EOD Updates

This guide configures automated, reliable Windows Task Scheduler jobs to run TickerWise End-of-Day (EOD) market data updates and chronological catch-up on trading days.

---

## 1. Scheduling Overview

- **Exchange**: National Stock Exchange of India (NSE).
- **Target Session**: End-of-Day (EOD) trading sessions (trading days: Monday through Friday).
- **Provider Cadence**: TejHQ executes primary daily ingestion at ~18:30 IST with a retry/derived stage run at ~21:30 IST.
- **Recommended Schedule**:
  1. **Primary EOD Ingestion**: **18:30 IST (UTC+5:30)**, Monday through Friday.
  2. **Secondary Reconciliation & Catch-Up**: **21:30 IST (UTC+5:30)**, Monday through Friday.
- **Execution Script**: `scripts\run_eod_scheduled.ps1` wrapping `scripts\run_eod_update.py`.
- **Concurrency Protection**: Lockfile mechanism (`logs\eod_update.lock`) with 30-minute stale detection preventing overlapping runs.
- **Idempotency**: Runs verify published provider dates and existing `ingestion_runs` before committing; duplicate runs are safely skipped without duplicate records.
- **Exit Codes**:
  - `0`: Success (new data ingested or unchanged day skipped).
  - `1`: Error (validation failure, database critical error).
  - `2`: Provider unavailable or pipeline stage not ready yet.

---

## 2. Quick Command Setup (`schtasks`)

Open PowerShell as Administrator in the repository directory and register the two scheduled tasks. Replace `<PROJECT_DIR>` with your actual repository path (e.g., `D:\stock-intelligence-workbench`):

```powershell
# 1. Primary Daily EOD Ingestion at 18:30 IST
schtasks /create /tn "TickerWise_EOD_Primary" `
  /tr "powershell.exe -NoProfile -ExecutionPolicy Bypass -File \"<PROJECT_DIR>\scripts\run_eod_scheduled.ps1\"" `
  /sc WEEKLY /d MON,TUE,WED,THU,FRI /st 18:30 `
  /ru "%USERNAME%"

# 2. Secondary Reconciliation & Catch-Up at 21:30 IST
schtasks /create /tn "TickerWise_EOD_Catchup" `
  /tr "powershell.exe -NoProfile -ExecutionPolicy Bypass -File \"<PROJECT_DIR>\scripts\run_eod_scheduled.ps1\" -CatchUp" `
  /sc WEEKLY /d MON,TUE,WED,THU,FRI /st 21:30 `
  /ru "%USERNAME%"
```

To verify the registered tasks:

```powershell
schtasks /query /tn "TickerWise_EOD_Primary" /fo LIST /v
schtasks /query /tn "TickerWise_EOD_Catchup" /fo LIST /v
```

---

## 3. GUI Configuration (`taskschd.msc`)

To configure via the Windows Task Scheduler GUI:

1. **General**:
   - Name: `TickerWise_EOD_Primary`
   - Description: `Automatically ingest NSE EOD market data from TejHQ into MySQL`
   - Security options: `Run whether user is logged on or not` (or `Run only when user is logged on`)
   - `Run with highest privileges`: Checked
2. **Triggers**:
   - Begin the task: `On a schedule`
   - Schedule: `Weekly`
   - Recur every: `1` weeks on `Monday, Tuesday, Wednesday, Thursday, Friday`
   - Start: `18:30:00` (IST)
3. **Actions**:
   - Action: `Start a program`
   - Program/script: `powershell.exe`
   - Add arguments: `-NoProfile -ExecutionPolicy Bypass -File "scripts\run_eod_scheduled.ps1"`
   - Start in: `<PROJECT_DIR>`
4. **Settings**:
   - `Allow task to be run on demand`: Checked
   - `Run task as soon as possible after a scheduled start is missed`: Checked
   - `If the task fails, restart every`: `15 minutes` (up to `3 times`)
   - `Stop the task if it runs longer than`: `1 hour`
   - `If the running task does not end when requested, force it to stop`: Checked
   - `If the task is already running, then the following rule applies`: `Do not start a new instance`

Repeat for `TickerWise_EOD_Catchup` at `21:30` IST with argument `-File "scripts\run_eod_scheduled.ps1" -CatchUp`.

---

## 4. Manual & On-Demand Operations

Use the virtualenv Python interpreter to execute targeted maintenance tasks:

```powershell
# Set environment
$env:PYTHONPATH="backend"

# Check provider status and latest available trading session
python scripts/run_eod_update.py --check-status

# Run dry run (validates API responses and normalization without committing to DB)
python scripts/run_eod_update.py --dry-run

# Run full market ingestion for latest available trading date
python scripts/run_eod_update.py

# Ingest specific historical trading date
python scripts/run_eod_update.py --date 2026-10-26

# Run chronological catch-up for all un-ingested market dates
python scripts/run_eod_update.py --catch-up

# Backfill historical OHLCV for specific symbols
python scripts/run_eod_update.py --backfill-symbols RELIANCE,TCS,INFY,HDFCBANK --from-date 2026-10-01 --to-date 2026-10-26

# Ingest official NSE shareholding pattern disclosures
python scripts/import_nse_shareholding.py --dir data/sample_filings
```

---

## 5. Audit Logging & Health Monitoring

- **Ingestion Log**: `logs/eod_update.log` (timestamped, line-by-line pipeline details)
- **Scheduler Log**: `logs/eod_update_scheduler.log` (process launch, lock verification, exit codes)
- **Data Quality Review**: `data/rejected/eod_snapshot_review_*.csv` (rows filtered due to validation or zero price)
- **Database Tracking**: Table `ingestion_runs` records `source_id`, `data_date`, `status`, `records_processed`, `records_inserted`, `records_updated`, `records_skipped`, and `started_at` / `completed_at` timestamps.
- **Provider Status API**: `GET http://localhost:8000/api/v1/providers/status`
