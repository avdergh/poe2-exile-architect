"""Pinned-PoB E2E smoke for the Research active-snapshot readback."""

from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.compute.engine import PobEngine  # noqa: E402
from server.knowledge import research_readback  # noqa: E402


def main() -> int:
    with PobEngine(show_engine_logs=False) as engine:
        engine.new_build()
        engine.paste_skill("Fireball 20/0  1")
        xml = engine.get_xml()
    result = research_readback.build_safe_readback(
        xml,
        source_hash_ref="source-hash:readback-smoke",
        version_context={"pobVersionOrCommit": "pinned"},
    )
    if result.get("status") != "available":
        raise RuntimeError(f"Research readback unavailable: {result.get('errorCode')}")
    if result.get("stateBinding", {}).get("weaponSetState") != "active":
        raise RuntimeError("Research readback did not bind the active weapon state")
    if any(key in result.get("stats", {}) for key in ("TotalDPS", "FullDPS")):
        raise RuntimeError("Research readback exposed out-of-scope damage metrics")
    serialized = str(result).casefold()
    if "<pathofbuilding" in serialized or "rawxml" in serialized:
        raise RuntimeError("Research readback exposed raw source material")
    print("RESEARCH READBACK SMOKE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
