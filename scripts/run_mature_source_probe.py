"""Minimal CLI entrypoint for mature source probe report generation."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import server.live.mature_source_probe as mature_source_probe  # noqa: E402


DEFAULT_OUTPUT_PATH = Path(__file__).resolve().parents[1] / "mature_source_probe_report.md"


def main() -> int:
    report = mature_source_probe.compare_sources(_default_probe_rows())
    if not report.get("ok"):
        print(f"生成失败：{report.get('unavailableReason', 'unknown_error')}", file=sys.stderr)
        return 1

    markdown = mature_source_probe.render_probe_report(report)
    output_path = Path(DEFAULT_OUTPUT_PATH)
    output_path.write_text(markdown, encoding="utf-8")
    print(f"探测报告已写入 {output_path}")
    return 0


def _default_probe_rows() -> list[dict[str, object]]:
    return [
        {
            "sourceType": "poe_ninja",
            "shapeReport": {
                "ok": False,
                "responseShape": ["leagueBuilds"],
                "unavailableReason": "ascendancy-only payload",
            },
            "discoverability": "high",
            "popularityTrust": "high",
            "payloadRichness": "low",
            "sanitizationBurden": "medium",
            "duplicationRisk": "medium",
            "browserDependence": "medium",
        },
        {
            "sourceType": "pobb_in",
            "shapeReport": {
                "ok": True,
                "responseShape": ["build"],
                "rowShape": ["skills", "tree", "items"],
            },
            "discoverability": "medium",
            "popularityTrust": "medium",
            "payloadRichness": "high",
            "sanitizationBurden": "high",
            "duplicationRisk": "high",
            "browserDependence": "low",
        },
    ]


if __name__ == "__main__":
    raise SystemExit(main())
