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
    [string]$McpHost = 'codex',
    [switch]$FromCheckout,
    [string]$Doctor,
    [string]$Uninstall,
    [switch]$DryRun,
    [switch]$Help
)

$ErrorActionPreference = 'Stop'

$RepoUrl = if ($env:POE_BD_CREATOR_REPO_URL) { $env:POE_BD_CREATOR_REPO_URL } else { 'https://github.com/avdergh/poe2-exile-architect.git' }
$RepoDir = if ($env:POE_BD_CREATOR_DIR) { $env:POE_BD_CREATOR_DIR } else { Join-Path $HOME '.poe-bd-creator\repo' }
$PluginLink = Join-Path $HOME '.poe-bd-creator-plugin'
$ScriptRepoDir = Split-Path -Parent $PSCommandPath
$RepoDir = if ($FromCheckout) { $ScriptRepoDir } else { $RepoDir }
$ManagedMcpBegin = '# BEGIN poe-bd-creator managed MCP server'
$ManagedMcpEnd = '# END poe-bd-creator managed MCP server'
$PortableSkills = @('poe-bd-research', 'poe-bd-research-worker', 'poe-bd-create', 'poe-bd-learn')
$PortableMcpHosts = @('claude', 'cursor', 'opencode')

$Platforms = [ordered]@{
    codex    = @{ Target = (Join-Path $HOME '.codex\skills');   Style = 'per-skill' }
    claude   = @{ Target = (Join-Path $HOME '.claude\skills');  Style = 'per-skill' }
    cursor   = @{ Target = (Join-Path $HOME '.cursor\skills');  Style = 'per-skill' }
    vscode   = @{ Target = (Join-Path $HOME '.copilot\skills'); Style = 'per-skill' }
    gemini   = @{ Target = (Join-Path $HOME '.agents\skills');  Style = 'per-skill' }
    opencode = @{ Target = (Join-Path $HOME '.config\opencode\skills'); Style = 'per-skill' }
    openclaw = @{ Target = (Join-Path $HOME '.openclaw\skills'); Style = 'folder' }
    hermes   = @{ Target = (Join-Path $HOME '.hermes\skills');  Style = 'folder' }
}

