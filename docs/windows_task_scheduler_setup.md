# Windows Task Scheduler Setup: TickerWise EOD Updates

This guide configures an automated, reliable Windows Task Scheduler job to run TickerWise End-of-Day (EOD) market data updates.

## 1. Scheduling Overview

- **Target Session**: NSE End-of-Day trading sessions.
- **Provider Timing**: TejHQ cron publishes daily at ~18:30 IST with a retry at ~21:30 IST; data is consistently ready by ~20:30–21:00 IST.
- **Scheduled Time**: **21:00 IST (UTC+5:30)**, Monday through Friday.
- **Execution Script**: `scripts/run_eod_scheduled.ps1` wrapping `scripts/run_eod_update.py`.
- **Interpreter**: `backend/.venv/Scripts/python.exe`.
- **Working Directory**: `D:\TickerWise`.
- **Concurrency Protection**: Lockfile mechanism preventing simultaneous overlapping executions.
- **Idempotency**: Runs check the provider's published date and existing `ingestion_runs` before committing; duplicate runs are safely skipped.

---

## 2. Quick Command Setup (`schtasks`)

Run PowerShell as Administrator and execute:

```powershell
schtasks /create /tn "TickerWise_EOD_Update" `
  /tr "powershell.exe -NoProfile -ExecutionPolicy Bypass -File \"D:\TickerWise\scripts\run_eod_scheduled.ps1\"" `
  /sc WEEKLY /d MON,TUE,WED,THU,FRI /st 21:00 `
  /ru "%USERNAME%"
```

To verify the registered task:

```powershell
schtasks /query /tn "TickerWise_EOD_Update" /fo LIST /v
```

---

## 3. GUI Configuration (Task Scheduler)

If configuring via `taskschd.msc`:

1. **General**:
   - Name: `TickerWise_EOD_Update`
   - Description: `Automatically ingest NSE EOD market data from TejHQ into MySQL`
   - Run whether user is logged on or not: Check (or Run only when user is logged on, based on user preference)
   - Run with highest privileges: Recommended
2. **Triggers**:
   - Begin the task: `On a schedule`
   - Schedule: `Weekly`
   - Recur every: `1` weeks on `Monday, Tuesday, Wednesday, Thursday, Friday`
   - Start: `21:00:00` (IST)
3. **Actions**:
   - Action: `Start a program`
   - Program/script: `powershell.exe`
   - Add arguments: `-NoProfile -ExecutionPolicy Bypass -File "D:\TickerWise\scripts\run_eod_scheduled.ps1"`
   - Start in (optional): `D:\TickerWise`
4. **Settings**:
   - Allow task to be run on demand: `Checked`
   - Run task as soon as possible after a scheduled start is missed: `Checked`
   - If the task fails, restart every: `15 minutes` (up to `3 times`)
   - If the running task does not end when requested, force it to stop: `Checked`
   - If the task is already running, then the following rule applies: `Do not start a new instance`

---

## 4. Manual / On-Demand Execution

To test the update manually at any time:

```powershell
# Check provider freshness and current trading date
& "D:\TickerWise\backend\.venv\Scripts\python.exe" "D:\TickerWise\scripts\run_eod_update.py" --check-status

# Perform a dry-run (verifies network and parsing without writing to DB)
& "D:\TickerWise\backend\.venv\Scripts\python.exe" "D:\TickerWise\scripts\run_eod_update.py" --dry-run

# Run full ingestion for latest available date
& "D:\TickerWise\backend\.venv\Scripts\python.exe" "D:\TickerWise\scripts\run_eod_update.py"

# Backfill historical OHLCV for a symbol
& "D:\TickerWise\backend\.venv\Scripts\python.exe" "D:\TickerWise\scripts\run_eod_update.py" --backfill-symbol RELIANCE --from-date 2026-10-01 --to-date 2026-10-14
```

---

## 5. Logs & Monitoring

- **Log File**: `D:\TickerWise\logs\eod_update.log`
- **Scheduler Log**: `D:\TickerWise\logs\eod_update_scheduler.log`
- **Review / Rejected Rows**: `D:\TickerWise\data\rejected\eod_snapshot_review_*.csv`
- **API Status**: `GET http://localhost:8000/api/v1/providers/status`
