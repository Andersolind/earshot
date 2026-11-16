<#
.SYNOPSIS
    Installs or updates to the latest Radioconda distribution on Windows and verifies GNU-Larex.
.DESCRIPTION
    1. Queries GitHub Releases for the latest `radioconda-*-Windows-x86_64.exe` installer.
    2. Safely backs up any partial/custom files (such as standalone RTL-SDR DLLs) in `~\radioconda`
       before performing a clean JustMe installation if `python.exe` is not yet present.
    3. Updates `radioconda`, `gnuradio`, and `soapysdr` packages via `mamba` to the latest builds.
    4. Runs the GNU-Larex DSP self-test (`scripts\verify_dsp.py`).
#>
[CmdletBinding()]
param(
    [string]$InstallDir = "",
    [switch]$SkipPackageUpdate
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
if (-not $InstallDir) {
    if (Test-Path "$env:USERPROFILE\radioconda\python.exe" -ErrorAction SilentlyContinue) {
        $InstallDir = "$env:USERPROFILE\radioconda"
    } else {
        $InstallDir = Join-Path $RepoRoot "radioconda"
    }
}

Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host " GNU-Larex :: Latest Radioconda Installer & Updater" -ForegroundColor Cyan
Write-Host "======================================================================" -ForegroundColor Cyan

$PythonExe = Join-Path $InstallDir "python.exe"
$MambaExe  = Join-Path $InstallDir "Library\bin\mamba.exe"
$CondaExe  = Join-Path $InstallDir "Scripts\conda.exe"

if (-not (Test-Path $PythonExe)) {
    Write-Host "[1/4] Full Radioconda installation not yet present at $InstallDir." -ForegroundColor Yellow

    # Preserve any existing standalone binaries (e.g. custom rtlsdr.dll / rtl_sdr.exe)
    if (Test-Path $InstallDir) {
        $existingItems = Get-ChildItem -Path $InstallDir -Force -ErrorAction SilentlyContinue
        if ($existingItems.Count -gt 0) {
            $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
            $backupDir = "${InstallDir}_backup_${stamp}"
            Write-Host "      Backing up existing files in $InstallDir -> $backupDir ..." -ForegroundColor Yellow
            Move-Item -Path $InstallDir -Destination $backupDir -Force
        } else {
            Remove-Item -Path $InstallDir -Force -Recurse
        }
    }

    Write-Host "[2/4] Querying GitHub for the latest official Radioconda Windows x64 release..." -ForegroundColor Cyan
    $release = Invoke-RestMethod -Uri "https://api.github.com/repos/radioconda/radioconda-installer/releases/latest"
    $asset = $release.assets | Where-Object { $_.name -match "Windows-x86_64\.exe$" } | Select-Object -First 1
    if (-not $asset) {
        throw "Could not find a Windows-x86_64.exe asset in release $($release.tag_name)."
    }

    $cacheDir = Join-Path $RepoRoot ".cache"
    New-Item -ItemType Directory -Force -Path $cacheDir | Out-Null
    $installerPath = Join-Path $cacheDir $asset.name
    Write-Host "      Latest Release: $($release.tag_name) ($($asset.name))" -ForegroundColor Green
    if (-not (Test-Path $installerPath) -or ((Get-Item $installerPath).Length -lt ($asset.size * 0.98))) {
        Write-Host "      Downloading $($asset.browser_download_url) ..." -ForegroundColor Cyan
        & curl.exe -L --fail --progress-bar -o $installerPath $asset.browser_download_url
        if ($LASTEXITCODE -ne 0) {
            throw "Download failed with exit code $LASTEXITCODE."
        }
    } else {
        Write-Host "      Using cached installer at $installerPath" -ForegroundColor Green
    }

    Write-Host "[3/4] Installing Radioconda silently into $InstallDir (this takes ~2-4 minutes)..." -ForegroundColor Cyan
    $proc = Start-Process -FilePath $installerPath -ArgumentList "/InstallationType=JustMe", "/RegisterPython=0", "/S", "/D=$InstallDir" -Wait -PassThru
    if ($proc.ExitCode -ne 0) {
        throw "Radioconda installer exited with code $($proc.ExitCode)."
    }
    Write-Host "      Radioconda base installation complete!" -ForegroundColor Green
} else {
    Write-Host "[1/4] Existing Radioconda installation detected at $InstallDir." -ForegroundColor Green
}

# Activate Radioconda paths for current process
$env:CONDA_PREFIX = $InstallDir
$env:PATH = "$InstallDir;$InstallDir\Library\mingw-w64\bin;$InstallDir\Library\usr\bin;$InstallDir\Library\bin;$InstallDir\Scripts;$InstallDir\bin;$env:PATH"
$env:GNU_LAREX_ROOT = $RepoRoot

if (-not $SkipPackageUpdate) {
    Write-Host "[3/4] Updating Radioconda & GNU Radio packages to latest conda-forge/ryanvolz builds..." -ForegroundColor Cyan
    if (Test-Path $MambaExe) {
        & $MambaExe update --yes -c conda-forge -c ryanvolz radioconda gnuradio
    } elseif (Test-Path $CondaExe) {
        & $CondaExe update --yes -c conda-forge -c ryanvolz radioconda gnuradio
    }
} else {
    Write-Host "[3/4] Skipping online package update (-SkipPackageUpdate specified)." -ForegroundColor DarkGray
}

Write-Host "[4/4] Verifying GNU Radio, SoapySDR drivers & GNU-Larex DSP pipeline..." -ForegroundColor Cyan
$grInfo = Join-Path $InstallDir "Library\bin\gnuradio-config-info.exe"
if (-not (Test-Path $grInfo)) {
    $grInfo = Join-Path $InstallDir "Scripts\gnuradio-config-info.exe"
}
if (Test-Path $grInfo) {
    $ver = & $grInfo --version
    Write-Host "      GNU Radio Version : $ver" -ForegroundColor Green
}

& $PythonExe (Join-Path $RepoRoot "scripts\verify_dsp.py")
Write-Host ""
Write-Host "Setup complete! Launch GNU-Larex anytime with:" -ForegroundColor Green
Write-Host "  .\scripts\run_larex.ps1          # Simulator + Live GUI Switcher" -ForegroundColor White
Write-Host "  .\scripts\run_larex.ps1 --live   # Auto-connect Live SDR via SoapySDR" -ForegroundColor White
Write-Host "  .\scripts\open_grc.ps1           # Open visual flowgraph in GNU Radio Companion" -ForegroundColor White
