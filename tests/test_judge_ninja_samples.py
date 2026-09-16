from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from scripts import run_judge_ninja_samples


@pytest.mark.parametrize(
    ("os_name", "platform", "runtime_parent", "browser_executable"),
    [
        ("nt", "win32", "AppData/Local", "chrome-win64/chrome.exe"),
        ("posix", "linux", ".local/share", "chrome-linux/chrome"),
        (
            "posix",
            "darwin",
            "Library/Application Support",
            "chrome-mac/Chromium.app/Contents/MacOS/Chromium",
        ),
    ],
    ids=["windows", "linux", "macos"],
)
def test_discover_playwright_runtime_tracks_current_codex_runtime_hash(
    tmp_path, monkeypatch, os_name, platform, runtime_parent, browser_executable
):
    # Simulate the discovery module's platform without changing pathlib's host platform.
    monkeypatch.setattr(run_judge_ninja_samples, "os", SimpleNamespace(name=os_name))
    monkeypatch.setattr(run_judge_ninja_samples, "sys", SimpleNamespace(platform=platform))
    monkeypatch.setattr(run_judge_ninja_samples.shutil, "which", lambda _name: None)
    home = tmp_path / "home"
    runtime_bin = (
        home
        / runtime_parent
        / "OpenAI"
        / "Codex"
        / "runtimes"
        / "cua_node"
        / "new-runtime-hash"
        / "bin"
    )
    playwright = runtime_bin / "node_modules" / "playwright"
    playwright.mkdir(parents=True)
    (playwright / "package.json").write_text("{}", encoding="utf-8")
    (playwright / "index.js").write_text("module.exports = {};", encoding="utf-8")
    node = runtime_bin / ("node.exe" if os_name == "nt" else "node")
    node.write_bytes(b"node")
    browser_root = tmp_path / "local" / "ms-playwright" / "chromium-9999"
    chromium = browser_root / browser_executable
    chromium.parent.mkdir(parents=True)
    chromium.write_bytes(b"chrome")

    result = run_judge_ninja_samples.discover_playwright_runtime(
        home=home,
        environ={"LOCALAPPDATA": str(tmp_path / "local")},
    )

    assert result == {
        "nodeExecutable": node.resolve(),
        "playwrightPackagePath": playwright.resolve(),
        "chromiumPath": chromium.resolve(),
    }


def test_discover_playwright_runtime_prefers_explicit_environment_overrides(tmp_path):
    node = tmp_path / "node.exe"
    node.write_bytes(b"node")
    playwright = tmp_path / "playwright"
    playwright.mkdir()
    (playwright / "package.json").write_text("{}", encoding="utf-8")
    (playwright / "index.js").write_text("module.exports = {};", encoding="utf-8")
    chromium = tmp_path / "chrome.exe"
    chromium.write_bytes(b"chrome")

    result = run_judge_ninja_samples.discover_playwright_runtime(
        home=tmp_path / "empty-home",
        environ={
            run_judge_ninja_samples.NODE_ENV: str(node),
            run_judge_ninja_samples.PLAYWRIGHT_ENV: str(playwright),
            run_judge_ninja_samples.CHROMIUM_ENV: str(chromium),
        },
    )

    assert result["nodeExecutable"] == node.resolve()
    assert result["playwrightPackagePath"] == playwright.resolve()
    assert result["chromiumPath"] == chromium.resolve()


def test_playwright_list_fetch_waits_for_character_link_for_at_most_15_seconds(
    monkeypatch, tmp_path
):
    captured: dict[str, object] = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return SimpleNamespace(returncode=0, stdout="<html></html>", stderr="")

    monkeypatch.setattr(run_judge_ninja_samples.subprocess, "run", fake_run)
    driver = object.__new__(run_judge_ninja_samples.PlaywrightHtmlDriver)
    driver.node_executable = "node"
    driver.playwright_package_path = tmp_path / "playwright"
    driver.chromium_path = tmp_path / "chrome.exe"

    driver.fetch_html("https://poe.ninja/poe2/builds/current?class=Martial+Artist")

    script = captured["args"][2]
    assert "waitForSelector" in script
    assert 'a[href*="/character/"]' in script
    assert "timeout: 15000" in script
    assert "waitUntil: 'commit'" in script
    assert captured["kwargs"]["timeout"] == 90


