from __future__ import annotations

from scripts import run_phase4_research_memory_benchmark as benchmark


def test_phase4_research_memory_benchmark_returns_safe_pass_report():
    report = benchmark.run_benchmark()

    assert report["status"] == "pass"
    assert report["safeArtifactOnly"] is True
    assert report["metrics"]["retrievalHitCount"] == 1
    assert report["metrics"]["duplicateRejected"] is True
    assert "eNrt" not in str(report)
    assert "rawXml" not in str(report)
