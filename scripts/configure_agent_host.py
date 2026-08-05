"""Safely register Exile Architect's local MCP server in supported agent hosts.

The repository installers own skill links. This helper owns only one named MCP entry and keeps a
small fingerprint receipt so uninstall never deletes a user-managed entry with the same name.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

SERVER_NAME = "poe2_build_mcp"
STATE_VERSION = 1
SUPPORTED_HOSTS = ("claude", "cursor", "opencode")


def _json_fingerprint(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _default_config_path(host: str, home: Path, environ: dict[str, str]) -> Path:
    if host == "opencode":
        override = environ.get("OPENCODE_CONFIG")
        return Path(override).expanduser() if override else home / ".config/opencode/opencode.json"
    if host == "cursor":
        return home / ".cursor/mcp.json"
    if host == "claude":
        return home / ".claude.json"
    raise ValueError(f"unsupported host: {host}")


def _container_key(host: str) -> str:
    return "mcp" if host == "opencode" else "mcpServers"


def _desired_entry(host: str, repo_root: Path, uv_command: Path) -> dict[str, Any]:
    repo = str(repo_root.resolve())
    uv = str(uv_command.resolve())
    args = ["run", "python", "-m", "server.main"]
    if host == "opencode":
        return {
            "type": "local",
            "command": [uv, *args],
            "cwd": repo,
            "environment": {"PYTHONPATH": repo},
            "enabled": True,
            "timeout": 120000,
        }
    return {
        "command": uv,
        "args": args,
        "cwd": repo,
        "env": {"PYTHONPATH": repo},
    }


def _load_object(path: Path, *, missing_ok: bool = True) -> dict[str, Any]:
    if not path.exists():
        if missing_ok:
            return {}
        raise FileNotFoundError(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"{path} is not strict JSON (comments/trailing commas are not rewritten automatically)"
        ) from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise


def _state_path(home: Path, override: Path | None) -> Path:
    return override or home / ".poe-bd-creator/host-config-state.json"


def _read_state(path: Path) -> dict[str, Any]:
    state = _load_object(path)
    if not state:
        return {"version": STATE_VERSION, "hosts": {}}
    if state.get("version") != STATE_VERSION or not isinstance(state.get("hosts"), dict):
        raise ValueError(f"unsupported installer state in {path}")
    return state


def _backup_once(config_path: Path) -> Path | None:
    if not config_path.exists():
        return None
    backup = config_path.with_name(f"{config_path.name}.poe-bd-creator.bak")
    if not backup.exists():
        shutil.copy2(config_path, backup)
    return backup


def _result(status: str, host: str, config_path: Path, **extra: Any) -> dict[str, Any]:
    return {
        "status": status,
        "host": host,
        "server": SERVER_NAME,
        "configPath": str(config_path),
        **extra,
    }


def install_host(
    host: str,
    *,
    repo_root: Path,
    uv_command: Path,
    home: Path,
    environ: dict[str, str] | None = None,
    config_path: Path | None = None,
    state_path: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    environ = environ or dict(os.environ)
    config_path = config_path or _default_config_path(host, home, environ)
    state_path = _state_path(home, state_path)
    config = _load_object(config_path)
    was_empty = not config
    state = _read_state(state_path)
    key = _container_key(host)
    container = config.setdefault(key, {})
    if not isinstance(container, dict):
        return _result("conflict", host, config_path, errorCode=f"{key}_must_be_object")

    desired = _desired_entry(host, repo_root, uv_command)
    desired_fingerprint = _json_fingerprint(desired)
    current = container.get(SERVER_NAME)
    receipt = state["hosts"].get(host)
    receipt_matches_current = bool(
        isinstance(receipt, dict)
        and receipt.get("managed") is True
        and receipt.get("configPath") == str(config_path)
        and current is not None
        and receipt.get("fingerprint") == _json_fingerprint(current)
    )

    if current == desired:
        return _result(
            "already_configured",
            host,
            config_path,
            managed=bool(receipt_matches_current),
        )
    if current is not None and not receipt_matches_current:
        return _result(
            "conflict",
            host,
            config_path,
            errorCode="unmanaged_server_entry_exists",
        )

    container[SERVER_NAME] = desired
    if host == "opencode" and was_empty:
        config["$schema"] = "https://opencode.ai/config.json"
    state["hosts"][host] = {
        "managed": True,
        "configPath": str(config_path),
        "fingerprint": desired_fingerprint,
    }
    if dry_run:
        return _result("would_configure", host, config_path, managed=True)
    backup = _backup_once(config_path)
    _atomic_write_json(config_path, config)
    _atomic_write_json(state_path, state)
    return _result(
        "configured",
        host,
        config_path,
        managed=True,
        backupPath=str(backup) if backup else None,
    )


def uninstall_host(
    host: str,
    *,
    home: Path,
    environ: dict[str, str] | None = None,
    config_path: Path | None = None,
    state_path: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    environ = environ or dict(os.environ)
    config_path = config_path or _default_config_path(host, home, environ)
    state_path = _state_path(home, state_path)
    config = _load_object(config_path)
    state = _read_state(state_path)
    container = config.get(_container_key(host))
    current = container.get(SERVER_NAME) if isinstance(container, dict) else None
    receipt = state["hosts"].get(host)
    owned = bool(
        isinstance(receipt, dict)
        and receipt.get("managed") is True
        and receipt.get("configPath") == str(config_path)
        and current is not None
        and receipt.get("fingerprint") == _json_fingerprint(current)
    )
    if not owned:
        return _result("not_managed", host, config_path)
    if dry_run:
        return _result("would_remove", host, config_path)

    del container[SERVER_NAME]
    if not container:
        del config[_container_key(host)]
    del state["hosts"][host]
    _atomic_write_json(config_path, config)
    _atomic_write_json(state_path, state)
    return _result("removed", host, config_path)


def doctor_host(
    host: str,
    *,
    repo_root: Path,
    uv_command: Path,
    home: Path,
    environ: dict[str, str] | None = None,
    config_path: Path | None = None,
    state_path: Path | None = None,
) -> dict[str, Any]:
    environ = environ or dict(os.environ)
    config_path = config_path or _default_config_path(host, home, environ)
    state_path = _state_path(home, state_path)
    checks: dict[str, bool] = {
        "repoRoot": repo_root.is_dir(),
        "serverEntryPoint": (repo_root / "server/main.py").is_file(),
        "uvCommand": uv_command.is_file(),
        "configFile": config_path.is_file(),
    }
    try:
        config = _load_object(config_path)
        container = config.get(_container_key(host))
        current = container.get(SERVER_NAME) if isinstance(container, dict) else None
        checks["serverEntry"] = current == _desired_entry(host, repo_root, uv_command)
        state = _read_state(state_path)
        receipt = state["hosts"].get(host)
        checks["managedReceipt"] = bool(
            isinstance(receipt, dict)
            and receipt.get("managed") is True
            and current is not None
            and receipt.get("fingerprint") == _json_fingerprint(current)
        )
    except (OSError, ValueError):
        checks["serverEntry"] = False
        checks["managedReceipt"] = False
    return _result(
        "healthy" if all(checks.values()) else "unhealthy", host, config_path, checks=checks
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "uninstall", "doctor"))
    parser.add_argument("--host", required=True, choices=SUPPORTED_HOSTS)
    parser.add_argument("--repo-root", type=Path)
    parser.add_argument("--uv-command", type=Path)
    parser.add_argument("--home", type=Path, default=Path.home())
    parser.add_argument("--config-path", type=Path)
    parser.add_argument("--state-path", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.action in {"install", "doctor"} and (not args.repo_root or not args.uv_command):
            raise ValueError("--repo-root and --uv-command are required for install/doctor")
        if args.action == "install":
            result = install_host(
                args.host,
                repo_root=args.repo_root,
                uv_command=args.uv_command,
                home=args.home,
                config_path=args.config_path,
                state_path=args.state_path,
                dry_run=args.dry_run,
            )
        elif args.action == "uninstall":
            result = uninstall_host(
                args.host,
                home=args.home,
                config_path=args.config_path,
                state_path=args.state_path,
                dry_run=args.dry_run,
            )
        else:
            result = doctor_host(
                args.host,
                repo_root=args.repo_root,
                uv_command=args.uv_command,
                home=args.home,
                config_path=args.config_path,
                state_path=args.state_path,
            )
    except (OSError, ValueError) as exc:
        result = {
            "status": "error",
            "host": args.host,
            "server": SERVER_NAME,
            "errorCode": type(exc).__name__,
            "message": str(exc),
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] not in {"conflict", "error", "unhealthy"} else 2


if __name__ == "__main__":
    sys.exit(main())
