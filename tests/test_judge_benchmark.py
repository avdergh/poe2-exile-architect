from __future__ import annotations

import json

from server.judge import benchmark


def test_benchmark_report_has_stable_fixture_order_and_context(tmp_path, monkeypatch):
    monkeypatch.setattr(benchmark.paths, "user_data_dir", lambda: tmp_path)

    report = benchmark.run_judge_benchmark(engine=None, persist=True)

    ids = [case["snapshotId"] for case in report["cases"]]
    assert ids == sorted(ids)
    assert report["fixtureSetId"] == benchmark.FIXTURE_SET_ID
    assert report["reproducibility"]["evaluatorVersion"]
    written = tmp_path / "runtime" / "judge_baseline_phase1.json"
    assert written.exists()
    loaded = json.loads(written.read_text(encoding="utf-8"))
    assert loaded["fixtureSetId"] == benchmark.FIXTURE_SET_ID