def test_playwright_detail_fetch_waits_for_import_input(monkeypatch, tmp_path):
    captured: dict[str, object] = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return SimpleNamespace(returncode=0, stdout="<html></html>", stderr="")

    monkeypatch.setattr(run_judge_ninja_samples.subprocess, "run", fake_run)
    driver = object.__new__(run_judge_ninja_samples.PlaywrightHtmlDriver)
    driver.node_executable = "node"
    driver.playwright_package_path = tmp_path / "playwright"
    driver.chromium_path = tmp_path / "chrome.exe"

    driver.fetch_html("https://poe.ninja/poe2/builds/runesofaldur/character/account/character")

    script = captured["args"][2]
    assert 'input[aria-label="Import code for Path of Building"]' in script
    assert "timeout: 30000" in script
    assert captured["kwargs"]["timeout"] == 90


def test_playwright_fetch_has_a_hard_process_timeout(monkeypatch, tmp_path):
    def fake_run(*_args, **_kwargs):
        raise run_judge_ninja_samples.subprocess.TimeoutExpired("node", 90)

    monkeypatch.setattr(run_judge_ninja_samples.subprocess, "run", fake_run)
    driver = object.__new__(run_judge_ninja_samples.PlaywrightHtmlDriver)
    driver.node_executable = "node"
    driver.playwright_package_path = tmp_path / "playwright"
    driver.chromium_path = tmp_path / "chrome.exe"

    with pytest.raises(
        run_judge_ninja_samples.NinjaSampleError,
        match="playwright_fetch_timed_out",
    ):
        driver.fetch_html("https://poe.ninja/poe2/builds/current")


def test_extract_character_links_from_rendered_html_reads_unique_character_urls():
    html = """
<html>
  <body>
    <tr>
      <td><a href="/poe2/builds/runesofaldur/character/acctA/CharA">CharA</a></td>
      <td><div>98<img alt="Stormweaver" /></div></td>
    </tr>
    <tr>
      <td><a href="/poe2/builds/runesofaldur/character/acctB/CharB">CharB</a></td>
      <td><div>97<img alt="Deadeye" /></div></td>
    </tr>
    <tr>
      <td><a href="/poe2/builds/runesofaldur/character/acctA/CharA">CharA</a></td>
      <td><div>98<img alt="Stormweaver" /></div></td>
    </tr>
  </body>
</html>
"""

    rows = run_judge_ninja_samples.extract_character_links_from_rendered_html(
        html, league_url="runesofaldur"
    )

    assert rows == [
        {
            "account": "acctA",
            "name": "CharA",
            "ascendancy": "Stormweaver",
            "level": 98,
            "url": "https://poe.ninja/poe2/builds/runesofaldur/character/acctA/CharA",
        },
        {
            "account": "acctB",
            "name": "CharB",
            "ascendancy": "Deadeye",
            "level": 97,
            "url": "https://poe.ninja/poe2/builds/runesofaldur/character/acctB/CharB",
        },
    ]


def test_build_character_url_uses_expected_shape():
    row = {"account": "acctA", "name": "CharA"}

    url = run_judge_ninja_samples.build_character_url("runesofaldur", row)

    assert url == "https://poe.ninja/poe2/builds/runesofaldur/character/acctA/CharA"


def test_sample_rows_balances_ascendancies_before_filling_remainder():
    rows = [
        {"account": "a1", "name": "n1", "ascendancy": "A", "level": 98},
        {"account": "a2", "name": "n2", "ascendancy": "A", "level": 97},
        {"account": "a3", "name": "n3", "ascendancy": "A", "level": 96},
        {"account": "b1", "name": "m1", "ascendancy": "B", "level": 98},
        {"account": "b2", "name": "m2", "ascendancy": "B", "level": 97},
        {"account": "c1", "name": "k1", "ascendancy": "C", "level": 98},
    ]

    sampled = run_judge_ninja_samples.sample_rows(rows, target_count=5, minimum_per_ascendancy=1)

    assert {row["ascendancy"] for row in sampled} == {"A", "B", "C"}
    assert len(sampled) == 5


