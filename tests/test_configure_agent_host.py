from __future__ import annotations

import json
from pathlib import Path

from scripts import configure_agent_host as host_config


def _runtime(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    (repo / "server").mkdir(parents=True)
    (repo / "server/main.py").write_text("", encoding="utf-8")
    uv = tmp_path / "uv"
    uv.write_text("", encoding="utf-8")
    return repo, uv


def test_opencode_install_preserves_config_and_is_idempotent(tmp_path):
    repo, uv = _runtime(tmp_path)
    config_path = tmp_path / "opencode.json"
    state_path = tmp_path / "state.json"
    config_path.write_text(json.dumps({"theme": "system", "mcp": {"other": {}}}))

    first = host_config.install_host(
        "opencode",
        repo_root=repo,
        uv_command=uv,
        home=tmp_path,
        config_path=config_path,
        state_path=state_path,
    )
    second = host_config.install_host(
        "opencode",
        repo_root=repo,
        uv_command=uv,
        home=tmp_path,
        config_path=config_path,
        state_path=state_path,
    )

    payload = json.loads(config_path.read_text(encoding="utf-8"))
    entry = payload["mcp"][host_config.SERVER_NAME]
    assert first["status"] == "configured"
    assert second == {
        "status": "already_configured",
        "host": "opencode",
        "server": host_config.SERVER_NAME,
        "configPath": str(config_path),
        "managed": True,
    }
    assert payload["theme"] == "system"
    assert payload["mcp"]["other"] == {}
    assert entry == {
        "type": "local",
        "command": [str(uv.resolve()), "run", "python", "-m", "server.main"],
        "cwd": str(repo.resolve()),
        "environment": {"PYTHONPATH": str(repo.resolve())},
        "enabled": True,
        "timeout": 120000,
    }
    assert config_path.with_name("opencode.json.poe-bd-creator.bak").exists()


def test_owned_entry_can_be_updated_and_removed(tmp_path):
    repo, uv = _runtime(tmp_path)
    config_path = tmp_path / "mcp.json"
    state_path = tmp_path / "state.json"
    host_config.install_host(
        "cursor",
        repo_root=repo,
        uv_command=uv,
        home=tmp_path,
        config_path=config_path,
        state_path=state_path,
    )
    next_repo = tmp_path / "next-repo"
    (next_repo / "server").mkdir(parents=True)
    (next_repo / "server/main.py").write_text("", encoding="utf-8")

    updated = host_config.install_host(
        "cursor",
        repo_root=next_repo,
        uv_command=uv,
        home=tmp_path,
        config_path=config_path,
        state_path=state_path,
    )
    removed = host_config.uninstall_host(
        "cursor",
        home=tmp_path,
        config_path=config_path,
        state_path=state_path,
    )

    assert updated["status"] == "configured"
    assert removed["status"] == "removed"
    assert "mcpServers" not in json.loads(config_path.read_text(encoding="utf-8"))


def test_unmanaged_conflict_is_never_overwritten_or_removed(tmp_path):
    repo, uv = _runtime(tmp_path)
    config_path = tmp_path / "claude.json"
    state_path = tmp_path / "state.json"
    original = {"mcpServers": {host_config.SERVER_NAME: {"command": "custom"}}}
    config_path.write_text(json.dumps(original), encoding="utf-8")

    installed = host_config.install_host(
        "claude",
        repo_root=repo,
        uv_command=uv,
        home=tmp_path,
        config_path=config_path,
        state_path=state_path,
    )
    removed = host_config.uninstall_host(
        "claude",
        home=tmp_path,
        config_path=config_path,
        state_path=state_path,
    )

    assert installed["status"] == "conflict"
    assert removed["status"] == "not_managed"
    assert json.loads(config_path.read_text(encoding="utf-8")) == original


def test_doctor_checks_exact_runtime_binding(tmp_path):
    repo, uv = _runtime(tmp_path)
    config_path = tmp_path / "opencode.json"
    state_path = tmp_path / "state.json"
    host_config.install_host(
        "opencode",
        repo_root=repo,
        uv_command=uv,
        home=tmp_path,
        config_path=config_path,
        state_path=state_path,
    )

    healthy = host_config.doctor_host(
        "opencode",
        repo_root=repo,
        uv_command=uv,
        home=tmp_path,
        config_path=config_path,
        state_path=state_path,
    )
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["mcp"][host_config.SERVER_NAME]["cwd"] = "wrong"
    config_path.write_text(json.dumps(payload), encoding="utf-8")
    unhealthy = host_config.doctor_host(
        "opencode",
        repo_root=repo,
        uv_command=uv,
        home=tmp_path,
        config_path=config_path,
        state_path=state_path,
    )

    assert healthy["status"] == "healthy"
    assert unhealthy["status"] == "unhealthy"
    assert unhealthy["checks"]["serverEntry"] is False
    assert unhealthy["checks"]["managedReceipt"] is False
