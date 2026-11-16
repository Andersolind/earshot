<#
.SYNOPSIS
    Opens `flowgraphs\gnu_larex_vibrometry.grc` in Radioconda's GNU Radio Companion (or compiles via grcc).
#>
[CmdletBinding()]
param(
    [switch]$CompileOnly,
    [string]$OutDir = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$GrcFile  = Join-Path $RepoRoot "flowgraphs\gnu_larex_vibrometry.grc"

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
    Write-Host "[GNU-Larex] Radioconda not yet installed -> running setup_radioconda.ps1..." -ForegroundColor Yellow
    & (Join-Path $PSScriptRoot "setup_radioconda.ps1") -SkipPackageUpdate
    $CondaRoot = Join-Path $RepoRoot "radioconda"
}

$CacheRoot = Join-Path $env:TEMP "gnu_larex_runtime"
New-Item -ItemType Directory -Force -Path (Join-Path $CacheRoot "matplotlib"), (Join-Path $CacheRoot "grc_hier"), (Join-Path $CacheRoot "xdg_state"), (Join-Path $CacheRoot "xdg_config"), (Join-Path $CacheRoot "xdg_cache\gnuradio\grc") -ErrorAction SilentlyContinue | Out-Null

$env:CONDA_PREFIX = $CondaRoot
$env:GNU_LAREX_ROOT = $RepoRoot
$env:PYTHONPATH = $RepoRoot
$env:MPLCONFIGDIR = Join-Path $CacheRoot "matplotlib"
$env:GRC_HIER_PATH = Join-Path $CacheRoot "grc_hier"
$env:XDG_STATE_HOME = Join-Path $CacheRoot "xdg_state"
$env:XDG_CONFIG_HOME = Join-Path $CacheRoot "xdg_config"
$env:XDG_CACHE_HOME = Join-Path $CacheRoot "xdg_cache"
if (-not (Test-Path "$env:APPDATA\.cache" -ErrorAction SilentlyContinue)) {
    $env:APPDATA = $CacheRoot
    New-Item -ItemType Directory -Force -Path "$CacheRoot\.cache\gnuradio\grc", "$CacheRoot\.local" -ErrorAction SilentlyContinue | Out-Null
}
$env:PATH = "$CondaRoot;$CondaRoot\Library\mingw-w64\bin;$CondaRoot\Library\usr\bin;$CondaRoot\Library\bin;$CondaRoot\Scripts;$CondaRoot\bin;$env:PATH"

$PythonExe = Join-Path $CondaRoot "python.exe"

if ($CompileOnly) {
    $GrccScript = Join-Path $CondaRoot "Scripts\grcc-script.py"
    if (-not $OutDir) { $OutDir = Join-Path $RepoRoot "flowgraphs" }
    Write-Host "[GNU-Larex] Compiling $GrcFile -> $OutDir ..." -ForegroundColor Cyan
    if (Test-Path $GrccScript) {
        & $PythonExe $GrccScript -o $OutDir $GrcFile
    } else {
        & $PythonExe -m gnuradio.grc.compiler -o $OutDir $GrcFile
    }
} else {
    $GrcScript = Join-Path $CondaRoot "Scripts\gnuradio-companion-script.py"
    Write-Host "[GNU-Larex] Opening GNU Radio Companion: $GrcFile" -ForegroundColor Cyan
    Set-Location $RepoRoot
    if (Test-Path $GrcScript) {
        & $PythonExe $GrcScript $GrcFile
    } else {
        & $PythonExe -m gnuradio.grc.main $GrcFile
    }
}
