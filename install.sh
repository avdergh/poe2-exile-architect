#!/usr/bin/env bash
# Exile Architect installer (macOS / Linux)

set -euo pipefail

REPO_URL="${POE_BD_CREATOR_REPO_URL:-https://github.com/avdergh/poe2-exile-architect.git}"
REPO_DIR="${POE_BD_CREATOR_DIR:-$HOME/.poe-bd-creator/repo}"
PLUGIN_LINK="$HOME/.poe-bd-creator-plugin"
DRY_RUN=0
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MANAGED_MCP_BEGIN="# BEGIN poe-bd-creator managed MCP server"
MANAGED_MCP_END="# END poe-bd-creator managed MCP server"

platforms_table() {
  cat <<EOF
codex|$HOME/.codex/skills|per-skill
claude|$HOME/.claude/skills|per-skill
cursor|$HOME/.cursor/skills|per-skill
vscode|$HOME/.copilot/skills|per-skill
gemini|$HOME/.agents/skills|per-skill
opencode|$HOME/.agents/skills|per-skill
openclaw|$HOME/.openclaw/skills|folder
hermes|$HOME/.hermes/skills|folder
EOF
}

platform_ids() { platforms_table | cut -d'|' -f1; }
plugin_root() { printf '%s\n' "$REPO_DIR/poe-bd-creator-plugin"; }
skills_root() { printf '%s\n' "$(plugin_root)/skills"; }
skill_list_root() {
  if [[ -d "$(skills_root)" ]]; then
    printf '%s\n' "$(skills_root)"
  elif [[ "$DRY_RUN" == "1" && -d "$SCRIPT_DIR/poe-bd-creator-plugin/skills" ]]; then
    printf '%s\n' "$SCRIPT_DIR/poe-bd-creator-plugin/skills"
  else
    printf '%s\n' "$(skills_root)"
  fi
}

usage() {
  cat <<USAGE
Exile Architect installer

Usage:
  install.sh [<platform>]            Install for <platform> (or prompt if omitted)
  install.sh --dry-run <platform>    Show actions without changing files
  install.sh --update                Pull latest changes
  install.sh --uninstall <platform>  Remove links for <platform>
  install.sh --help

Supported platforms:
$(platform_ids | sed 's/^/  - /')

Environment:
  POE_BD_CREATOR_REPO_URL  Override clone URL
  POE_BD_CREATOR_DIR       Override clone destination
USAGE
}

say() { printf '%s\n' "$*" >&2; }

do_step() {
  if [[ "$DRY_RUN" == "1" ]]; then
    say "[dry-run] $*"
  else
    "$@"
  fi
}

resolve_platform() {
  local id="$1" row
  row="$(platforms_table | awk -F'|' -v id="$id" '$1==id {print; exit}')"
  if [[ -z "$row" ]]; then
    say "Unknown platform: $id"
    say "Supported: $(platform_ids | tr '\n' ' ')"
    exit 1
  fi
  printf '%s\n' "$row"
}