def test_finalize_sample_classification_marks_low_scoring_pass_sample_for_review():
    sample = {
        "snapshotId": "s1",
        "pass": True,
        "aggregateScore": {"value": 0.42},
        "scoreVector": {
            "offense": {"value": 0.62},
            "defense": {"value": 0.41},
            "recovery": {"value": 0.77},
            "mobility": {"value": 0.58},
        },
        "hardFailures": [],
        "caveats": [],
    }

    out = run_judge_ninja_samples.finalize_sample_classification(sample)

    assert out["scoreReviewNeeded"] is True
    assert out["scoreReviewReasons"] == ["aggregate_below_0_5", "defense_below_0_5"]
    assert out["finalClassification"] == "judge_score_review_required"


def test_finalize_sample_classification_separates_severe_playability_from_legality():
    sample = {
        "pass": True,
        "hardFailures": [],
        "playabilityFailures": ["severe_elemental_resistance_shortfall"],
        "caveats": [],
        "modelability": {"status": "full", "coreBlocked": False},
        "aggregateScore": {"value": 0.4},
        "scoreVector": {},
    }

    out = run_judge_ninja_samples.finalize_sample_classification(sample)

    assert out["pass"] is True
    assert out["finalClassification"] == "severe_playability_failure"
    assert out["scoreReviewNeeded"] is False


def test_finalize_sample_classification_clears_review_for_known_limited_offense_gap():
    sample = {
        "snapshotId": "s1b",
        "pass": True,
        "aggregateScore": {"value": 0.58},
        "scoreVector": {
            "offense": {"value": 0.0},
            "defense": {"value": 1.0},
            "recovery": {"value": 0.89},
            "mobility": {"value": 1.0},
        },
        "scoreBreakdown": {
            "offense": {
                "rawValue": 484.95,
                "provenance": "isolated_full_dps_rollup",
                "evidenceLevel": "limited",
            }
        },
        "hardFailures": [],
        "caveats": ["limited_offense_floor_unverified_caveat", "full_dps_rollup_caveat"],
    }

    out = run_judge_ninja_samples.finalize_sample_classification(sample)

    assert out["scoreReviewNeeded"] is False
    assert out["finalClassification"] == "judge_offense_evidence_gap"


def test_finalize_sample_classification_clears_review_for_known_avoidance_defense_gap():
    sample = {
        "snapshotId": "s1c",
        "pass": True,
        "aggregateScore": {"value": 0.57},
        "scoreVector": {
            "offense": {"value": 0.55},
            "defense": {"value": 0.41},
            "recovery": {"value": 0.89},
            "mobility": {"value": 1.0},
        },
        "scoreBreakdown": {
            "defense": {"scorePolicy": "avoidance_evasion_hybrid"},
            "physical": {"rawValue": 4983.0},
        },
        "defenseModel": {
            "avoidanceModel": {"evadeChance": 67.0},
            "hitMitigationModel": {"totalEHP": 36842.0},
        },
        "hardFailures": [],
        "caveats": ["full_dps_rollup_caveat"],
    }

    out = run_judge_ninja_samples.finalize_sample_classification(sample)

    assert out["scoreReviewNeeded"] is False
    assert out["finalClassification"] == "judge_pass_and_scores_explained"


def test_finalize_sample_classification_clears_review_for_explained_real_low_scores():
    sample = {
        "snapshotId": "s1d",
        "pass": True,
        "aggregateScore": {"value": 0.38},
        "scoreVector": {
            "offense": {"value": 0.58},
            "defense": {"value": 0.21},
            "recovery": {"value": 0.08},
            "mobility": {"value": 1.0},
        },
        "scoreBreakdown": {
            "offense": {"evidenceLevel": "strong"},
            "defense": {"scorePolicy": "max_hit_shortboard"},
            "physical": {"rawValue": 4258.0},
            "recovery": {"rawValue": 48.1, "primaryPool": 2811.0, "qualityFloor": 42.165},
            "mobility": {"scorePolicy": "movement_speed", "rawValue": 1.8},
        },
        "defenseModel": {
            "avoidanceModel": {"evadeChance": 48.0},
            "hitMitigationModel": {"totalEHP": 17139.0},
        },
        "hardFailures": [],
        "caveats": [],
    }

    out = run_judge_ninja_samples.finalize_sample_classification(sample)

    assert out["scoreReviewNeeded"] is False
    assert out["finalClassification"] == "judge_pass_and_scores_explained"


