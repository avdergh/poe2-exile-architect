#!/usr/bin/env bash
# PoE BD Creator installer (macOS / Linux)

set -euo pipefail

REPO_URL="${POE_BD_CREATOR_REPO_URL:-https://github.com/Egonex-AI/poe-bd-creator.git}"
REPO_DIR="${POE_BD_CREATOR_DIR:-$HOME/.poe-bd-creator/repo}"
PLUGIN_LINK="$HOME/.poe-bd-creator-plugin"
DRY_RUN=0
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

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
PoE BD Creator installer

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
      printf '%s\n' "poe-bd-research"
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
    printf '%s\n' "poe-bd-research"
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

cmd_install() {
  local id="$1" row target style
  row="$(resolve_platform "$id")"
  target="$(printf '%s\n' "$row" | cut -d'|' -f2)"
  style="$(printf '%s\n' "$row" | cut -d'|' -f3)"
  clone_or_update
  say "Linking skills for $id ($style -> $target)"
  link_skills "$target" "$style"
  say "Linking universal plugin root"
  link_plugin_root
  say "Installed PoE BD Creator skill for $id. Restart the host to discover /poe-bd-research."
}

cmd_uninstall() {
  local id="$1" row target style
  row="$(resolve_platform "$id")"
  target="$(printf '%s\n' "$row" | cut -d'|' -f2)"
  style="$(printf '%s\n' "$row" | cut -d'|' -f3)"
  unlink_skills "$target" "$style"
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
