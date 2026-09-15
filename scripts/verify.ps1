[CmdletBinding()]
param(
    [ValidateSet("quick", "noncompute", "compute", "full", "lint")]
    [string]$Profile = "quick"
)

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$VerificationTempRoot = if ($env:POE_VERIFY_TEMP_ROOT) {
    $env:POE_VERIFY_TEMP_ROOT
}
else {
    Join-Path ([System.IO.Path]::GetTempPath()) ("pv-" + $PID)
}
New-Item -ItemType Directory -Force -Path $VerificationTempRoot | Out-Null
# Hash-addressed receipts/quarantine can exceed Win32 MAX_PATH under pytest's nested default.
# Keep one short process-owned base; profiles invoke pytest sequentially.
$VerificationPytestBase = Join-Path $VerificationTempRoot "pt"
$env:PYTEST_ADDOPTS = (($env:PYTEST_ADDOPTS + ' --basetemp="' + $VerificationPytestBase + '"').Trim())
$env:TEMP = $VerificationTempRoot
$env:TMP = $env:TEMP
$env:POE2_MCP_DATA = Join-Path $VerificationTempRoot "user-data-$PID"
if (-not $env:UV_CACHE_DIR) {
    $env:UV_CACHE_DIR = Join-Path $RepoRoot ".uv-cache"
}
$env:npm_config_cache = Join-Path $RepoRoot ".npm-cache"
New-Item -ItemType Directory -Force -Path $env:TEMP | Out-Null
New-Item -ItemType Directory -Force -Path $env:POE2_MCP_DATA | Out-Null
New-Item -ItemType Directory -Force -Path $env:npm_config_cache | Out-Null
$Uv = Join-Path $RepoRoot ".tools\uv\uv.exe"
if (-not (Test-Path $Uv)) {
    $Uv = "uv"
}

$ComputePytestTimeoutSeconds = 1800
$ComputeMinimumOuterTimeoutMs = 1800000

function Invoke-Uv {
    param(
        [string]$Name,
        [string[]]$Arguments
    )

    Write-Host "==> $Name"
    & $Uv run @Arguments
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

function Invoke-UvAdvisory {
    param(
        [string]$Name,
        [string[]]$Arguments
    )

    Write-Host "==> $Name (advisory)"
    & $Uv run @Arguments
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "$Name reported differences; continuing because formatting is advisory."
    }
}

function Invoke-ManifestValidation {
    Invoke-Uv "mcpb manifest validation" @(
        "python",
        "scripts/validate_mcpb_manifest.py",
        "manifest.json"
    )
}

function Invoke-StaticChecks {
    Invoke-Uv "ruff check" @("ruff", "check", "server", "scripts", "pipeline", "tests")
    Invoke-UvAdvisory "ruff format --check" @(
        "ruff",
        "format",
        "--check",
        "server",
        "scripts",
        "pipeline",
        "tests"
    )
    Invoke-Uv "mypy freshness boundary" @("mypy", "server/freshness")
    Invoke-ManifestValidation
}

function Invoke-ReleaseContractChecks {
    $VerifyRoot = Join-Path $VerificationTempRoot (
        "poe-bd-verify-" + $PID + "-" + [Guid]::NewGuid().ToString("N")
    )
    New-Item -ItemType Directory -Path $VerifyRoot | Out-Null
    try {
        Invoke-Uv "research schema migration replay" @(
            "pytest",
            "tests/test_mature_learning.py",
            "-q",
            "-k",
            "migration or concurrent"
        )
        Invoke-Uv "research release seed validation" @(
            "python",
            "-c",
            "from pathlib import Path; from server.knowledge import mature_learning; mature_learning.validate_release_seed(Path('data/mature_build_learning/release.sqlite'), allow_legacy_schema=True); print('RESEARCH SEED OK')"
        )
        Invoke-Uv "research release seed content" @(
            "python",
            "scripts/smoke_research_release_seed.py"
        )
        Invoke-Uv "DSH skill adaptation check" @(
            "python",
            "scripts/adapt_skills_for_dsh.py",
            "--check"
        )
        Invoke-Uv "bundle and Codex plugin build" @(
            "python",
            "scripts/build_codex_plugin.py",
            "--version",
            "verify-0.5.0",
            "--out",
            $VerifyRoot
        )
        $Platform = if ($IsWindows) { "win-x64" } elseif ($IsMacOS) { "mac-arm64" } else { "linux-x64" }
        Invoke-Uv "staged four-domain MCP smoke" @(
            "python",
            "scripts/smoke_staged_mcp_domains.py",
            "--stage",
            (Join-Path $VerifyRoot ("bundle-" + $Platform))
        )
        Invoke-Uv "pinned PoB Research readback E2E" @(
            "python",
            "scripts/smoke_research_readback.py"
        )
    }
    finally {
        if (Test-Path -LiteralPath $VerifyRoot) {
            $ReleaseCleanupPath = [System.IO.Path]::GetFullPath($VerifyRoot)
            $ReleaseCleanupParent = [System.IO.Path]::GetFullPath($VerificationTempRoot).TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
            if (-not $ReleaseCleanupPath.StartsWith($ReleaseCleanupParent, [System.StringComparison]::OrdinalIgnoreCase)) {
                throw "Release cleanup path escaped its verification directory: $ReleaseCleanupPath"
            }
            Remove-Item -LiteralPath $ReleaseCleanupPath -Recurse -Force
        }
    }
}

Push-Location $RepoRoot
try {
    switch ($Profile) {
        "quick" {
            # Default developer loop: run tests touched by agent-facing lifecycle/server work,
            # then cheap static checks. Avoid the slow PoB compute golden suite here.
            Invoke-Uv "quick pytest" @(
                "pytest",
                "tests/test_lifecycle.py",
                "tests/test_server.py",
                "tests/test_project_config.py",
                "tests/test_dsh_adapter.py",
                "-p",
                "no:cacheprovider",
                "-q"
            )
            Invoke-StaticChecks
        }
        "noncompute" {
            # Broad Python regression without the heavy Path of Building compute certification.
            Invoke-Uv "pytest without compute golden suite" @(
                "pytest",
                "-q",
                "-p",
                "no:cacheprovider",
                "--ignore=tests/test_compute.py"
            )
            Invoke-StaticChecks
        }
        "compute" {
            # Heavy engine certification. Use when compute, PoB runtime, optimization, or item
            # generation behavior changes. This profile commonly runs for 15+ minutes on Windows;
            # callers that wrap this script must allow at least $ComputeMinimumOuterTimeoutMs ms.
            Write-Host (
                "    note: compute profile commonly runs 15+ minutes; " +
                "use outer timeout >= $ComputeMinimumOuterTimeoutMs ms"
            )
            Invoke-Uv "compute golden suite" @(
                "pytest",
                "tests/test_compute.py",
                "tests/test_reservation_ledger.py",
                "-q",
                "-p",
                "no:cacheprovider",
                "--timeout=$ComputePytestTimeoutSeconds"
            )
        }
        "full" {
            # Comprehensive release/merge confidence gate without the very slow PoB golden suite.
            # Engine certification stays available through the explicit `compute` profile only.
            Invoke-Uv "full pytest without compute golden suite" @(
                "pytest",
                "-q",
                "-p",
                "no:cacheprovider",
                "--ignore=tests/test_compute.py"
            )
            Invoke-StaticChecks
            Invoke-ReleaseContractChecks
        }
        "lint" {
            Invoke-StaticChecks
        }
    }
}
finally {
    Pop-Location
}