def test_finalize_sample_classification_marks_hard_failure_as_real_legality_failure():
    sample = {
        "snapshotId": "s2",
        "pass": False,
        "hardFailures": ["attribute_requirement_unmet"],
        "physicalInvalidFailures": ["attribute_requirement_unmet"],
        "caveats": [],
    }

    out = run_judge_ninja_samples.finalize_sample_classification(sample)

    assert out["scoreReviewNeeded"] is False
    assert out["finalClassification"] == "real_legality_failure"


def test_finalize_sample_classification_treats_reference_attr_mismatch_as_unsolved_gap():
    sample = {
        "snapshotId": "s2b",
        "pass": False,
        "hardFailures": [],
        "physicalInvalidFailures": [],
        "caveats": ["trusted_reference_attribute_requirement_mismatch_caveat"],
        "rewardEligible": "limited",
    }

    out = run_judge_ninja_samples.finalize_sample_classification(sample)

    assert out["scoreReviewNeeded"] is False
    assert out["finalClassification"] == "judge_unsolved_modelability_gap"


def test_finalize_sample_classification_prefers_unsolved_gap_for_suspect_state_failure():
    sample = {
        "snapshotId": "s3",
        "pass": False,
        "hardFailures": ["uncapped_resistance"],
        "physicalInvalidFailures": [],
        "caveats": ["state_or_import_suspect_caveat", "defense_state_unverified_caveat"],
    }

    out = run_judge_ninja_samples.finalize_sample_classification(sample)

    assert out["finalClassification"] == "judge_unsolved_modelability_gap"


def test_finalize_sample_classification_keeps_source_data_problem():
    sample = {
        "snapshotId": "s3b",
        "pass": False,
        "hardFailures": ["pob_compute_failed"],
        "physicalInvalidFailures": [],
        "caveats": ["source_data_problem_caveat"],
        "finalClassification": "source_data_problem",
    }

    out = run_judge_ninja_samples.finalize_sample_classification(sample)

    assert out["finalClassification"] == "source_data_problem"


def test_finalize_sample_classification_promotes_source_data_problem_caveat():
    sample = {
        "snapshotId": "s3c",
        "pass": False,
        "hardFailures": ["uncapped_resistance"],
        "physicalInvalidFailures": [],
        "caveats": ["source_data_problem_caveat", "state_or_import_suspect_caveat"],
    }

    out = run_judge_ninja_samples.finalize_sample_classification(sample)

    assert out["finalClassification"] == "source_data_problem"


def test_summarize_results_counts_pass_review_and_classifications():
    summary = run_judge_ninja_samples.summarize_results(
        [
            {
                "pass": True,
                "scoreReviewNeeded": False,
                "finalClassification": "judge_pass_and_scores_explained",
            },
            {
                "pass": True,
                "scoreReviewNeeded": True,
                "finalClassification": "judge_unsolved_modelability_gap",
            },
            {
                "pass": False,
                "scoreReviewNeeded": False,
                "finalClassification": "real_legality_failure",
            },
        ]
    )

    assert summary == {
        "sampleCount": 3,
        "passCount": 2,
        "scoreReviewCount": 1,
        "classifications": {
            "judge_pass_and_scores_explained": 1,
            "judge_unsolved_modelability_gap": 1,
            "real_legality_failure": 1,
        },
    }


