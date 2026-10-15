# TickerWise Automated EOD Update Runner for Windows Task Scheduler
# Timezone: Asia/Kolkata (IST)

param (
    [switch]$Force,
    [switch]$Verbose
)

$ErrorActionPreference = "Stop"

# Resolve directories
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$PythonExe = Join-Path $ProjectRoot "backend\.venv\Scripts\python.exe"
$UpdateScript = Join-Path $ProjectRoot "scripts\run_eod_update.py"
$LogsDir = Join-Path $ProjectRoot "logs"
$LogFile = Join-Path $LogsDir "eod_update_scheduler.log"
$LockFile = Join-Path $LogsDir "eod_update.lock"

# Ensure logs dir exists
if (-not (Test-Path $LogsDir)) {
    New-Item -ItemType Directory -Path $LogsDir -Force | Out-Null
}

$Timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Add-Content -Path $LogFile -Value "[$Timestamp] Starting scheduled EOD update run."

# Concurrency lock
if (Test-Path $LockFile) {
    $LockAge = (Get-Date) - (Get-Item $LockFile).LastWriteTime
    if ($LockAge.TotalMinutes -lt 30) {
        $Msg = "[$Timestamp] Another EOD update is already in progress (lock file active). Skipping."
        Add-Content -Path $LogFile -Value $Msg
        Write-Warning $Msg
        exit 0
    } else {
        Add-Content -Path $LogFile -Value "[$Timestamp] Stale lock file found (>30 min). Overriding."
        Remove-Item $LockFile -Force
    }
}

Set-Content -Path $LockFile -Value "$PID"

try {
    Set-Location $ProjectRoot

    $ArgsList = @("$UpdateScript")
    if ($Force) { $ArgsList += "--force" }
    if ($Verbose) { $ArgsList += "--verbose" }

    $Process = Start-Process -FilePath $PythonExe -ArgumentList $ArgsList -WorkingDirectory $ProjectRoot -NoNewWindow -PassThru -Wait
    $ExitCode = $Process.ExitCode

    $EndTimestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $LogFile -Value "[$EndTimestamp] EOD update process finished with exit code $ExitCode."
    exit $ExitCode
}
finally {
    if (Test-Path $LockFile) {
        Remove-Item $LockFile -Force
    }
}