function Show-Usage {
@"
Exile Architect installer (Windows)

Usage:
  install.ps1 [<platform>]          Install for <platform> (or prompt if omitted)
  install.ps1 -DryRun <platform>    Show actions without changing files
  install.ps1 -FromCheckout <platform>  Install this checkout without clone/pull
  install.ps1 -Update               Pull latest changes
  install.ps1 -RegisterMcpOnly [-McpHost <host>]  Register this checkout's MCP server
  install.ps1 -Doctor <host>        Check MCP runtime/config binding
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

function Assert-ResearchSkillPair([string]$Root) {
    if (-not (Test-Path $Root)) { Write-Error "Skills directory not found: $Root" }
    $hasController = Test-Path (Join-Path $Root 'poe-bd-research\SKILL.md')
    $hasWorker = Test-Path (Join-Path $Root 'poe-bd-research-worker\SKILL.md')
    if ($hasController -ne $hasWorker) {
        Write-Error 'Research skill installation is incomplete: poe-bd-research and poe-bd-research-worker must both exist.'
    }
}

function Get-SkillNames([string]$Id) {
    $root = Get-SkillListRoot
    Assert-ResearchSkillPair $root
    $all = @(Get-ChildItem -Path $root -Directory | Select-Object -ExpandProperty Name)
    if ($Id -eq 'codex') { return $all }
    return @($PortableSkills | Where-Object { $all -contains $_ })
}

function Get-SkillNamesForUninstall {
    $root = Get-SkillListRoot
    if (Test-Path $root) {
        return @(Get-ChildItem -Path $root -Directory | Select-Object -ExpandProperty Name)
    }
    return @('poe-bd-research', 'poe-bd-research-worker', 'poe-bd-create', 'poe-bd-learn', 'poe-bd-research-loop', 'poe-bd-learning-loop')
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

function Link-Skills([string]$Target, [string]$Style, [string]$Id) {
    $root = Get-SkillsRoot
    Assert-ResearchSkillPair (Get-SkillListRoot)
    if (-not $DryRun -and -not (Test-Path $Target)) { New-Item -ItemType Directory -Path $Target | Out-Null }
    switch ($Style) {
        'per-skill' {
            foreach ($skill in Get-SkillNames $Id) {
                New-SafeJunction (Join-Path $Target $skill) (Join-Path $root $skill)
            }
            if ($Id -ne 'codex') {
                foreach ($skill in @('poe-bd-research-loop', 'poe-bd-learning-loop')) {
                    Remove-Reparse (Join-Path $Target $skill) | Out-Null
                }
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
    $checkoutUv = Join-Path (Normalize-PathText $ScriptRepoDir) '.tools\uv\uv.exe'
    if (Test-Path $checkoutUv) { return $checkoutUv }
    $installed = Get-Command uv -ErrorAction SilentlyContinue
    if ($installed -and $installed.Source) { return $installed.Source }
    Write-Error 'MCP installation requires uv. Install uv from https://docs.astral.sh/uv/ and rerun the installer.'
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
    $servers = @(
        @{ Name = 'poe_knowledge_mcp'; Module = 'server.mcp.knowledge_server' },
        @{ Name = 'poe_build_mcp';    Module = 'server.mcp.build_server' },
        @{ Name = 'poe_research_mcp'; Module = 'server.mcp.research_server' },
        @{ Name = 'poe_learning_mcp'; Module = 'server.mcp.learning_server' }
    )

    if ($DryRun) {
        Write-Host "[dry-run] register Codex MCP servers ($($servers.Name -join ', ')) in $configPath"
        return
    }

    $configDir = Split-Path -Parent $configPath
    if (-not (Test-Path $configDir)) { New-Item -ItemType Directory -Path $configDir | Out-Null }

    $existing = if (Test-Path $configPath) { Get-Content -LiteralPath $configPath -Raw } else { '' }
    foreach ($server in $servers) {
        if ($existing -match ('(?m)^\[mcp_servers\.' + [regex]::Escape($server.Name) + '\]\s*$') -and $existing -notlike "*$ManagedMcpBegin*") {
            Write-Warning "Codex MCP server $($server.Name) already exists but is not installer-managed; leaving it unchanged."
            return
        }
    }

    $clean = (Remove-Managed-McpBlock $existing).TrimEnd()
    $lines = New-Object System.Collections.Generic.List[string]
    $lines.Add($ManagedMcpBegin)
    foreach ($server in $servers) {
        $tomlArgs = '["' + ((@('run', 'python', '-m', $server.Module) | ForEach-Object { $_.Replace('"', '\"') }) -join '", "') + '"]'
        $lines.Add("[mcp_servers.$($server.Name)]")
        $lines.Add(('command = {0}' -f (Format-TomlString $command)))
        $lines.Add(('args = {0}' -f $tomlArgs))
        $lines.Add(('cwd = {0}' -f (Format-TomlString $repoRoot)))
        $lines.Add('startup_timeout_sec = 120')
        $lines.Add('')
        $lines.Add("[mcp_servers.$($server.Name).env]")
        $lines.Add(('PYTHONPATH = {0}' -f (Format-TomlString $repoRoot)))
        $lines.Add('')
    }
    $lines.Add($ManagedMcpEnd)
    $block = $lines -join [Environment]::NewLine

    $next = if ($clean) { $clean + [Environment]::NewLine + [Environment]::NewLine + $block + [Environment]::NewLine } else { $block + [Environment]::NewLine }
    Set-Content -LiteralPath $configPath -Value $next -Encoding UTF8
    Write-Host "Registered Codex MCP servers ($($servers.Name -join ', ')) in $configPath"
}

function Unregister-Codex-McpServer {
    $configPath = Get-Codex-ConfigPath
    if (-not (Test-Path $configPath)) { return }
    $existing = Get-Content -LiteralPath $configPath -Raw
    if ($existing -notlike "*$ManagedMcpBegin*") { return }
    if ($DryRun) { Write-Host "[dry-run] remove Codex MCP servers from $configPath"; return }
    $next = (Remove-Managed-McpBlock $existing).TrimEnd() + [Environment]::NewLine
    Set-Content -LiteralPath $configPath -Value $next -Encoding UTF8
    Write-Host "Removed installer-managed Codex MCP servers from $configPath"
}

function Invoke-PortableHostConfig([string]$Action, [string]$HostId) {
    $uv = Resolve-UvCommand
    $script = Join-Path $RepoDir 'scripts\configure_agent_host.py'
    if (-not (Test-Path $script)) {
        $script = Join-Path $ScriptRepoDir 'scripts\configure_agent_host.py'
    }
    $projectRoot = if (Test-Path (Join-Path $RepoDir 'pyproject.toml')) {
        $RepoDir
    } else {
        $ScriptRepoDir
    }
    $uvArgs = @('run', '--project', $projectRoot, 'python', $script, $Action, '--host', $HostId)
    if ($Action -ne 'uninstall') {
        $uvArgs += @('--repo-root', (Normalize-PathText $RepoDir), '--uv-command', $uv)
    }
    if ($DryRun) { $uvArgs += '--dry-run' }
    & $uv @uvArgs
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to $Action MCP configuration for $HostId. Existing configuration was left unchanged."
    }
}

function Register-McpServer([string]$Id) {
    if ($Id -eq 'codex') { Register-Codex-McpServer; return }
    if ($PortableMcpHosts -contains $Id) { Invoke-PortableHostConfig 'install' $Id; return }
    Write-Warning "$Id skill links were installed, but automatic MCP registration is not available for this host."
}

function Unregister-McpServer([string]$Id) {
    if ($Id -eq 'codex') { Unregister-Codex-McpServer; return }
    if ($PortableMcpHosts -contains $Id) { Invoke-PortableHostConfig 'uninstall' $Id }
}

function Cmd-Install([string]$Id) {
    $cfg = Resolve-Platform $Id
    if (-not $FromCheckout) { Clone-Or-Update }
    if (($Id -eq 'codex' -or $PortableMcpHosts -contains $Id) -and -not $DryRun) {
        $null = Resolve-UvCommand
    }
    Write-Host "Linking skills for $Id ($($cfg.Style) -> $($cfg.Target))"
    Link-Skills $cfg.Target $cfg.Style $Id
    Write-Host 'Linking universal plugin root'
    Link-Plugin-Root
    Install-BuildConverterProvider
    Register-McpServer $Id
    $installedSkills = if ($Id -eq 'codex') {
        '/poe-bd-research (+ explicit worker), /poe-bd-create, /poe-bd-learn, /poe-bd-research-loop, and /poe-bd-learning-loop'
    } else {
        '/poe-bd-research (+ explicit worker), /poe-bd-create and /poe-bd-learn'
    }
    Write-Host "Installed Exile Architect for $Id. Restart the host to discover $installedSkills."
}

function Cmd-Uninstall([string]$Id) {
    $cfg = Resolve-Platform $Id
    Write-Host "Removing skill links for $Id"
    Unlink-Skills $cfg.Target $cfg.Style
    Unregister-McpServer $Id
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
    Register-McpServer $McpHost
    return
}
if ($Doctor) {
    $RepoDir = if ($FromCheckout) { $ScriptRepoDir } else { $RepoDir }
    if ($Doctor -eq 'codex') {
        Write-Warning 'Codex doctor remains available through a new Codex task and engine_health.'
        return
    }
    if (-not ($PortableMcpHosts -contains $Doctor)) {
        Write-Error "Doctor supports: codex, $($PortableMcpHosts -join ', ')"
    }
    Invoke-PortableHostConfig 'doctor' $Doctor
    return
}
if ($Update) { Cmd-Update; return }
if ($Uninstall) { Cmd-Uninstall $Uninstall; return }
if (-not $Platform) { $Platform = Prompt-Platform }
Cmd-Install $Platform
