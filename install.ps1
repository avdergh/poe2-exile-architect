<#
.SYNOPSIS
  Exile Architect installer for Windows.

.DESCRIPTION
  Clones/updates the project checkout, links the Exile Architect skills into
  the selected agent host, and registers the local MCP server for Codex. It
  refuses to overwrite real user directories and uninstall removes only
  installer-owned links/config blocks.

.EXAMPLE
  .\install.ps1 codex
  .\install.ps1 -DryRun codex
  .\install.ps1 -Uninstall codex
#>

param(
    [Parameter(Position = 0)]
    [string]$Platform,
    [switch]$Update,
    [switch]$RegisterMcpOnly,
    [string]$Uninstall,
    [switch]$DryRun,
    [switch]$Help
)

$ErrorActionPreference = 'Stop'

$RepoUrl = if ($env:POE_BD_CREATOR_REPO_URL) { $env:POE_BD_CREATOR_REPO_URL } else { 'https://github.com/avdergh/poe2-exile-architect.git' }
$RepoDir = if ($env:POE_BD_CREATOR_DIR) { $env:POE_BD_CREATOR_DIR } else { Join-Path $HOME '.poe-bd-creator\repo' }
$PluginLink = Join-Path $HOME '.poe-bd-creator-plugin'
$ScriptRepoDir = Split-Path -Parent $PSCommandPath
$ManagedMcpBegin = '# BEGIN poe-bd-creator managed MCP server'
$ManagedMcpEnd = '# END poe-bd-creator managed MCP server'

$Platforms = [ordered]@{
    codex    = @{ Target = (Join-Path $HOME '.codex\skills');   Style = 'per-skill' }
    claude   = @{ Target = (Join-Path $HOME '.claude\skills');  Style = 'per-skill' }
    cursor   = @{ Target = (Join-Path $HOME '.cursor\skills');  Style = 'per-skill' }
    vscode   = @{ Target = (Join-Path $HOME '.copilot\skills'); Style = 'per-skill' }
    gemini   = @{ Target = (Join-Path $HOME '.agents\skills');  Style = 'per-skill' }
    opencode = @{ Target = (Join-Path $HOME '.agents\skills');  Style = 'per-skill' }
    openclaw = @{ Target = (Join-Path $HOME '.openclaw\skills'); Style = 'folder' }
    hermes   = @{ Target = (Join-Path $HOME '.hermes\skills');  Style = 'folder' }
}

function Show-Usage {
@"
Exile Architect installer (Windows)

Usage:
  install.ps1 [<platform>]          Install for <platform> (or prompt if omitted)
  install.ps1 -DryRun <platform>    Show actions without changing files
  install.ps1 -Update               Pull latest changes
  install.ps1 -RegisterMcpOnly      Register this checkout's MCP server without cloning/linking
  install.ps1 -Uninstall <platform> Remove links for <platform>
  install.ps1 -Help

Supported platforms:
$($Platforms.Keys -join ', ')

Environment:
  POE_BD_CREATOR_REPO_URL  Override clone URL
  POE_BD_CREATOR_DIR       Override clone destination
"@
}

function Resolve-Platform([string]$Id) {
    if (-not $Platforms.Contains($Id)) {
        Write-Error "Unknown platform: $Id. Supported: $($Platforms.Keys -join ', ')"
    }
    return $Platforms[$Id]
}

function Prompt-Platform {
    $ids = @($Platforms.Keys)
    Write-Host 'Which platform are you installing for?'
    for ($i = 0; $i -lt $ids.Count; $i++) {
        Write-Host ("  {0}) {1}" -f ($i + 1), $ids[$i])
    }
    $choice = Read-Host ("Choose [1-{0}]" -f $ids.Count)
    $n = 0
    if (-not [int]::TryParse($choice, [ref]$n) -or $n -lt 1 -or $n -gt $ids.Count) {
        Write-Error "Invalid choice: $choice"
    }
    return $ids[$n - 1]
}

function Get-PluginRoot { Join-Path $RepoDir 'poe-bd-creator-plugin' }
function Get-SkillsRoot { Join-Path (Get-PluginRoot) 'skills' }
function Get-SkillListRoot {
    $installed = Get-SkillsRoot
    if (Test-Path $installed) { return $installed }
    $local = Join-Path $ScriptRepoDir 'poe-bd-creator-plugin\skills'
    if ($DryRun -and (Test-Path $local)) { return $local }
    return $installed
}

