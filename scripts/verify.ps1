[CmdletBinding()]
param(
    [ValidateSet("quick", "noncompute", "compute", "full", "lint")]
    [string]$Profile = "quick"
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
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

function Invoke-ManifestValidation {
    Write-Host "==> mcpb manifest validation"
    & npx --yes "@anthropic-ai/mcpb" validate manifest.json
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

function Invoke-StaticChecks {
    Invoke-Uv "ruff check" @("ruff", "check", "server", "scripts", "pipeline", "tests")
    Invoke-Uv "ruff format --check" @(
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
                "-q"
            )
            Invoke-StaticChecks
        }
        "noncompute" {
            # Broad Python regression without the heavy Path of Building compute certification.
            Invoke-Uv "pytest without compute golden suite" @(
                "pytest",
                "-q",
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
                "-q",
                "--timeout=$ComputePytestTimeoutSeconds"
            )
        }
        "full" {
            # Release/merge confidence gate. This is intentionally expensive and includes the
            # compute suite, so it uses the same long per-test timeout budget.
            Write-Host (
                "    note: full profile includes compute; " +
                "use outer timeout >= $ComputeMinimumOuterTimeoutMs ms"
            )
            Invoke-Uv "full pytest" @("pytest", "-q", "--timeout=$ComputePytestTimeoutSeconds")
            Invoke-StaticChecks
        }
        "lint" {
            Invoke-StaticChecks
        }
    }
}
finally {
    Pop-Location
}
