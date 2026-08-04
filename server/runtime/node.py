"""Discover a usable Node.js toolchain without assuming a global installation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import sys


NODE_ENV = "POE_BD_NODE_EXECUTABLE"
NPX_ENV = "POE_BD_NPX_EXECUTABLE"
PNPM_ENV = "POE_BD_PNPM_EXECUTABLE"


@dataclass(frozen=True)
class PackageRunner:
    """A package runner capable of executing a one-shot npm package."""

    kind: str
    executable: Path


def resolve_node_executable(
    configured: str | Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Path | None:
    """Resolve Node from explicit configuration, PATH, or host-bundled runtimes."""
    env = environ if environ is not None else os.environ
    home_dir = Path(home) if home is not None else Path.home()
    candidates = _path_candidates(configured, env.get(NODE_ENV))
    candidates.extend(_which_candidates(("node", "node.cmd"), env))

    executable_name = "node.exe" if os.name == "nt" else "node"
    for dependencies in _codex_dependency_roots(home_dir):
        candidates.append(dependencies / "node" / "bin" / executable_name)
    for runtime_bin in _legacy_codex_node_bins(home_dir):
        candidates.append(runtime_bin / executable_name)
    return _first_executable(candidates)


def resolve_package_runner(
    *,
    node_executable: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> PackageRunner | None:
    """Resolve npx first, then pnpm, including Codex-bundled toolchains."""
    env = environ if environ is not None else os.environ
    home_dir = Path(home) if home is not None else Path.home()
    node = (
        Path(node_executable)
        if node_executable is not None
        else resolve_node_executable(environ=env, home=home_dir)
    )

    npx_candidates = _path_candidates(env.get(NPX_ENV))
    npx_candidates.extend(_which_candidates(("npx", "npx.cmd"), env))
    pnpm_candidates = _path_candidates(env.get(PNPM_ENV))
    pnpm_candidates.extend(_which_candidates(("pnpm", "pnpm.cmd"), env))

    if node is not None:
        npx_candidates.extend(
            [
                node.parent / ("npx.cmd" if os.name == "nt" else "npx"),
                node.parent / ("npx.exe" if os.name == "nt" else "npx"),
            ]
        )

    for dependencies in _codex_dependency_roots(home_dir):
        npx_candidates.extend(
            [
                dependencies / "bin" / "override" / _command_name("npx"),
                dependencies / "bin" / "fallback" / _command_name("npx"),
            ]
        )
        pnpm_candidates.extend(
            [
                dependencies / "bin" / "override" / _command_name("pnpm"),
                dependencies / "bin" / "fallback" / _command_name("pnpm"),
            ]
        )

    npx = _first_executable(npx_candidates)
    if npx is not None:
        return PackageRunner(kind="npx", executable=npx)
    pnpm = _first_executable(pnpm_candidates)
    if pnpm is not None:
        return PackageRunner(kind="pnpm", executable=pnpm)
    return None


def _codex_dependency_roots(home: Path) -> list[Path]:
    root = home / ".cache" / "codex-runtimes"
    if not root.is_dir():
        return []
    candidates: list[Path] = []
    try:
        runtimes = list(root.iterdir())
    except OSError:
        return []
    for runtime in runtimes:
        dependencies = runtime / "dependencies"
        if dependencies.is_dir():
            candidates.append(dependencies)
    return _newest_first(candidates)


def _legacy_codex_node_bins(home: Path) -> list[Path]:
    if os.name == "nt":
        root = home / "AppData" / "Local" / "OpenAI" / "Codex" / "runtimes" / "cua_node"
    elif sys.platform == "darwin":
        root = (
            home / "Library" / "Application Support" / "OpenAI" / "Codex" / "runtimes" / "cua_node"
        )
    else:
        root = home / ".local" / "share" / "OpenAI" / "Codex" / "runtimes" / "cua_node"
    if not root.is_dir():
        return []
    try:
        runtimes = list(root.iterdir())
    except OSError:
        return []
    return _newest_first([path / "bin" for path in runtimes if path.is_dir()])


def _newest_first(paths: list[Path]) -> list[Path]:
    def modified(path: Path) -> float:
        try:
            return path.stat().st_mtime
        except OSError:
            return 0.0

    return sorted(paths, key=modified, reverse=True)


def _which_candidates(names: tuple[str, ...], environ: Mapping[str, str]) -> list[Path]:
    path_value = environ.get("PATH", "")
    return [
        Path(found) for name in names if (found := shutil.which(name, path=path_value)) is not None
    ]


def _path_candidates(*values: str | Path | None) -> list[Path]:
    return [Path(value).expanduser() for value in values if value]


def _first_executable(candidates: list[Path]) -> Path | None:
    seen: set[str] = set()
    for candidate in candidates:
        key = os.path.normcase(str(candidate))
        if key in seen:
            continue
        seen.add(key)
        if not candidate.is_file():
            continue
        if os.name != "nt" and not os.access(candidate, os.X_OK):
            continue
        return candidate.resolve()
    return None


def _command_name(name: str) -> str:
    return f"{name}.cmd" if os.name == "nt" else name
