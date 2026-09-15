#!/usr/bin/env bash
# Exile Architect installer (macOS / Linux)

set -euo pipefail

REPO_URL="${POE_BD_CREATOR_REPO_URL:-https://github.com/avdergh/poe2-exile-architect.git}"
REPO_DIR="${POE_BD_CREATOR_DIR:-$HOME/.poe-bd-creator/repo}"
PLUGIN_LINK="$HOME/.poe-bd-creator-plugin"
DRY_RUN=0
FROM_CHECKOUT=0
FORCE=0
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MANAGED_MCP_BEGIN="# BEGIN poe-bd-creator managed MCP server"
MANAGED_MCP_END="# END poe-bd-creator managed MCP server"
PORTABLE_SKILLS="poe-bd-research poe-bd-research-worker poe-bd-create poe-bd-learn"
# DeepSeek Harness installs as a user-authored agent preset, not as a skills
# directory: ${DSH_HOME:-$HOME/.dsh}/.agent-presets/poe-bd/.
DSH_HOME_DIR="${DSH_HOME:-$HOME/.dsh}"
DSH_PRESET_TARGET="$DSH_HOME_DIR/.agent-presets/poe-bd"

platforms_table() {
  cat <<EOF
codex|$HOME/.codex/skills|per-skill
claude|$HOME/.claude/skills|per-skill
cursor|$HOME/.cursor/skills|per-skill
vscode|$HOME/.copilot/skills|per-skill
gemini|$HOME/.agents/skills|per-skill
opencode|$HOME/.config/opencode/skills|per-skill
openclaw|$HOME/.openclaw/skills|folder
hermes|$HOME/.hermes/skills|folder
dsh|$DSH_PRESET_TARGET|dsh-preset
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
  install.sh --force <platform>      Reinstall over an existing install (rotates a kept backup)
  install.sh --from-checkout <platform>  Install this checkout without clone/pull
  install.sh --update                Pull latest changes
  install.sh --register-mcp-only [host]  Register this checkout's MCP server
  install.sh --doctor <host>         Check MCP runtime/config binding
  install.sh --uninstall <platform>  Remove links for <platform>
  install.sh --help

Supported platforms:
$(platform_ids | sed 's/^/  - /')

Environment:
  POE_BD_CREATOR_REPO_URL  Override clone URL
  POE_BD_CREATOR_DIR       Override clone destination
  DSH_HOME                 DeepSeek Harness home (default: $HOME/.dsh)

Notes:
  The `dsh` platform installs the poe-bd agent preset under
  ${DSH_HOME:-$HOME/.dsh}/.agent-presets/poe-bd and, next to it, a filled-in copy
  of the layer-1 MCP patch. Select EITHER the preset OR that patch in DSH, never
  both.
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

validate_research_skill_pair() {
  local root controller=0 worker=0
  root="$(skill_list_root)"
  [[ -f "$root/poe-bd-research/SKILL.md" ]] && controller=1
  [[ -f "$root/poe-bd-research-worker/SKILL.md" ]] && worker=1
  if [[ "$controller" -ne "$worker" ]]; then
    say "Research skill installation is incomplete: poe-bd-research and poe-bd-research-worker must both exist."
    return 1
  fi
}

list_skills() {
  local id="${1:-codex}" root
  root="$(skill_list_root)"
  if [[ ! -d "$root" ]]; then
    if [[ "$DRY_RUN" == "1" ]]; then
      if [[ "$id" == "codex" ]]; then
        printf '%s\n' "poe-bd-research" "poe-bd-research-worker" "poe-bd-create" "poe-bd-learn" "poe-bd-research-loop" "poe-bd-learning-loop"
      else
        printf '%s\n' $PORTABLE_SKILLS
      fi
      return 0
    fi
    say "Skills directory not found: $root"
    exit 1
  fi
  local d
  for d in "$root"/*/; do
    [[ -d "$d" ]] || continue
    local name
    name="$(basename "$d")"
    if [[ "$id" == "codex" || " $PORTABLE_SKILLS " == *" $name "* ]]; then
      printf '%s\n' "$name"
    fi
  done
}

list_skills_for_uninstall() {
  local root
  root="$(skill_list_root)"
  if [[ -d "$root" ]]; then
    list_skills codex
  else
    printf '%s\n' "poe-bd-research" "poe-bd-research-worker" "poe-bd-create" "poe-bd-learn" "poe-bd-research-loop" "poe-bd-learning-loop"
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
  local target="$1" style="$2" id="$3" root
  # DeepSeek Harness consumes a copied agent preset, not a skills directory:
  # install_dsh_preset installs the whole preset (composition + skills) and
  # fills in the checkout/uv placeholders on the way in.
  [[ "$style" == "dsh-preset" ]] && return 0
  validate_research_skill_pair || exit 1
  root="$(skills_root)"
  [[ "$DRY_RUN" == "1" ]] || mkdir -p "$target"
  case "$style" in
    per-skill)
      local skill
      while IFS= read -r skill; do
        safe_link "$root/$skill" "$target/$skill"
      done < <(list_skills "$id")
      if [[ "$id" != "codex" ]]; then
        remove_link "$target/poe-bd-research-loop"
        remove_link "$target/poe-bd-learning-loop"
      fi
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
  [[ "$style" == "dsh-preset" ]] && return 0
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
  local checkout_uv="$SCRIPT_DIR/.tools/uv/uv"
  if [[ -x "$checkout_uv" ]]; then
    printf '%s\n' "$checkout_uv"
    return 0
  fi
  if command -v uv >/dev/null 2>&1; then
    command -v uv
    return 0
  fi
  say "MCP installation requires uv. Install uv from https://docs.astral.sh/uv/ and rerun the installer."
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
    say "[dry-run] register Codex MCP servers (poe_knowledge_mcp, poe_build_mcp, poe_research_mcp, poe_learning_mcp) in $config_path"
    return 0
  fi

  mkdir -p "$(dirname "$config_path")"
  local existing=""
  [[ -f "$config_path" ]] && existing="$(cat "$config_path")"
  local name
  for name in poe_knowledge_mcp poe_build_mcp poe_research_mcp poe_learning_mcp; do
    if grep -q "^\[mcp_servers\.${name}\]$" <<<"$existing" && ! grep -qF "$MANAGED_MCP_BEGIN" <<<"$existing"; then
      say "Codex MCP server $name already exists but is not installer-managed; leaving it unchanged."
      return 0
    fi
  done

  clean="$(remove_managed_mcp_block "$existing" | sed -e ':a' -e '/^[[:space:]]*$/{$d;N;ba' -e '}')"
  block="$(cat <<EOF
$MANAGED_MCP_BEGIN
[mcp_servers.poe_knowledge_mcp]
command = $(toml_string "$command")
args = ["run", "python", "-m", "server.mcp.knowledge_server"]
cwd = $(toml_string "$repo_root")
startup_timeout_sec = 120

[mcp_servers.poe_knowledge_mcp.env]
PYTHONPATH = $(toml_string "$repo_root")

[mcp_servers.poe_build_mcp]
command = $(toml_string "$command")
args = ["run", "python", "-m", "server.mcp.build_server"]
cwd = $(toml_string "$repo_root")
startup_timeout_sec = 120

[mcp_servers.poe_build_mcp.env]
PYTHONPATH = $(toml_string "$repo_root")

[mcp_servers.poe_research_mcp]
command = $(toml_string "$command")
args = ["run", "python", "-m", "server.mcp.research_server"]
cwd = $(toml_string "$repo_root")
startup_timeout_sec = 120

[mcp_servers.poe_research_mcp.env]
PYTHONPATH = $(toml_string "$repo_root")

[mcp_servers.poe_learning_mcp]
command = $(toml_string "$command")
args = ["run", "python", "-m", "server.mcp.learning_server"]
cwd = $(toml_string "$repo_root")
startup_timeout_sec = 120

[mcp_servers.poe_learning_mcp.env]
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
  say "Registered Codex MCP servers (poe_knowledge_mcp, poe_build_mcp, poe_research_mcp, poe_learning_mcp) in $config_path"
}

unregister_codex_mcp_server() {
  local config_path existing next
  config_path="$(codex_config_path)"
  [[ -f "$config_path" ]] || return 0
  existing="$(cat "$config_path")"
  grep -qF "$MANAGED_MCP_BEGIN" <<<"$existing" || return 0
  if [[ "$DRY_RUN" == "1" ]]; then
    say "[dry-run] remove Codex MCP servers from $config_path"
    return 0
  fi
  next="$(remove_managed_mcp_block "$existing" | sed -e ':a' -e '/^[[:space:]]*$/{$d;N;ba' -e '}')"
  printf '%s\n' "$next" > "$config_path"
  say "Removed installer-managed Codex MCP servers from $config_path"
}

install_dsh_preset() {
  local action="$1" uv_path script project_root
  uv_path="$(resolve_uv_command)"
  script="$REPO_DIR/scripts/install_dsh_preset.py"
  [[ -f "$script" ]] || script="$SCRIPT_DIR/scripts/install_dsh_preset.py"
  if [[ ! -f "$script" ]]; then
    say "scripts/install_dsh_preset.py not found in this checkout."
    exit 1
  fi
  project_root="$REPO_DIR"
  [[ -f "$project_root/pyproject.toml" ]] || project_root="$SCRIPT_DIR"
  local args=(run --project "$project_root" python "$script" "$action")
  if [[ "$action" == "install" ]]; then
    args+=(--repo-root "$REPO_DIR" --uv-command "$uv_path")
    [[ "$FORCE" == "1" ]] && args+=(--force)
  fi
  [[ "$DRY_RUN" == "1" ]] && args+=(--dry-run)
  "$uv_path" "${args[@]}"
}

is_portable_mcp_host() {
  [[ "$1" == "claude" || "$1" == "cursor" || "$1" == "opencode" ]]
}

configure_portable_host() {
  local action="$1" host="$2" uv_path script project_root
  uv_path="$(resolve_uv_command)"
  script="$REPO_DIR/scripts/configure_agent_host.py"
  [[ -f "$script" ]] || script="$SCRIPT_DIR/scripts/configure_agent_host.py"
  project_root="$REPO_DIR"
  [[ -f "$project_root/pyproject.toml" ]] || project_root="$SCRIPT_DIR"
  local args=(run --project "$project_root" python "$script" "$action" --host "$host")
  if [[ "$action" != "uninstall" ]]; then
    args+=(--repo-root "$REPO_DIR" --uv-command "$uv_path")
  fi
  [[ "$DRY_RUN" == "1" ]] && args+=(--dry-run)
  "$uv_path" "${args[@]}"
}

register_mcp_server() {
  local id="$1"
  if [[ "$id" == "codex" ]]; then
    register_codex_mcp_server
  elif [[ "$id" == "dsh" ]]; then
    install_dsh_preset install
  elif is_portable_mcp_host "$id"; then
    configure_portable_host install "$id"
  else
    say "$id skill links were installed, but automatic MCP registration is not available for this host."
  fi
}

unregister_mcp_server() {
  local id="$1"
  if [[ "$id" == "codex" ]]; then
    unregister_codex_mcp_server
  elif [[ "$id" == "dsh" ]]; then
    install_dsh_preset uninstall
  elif is_portable_mcp_host "$id"; then
    configure_portable_host uninstall "$id"
  fi
}

cmd_install() {
  local id="$1" row target style
  row="$(resolve_platform "$id")"
  target="$(printf '%s\n' "$row" | cut -d'|' -f2)"
  style="$(printf '%s\n' "$row" | cut -d'|' -f3)"
  [[ "$FROM_CHECKOUT" == "1" ]] || clone_or_update
  if [[ "$id" == "codex" || "$id" == "dsh" ]] || is_portable_mcp_host "$id"; then
    [[ "$DRY_RUN" == "1" ]] || resolve_uv_command >/dev/null
  fi
  say "Linking skills for $id ($style -> $target)"
  link_skills "$target" "$style" "$id"
  if [[ "$id" != "dsh" ]]; then
    say "Linking universal plugin root"
    link_plugin_root
  fi
  install_build_converter_provider
  register_mcp_server "$id"
  if [[ "$id" == "dsh" ]]; then
    say "Installed the Exile Architect poe-bd preset for DeepSeek Harness at $target."
    say "Open a new DSH session and pick the poe-bd preset."
    say "Host-wide registration instead (never both): dsh web --patch $target/poe-bd.mcp.cordis.yml"
  elif [[ "$id" == "codex" ]]; then
    say "Installed Exile Architect for $id. Restart the host to discover all four workflows."
  else
    say "Installed Exile Architect for $id. Restart the host to discover /poe-bd-research, /poe-bd-create and /poe-bd-learn."
  fi
}

cmd_uninstall() {
  local id="$1" row target style
  row="$(resolve_platform "$id")"
  target="$(printf '%s\n' "$row" | cut -d'|' -f2)"
  style="$(printf '%s\n' "$row" | cut -d'|' -f3)"
  unlink_skills "$target" "$style"
  unregister_mcp_server "$id"
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
    --force)
      FORCE=1
      shift
      cmd_install "${1:-$(prompt_platform)}"
      ;;
    --from-checkout)
      FROM_CHECKOUT=1
      REPO_DIR="$SCRIPT_DIR"
      shift
      cmd_install "${1:-$(prompt_platform)}"
      ;;
    --update)
      cmd_update
      ;;
    --register-mcp-only)
      REPO_DIR="$SCRIPT_DIR"
      resolve_uv_command >/dev/null
      shift
      register_mcp_server "${1:-codex}"
      ;;
    --doctor)
      shift
      [[ -n "${1:-}" ]] || { say "--doctor requires a host"; exit 1; }
      if [[ "$1" == "codex" ]]; then
        say "Codex doctor remains available through a new Codex task and engine_health."
      elif [[ "$1" == "dsh" ]]; then
        install_dsh_preset doctor
      elif is_portable_mcp_host "$1"; then
        configure_portable_host doctor "$1"
      else
        say "Doctor supports: codex, dsh, claude, cursor, opencode"
        exit 1
      fi
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