def test_evaluate_ninja_sample_row_uses_browser_html_and_finalizes(monkeypatch):
    class _FakeBrowser:
        def fetch_html(self, url: str) -> str:
            assert url == "https://poe.ninja/poe2/builds/runesofaldur/character/acctA/CharA"
            return """
<html>
  <head><title>Builds - CharA - Path of Exile 2 - poe.ninja</title></head>
  <body>
    <input aria-label="Import code for Path of Building" type="text" value="eNrtExampleImportCode123" />
    <a href="pob2://poeninja/overview/code?account=acctA&name=CharA&overview=runes-of-aldur"></a>
  </body>
</html>
"""

    def fake_evaluate_source(source: str, snapshot_id: str):
        assert source == "eNrtExampleImportCode123"
        assert snapshot_id == "ninja_sample_001"
        return {
            "snapshotId": snapshot_id,
            "sourceHash": "hash1",
            "summary": {
                "class": "Monk",
                "ascendancy": "Stormweaver",
                "mainSkill": "Spark",
                "level": 98,
            },
            "pass": True,
            "rewardEligible": "limited",
            "rewardStrength": "limited",
            "aggregateScore": {"value": 0.42},
            "scoreVector": {
                "offense": {"value": 0.62},
                "defense": {"value": 0.41},
                "recovery": {"value": 0.77},
                "mobility": {"value": 0.58},
            },
            "hardFailures": [],
            "physicalInvalidFailures": [],
            "caveats": [],
        }

    monkeypatch.setattr(run_judge_ninja_samples, "evaluate_source", fake_evaluate_source)

    out = run_judge_ninja_samples.evaluate_ninja_sample_row(
        {
            "account": "acctA",
            "name": "CharA",
            "ascendancy": "Stormweaver",
            "level": 98,
            "url": "https://poe.ninja/poe2/builds/runesofaldur/character/acctA/CharA",
        },
        league_url="runesofaldur",
        browser_driver=_FakeBrowser(),
        snapshot_id="ninja_sample_001",
    )

    assert out["finalClassification"] == "judge_score_review_required"
    assert out["scoreReviewNeeded"] is True
    assert (
        out["ninjaSample"]["characterUrl"]
        == "https://poe.ninja/poe2/builds/runesofaldur/character/acctA/CharA"
    )


def test_extract_import_code_handles_input_attribute_order_fallback():
    html = """
<html>
  <head><title>Builds - CharA - Path of Exile 2 - poe.ninja</title></head>
  <body>
    <input readonly="" autocomplete="off" class="foo" type="text" value="eNrtExampleImportCode123" aria-label="Import code for Path of Building" />
    <a href="pob2://poeninja/overview/code?account=acctA&name=CharA&overview=runes-of-aldur"></a>
  </body>
</html>
"""

    out = run_judge_ninja_samples.extract_import_code_from_rendered_build_page(html)

    assert out["ok"] is True
    assert out["importCode"] == "eNrtExampleImportCode123"


def test_run_browser_sampled_rows_returns_summary(monkeypatch):
    calls = []

    def fake_eval(row, *, league_url, browser_driver, snapshot_id):
        calls.append((row["name"], league_url, snapshot_id))
        return {
            "snapshotId": snapshot_id,
            "pass": snapshot_id.endswith("1"),
            "scoreReviewNeeded": snapshot_id.endswith("2"),
            "finalClassification": (
                "judge_pass_and_scores_explained"
                if snapshot_id.endswith("1")
                else "judge_unsolved_modelability_gap"
            ),
        }

    monkeypatch.setattr(run_judge_ninja_samples, "evaluate_ninja_sample_row", fake_eval)

    out = run_judge_ninja_samples.run_browser_sampled_rows(
        [
            {"name": "a", "account": "acct1"},
            {"name": "b", "account": "acct2"},
        ],
        league_url="runesofaldur",
        browser_driver=object(),
    )

    assert calls == [
        ("a", "runesofaldur", "ninja_sample_001"),
        ("b", "runesofaldur", "ninja_sample_002"),
    ]
    assert out["summary"] == {
        "sampleCount": 2,
        "passCount": 1,
        "scoreReviewCount": 1,
        "classifications": {
            "judge_pass_and_scores_explained": 1,
            "judge_unsolved_modelability_gap": 1,
        },
    }


def test_evaluate_ninja_sample_row_safely_turns_fetch_error_into_source_data_problem():
    class _BrokenBrowser:
        def fetch_html(self, _url: str) -> str:
            raise RuntimeError("browser blew up")

    out = run_judge_ninja_samples.evaluate_ninja_sample_row_safely(
        {
            "account": "acctA",
            "name": "CharA",
            "ascendancy": "Stormweaver",
            "level": 98,
        },
        league_url="runesofaldur",
        browser_driver=_BrokenBrowser(),
        snapshot_id="ninja_sample_001",
    )

    assert out["pass"] is False
    assert out["finalClassification"] == "source_data_problem"
    assert "source_data_problem_caveat" in out["caveats"]
    assert (
        out["ninjaSample"]["characterUrl"]
        == "https://poe.ninja/poe2/builds/runesofaldur/character/acctA/CharA"
    )


