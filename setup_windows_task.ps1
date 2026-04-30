#Requires -Version 5.1
# AtlasDB — Register (or replace) the SP-API reports refresh scheduled task.
#
# Task name : AtlasDB SP-API Reports Refresh
# Triggers  : Daily 23:18, 09:38, 14:28, 18:48 + ONLOGON (8-min delay)
# Action    : run_reports_refresh.ps1 via powershell.exe
#
# NOTE — Wake timers (WakeToRun):
#   Wake-from-sleep requires "Allow wake timers" enabled in the active power plan
#   (Power Options → Change plan settings → Change advanced power settings →
#    Sleep → Allow wake timers → Enable).
#   Wake-from-hibernate is NOT reliable on Windows — hibernation checkpoints the
#   OS and Task Scheduler may not fire until the next manual wake.
#   The ONLOGON trigger with an 8-minute delay is included as a safety net for
#   machines that hibernate overnight.
#
# NOTE — Admin:
#   Registering a scheduled task for the current user does NOT require elevation,
#   provided the principal runs with the user's own credentials (RunLevel Limited).
#   If you see "Access is denied", re-run from an elevated prompt.

$ErrorActionPreference = "Stop"

$TaskName    = "AtlasDB SP-API Reports Refresh"
$ProjectDir  = "C:\DevProjects-b\AtlasDB"
$ScriptPath  = "$ProjectDir\run_reports_refresh.ps1"
$PythonPath  = "$ProjectDir\.venv\Scripts\python.exe"
$EnvPath     = "$ProjectDir\.env"
$LogDir      = "$ProjectDir\data\logs"

# ---- Admin check (informational only — task registration doesn't require it) ----
$currentPrincipal = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
$isAdmin = $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if ($isAdmin) {
    Write-Host "[INFO] Running as Administrator." -ForegroundColor Cyan
} else {
    Write-Host "[INFO] Running as standard user (elevation not required for this task)." -ForegroundColor Cyan
}

# ---- Pre-flight checks ----
$preflight = $true

if (-not (Test-Path $ScriptPath)) {
    Write-Host "[FAIL] run_reports_refresh.ps1 not found: $ScriptPath" -ForegroundColor Red
    $preflight = $false
}

if (-not (Test-Path $PythonPath)) {
    Write-Host "[FAIL] Python venv not found: $PythonPath" -ForegroundColor Red
    $preflight = $false
}

if (-not (Test-Path $EnvPath)) {
    Write-Host "[FAIL] .env file not found: $EnvPath" -ForegroundColor Red
    $preflight = $false
}

# Check for Google OAuth token — warn if GOOGLE_OAUTH_TOKEN_JSON is not set
$tokenJsonPath = $env:GOOGLE_OAUTH_TOKEN_JSON
if (-not $tokenJsonPath -or -not (Test-Path $tokenJsonPath)) {
    Write-Host "[WARN] GOOGLE_OAUTH_TOKEN_JSON is not set or file does not exist." -ForegroundColor Yellow
    Write-Host "       Sheets export steps will fail until Google OAuth is authorised." -ForegroundColor Yellow
    Write-Host "       Run 'python src/main.py export-sheets --marketplace US --report fba-inventory'" -ForegroundColor Yellow
    Write-Host "       interactively once to complete the browser auth flow." -ForegroundColor Yellow
}

if (-not $preflight) {
    Write-Host ""
    Write-Host "[ABORT] One or more pre-flight checks failed. Fix above issues and re-run." -ForegroundColor Red
    exit 1
}

Write-Host "[OK] Pre-flight checks passed." -ForegroundColor Green

# ---- Ensure log directory exists ----
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
    Write-Host "[OK] Created log directory: $LogDir"
}

# ---- Build task components ----
$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$ScriptPath`"" `
    -WorkingDirectory $ProjectDir

# Daily triggers
$trigger2318 = New-ScheduledTaskTrigger -Daily -At "23:18"
$trigger0938 = New-ScheduledTaskTrigger -Daily -At "09:38"
$trigger1428 = New-ScheduledTaskTrigger -Daily -At "14:28"
$trigger1848 = New-ScheduledTaskTrigger -Daily -At "18:48"

# ONLOGON trigger with 8-minute delay (safety net after hibernate/reboot)
$triggerLogon = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$triggerLogon.Delay = "PT8M"

$triggers = @($trigger2318, $trigger0938, $trigger1428, $trigger1848, $triggerLogon)

# Settings
$settings = New-ScheduledTaskSettingsSet `
    -WakeToRun `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -RestartInterval (New-TimeSpan -Minutes 15) `
    -RestartCount 2 `
    -DontStopIfGoingOnBatteries

# Principal: current user, interactive logon, limited privilege
$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Limited

# ---- Remove existing task if present ----
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "[OK] Removed existing task: $TaskName"
}

# ---- Register task ----
Register-ScheduledTask `
    -TaskName  $TaskName `
    -Action    $action `
    -Trigger   $triggers `
    -Settings  $settings `
    -Principal $principal `
    -Description "Ingests SP-API reports and exports to Google Sheets for US, CA, UK marketplaces." `
    | Out-Null

Write-Host ""
Write-Host "===== Task registered successfully =====" -ForegroundColor Green
Write-Host "  Task name  : $TaskName"
Write-Host "  Script     : $ScriptPath"
Write-Host "  Log dir    : $LogDir"
Write-Host ""
Write-Host "  Triggers   :"
Write-Host "    Daily 23:18  (primary overnight run)"
Write-Host "    Daily 09:38"
Write-Host "    Daily 14:28"
Write-Host "    Daily 18:48"
Write-Host "    ONLOGON + 8 min delay for $($env:USERNAME) (hibernate safety net)"
Write-Host ""
Write-Host "  Settings   :"
Write-Host "    WakeToRun              = true  (requires wake timers enabled in power plan)"
Write-Host "    StartWhenAvailable     = true  (runs missed triggers on next wake)"
Write-Host "    MultipleInstances      = IgnoreNew"
Write-Host "    ExecutionTimeLimit     = 2 hours"
Write-Host "    RestartOnFailure       = 15 min interval, up to 2 retries"
Write-Host "    DontStopIfOnBatteries  = true"
Write-Host ""

# Show next run times
$taskInfo = Get-ScheduledTask -TaskName $TaskName | Get-ScheduledTaskInfo -ErrorAction SilentlyContinue
if ($taskInfo -and $taskInfo.NextRunTime) {
    Write-Host "  Next run   : $($taskInfo.NextRunTime.ToString('yyyy-MM-dd HH:mm:ss'))"
} else {
    Write-Host "  Next run   : (run 'Get-ScheduledTask -TaskName \"$TaskName\" | Get-ScheduledTaskInfo' to check)"
}

Write-Host ""
Write-Host "[REMINDER] If wake-from-sleep is needed, enable wake timers in your active power plan:" -ForegroundColor Yellow
Write-Host "  Power Options → Change plan settings → Change advanced power settings" -ForegroundColor Yellow
Write-Host "  → Sleep → Allow wake timers → Enable" -ForegroundColor Yellow