function Invoke-Step([string]$Message, [scriptblock]$Action) {
    if ($DryRun) {
        Write-Host "[dry-run] $Message"
        return
    }
    Write-Host $Message
    & $Action
}

function Clone-Or-Update {
    if (Test-Path (Join-Path $RepoDir '.git')) {
        Invoke-Step "Updating existing checkout at $RepoDir" { git -C $RepoDir pull --ff-only }
    } else {
        Invoke-Step "Cloning $RepoUrl to $RepoDir" {
            $parent = Split-Path -Parent $RepoDir
            if (-not (Test-Path $parent)) { New-Item -ItemType Directory -Path $parent | Out-Null }
            git clone $RepoUrl $RepoDir
        }
    }
}

function Get-SkillNames {
    $root = Get-SkillListRoot
    if (-not (Test-Path $root)) { Write-Error "Skills directory not found: $root" }
    Get-ChildItem -Path $root -Directory | Select-Object -ExpandProperty Name
}

function Get-SkillNamesForUninstall {
    $root = Get-SkillListRoot
    if (Test-Path $root) {
        return @(Get-ChildItem -Path $root -Directory | Select-Object -ExpandProperty Name)
    }
    return @('poe-bd-research', 'poe-bd-create', 'poe-bd-research-loop', 'poe-bd-learning-loop')
}

function Test-IsReparse([string]$Path) {
    if (-not (Test-Path $Path)) { return $false }
    $item = Get-Item -LiteralPath $Path -Force
    return ($item.LinkType -eq 'Junction' -or $item.LinkType -eq 'SymbolicLink')
}

function Get-ReparseTarget([string]$Path) {
    $item = Get-Item -LiteralPath $Path -Force
    if ($item.PSObject.Properties.Name -contains 'LinkTarget' -and $item.LinkTarget) {
        return [string]$item.LinkTarget
    }
    if ($item.Target) {
        if ($item.Target -is [array]) { return [string]$item.Target[0] }
        return [string]$item.Target
    }
    return ''
}