def test_write_sanitized_ninja_report_omits_account_and_name(monkeypatch, tmp_path):
    monkeypatch.setattr(run_judge_ninja_samples.paths, "user_data_dir", lambda: tmp_path)

    report = {
        "summary": {
            "sampleCount": 1,
            "passCount": 1,
            "scoreReviewCount": 0,
            "classifications": {"judge_pass_and_scores_explained": 1},
        },
        "samples": [
            {
                "snapshotId": "ninja_sample_001",
                "summary": {
                    "class": "Ranger",
                    "ascendancy": "Deadeye",
                    "mainSkill": "Ice Shot",
                    "level": 98,
                },
                "pass": True,
                "finalClassification": "judge_pass_and_scores_explained",
                "scoreReviewNeeded": False,
                "aggregateScore": {"value": 0.71},
                "scoreVector": {"offense": {"value": 0.7}},
                "scoreBreakdown": {
                    "offense": {
                        "provenance": "isolated_full_dps_rollup",
                        "evidenceLevel": "limited",
                        "sourceMetricDetail": "FullDPS",
                        "skillName": "Ice Shot",
                        "rawValue": 420000,
                    }
                },
                "defenseModel": {"poolModel": "es", "confidence": "full"},
                "hardFailures": [],
                "physicalInvalidFailures": [],
                "caveats": ["full_dps_rollup_caveat"],
                "rewardEligible": "limited",
                "rewardStrength": "limited",
                "reproducibility": {"evaluatorVersion": "judge_phase1_v3"},
                "ninjaSample": {
                    "account": "acctA",
                    "name": "CharA",
                    "ascendancy": "Deadeye",
                    "level": 98,
                    "characterUrl": "https://poe.ninja/x",
                },
            }
        ],
    }

    out_path = run_judge_ninja_samples.write_sanitized_ninja_report(
        report, filename="calibration.json"
    )
    saved = out_path.read_text(encoding="utf-8")

    assert out_path.name == "calibration.json"
    assert "acctA" not in saved
    assert "CharA" not in saved
    assert "https://poe.ninja/x" not in saved
    assert "characterUrlRef" in saved


def test_write_dual_sanitized_ninja_reports_writes_raw_and_final(monkeypatch, tmp_path):
    monkeypatch.setattr(run_judge_ninja_samples.paths, "user_data_dir", lambda: tmp_path)

    raw_report = {
        "summary": {"sampleCount": 1},
        "samples": [
            {
                "snapshotId": "raw_1",
                "summary": {},
                "ninjaSample": {"account": "acctA", "name": "CharA"},
            }
        ],
    }
    final_report = {
        "summary": {"sampleCount": 1},
        "samples": [
            {
                "snapshotId": "final_1",
                "summary": {},
                "ninjaSample": {"account": "acctA", "name": "CharA"},
            }
        ],
    }

    raw_path, final_path = run_judge_ninja_samples.write_dual_sanitized_ninja_reports(
        raw_report=raw_report,
        final_report=final_report,
        stem="judge_calibration",
    )

    assert raw_path.name == "judge_calibration_raw.json"
    assert final_path.name == "judge_calibration_final.json"
    assert "acctA" not in raw_path.read_text(encoding="utf-8")
    assert "acctA" not in final_path.read_text(encoding="utf-8")


def test_write_combined_calibration_report_writes_dual_116_files(monkeypatch, tmp_path):
    monkeypatch.setattr(run_judge_ninja_samples.paths, "user_data_dir", lambda: tmp_path)

    historical_report = {
        "samples": [{"snapshotId": "hist_1", "summary": {"class": "Monk"}}],
    }
    ninja_raw_report = {
        "samples": [
            {
                "snapshotId": "ninja_raw_1",
                "summary": {"class": "Ranger"},
                "ninjaSample": {"account": "acctA", "name": "CharA"},
            }
        ],
    }
    ninja_final_report = {
        "samples": [
            {
                "snapshotId": "ninja_final_1",
                "summary": {"class": "Ranger"},
                "ninjaSample": {"account": "acctA", "name": "CharA"},
            }
        ],
    }

    raw_path, final_path = run_judge_ninja_samples.write_combined_calibration_report(
        historical_report=historical_report,
        ninja_raw_report=ninja_raw_report,
        ninja_final_report=ninja_final_report,
    )

    assert raw_path.name == "judge_phase1_calibration_116_raw.json"
    assert final_path.name == "judge_phase1_calibration_116_final.json"
    assert "acctA" not in raw_path.read_text(encoding="utf-8")
    assert "acctA" not in final_path.read_text(encoding="utf-8")


