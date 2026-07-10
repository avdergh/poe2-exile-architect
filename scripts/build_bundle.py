"""Assemble a self-contained poe2-build-mcp bundle and zip it to a `.mcpb`.

Stages the server, the PoB engine subset (src + runtime/lua + headless shim), the corpus,
vendored Python deps, and — if present at runtime/luajit/<platform>/ — a per-OS LuaJIT binary.
Then zips everything to dist/poe2-build-mcp-<version>-<platform>.mcpb.

Run per-OS (locally or in CI). LuaJIT is supplied by the caller/CI in runtime/luajit/<platform>/
(the server auto-detects a bundled binary there via server/paths.py).

    uv run python scripts/build_bundle.py --version 2026.06.19
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLATFORM = {"win32": "win-x64", "darwin": "mac-arm64", "linux": "linux-x64"}

# GUI art the headless engine never loads (rendering/image loading is stubbed) — excluded
# from bundles. This is the bulk of PoB's size (passive-tree/gem textures).
ART_SUFFIXES = (
    ".dds",
    ".zst",
    ".png",
    ".jpg",
    ".jpeg",
    ".tga",
    ".gif",
    ".bk2",
    ".mp4",
    ".ogg",
    ".mp3",
)


def _copy(src: Path, dst: Path, skip_art: bool = False) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        patterns = ["__pycache__", "*.pyc"]
        if skip_art:
            patterns += [f"*{ext}" for ext in ART_SUFFIXES]
        shutil.copytree(src, dst, ignore=shutil.ignore_patterns(*patterns))
    else:
        shutil.copy2(src, dst)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default="dev", help="bundle/data version stamp")
    ap.add_argument("--platform", default=PLATFORM.get(sys.platform, "unknown"))
    ap.add_argument("--out", default=str(ROOT / "dist"))
    args = ap.parse_args()

    corpus = ROOT / "data" / "corpus.sqlite"
    if not corpus.exists():
        print("corpus missing; building it…")
        subprocess.run([sys.executable, "-m", "pipeline.build_corpus"], check=True, cwd=ROOT)

    stage = Path(args.out) / f"bundle-{args.platform}"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)

    # Server code + manifest + bundle icon (shown for the extension in Claude Desktop)
    _copy(ROOT / "server", stage / "server")
    _copy(ROOT / "manifest.json", stage / "manifest.json")
    _copy(ROOT / "assets" / "icon.png", stage / "assets" / "icon.png")

    # Bundled seed data
    _copy(corpus, stage / "data" / "corpus.sqlite")
    _copy(
        ROOT / "data" / "compatibility" / "pob.json",
        stage / "data" / "compatibility" / "pob.json",
    )
    (stage / "data" / "VERSION").write_text(args.version)

    # Reference/calibration build set (committed source, small) — ships beside the corpus so
    # list_reference_builds/benchmark_build work offline. Self-update doesn't touch it; it tracks
    # the bundled code/tree version and refreshes on .mcpb reinstall.
    refbuilds = ROOT / "data" / "reference_builds.json"
    if refbuilds.exists():
        _copy(refbuilds, stage / "data" / "reference_builds.json")
    else:
        print("NOTE: data/reference_builds.json missing — reference-build tools will be empty.")

    # PoB engine (the parts the headless engine needs at runtime)
    _copy(ROOT / "pob" / "pob_headless.lua", stage / "pob" / "pob_headless.lua")
    _copy(ROOT / "pob" / "PINNED.md", stage / "pob" / "PINNED.md")
    pob = ROOT / "pob" / "PathOfBuilding-PoE2"
    _copy(pob / "src", stage / "pob" / "PathOfBuilding-PoE2" / "src", skip_art=True)
    _copy(
        pob / "runtime" / "lua",
        stage / "pob" / "PathOfBuilding-PoE2" / "runtime" / "lua",
        skip_art=True,
    )

    # Vendor Python dependencies into lib/ (manifest puts this on PYTHONPATH).
    # Prefer uv (present in CI) for speed; fall back to pip.
    print("vendoring python deps into lib/ …")
    uv = shutil.which("uv")
    if uv:
        cmd = [uv, "pip", "install", "--target", str(stage / "lib"), "mcp>=1.2"]
    else:
        cmd = [
            sys.executable,
            "-m",
            "pip",
            "install",
            "-q",
            "--target",
            str(stage / "lib"),
            "mcp>=1.2",
        ]
    subprocess.run(cmd, check=True)

    # Per-OS LuaJIT binary, if provided (CI builds this).
    luajit = ROOT / "runtime" / "luajit" / args.platform
    if luajit.exists():
        _copy(luajit, stage / "runtime" / "luajit" / args.platform)
    else:
        print(
            f"NOTE: no LuaJIT at runtime/luajit/{args.platform}/ — bundle will need a system LuaJIT."
        )

    # Zip to .mcpb
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    mcpb = out / f"poe2-build-mcp-{args.version}-{args.platform}.mcpb"
    if mcpb.exists():
        mcpb.unlink()
    with zipfile.ZipFile(mcpb, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in stage.rglob("*"):
            if p.is_file():
                zf.write(p, p.relative_to(stage))

    print(f"\nbundle: {mcpb}  ({mcpb.stat().st_size / 1e6:.1f} MB)")
    print(f"staging: {stage}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
