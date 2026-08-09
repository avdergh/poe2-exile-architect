"""Build a self-contained Codex plugin distribution from the runtime bundle."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLATFORM = {"win32": "win-x64", "darwin": "mac-arm64", "linux": "linux-x64"}


def build_codex_plugin(
    *,
    version: str,
    platform: str,
    output_root: str | Path,
    physical_graph_dir: str | Path | None = None,
) -> dict[str, object]:
    out = Path(output_root).resolve()
    bundle_command = [
        sys.executable,
        str(ROOT / "scripts" / "build_bundle.py"),
        "--version",
        version,
        "--platform",
        platform,
        "--out",
        str(out),
    ]
    if physical_graph_dir is not None:
        bundle_command.extend(["--physical-graph-dir", str(physical_graph_dir)])
    subprocess.run(bundle_command, check=True, cwd=ROOT)

    runtime_stage = out / f"bundle-{platform}"
    plugin_stage = out / "codex-plugin" / "poe-bd-creator"
    if plugin_stage.exists():
        shutil.rmtree(plugin_stage)
    plugin_stage.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(runtime_stage, plugin_stage)
    shutil.copytree(
        ROOT / "poe-bd-creator-plugin",
        plugin_stage,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )

    required = (
        ".codex-plugin/plugin.json",
        ".mcp.json",
        "scripts/run_plugin_server.mjs",
        "scripts/run_plugin_server.py",
        "scripts/create_build.py",
        "scripts/research_mature_builds.py",
        "scripts/run_phase45_researcher_batch.py",
        "scripts/run_phase4_deep_review_acceptance.py",
        "scripts/run_judge_ninja_samples.py",
        "scripts/run_judge_user_samples.py",
        "server/main.py",
        "server/mcp/knowledge_server.py",
        "server/mcp/build_server.py",
        "server/mcp/research_server.py",
        "server/mcp/learning_server.py",
        "server/MCP_BOOTSTRAP.md",
        "server/MCP_KNOWLEDGE_BOOTSTRAP.md",
        "server/MCP_BUILD_BOOTSTRAP.md",
        "server/MCP_RESEARCH_BOOTSTRAP.md",
        "server/MCP_LEARNING_BOOTSTRAP.md",
        "data/corpus.sqlite",
        "data/mature_build_learning/release.sqlite",
        "data/comparative_learning/learning-memory.seed.jsonl",
        "data/physical_graph/seed.json",
        "pob/pob_headless.lua",
    )
    missing = [name for name in required if not (plugin_stage / name).exists()]
    if missing:
        raise FileNotFoundError("Codex plugin distribution is incomplete: " + ", ".join(missing))

    plugin_manifest = json.loads(
        (plugin_stage / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    plugin_version = str(plugin_manifest["version"])
    archive = out / f"poe-bd-creator-codex-{plugin_version}-{platform}.zip"
    archive.unlink(missing_ok=True)
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as handle:
        for path in plugin_stage.rglob("*"):
            if path.is_file():
                handle.write(path, path.relative_to(plugin_stage.parent))

    report = {
        "status": "built",
        "pluginVersion": plugin_version,
        "runtimeVersion": version,
        "platform": platform,
        "stage": str(plugin_stage),
        "archive": str(archive),
        "archiveSizeBytes": archive.stat().st_size,
    }
    (out / "codex-plugin-build.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--platform", default=PLATFORM.get(sys.platform, "unknown"))
    parser.add_argument("--out", default=str(ROOT / "dist"))
    parser.add_argument("--physical-graph-dir")
    args = parser.parse_args(argv)
    report = build_codex_plugin(
        version=args.version,
        platform=args.platform,
        output_root=args.out,
        physical_graph_dir=args.physical_graph_dir,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