def test_main_print_only_uses_browser_discovery(monkeypatch, capsys):
    class _FakeBrowser:
        def fetch_html(self, _url: str) -> str:
            return """
<html>
  <body>
    <tr>
      <td><a href="/poe2/builds/runesofaldur/character/acctA/CharA">CharA</a></td>
      <td><div>98<img alt="Stormweaver" /></div></td>
    </tr>
    <tr>
      <td><a href="/poe2/builds/runesofaldur/character/acctB/CharB">CharB</a></td>
      <td><div>97<img alt="Deadeye" /></div></td>
    </tr>
  </body>
</html>
"""

    monkeypatch.setattr(run_judge_ninja_samples, "PlaywrightHtmlDriver", _FakeBrowser)

    assert (
        run_judge_ninja_samples.main(
            ["--league-url", "runesofaldur", "--target-count", "2", "--print-only"]
        )
        == 0
    )

    stdout = capsys.readouterr().out
    output = json.loads(stdout)
    assert output["buildListRef"].startswith("ninja-list-hash:")
    assert [row["ascendancy"] for row in output["sampledRows"]] == ["Deadeye", "Stormweaver"]
    assert [row["level"] for row in output["sampledRows"]] == [97, 98]
    assert all(row["rowRef"].startswith("ninja-row-hash:") for row in output["sampledRows"])
    assert all(
        row["characterUrlRef"].startswith("ninja-url-hash:") for row in output["sampledRows"]
    )
    assert "acctA" not in stdout
    assert "CharA" not in stdout
    assert "https://poe.ninja/poe2/builds/runesofaldur/character" not in stdout


def test_main_stdout_omits_sample_identity_after_evaluation(monkeypatch, capsys):
    class _FakeBrowser:
        def fetch_html(self, url: str) -> str:
            if "character" not in url:
                return """
<html>
  <body>
    <tr>
      <td><a href="/poe2/builds/runesofaldur/character/acctA/CharA">CharA</a></td>
      <td><div>98<img alt="Stormweaver" /></div></td>
    </tr>
  </body>
</html>
"""
            return """
<html>
  <head><title>Builds - CharA - Path of Exile 2 - poe.ninja</title></head>
  <body>
    <input aria-label="Import code for Path of Building" type="text" value="eNrtExampleImportCode123" />
  </body>
</html>
"""

    def fake_evaluate_source(source: str, snapshot_id: str):
        return {
            "snapshotId": snapshot_id,
            "summary": {"class": "Monk", "ascendancy": "Stormweaver", "level": 98},
            "pass": True,
            "hardFailures": [],
            "physicalInvalidFailures": [],
            "caveats": [],
        }

    monkeypatch.setattr(run_judge_ninja_samples, "PlaywrightHtmlDriver", _FakeBrowser)
    monkeypatch.setattr(run_judge_ninja_samples, "evaluate_source", fake_evaluate_source)
    monkeypatch.setattr(
        run_judge_ninja_samples,
        "write_dual_sanitized_ninja_reports",
        lambda **_kwargs: (None, None),
    )

    assert (
        run_judge_ninja_samples.main(["--league-url", "runesofaldur", "--target-count", "1"]) == 0
    )

    stdout = capsys.readouterr().out
    output = json.loads(stdout)
    assert output["buildListRef"].startswith("ninja-list-hash:")
    assert output["sampledRows"][0]["rowRef"].startswith("ninja-row-hash:")
    assert "acctA" not in stdout
    assert "CharA" not in stdout
    assert "https://poe.ninja/poe2/builds/runesofaldur/character" not in stdout