prompt_platform() {
  local ids=()
  while IFS= read -r id; do ids+=("$id"); done < <(platform_ids)
  say "Which platform are you installing for?"
  local i=1
  for id in "${ids[@]}"; do
    say "  $i) $id"
    i=$((i + 1))
  done
  printf 'Choose [1-%d]: ' "${#ids[@]}" >&2
  local choice=""
  if { exec 3</dev/tty; } 2>/dev/null; then
    read -r choice <&3 || true
    exec 3<&-
  else
    read -r choice || true
  fi
  if ! [[ "$choice" =~ ^[0-9]+$ ]] || (( choice < 1 || choice > ${#ids[@]} )); then
    say "Invalid choice: $choice"
    exit 1
  fi
  printf '%s\n' "${ids[$((choice - 1))]}"
}

clone_or_update() {
  if [[ -d "$REPO_DIR/.git" ]]; then
    say "Updating existing checkout at $REPO_DIR"
    [[ "$DRY_RUN" == "1" ]] || git -C "$REPO_DIR" pull --ff-only
  else
    say "Cloning $REPO_URL to $REPO_DIR"
    if [[ "$DRY_RUN" != "1" ]]; then
      mkdir -p "$(dirname "$REPO_DIR")"
      git clone "$REPO_URL" "$REPO_DIR"
    fi
  fi
}

list_skills() {
  local root
  root="$(skill_list_root)"
  if [[ ! -d "$root" ]]; then
    if [[ "$DRY_RUN" == "1" ]]; then
      printf '%s\n' "poe-bd-research" "poe-bd-create"
      return 0
    fi
    say "Skills directory not found: $root"
    exit 1
  fi
  local d
  for d in "$root"/*/; do
    [[ -d "$d" ]] || continue
    basename "$d"
  done
}

list_skills_for_uninstall() {
  local root
  root="$(skill_list_root)"
  if [[ -d "$root" ]]; then
    list_skills
  else
    printf '%s\n' "poe-bd-research" "poe-bd-create"
  fi
}

normalize_path_text() {
  python - "$1" <<'PY'
import os, sys
print(os.path.abspath(sys.argv[1]).rstrip("/\\"))
PY
}

target_owned_by_installer() {
  local actual="$1" root
  root="$(plugin_root)"
  local actual_norm root_norm
  actual_norm="$(normalize_path_text "$actual")"
  root_norm="$(normalize_path_text "$root")"
  [[ "$actual_norm" == "$root_norm" || "$actual_norm" == "$root_norm"/* ]]
}

link_owned_by_installer() {
  local path="$1"
  [[ -L "$path" ]] || return 1
  target_owned_by_installer "$(readlink "$path")"
}

safe_link() {
  local src="$1" dst="$2"
  if [[ -e "$dst" && ! -L "$dst" ]]; then
    say "Refusing to overwrite $dst because it is a real file/directory."
    exit 1
  fi
  if [[ -L "$dst" ]] && ! link_owned_by_installer "$dst"; then
    say "Refusing to overwrite $dst because it is a link not owned by this installer."
    exit 1
  fi
  if [[ "$DRY_RUN" == "1" ]]; then
    say "[dry-run] link $dst -> $src"
    return 0
  fi
  ln -sfn "$src" "$dst"
}

remove_link() {
  local path="$1"
  if [[ -L "$path" ]]; then
    if ! link_owned_by_installer "$path"; then
      say "Refusing to remove $path because it is a link not owned by this installer."
      return 0
    fi
    if [[ "$DRY_RUN" == "1" ]]; then
      say "[dry-run] remove link $path"
    else
      rm -f "$path"
    fi
  elif [[ -e "$path" ]]; then
    say "Refusing to remove $path because it is a real file/directory."
  fi
}

link_skills() {
  local target="$1" style="$2" root
  root="$(skills_root)"
  [[ "$DRY_RUN" == "1" ]] || mkdir -p "$target"
  case "$style" in
    per-skill)
      local skill
      while IFS= read -r skill; do
        safe_link "$root/$skill" "$target/$skill"
      done < <(list_skills)
      ;;
    folder)
      safe_link "$root" "$target/poe-bd-creator"
      ;;
    *)
      say "Unknown style: $style"
      exit 1
      ;;
  esac
}

unlink_skills() {
  local target="$1" style="$2"
  [[ -d "$target" ]] || return 0
  case "$style" in
    per-skill)
      local skill
      while IFS= read -r skill; do
        remove_link "$target/$skill"
      done < <(list_skills_for_uninstall)
      local link
      for link in "$target"/*; do
        [[ -L "$link" ]] || continue
        link_owned_by_installer "$link" && remove_link "$link"
      done
      ;;
    folder)
      remove_link "$target/poe-bd-creator"
      ;;
  esac
}

link_plugin_root() {
  safe_link "$(plugin_root)" "$PLUGIN_LINK"
}

toml_string() {
  local value="$1"
  if [[ "$value" != *"'"* ]]; then
    printf "'%s'" "$value"
  else
    python - "$value" <<'PY'
import sys
print('"' + sys.argv[1].replace("\\", "\\\\").replace('"', '\\"') + '"')
PY
  fi
}

codex_config_path() {
  printf '%s\n' "$HOME/.codex/config.toml"
}

resolve_uv_command() {
  local local_uv="$REPO_DIR/.tools/uv/uv"
  if [[ -x "$local_uv" ]]; then
    printf '%s\n' "$local_uv"
    return 0
  fi
  if command -v uv >/dev/null 2>&1; then
    command -v uv
    return 0
  fi
  say "Codex MCP installation requires uv. Install uv from https://docs.astral.sh/uv/ and rerun the installer."
  return 1
}

install_build_converter_provider() {
  local uv_path=""
  if [[ -x "$REPO_DIR/.tools/uv/uv" ]]; then
    uv_path="$REPO_DIR/.tools/uv/uv"
  elif command -v uv >/dev/null 2>&1; then
    uv_path="$(command -v uv)"
  fi
  if [[ -z "$uv_path" ]]; then
    say "Skipping Build Planner converter preparation because uv is unavailable. Core skill installation continues."
    return 0
  fi
  if [[ "$DRY_RUN" == "1" ]]; then
    say "[dry-run] prepare pinned PoB to .build converter provider"
    return 0
  fi
  if ! "$uv_path" run python "$REPO_DIR/scripts/install_build_converter_provider.py"; then
    say "Build Planner converter preparation failed. Core MCP features remain available; rerun scripts/install_build_converter_provider.py after installing Node.js and npm."
  fi
}

remove_managed_mcp_block() {
  python - "$1" <<'PY'
import re
import sys

begin = "# BEGIN poe-bd-creator managed MCP server"
end = "# END poe-bd-creator managed MCP server"
text = sys.argv[1]
pattern = rf"(?ms)^{re.escape(begin)}\r?\n.*?^{re.escape(end)}\r?\n?"
print(re.sub(pattern, "", text), end="")
PY
}

register_codex_mcp_server() {
  local config_path repo_root uv_path command clean block next
  config_path="$(codex_config_path)"
  repo_root="$(normalize_path_text "$REPO_DIR")"
  command="$(resolve_uv_command)"

  if [[ "$DRY_RUN" == "1" ]]; then
    say "[dry-run] register Codex MCP server poe2_build_mcp in $config_path"
    return 0
  fi

  mkdir -p "$(dirname "$config_path")"
  local existing=""
  [[ -f "$config_path" ]] && existing="$(cat "$config_path")"
  if grep -q '^\[mcp_servers\.poe2_build_mcp\]$' <<<"$existing" && ! grep -qF "$MANAGED_MCP_BEGIN" <<<"$existing"; then
    say "Codex MCP server poe2_build_mcp already exists but is not installer-managed; leaving it unchanged."
    return 0
  fi

  clean="$(remove_managed_mcp_block "$existing" | sed -e ':a' -e '/^[[:space:]]*$/{$d;N;ba' -e '}')"
  block="$(cat <<EOF
$MANAGED_MCP_BEGIN
[mcp_servers.poe2_build_mcp]
command = $(toml_string "$command")
args = ["run", "python", "-m", "server.main"]
cwd = $(toml_string "$repo_root")
startup_timeout_sec = 120

[mcp_servers.poe2_build_mcp.env]
PYTHONPATH = $(toml_string "$repo_root")
$MANAGED_MCP_END
EOF
)"

  if [[ -n "$clean" ]]; then
    next="$clean

$block
"
  else
    next="$block
"
  fi
  printf '%s' "$next" > "$config_path"
  say "Registered Codex MCP server poe2_build_mcp in $config_path"
}

unregister_codex_mcp_server() {
  local config_path existing next
  config_path="$(codex_config_path)"
  [[ -f "$config_path" ]] || return 0
  existing="$(cat "$config_path")"
  grep -qF "$MANAGED_MCP_BEGIN" <<<"$existing" || return 0
  if [[ "$DRY_RUN" == "1" ]]; then
    say "[dry-run] remove Codex MCP server poe2_build_mcp from $config_path"
    return 0
  fi
  next="$(remove_managed_mcp_block "$existing" | sed -e ':a' -e '/^[[:space:]]*$/{$d;N;ba' -e '}')"
  printf '%s\n' "$next" > "$config_path"
  say "Removed installer-managed Codex MCP server poe2_build_mcp from $config_path"
}

cmd_install() {
  local id="$1" row target style
  row="$(resolve_platform "$id")"
  if [[ "$id" == "codex" && "$DRY_RUN" != "1" ]]; then
    resolve_uv_command >/dev/null
  fi
  target="$(printf '%s\n' "$row" | cut -d'|' -f2)"
  style="$(printf '%s\n' "$row" | cut -d'|' -f3)"
  clone_or_update
  say "Linking skills for $id ($style -> $target)"
  link_skills "$target" "$style"
  say "Linking universal plugin root"
  link_plugin_root
  install_build_converter_provider
  if [[ "$id" == "codex" ]]; then
    register_codex_mcp_server
  fi
  say "Installed Exile Architect skills for $id. Restart the host to discover /poe-bd-research and /poe-bd-create."
}

cmd_uninstall() {
  local id="$1" row target style
  row="$(resolve_platform "$id")"
  target="$(printf '%s\n' "$row" | cut -d'|' -f2)"
  style="$(printf '%s\n' "$row" | cut -d'|' -f3)"
  unlink_skills "$target" "$style"
  if [[ "$id" == "codex" ]]; then
    unregister_codex_mcp_server
  fi
  remove_link "$PLUGIN_LINK"
  say "Checkout kept at $REPO_DIR."
}

cmd_update() {
  if [[ ! -d "$REPO_DIR/.git" ]]; then
    say "No installation found at $REPO_DIR. Run install first."
    exit 1
  fi
  [[ "$DRY_RUN" == "1" ]] || git -C "$REPO_DIR" pull --ff-only
}

main() {
  local command="${1:-}"
  case "$command" in
    -h|--help)
      usage
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      cmd_install "${1:-$(prompt_platform)}"
      ;;
    --update)
      cmd_update
      ;;
    --uninstall)
      shift
      [[ -n "${1:-}" ]] || { say "--uninstall requires a platform"; exit 1; }
      cmd_uninstall "$1"
      ;;
    "")
      cmd_install "$(prompt_platform)"
      ;;
    -*)
      say "Unknown option: $command"
      usage >&2
      exit 1
      ;;
    *)
      cmd_install "$command"
      ;;
  esac
}

main "$@"
