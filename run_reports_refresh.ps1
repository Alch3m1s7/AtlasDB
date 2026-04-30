#Requires -Version 5.1
# AtlasDB SP-API report refresh — US, CA, UK
# Logs to data/logs/reports_refresh_<timestamp>.log
# Uses a lock file to prevent overlapping instances.
$ErrorActionPreference = "Stop"

$ProjectDir = "C:\DevProjects-b\AtlasDB"
$Python     = "$ProjectDir\.venv\Scripts\python.exe"
$LogDir     = "$ProjectDir\data\logs"
$Timestamp  = Get-Date -Format "yyyyMMdd_HHmmss"
$LogFile    = "$LogDir\reports_refresh_$Timestamp.log"
$LockFile   = "$LogDir\refresh.lock"

# --- Ensure log directory exists ---
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

# --- Overlap prevention ---
# Task Scheduler is configured with MultipleInstances=IgnoreNew, but we also
# guard here so manual runs cannot overlap a running scheduled instance.
if (Test-Path $LockFile) {
    $rawPid = (Get-Content $LockFile -Raw).Trim()
    $otherRunning = $false
    if ($rawPid -match '^\d+$') {
        $otherRunning = ($null -ne (Get-Process -Id ([int]$rawPid) -ErrorAction SilentlyContinue))
    }
    if ($otherRunning) {
        "[$Timestamp] Another instance is running (PID $rawPid). Exiting." |
            Tee-Object -Append -FilePath $LogFile
        exit 1
    }
    # Stale lock from a previous crash — remove it
    Remove-Item $LockFile -Force -ErrorAction SilentlyContinue
}
Set-Content -Path $LockFile -Value $PID -Encoding utf8

try {
    Set-Location $ProjectDir

    $StartTime = Get-Date
    "[$($StartTime.ToString('yyyy-MM-dd HH:mm:ss'))] ===== AtlasDB Reports Refresh START =====" |
        Tee-Object -Append -FilePath $LogFile
    "  Python  : $Python" | Tee-Object -Append -FilePath $LogFile
    "  LogFile : $LogFile" | Tee-Object -Append -FilePath $LogFile

    $Marketplaces      = @("US", "CA", "UK")
    $FailedMarketplaces = @()

    foreach ($mkt in $Marketplaces) {
        $tStep = Get-Date
        "" | Tee-Object -Append -FilePath $LogFile
        "[$($tStep.ToString('HH:mm:ss'))] ----- BEGIN $mkt -----" |
            Tee-Object -Append -FilePath $LogFile

        # ---- ingest-report --report all ----
        "[$($tStep.ToString('HH:mm:ss'))] ingest-report --marketplace $mkt --report all" |
            Tee-Object -Append -FilePath $LogFile

        $ingestOK = $false
        try {
            & $Python src/main.py ingest-report --marketplace $mkt --report all |
                Tee-Object -Append -FilePath $LogFile
            if ($LASTEXITCODE -eq 0) {
                $ingestOK = $true
            } else {
                "[$((Get-Date).ToString('HH:mm:ss'))] ERROR: ingest-report exited $LASTEXITCODE for $mkt" |
                    Tee-Object -Append -FilePath $LogFile
            }
        } catch {
            "[$((Get-Date).ToString('HH:mm:ss'))] ERROR: ingest-report threw for ${mkt}: $($_.Exception.Message)" |
                Tee-Object -Append -FilePath $LogFile
        }

        if (-not $ingestOK) {
            "[$((Get-Date).ToString('HH:mm:ss'))] SKIPPING export-sheets for $mkt (ingest failed)" |
                Tee-Object -Append -FilePath $LogFile
            $FailedMarketplaces += $mkt
            continue
        }

        # ---- export-sheets --report all ----
        $tExport = Get-Date
        "[$($tExport.ToString('HH:mm:ss'))] export-sheets --marketplace $mkt --report all" |
            Tee-Object -Append -FilePath $LogFile

        $exportOK = $false
        try {
            & $Python src/main.py export-sheets --marketplace $mkt --report all |
                Tee-Object -Append -FilePath $LogFile
            if ($LASTEXITCODE -eq 0) {
                $exportOK = $true
            } else {
                "[$((Get-Date).ToString('HH:mm:ss'))] ERROR: export-sheets exited $LASTEXITCODE for $mkt" |
                    Tee-Object -Append -FilePath $LogFile
            }
        } catch {
            "[$((Get-Date).ToString('HH:mm:ss'))] ERROR: export-sheets threw for ${mkt}: $($_.Exception.Message)" |
                Tee-Object -Append -FilePath $LogFile
        }

        if (-not $exportOK) {
            "[$((Get-Date).ToString('HH:mm:ss'))] FAILED: export-sheets failed for $mkt" |
                Tee-Object -Append -FilePath $LogFile
            $FailedMarketplaces += $mkt
            continue
        }

        "[$((Get-Date).ToString('HH:mm:ss'))] OK: $mkt completed successfully" |
            Tee-Object -Append -FilePath $LogFile
    }

    $EndTime  = Get-Date
    $Duration = ($EndTime - $StartTime).ToString("hh\:mm\:ss")

    "" | Tee-Object -Append -FilePath $LogFile
    if ($FailedMarketplaces.Count -gt 0) {
        "[$($EndTime.ToString('yyyy-MM-dd HH:mm:ss'))] ===== FINISHED WITH ERRORS  duration=$Duration  failed=$($FailedMarketplaces -join ',') =====" |
            Tee-Object -Append -FilePath $LogFile
        exit 1
    }

    "[$($EndTime.ToString('yyyy-MM-dd HH:mm:ss'))] ===== SUCCESS  duration=$Duration =====" |
        Tee-Object -Append -FilePath $LogFile
    exit 0

} finally {
    # Always remove the lock file — runs even when exit is called inside try.
    Remove-Item $LockFile -Force -ErrorAction SilentlyContinue
}
