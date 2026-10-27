# TickerWise Windows Task Scheduler Registration Script
# Configures automated EOD update runs every weekday at 19:30 IST

param (
    [string]$TaskName = "TickerWise_EOD_Update",
    [string]$ExecutionTime = "19:30"
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$RunnerScript = Join-Path $ProjectRoot "scripts\run_eod_scheduled.ps1"

Write-Host "Configuring Windows Scheduled Task: $TaskName"
Write-Host "Project Root: $ProjectRoot"
Write-Host "Runner Script: $RunnerScript"
Write-Host "Scheduled Time: $ExecutionTime (Mon-Fri)"

$Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-ExecutionPolicy Bypass -WindowStyle Hidden -File `"$RunnerScript`" -CatchUp" -WorkingDirectory $ProjectRoot
$Trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday -At $ExecutionTime
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2)

try {
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description "TickerWise End-of-Day Market Data Automated Catch-up and Ingestion for NSE Equity" -Force
    Write-Host "Successfully registered scheduled task '$TaskName'."
} catch {
    Write-Warning "Could not register scheduled task via PowerShell cmdlet: $_"
    Write-Host "Attempting fallback via schtasks.exe..."
    $Cmd = "powershell.exe -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$RunnerScript`" -CatchUp"
    schtasks /create /tn $TaskName /tr $Cmd /sc weekly /d MON,TUE,WED,THU,FRI /st $ExecutionTime /f
}

# Verify registration
Write-Host "Verifying task registration with schtasks:"
schtasks /query /tn $TaskName /fo LIST