function Normalize-PathText([string]$PathText) {
    if (-not $PathText) { return '' }
    try { return ([System.IO.Path]::GetFullPath($PathText)).TrimEnd('\', '/') }
    catch { return $PathText.TrimEnd('\', '/') }
}

function Format-TomlString([string]$Value) {
    if ($Value -notlike "*'*") { return "'$Value'" }
    $escaped = $Value.Replace('\', '\\').Replace('"', '\"')
    return '"' + $escaped + '"'
}

function Test-TargetWithin([string]$TargetPath, [string]$RootPath) {
    $target = Normalize-PathText $TargetPath
    $root = Normalize-PathText $RootPath
    if (-not $target -or -not $root) { return $false }
    $comparison = [System.StringComparison]::OrdinalIgnoreCase
    return ($target.Equals($root, $comparison) -or $target.StartsWith($root + [System.IO.Path]::DirectorySeparatorChar, $comparison))
}

function Test-OwnedTarget([string]$TargetPath) {
    return (Test-TargetWithin $TargetPath (Get-PluginRoot))
}

function Test-OwnedReparse([string]$Path) {
    if (-not (Test-IsReparse $Path)) { return $false }
    return (Test-OwnedTarget (Get-ReparseTarget $Path))
}

function Remove-Reparse([string]$Path) {
    if (-not (Test-Path $Path)) { return $false }
    $item = Get-Item -LiteralPath $Path -Force
    if ($item.LinkType -eq 'Junction' -or $item.LinkType -eq 'SymbolicLink') {
        if (-not (Test-OwnedTarget (Get-ReparseTarget $Path))) {
            Write-Warning "Refusing to delete $Path because it is a link not owned by this installer."
            return $false
        }
        if ($DryRun) { Write-Host "[dry-run] remove link $Path"; return $true }
        $item.Delete()
        return $true
    }
    Write-Warning "Refusing to delete $Path because it is a real file/directory."
    return $false
}

function New-SafeJunction([string]$LinkPath, [string]$TargetPath) {
    if (Test-Path $LinkPath) {
        if (Test-IsReparse $LinkPath) {
            if (-not (Test-OwnedReparse $LinkPath)) {
                Write-Error "Refusing to overwrite $LinkPath because it is a link not owned by this installer."
            }
            if ($DryRun) { Write-Host "[dry-run] replace link $LinkPath -> $TargetPath"; return }
            (Get-Item -LiteralPath $LinkPath -Force).Delete()
        } else {
            Write-Error "Refusing to overwrite $LinkPath because it is a real file/directory."
        }
    }
    if ($DryRun) { Write-Host "[dry-run] link $LinkPath -> $TargetPath"; return }
    New-Item -ItemType Junction -Path $LinkPath -Target $TargetPath | Out-Null
}

function Link-Skills([string]$Target, [string]$Style) {
    $root = Get-SkillsRoot
    if (-not $DryRun -and -not (Test-Path $Target)) { New-Item -ItemType Directory -Path $Target | Out-Null }
    switch ($Style) {
        'per-skill' {
            foreach ($skill in Get-SkillNames) {
                New-SafeJunction (Join-Path $Target $skill) (Join-Path $root $skill)
            }
        }
        'folder' {
            New-SafeJunction (Join-Path $Target 'poe-bd-creator') $root
        }
        default { Write-Error "Unknown style: $Style" }
    }
}

function Unlink-Skills([string]$Target, [string]$Style) {
    if (-not (Test-Path $Target)) { return }
    switch ($Style) {
        'per-skill' {
            foreach ($skill in Get-SkillNamesForUninstall) {
                Remove-Reparse (Join-Path $Target $skill) | Out-Null
            }
            foreach ($child in Get-ChildItem -LiteralPath $Target -Force -ErrorAction SilentlyContinue) {
                if (Test-OwnedReparse $child.FullName) {
                    Remove-Reparse $child.FullName | Out-Null
                }
            }
        }
        'folder' {
            Remove-Reparse (Join-Path $Target 'poe-bd-creator') | Out-Null
        }
    }
}

function Link-Plugin-Root {
    $src = Get-PluginRoot
    New-SafeJunction $PluginLink $src
}

function Get-Codex-ConfigPath { Join-Path $HOME '.codex\config.toml' }

function Resolve-UvCommand {
    $localUv = Join-Path (Normalize-PathText $RepoDir) '.tools\uv\uv.exe'
    if (Test-Path $localUv) { return $localUv }
    $installed = Get-Command uv -ErrorAction SilentlyContinue
    if ($installed -and $installed.Source) { return $installed.Source }
    Write-Error 'Codex MCP installation requires uv. Install uv from https://docs.astral.sh/uv/ and rerun the installer.'
}

function Install-BuildConverterProvider {
    $uv = $null
    $localUv = Join-Path (Normalize-PathText $RepoDir) '.tools\uv\uv.exe'
    if (Test-Path $localUv) { $uv = $localUv }
    if (-not $uv) {
        $installedUv = Get-Command uv -ErrorAction SilentlyContinue
        if ($installedUv -and $installedUv.Source) { $uv = $installedUv.Source }
    }
    if (-not $uv) {
        Write-Warning 'Skipping Build Planner converter preparation because uv is unavailable. Core skill installation continues.'
        return
    }
    $script = Join-Path $RepoDir 'scripts\install_build_converter_provider.py'
    Invoke-Step 'Preparing pinned PoB to .build converter provider' {
        & $uv run python $script
        if ($LASTEXITCODE -ne 0) {
            Write-Warning 'Build Planner converter preparation failed. Core MCP features remain available; rerun scripts/install_build_converter_provider.py after installing Node.js and npm.'
        }
    }
}

function Remove-Managed-McpBlock([string]$Text) {
    $begin = [regex]::Escape($ManagedMcpBegin)
    $end = [regex]::Escape($ManagedMcpEnd)
    $pattern = "(?ms)^$begin\r?\n.*?^$end\r?\n?"
    return [regex]::Replace($Text, $pattern, '')
}

function Register-Codex-McpServer {
    $configPath = Get-Codex-ConfigPath
    $repoRoot = Normalize-PathText $RepoDir
    $command = Resolve-UvCommand
    $args = @("run", "python", "-m", "server.main")

    if ($DryRun) {
        Write-Host "[dry-run] register Codex MCP server poe2_build_mcp in $configPath"
        return
    }

    $configDir = Split-Path -Parent $configPath
    if (-not (Test-Path $configDir)) { New-Item -ItemType Directory -Path $configDir | Out-Null }

    $existing = if (Test-Path $configPath) { Get-Content -LiteralPath $configPath -Raw } else { '' }
    if ($existing -match '(?m)^\[mcp_servers\.poe2_build_mcp\]\s*$' -and $existing -notlike "*$ManagedMcpBegin*") {
        Write-Warning "Codex MCP server poe2_build_mcp already exists but is not installer-managed; leaving it unchanged."
        return
    }

    $clean = (Remove-Managed-McpBlock $existing).TrimEnd()
    $tomlArgs = '["' + (($args | ForEach-Object { $_.Replace('"', '\"') }) -join '", "') + '"]'
    $block = @(
        $ManagedMcpBegin,
        '[mcp_servers.poe2_build_mcp]',
        ('command = {0}' -f (Format-TomlString $command)),
        ('args = {0}' -f $tomlArgs),
        ('cwd = {0}' -f (Format-TomlString $repoRoot)),
        'startup_timeout_sec = 120',
        '',
        '[mcp_servers.poe2_build_mcp.env]',
        ('PYTHONPATH = {0}' -f (Format-TomlString $repoRoot)),
        $ManagedMcpEnd
    ) -join [Environment]::NewLine

    $next = if ($clean) { $clean + [Environment]::NewLine + [Environment]::NewLine + $block + [Environment]::NewLine } else { $block + [Environment]::NewLine }
    Set-Content -LiteralPath $configPath -Value $next -Encoding UTF8
    Write-Host "Registered Codex MCP server poe2_build_mcp in $configPath"
}

function Unregister-Codex-McpServer {
    $configPath = Get-Codex-ConfigPath
    if (-not (Test-Path $configPath)) { return }
    $existing = Get-Content -LiteralPath $configPath -Raw
    if ($existing -notlike "*$ManagedMcpBegin*") { return }
    if ($DryRun) { Write-Host "[dry-run] remove Codex MCP server poe2_build_mcp from $configPath"; return }
    $next = (Remove-Managed-McpBlock $existing).TrimEnd() + [Environment]::NewLine
    Set-Content -LiteralPath $configPath -Value $next -Encoding UTF8
    Write-Host "Removed installer-managed Codex MCP server poe2_build_mcp from $configPath"
}

function Cmd-Install([string]$Id) {
    $cfg = Resolve-Platform $Id
    if ($Id -eq 'codex' -and -not $DryRun) { $null = Resolve-UvCommand }
    Clone-Or-Update
    Write-Host "Linking skills for $Id ($($cfg.Style) -> $($cfg.Target))"
    Link-Skills $cfg.Target $cfg.Style
    Write-Host 'Linking universal plugin root'
    Link-Plugin-Root
    Install-BuildConverterProvider
    if ($Id -eq 'codex') { Register-Codex-McpServer }
    Write-Host "Installed Exile Architect skills for $Id. Restart the host to discover /poe-bd-research, /poe-bd-create, /poe-bd-research-loop, and /poe-bd-learning-loop."
}

function Cmd-Uninstall([string]$Id) {
    $cfg = Resolve-Platform $Id
    Write-Host "Removing skill links for $Id"
    Unlink-Skills $cfg.Target $cfg.Style
    if ($Id -eq 'codex') { Unregister-Codex-McpServer }
    Remove-Reparse $PluginLink | Out-Null
    Write-Host "Checkout kept at $RepoDir."
}

function Cmd-Update {
    if (-not (Test-Path (Join-Path $RepoDir '.git'))) {
        Write-Error "No installation found at $RepoDir. Run install first."
    }
    Invoke-Step "Updating $RepoDir" { git -C $RepoDir pull --ff-only }
}

if ($Help) { Show-Usage; return }
if ($RegisterMcpOnly) {
    $RepoDir = $ScriptRepoDir
    $null = Resolve-UvCommand
    Register-Codex-McpServer
    return
}
if ($Update) { Cmd-Update; return }
if ($Uninstall) { Cmd-Uninstall $Uninstall; return }
if (-not $Platform) { $Platform = Prompt-Platform }
Cmd-Install $Platform
