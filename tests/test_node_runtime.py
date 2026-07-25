from __future__ import annotations

import os
from pathlib import Path

from server.runtime import node


def _touch_executable(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    if os.name != "nt":
        path.chmod(0o755)
    return path


def _node_name() -> str:
    return "node.exe" if os.name == "nt" else "node"


def _command_name(name: str) -> str:
    return f"{name}.cmd" if os.name == "nt" else name


def test_node_runtime_prefers_explicit_configuration(tmp_path):
    explicit = _touch_executable(tmp_path / "configured" / _node_name())
    bundled = _touch_executable(
        tmp_path
        / "home"
        / ".cache"
        / "codex-runtimes"
        / "primary"
        / "dependencies"
        / "node"
        / "bin"
        / _node_name()
    )

    resolved = node.resolve_node_executable(
        explicit,
        environ={"PATH": ""},
        home=tmp_path / "home",
    )

    assert resolved == explicit.resolve()
    assert resolved != bundled.resolve()


def test_node_runtime_discovers_codex_primary_runtime(tmp_path):
    bundled = _touch_executable(
        tmp_path
        / ".cache"
        / "codex-runtimes"
        / "codex-primary-runtime"
        / "dependencies"
        / "node"
        / "bin"
        / _node_name()
    )

    resolved = node.resolve_node_executable(environ={"PATH": ""}, home=tmp_path)

    assert resolved == bundled.resolve()


def test_package_runner_falls_back_to_codex_pnpm(tmp_path):
    dependencies = tmp_path / ".cache" / "codex-runtimes" / "codex-primary-runtime" / "dependencies"
    bundled_node = _touch_executable(dependencies / "node" / "bin" / _node_name())
    bundled_pnpm = _touch_executable(dependencies / "bin" / "fallback" / _command_name("pnpm"))

    runner = node.resolve_package_runner(
        node_executable=bundled_node,
        environ={"PATH": ""},
        home=tmp_path,
    )

    assert runner is not None
    assert runner.kind == "pnpm"
    assert runner.executable == bundled_pnpm.resolve()


def test_package_runner_prefers_explicit_npx(tmp_path):
    explicit_npx = _touch_executable(tmp_path / "configured" / _command_name("npx"))
    bundled_node = _touch_executable(tmp_path / "node" / _node_name())
    bundled_pnpm = _touch_executable(
        tmp_path
        / ".cache"
        / "codex-runtimes"
        / "codex-primary-runtime"
        / "dependencies"
        / "bin"
        / "fallback"
        / _command_name("pnpm")
    )

    runner = node.resolve_package_runner(
        node_executable=bundled_node,
        environ={"PATH": "", node.NPX_ENV: str(explicit_npx)},
        home=tmp_path,
    )

    assert runner is not None
    assert runner.kind == "npx"
    assert runner.executable == explicit_npx.resolve()
    assert runner.executable != bundled_pnpm.resolve()
