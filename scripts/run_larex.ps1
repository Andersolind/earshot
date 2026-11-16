<#
.SYNOPSIS
    Launches the GNU-Larex RF Vibrometry, Subvocalization & Respiration Suite using Radioconda.
.EXAMPLE
    .\scripts\run_larex.ps1
    .\scripts\run_larex.ps1 --live --freq 915 --gain 38
    .\scripts\run_larex.ps1 --live --sdr-args "driver=plutosdr" --cw-tx --freq 2450
#>
$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot

$Candidates = @(
    (Join-Path $RepoRoot "radioconda"),
    "$env:USERPROFILE\radioconda",
    "$env:LOCALAPPDATA\radioconda",
    "C:\radioconda",
    "$env:CONDA_PREFIX"
)

$CondaRoot = $null
foreach ($cand in $Candidates) {
    if ($cand -and (Test-Path (Join-Path $cand "python.exe") -ErrorAction SilentlyContinue)) {
        $CondaRoot = $cand
        break
    }
}

if (-not $CondaRoot) {
    Write-Host "[GNU-Larex] Radioconda python.exe not found yet -> running setup_radioconda.ps1 first..." -ForegroundColor Yellow
    & (Join-Path $PSScriptRoot "setup_radioconda.ps1") -SkipPackageUpdate
    $CondaRoot = Join-Path $RepoRoot "radioconda"
}

$CacheRoot = Join-Path $env:TEMP "gnu_larex_runtime"
New-Item -ItemType Directory -Force -Path (Join-Path $CacheRoot "matplotlib"), (Join-Path $CacheRoot "grc_hier") -ErrorAction SilentlyContinue | Out-Null

$env:CONDA_PREFIX = $CondaRoot
$env:KMP_DUPLICATE_LIB_OK = "TRUE"
$env:GNU_LAREX_ROOT = $RepoRoot
$env:PYTHONPATH = $RepoRoot
$env:MPLCONFIGDIR = Join-Path $CacheRoot "matplotlib"
$env:GRC_HIER_PATH = Join-Path $CacheRoot "grc_hier"
if (-not (Test-Path "$env:APPDATA\.cache" -ErrorAction SilentlyContinue)) {
    $env:APPDATA = $CacheRoot
    New-Item -ItemType Directory -Force -Path "$CacheRoot\.cache\gnuradio", "$CacheRoot\.local" -ErrorAction SilentlyContinue | Out-Null
}
$env:PATH = "$CondaRoot;$CondaRoot\Library\mingw-w64\bin;$CondaRoot\Library\usr\bin;$CondaRoot\Library\bin;$CondaRoot\Scripts;$CondaRoot\bin;$env:PATH"

$PythonExe = Join-Path $CondaRoot "python.exe"
$AppScript = Join-Path $RepoRoot "src\gnu_larex_vibrometry.py"

# Ensure any previous gnu_larex_vibrometry.py instance releases WinUSB SDR & port 8765 cleanly
$Existing = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*gnu_larex_vibrometry.py*" }
if ($Existing) {
    $Existing | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Milliseconds 1400
}

Write-Host "[GNU-Larex] Launching with Radioconda at: $CondaRoot" -ForegroundColor Cyan
& $PythonExe -B -u $AppScript @args
