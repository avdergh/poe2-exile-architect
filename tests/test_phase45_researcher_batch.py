from __future__ import annotations

import json
from html import escape

from scripts import run_phase45_researcher_batch
from server.compute import pob_code


RAW_MARKERS = (
    "eNrt",
    "rawXml",
    "rawImportCode",
    "PathOfBuilding",
    "<Build",
    "<Skills",
    "nameSpec",
    "transientPacketPath",
    "transientPromptPath",
    "pobb.in/",
    "poe.ninja/",
    "acctA",
    "acctB",
    "acctC",
    "CharA",
    "CharB",
    "CharC",
)


class _FakeBrowser:
    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages
        self.urls: list[str] = []

    def fetch_html(self, url: str) -> str:
        self.urls.append(url)
        return self.pages.get(url, "<html><body></body></html>")


def test_researcher_batch_collects_filters_dedupes_and_prepares_one_case(tmp_path):
    code_a = _sample_code("LightningArrowPlayer", ascendancy="Deadeye", level=95)
    code_b = _sample_code("SparkPlayer", ascendancy="Stormweaver", level=100)
    browser = _FakeBrowser(
        {
            "https://poe.ninja/poe2/builds/runesofaldur?min-level=90&max-level=100": """
<html><body>
  <tr><td><a href="/poe2/builds/runesofaldur/character/acctA/CharA">CharA</a></td>
      <td><div>95<img alt="Deadeye" /></div></td></tr>
  <tr><td><a href="/poe2/builds/runesofaldur/character/acctB/CharB">CharB</a></td>
      <td><div>89<img alt="Deadeye" /></div></td></tr>
  <tr><td><a href="/poe2/builds/runesofaldur/character/acctC/CharC">CharC</a></td>
      <td><div>100<img alt="Stormweaver" /></div></td></tr>
</body></html>
""",
            "https://poe.ninja/poe2/builds/runesofaldur/character/acctA/CharA": _build_page(code_a),
            "https://poe.ninja/poe2/builds/runesofaldur/character/acctC/CharC": _build_page(code_b),
        }
    )

    report, transient = run_phase45_researcher_batch.build_researcher_batch_report(
        league_url="runesofaldur",
        limit=50,
        level_min=90,
        level_max=100,
        ascendancies=["Deadeye"],
        output_dir=tmp_path,
        temp_root=tmp_path.parent / "transient-collects",
        browser_driver=browser,
    )

    assert report["status"] == "ready_for_external_researcher"
    assert report["sampleCount"] == 1
    assert report["pendingCount"] == 1
    assert report["preparedCount"] == 1
    assert report["nextCase"]["sampleId"] == report["samples"][0]["sampleId"]
    assert report["samples"][0]["ascendancy"] == "Deadeye"
    assert report["samples"][0]["level"] == 95
    assert report["samples"][0]["status"] == "packet_ready"
    assert report["samples"][0]["sourceHashRef"].startswith("source-hash:")
    assert report["samples"][0]["packetSafeHash"]
    assert len(transient) == 1

    serialized = json.dumps(report, ensure_ascii=False)
    assert not any(marker in serialized for marker in RAW_MARKERS)
    state_text = (tmp_path / "phase45_researcher_batch_state.json").read_text(encoding="utf-8")
    assert not any(marker in state_text for marker in RAW_MARKERS)

    prompt_text = transient[0]["promptPath"].read_text(encoding="utf-8")
    packet_text = transient[0]["packetPath"].read_text(encoding="utf-8")
    assert "query_research_memory" in prompt_text
    assert "BuildDesignObservation" in prompt_text
    assert "one build sample only" in prompt_text
    assert "rawImportCode" in packet_text
    assert "PathOfBuilding" in packet_text
    assert "programmaticDiagnostics" in packet_text


def test_researcher_batch_passes_optional_class_filter_to_poe_ninja(tmp_path):
    code = _sample_code("BonestormPlayer", ascendancy="Blood Mage", level=95)
    list_url = (
        "https://poe.ninja/poe2/builds/runesofaldur?min-level=95&max-level=95&class=Blood+Mage"
    )
    browser = _FakeBrowser(
        {
            list_url: """
<html><body>
  <tr><td><a href="/poe2/builds/runesofaldur/character/acctA/CharA">CharA</a></td>
      <td><div>95<img alt="Blood Mage" /></div></td></tr>
</body></html>
""",
            "https://poe.ninja/poe2/builds/runesofaldur/character/acctA/CharA": _build_page(code),
        }
    )

    report, _ = run_phase45_researcher_batch.build_researcher_batch_report(
        league_url="runesofaldur",
        limit=1,
        level_min=95,
        level_max=95,
        ninja_classes=["Blood Mage"],
        output_dir=tmp_path,
        temp_root=tmp_path.parent / "transient-ninja-class-filter",
        browser_driver=browser,
    )

    assert browser.urls[0] == list_url
    assert report["sampleCount"] == 1
    assert report["samples"][0]["ascendancy"] == "Blood Mage"


def test_researcher_batch_backfills_duplicate_ninja_payloads_to_requested_limit(tmp_path):
    code_a = _sample_code("BonestormPlayer", ascendancy="Blood Mage", level=95)
    code_c = _sample_code("PlasmaBlastPlayer", ascendancy="Blood Mage", level=95)
    list_url = (
        "https://poe.ninja/poe2/builds/runesofaldur?min-level=95&max-level=95&class=Blood+Mage"
    )
    browser = _FakeBrowser(
        {
            list_url: """
<html><body>
  <tr><td><a href="/poe2/builds/runesofaldur/character/acctA/CharA">CharA</a></td>
      <td><div>95<img alt="Blood Mage" /></div></td></tr>
  <tr><td><a href="/poe2/builds/runesofaldur/character/acctB/CharB">CharB</a></td>
      <td><div>95<img alt="Blood Mage" /></div></td></tr>
  <tr><td><a href="/poe2/builds/runesofaldur/character/acctC/CharC">CharC</a></td>
      <td><div>95<img alt="Blood Mage" /></div></td></tr>
</body></html>
""",
            "https://poe.ninja/poe2/builds/runesofaldur/character/acctA/CharA": _build_page(code_a),
            "https://poe.ninja/poe2/builds/runesofaldur/character/acctB/CharB": _build_page(code_a),
            "https://poe.ninja/poe2/builds/runesofaldur/character/acctC/CharC": _build_page(code_c),
        }
    )

    report, _ = run_phase45_researcher_batch.build_researcher_batch_report(
        league_url="runesofaldur",
        limit=2,
        level_min=95,
        level_max=95,
        ninja_classes=["Blood Mage"],
        output_dir=tmp_path,
        temp_root=tmp_path.parent / "transient-ninja-backfill",
        browser_driver=browser,
    )

    assert report["sampleCount"] == 2
    assert browser.urls[-1].endswith("/character/acctC/CharC")


def test_researcher_batch_normalizes_url_style_class_and_rejects_other_classes(tmp_path):
    code_a = _sample_code("BonestormPlayer", ascendancy="Blood Mage", level=95)
    code_b = _sample_code("PlasmaBlastPlayer", ascendancy="Blood Mage", level=95)
    list_url = (
        "https://poe.ninja/poe2/builds/runesofaldur?min-level=95&max-level=95&class=Blood+Mage"
    )
    browser = _FakeBrowser(
        {
            list_url: """
<html><body>
  <tr><td><a href="/poe2/builds/runesofaldur/character/acctX/OtherA">OtherA</a></td>
      <td><div>95<img alt="Deadeye" /></div></td></tr>
  <tr><td><a href="/poe2/builds/runesofaldur/character/acctA/CharA">CharA</a></td>
      <td><div>95<img alt="Blood Mage" /></div></td></tr>
  <tr><td><a href="/poe2/builds/runesofaldur/character/acctY/OtherB">OtherB</a></td>
      <td><div>95<img alt="Stormweaver" /></div></td></tr>
  <tr><td><a href="/poe2/builds/runesofaldur/character/acctB/CharB">CharB</a></td>
      <td><div>95<img alt="Blood Mage" /></div></td></tr>
</body></html>
""",
            "https://poe.ninja/poe2/builds/runesofaldur/character/acctA/CharA": _build_page(code_a),
            "https://poe.ninja/poe2/builds/runesofaldur/character/acctB/CharB": _build_page(code_b),
        }
    )

    report, _ = run_phase45_researcher_batch.build_researcher_batch_report(
        league_url="runesofaldur",
        limit=2,
        level_min=95,
        level_max=95,
        ninja_classes=["Blood+Mage"],
        output_dir=tmp_path,
        temp_root=tmp_path.parent / "transient-ninja-url-class-filter",
        browser_driver=browser,
    )

    assert browser.urls[0] == list_url
    assert "%2B" not in browser.urls[0]
    assert report["sampleCount"] == 2
    assert {sample["ascendancy"] for sample in report["samples"]} == {"Blood Mage"}
    assert not any("OtherA" in url or "OtherB" in url for url in browser.urls)


def test_ninja_class_normalization_accepts_spaces_plus_and_encoded_separators():
    normalize = run_phase45_researcher_batch._normalize_ninja_classes

    assert normalize(
        ["Blood Mage", "Blood+Mage", "Blood%20Mage", "Blood%2BMage", "  Blood   Mage  "]
    ) == ["Blood Mage"]


def test_researcher_batch_retries_an_empty_ninja_list_twice_before_success():
    code = _sample_code("FlickerStrikePlayer", ascendancy="Martial Artist", level=94)
    list_url = (
        "https://poe.ninja/poe2/builds/runesofaldur?min-level=94&max-level=94&class=Martial+Artist"
    )
    detail_url = "https://poe.ninja/poe2/builds/runesofaldur/character/acctA/CharA"

    class _RetryBrowser:
        def __init__(self) -> None:
            self.list_fetch_count = 0

        def fetch_html(self, url: str) -> str:
            if url == list_url:
                self.list_fetch_count += 1
                if self.list_fetch_count <= 2:
                    return "<html><body></body></html>"
                return """
<html><body>
  <tr><td><a href="/poe2/builds/runesofaldur/character/acctA/CharA">CharA</a></td>
      <td><div>94<img alt="Martial Artist" /></div></td></tr>
</body></html>
"""
            assert url == detail_url
            return _build_page(code)

    browser = _RetryBrowser()

    cases = run_phase45_researcher_batch._cases_from_ninja(
        league_url="runesofaldur",
        limit=1,
        level_min=94,
        level_max=94,
        ascendancies=[],
        browser_driver=browser,
        ninja_classes=["Martial+Artist"],
    )

    assert browser.list_fetch_count == 3
    assert len(cases) == 1
    assert cases[0]["ascendancy"] == "Martial Artist"


def test_researcher_batch_stops_after_two_empty_ninja_list_retries():
    list_url = (
        "https://poe.ninja/poe2/builds/runesofaldur?min-level=94&max-level=94&class=Martial+Artist"
    )

    class _EmptyBrowser:
        def __init__(self) -> None:
            self.list_fetch_count = 0

        def fetch_html(self, url: str) -> str:
            assert url == list_url
            self.list_fetch_count += 1
            return "<html><body></body></html>"

    browser = _EmptyBrowser()

    cases = run_phase45_researcher_batch._cases_from_ninja(
        league_url="runesofaldur",
        limit=1,
        level_min=94,
        level_max=94,
        ascendancies=[],
        browser_driver=browser,
        ninja_classes=["Martial Artist"],
    )

    assert cases == []
    assert browser.list_fetch_count == 3


def test_researcher_batch_resume_prepares_next_uncompleted_case(tmp_path):
    code_a = _sample_code("LightningArrowPlayer", ascendancy="Deadeye", level=95)
    code_b = _sample_code("SparkPlayer", ascendancy="Stormweaver", level=96)
    browser = _FakeBrowser(
        {
            "https://poe.ninja/poe2/builds/runesofaldur?min-level=90&max-level=100": """
<html><body>
  <tr><td><a href="/poe2/builds/runesofaldur/character/acctA/CharA">CharA</a></td>
      <td><div>95<img alt="Deadeye" /></div></td></tr>
  <tr><td><a href="/poe2/builds/runesofaldur/character/acctB/CharB">CharB</a></td>
      <td><div>96<img alt="Stormweaver" /></div></td></tr>
</body></html>
""",
            "https://poe.ninja/poe2/builds/runesofaldur/character/acctA/CharA": _build_page(code_a),
            "https://poe.ninja/poe2/builds/runesofaldur/character/acctB/CharB": _build_page(code_b),
        }
    )
    first, _ = run_phase45_researcher_batch.build_researcher_batch_report(
        league_url="runesofaldur",
        limit=2,
        worker_count=1,
        level_min=90,
        level_max=100,
        output_dir=tmp_path,
        temp_root=tmp_path.parent / "transient-resume",
        browser_driver=browser,
    )
    state_path = tmp_path / "phase45_researcher_batch_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["cases"][0]["status"] = "accepted"
    state_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")

    second, transient = run_phase45_researcher_batch.build_researcher_batch_report(
        league_url="runesofaldur",
        limit=2,
        worker_count=1,
        level_min=90,
        level_max=100,
        output_dir=tmp_path,
        temp_root=tmp_path.parent / "transient-resume",
        browser_driver=browser,
        resume=True,
    )

    assert first["nextCase"]["sampleId"] != second["nextCase"]["sampleId"]
    assert second["completedCount"] == 1
    assert second["pendingCount"] == 1
    assert second["preparedCount"] == 1
    assert len(transient) == 1


def test_researcher_batch_local_source_file_uses_same_single_case_queue(tmp_path):
    source_file = tmp_path / "sample.txt"
    source_file.write_text(
        _sample_code("LightningArrowPlayer", ascendancy="Deadeye", level=95),
        encoding="utf-8",
    )

    report, transient = run_phase45_researcher_batch.build_researcher_batch_report(
        source_files=[source_file],
        output_dir=tmp_path,
        temp_root=tmp_path.parent / "transient-local",
    )

    assert report["status"] == "ready_for_external_researcher"
    assert report["sampleCount"] == 1
    assert report["samples"][0]["sourceType"] == "local_pob_code_file"
    assert len(transient) == 1


def test_researcher_batch_source_batch_file_splits_without_multi_case_prompt(tmp_path):
    source_batch = tmp_path / "samples.txt"
    source_batch.write_text(
        _sample_code("LightningArrowPlayer", ascendancy="Deadeye", level=95)
        + "\n---POB-SAMPLE---\n"
        + _sample_code("SparkPlayer", ascendancy="Stormweaver", level=96),
        encoding="utf-8",
    )

    report, transient = run_phase45_researcher_batch.build_researcher_batch_report(
        source_batch_files=[source_batch],
        output_dir=tmp_path,
        temp_root=tmp_path.parent / "transient-batch",
    )

    assert report["sampleCount"] == 2
    assert report["preparedCount"] == 2
    assert len(transient) == 2
    for item in transient:
        packet_text = item["packetPath"].read_text(encoding="utf-8")
        assert packet_text.count("rawImportCode") == 1


def test_researcher_batch_source_batch_file_splits_delimited_xml_samples(tmp_path):
    source_batch = tmp_path / "samples.xml.txt"
    source_batch.write_text(
        _sample_xml("LightningArrowPlayer", ascendancy="Deadeye", level=95)
        + "\n---POB-SAMPLE---\n"
        + _sample_xml("SparkPlayer", ascendancy="Stormweaver", level=96),
        encoding="utf-8",
    )

    report, transient = run_phase45_researcher_batch.build_researcher_batch_report(
        source_batch_files=[source_batch],
        output_dir=tmp_path,
        temp_root=tmp_path.parent / "transient-xml-batch",
        worker_count=2,
    )

    assert report["sampleCount"] == 2
    assert report["preparedCount"] == 2
    assert len(transient) == 2


def test_researcher_batch_worker_pool_prepares_multiple_single_case_prompts(tmp_path):
    source_batch = tmp_path / "samples.txt"
    source_batch.write_text(
        "\n---POB-SAMPLE---\n".join(
            _sample_code(f"Skill{i}Player", ascendancy="Deadeye", level=95 + i) for i in range(6)
        ),
        encoding="utf-8",
    )

    report, transient = run_phase45_researcher_batch.build_researcher_batch_report(
        source_batch_files=[source_batch],
        output_dir=tmp_path,
        temp_root=tmp_path.parent / "transient-worker-pool",
        worker_count=5,
    )

    assert report["sampleCount"] == 6
    assert report["preparedCount"] == 5
    assert report["pendingCount"] == 6
    assert len(transient) == 5
    assert [item["sampleId"] for item in report["preparedCases"]] == [
        f"case:phase45-researcher-{i:03d}" for i in range(1, 6)
    ]
    assert report["nextCase"]["sampleId"] == "case:phase45-researcher-001"
    assert len(report["workerActions"]) == 5
    assert all("--packet-safe-hash" in item["windowsCommand"] for item in report["workerActions"])

    for item in transient:
        packet_text = item["packetPath"].read_text(encoding="utf-8")
        prompt_text = item["promptPath"].read_text(encoding="utf-8")
        assert packet_text.count("rawImportCode") == 1
        assert "one build sample only" in prompt_text

    serialized = json.dumps(report, ensure_ascii=False)
    assert not any(marker in serialized for marker in RAW_MARKERS)
    assert str(tmp_path.parent) not in serialized


def test_researcher_batch_worker_count_can_be_lowered_to_one(tmp_path):
    source_batch = tmp_path / "samples.txt"
    source_batch.write_text(
        _sample_code("LightningArrowPlayer", ascendancy="Deadeye", level=95)
        + "\n---POB-SAMPLE---\n"
        + _sample_code("SparkPlayer", ascendancy="Stormweaver", level=96),
        encoding="utf-8",
    )

    report, transient = run_phase45_researcher_batch.build_researcher_batch_report(
        source_batch_files=[source_batch],
        output_dir=tmp_path,
        temp_root=tmp_path.parent / "transient-worker-one",
        worker_count=1,
    )

    assert report["preparedCount"] == 1
    assert len(transient) == 1
    assert len(report["workerActions"]) == 1


def test_researcher_batch_resume_preserves_in_flight_packet_ready_cases(tmp_path):
    source_batch = tmp_path / "samples.txt"
    source_batch.write_text(
        "\n---POB-SAMPLE---\n".join(
            _sample_code(f"Skill{i}Player", ascendancy="Deadeye", level=95 + i) for i in range(4)
        ),
        encoding="utf-8",
    )
    first, _ = run_phase45_researcher_batch.build_researcher_batch_report(
        source_batch_files=[source_batch],
        output_dir=tmp_path,
        temp_root=tmp_path.parent / "transient-resume-worker-pool",
        worker_count=2,
    )
    first_hashes = {item["sampleId"]: item["packetSafeHash"] for item in first["preparedCases"]}
    accepted = first["preparedCases"][0]["sampleId"]
    run_phase45_researcher_batch.mark_case_accepted(
        output_dir=tmp_path,
        sample_id=accepted,
    )

    second, transient = run_phase45_researcher_batch.build_researcher_batch_report(
        source_batch_files=[source_batch],
        output_dir=tmp_path,
        temp_root=tmp_path.parent / "transient-resume-worker-pool",
        worker_count=2,
        resume=True,
    )

    still_running = first["preparedCases"][1]["sampleId"]
    state_by_sample = {item["sampleId"]: item for item in second["samples"]}
    assert state_by_sample[still_running]["packetSafeHash"] == first_hashes[still_running]
    assert second["preparedCount"] == 1
    assert second["preparedCases"][0]["sampleId"] == "case:phase45-researcher-003"
    assert len(transient) == 1


def test_researcher_batch_resume_does_not_reissue_full_worker_pool_when_all_slots_busy(tmp_path):
    source_batch = tmp_path / "samples.txt"
    source_batch.write_text(
        "\n---POB-SAMPLE---\n".join(
            _sample_code(f"Skill{i}Player", ascendancy="Deadeye", level=95 + i) for i in range(4)
        ),
        encoding="utf-8",
    )
    first, _ = run_phase45_researcher_batch.build_researcher_batch_report(
        source_batch_files=[source_batch],
        output_dir=tmp_path,
        temp_root=tmp_path.parent / "transient-resume-busy",
        worker_count=2,
    )

    second, transient = run_phase45_researcher_batch.build_researcher_batch_report(
        source_batch_files=[source_batch],
        output_dir=tmp_path,
        temp_root=tmp_path.parent / "transient-resume-busy",
        worker_count=2,
        resume=True,
    )

    assert len(first["preparedCases"]) == 2
    assert second["preparedCount"] == 0
    assert second["preparedCases"] == []
    assert transient == []


def test_researcher_batch_source_start_index_preserves_global_case_refs(tmp_path):
    source_batch = tmp_path / "samples.txt"
    source_batch.write_text(
        _sample_code("LightningArrowPlayer", ascendancy="Deadeye", level=95)
        + "\n---POB-SAMPLE---\n"
        + _sample_code("SparkPlayer", ascendancy="Stormweaver", level=96),
        encoding="utf-8",
    )

    report, _ = run_phase45_researcher_batch.build_researcher_batch_report(
        source_batch_files=[source_batch],
        output_dir=tmp_path,
        temp_root=tmp_path.parent / "transient-start-index",
        sample_start_index=11,
    )

    assert [item["sampleId"] for item in report["samples"]] == [
        "case:phase45-researcher-011",
        "case:phase45-researcher-012",
    ]
    state = json.loads((tmp_path / "phase45_researcher_batch_state.json").read_text("utf-8"))
    assert [item["sampleId"] for item in state["cases"]] == [
        "case:phase45-researcher-011",
        "case:phase45-researcher-012",
    ]


def test_researcher_batch_mark_accepted_updates_safe_state_without_raw(tmp_path):
    source_file = tmp_path / "sample.txt"
    source_file.write_text(
        _sample_code("LightningArrowPlayer", ascendancy="Deadeye", level=95),
        encoding="utf-8",
    )
    first, _ = run_phase45_researcher_batch.build_researcher_batch_report(
        source_files=[source_file],
        output_dir=tmp_path,
        temp_root=tmp_path.parent / "transient-mark",
    )

    marked = run_phase45_researcher_batch.mark_case_accepted(
        output_dir=tmp_path,
        sample_id=first["nextCase"]["sampleId"],
    )

    assert marked["status"] == "case_marked_accepted"
    assert marked["completedCount"] == 1
    assert marked["pendingCount"] == 0
    state_text = (tmp_path / "phase45_researcher_batch_state.json").read_text(encoding="utf-8")
    assert not any(marker in state_text for marker in RAW_MARKERS)


def test_researcher_batch_next_action_is_cross_platform_and_has_no_absolute_temp_paths(tmp_path):
    source_file = tmp_path / "sample.txt"
    source_file.write_text(
        _sample_code("LightningArrowPlayer", ascendancy="Deadeye", level=95),
        encoding="utf-8",
    )
    report, _ = run_phase45_researcher_batch.build_researcher_batch_report(
        source_files=[source_file],
        output_dir=tmp_path,
        temp_root=tmp_path.parent / "transient-next-action",
    )

    next_action = run_phase45_researcher_batch.build_next_action(report, output_dir=tmp_path)

    assert next_action["sampleId"] == report["nextCase"]["sampleId"]
    assert next_action["packetSafeHash"] == report["nextCase"]["packetSafeHash"]
    assert "scripts/run_phase45_researcher_batch.py" in next_action["posixCommand"]
    assert "scripts\\run_phase45_researcher_batch.py" in next_action["windowsCommand"]
    assert "./.tools/uv/uv" in next_action["posixCommand"]
    assert ".\\.tools\\uv\\uv.exe" in next_action["windowsCommand"]
    assert "--print-next-prompt" in next_action["posixCommand"]
    assert "--print-next-prompt" in next_action["windowsCommand"]
    assert str(tmp_path.parent) not in json.dumps(next_action, ensure_ascii=False)
    assert not any(marker in json.dumps(next_action, ensure_ascii=False) for marker in RAW_MARKERS)


def test_researcher_batch_print_next_prompt_reads_transient_prompt_without_durable_path(tmp_path):
    source_file = tmp_path / "sample.txt"
    source_file.write_text(
        _sample_code("LightningArrowPlayer", ascendancy="Deadeye", level=95),
        encoding="utf-8",
    )
    report, transient = run_phase45_researcher_batch.build_researcher_batch_report(
        source_files=[source_file],
        output_dir=tmp_path,
        temp_root=tmp_path.parent / "transient-print-prompt",
    )

    prompt_text = run_phase45_researcher_batch.load_next_prompt(
        output_dir=tmp_path,
        temp_root=tmp_path.parent / "transient-print-prompt",
    )

    assert prompt_text == transient[0]["promptPath"].read_text(encoding="utf-8")
    assert "query_research_memory" in prompt_text
    assert report["nextCase"]["packetSafeHash"] in prompt_text or "safeHash" in prompt_text
    state_text = (tmp_path / "phase45_researcher_batch_state.json").read_text(encoding="utf-8")
    assert "promptPath" not in state_text
    assert "packetPath" not in state_text


def test_researcher_batch_cli_print_next_prompt_outputs_prompt_not_json(tmp_path, capsys):
    source_file = tmp_path / "sample.txt"
    source_file.write_text(
        _sample_code("LightningArrowPlayer", ascendancy="Deadeye", level=95),
        encoding="utf-8",
    )
    run_phase45_researcher_batch.build_researcher_batch_report(
        source_files=[source_file],
        output_dir=tmp_path,
        temp_root=tmp_path.parent / "transient-cli-prompt",
    )

    code = run_phase45_researcher_batch.main(
        [
            "--output-dir",
            str(tmp_path),
            "--temp-root",
            str(tmp_path.parent / "transient-cli-prompt"),
            "--print-next-prompt",
        ]
    )

    out = capsys.readouterr().out
    assert code == 0
    assert "[SYSTEM]" in out
    assert "MATURE BUILD ANALYSIS" in out
    assert "transientPromptPath" not in out


def test_researcher_batch_cli_summary_includes_worker_actions(tmp_path, capsys):
    source_batch = tmp_path / "samples.txt"
    source_batch.write_text(
        _sample_code("LightningArrowPlayer", ascendancy="Deadeye", level=95)
        + "\n---POB-SAMPLE---\n"
        + _sample_code("SparkPlayer", ascendancy="Stormweaver", level=96),
        encoding="utf-8",
    )

    code = run_phase45_researcher_batch.main(
        [
            "--source-batch-file",
            str(source_batch),
            "--output-dir",
            str(tmp_path / "queue"),
            "--temp-root",
            str(tmp_path.parent / "transient-cli-worker-actions"),
            "--worker-count",
            "2",
            "--json-output",
            str(tmp_path / "report.json"),
            "--md-output",
            str(tmp_path / "report.md"),
        ]
    )

    out = json.loads(capsys.readouterr().out)
    assert code == 0
    assert out["preparedCount"] == 2
    assert len(out["workerActions"]) == 2
    assert all("--packet-safe-hash" in item["windowsCommand"] for item in out["workerActions"])


def test_accept_single_review_resolves_review_file_relative_to_output_dir(tmp_path, monkeypatch):
    review_dir = tmp_path / "reviews"
    review_dir.mkdir()
    review_file = review_dir / "case-001-review.json"
    review_file.write_text('{"schemaVersion": 1}', encoding="utf-8")
    calls = {}

    def fake_accept_deep_review_candidates(**kwargs):
        calls.update(kwargs)
        return {
            "status": "accepted",
            "acceptedPatternCount": 1,
            "deferredCandidateCount": 0,
            "patternWrite": {},
        }

    monkeypatch.setattr(
        "scripts.phase45_accept_single_review.acceptance.accept_deep_review_candidates",
        fake_accept_deep_review_candidates,
    )
    from scripts import phase45_accept_single_review

    code = phase45_accept_single_review.main(
        [
            "--review-file",
            "reviews/case-001-review.json",
            "--case-id",
            "case:phase45-researcher-001",
            "--output-dir",
            str(tmp_path),
            "--db-path",
            str(tmp_path / "memory.sqlite"),
        ]
    )

    assert code == 0
    assert calls["review_file"] == review_file


def test_researcher_batch_rejects_durable_temp_roots(tmp_path):
    source_file = tmp_path / "sample.txt"
    source_file.write_text(
        _sample_code("LightningArrowPlayer", ascendancy="Deadeye", level=95),
        encoding="utf-8",
    )

    for unsafe_temp_root in (tmp_path, run_phase45_researcher_batch.REPO_ROOT / "tmp-packets"):
        try:
            run_phase45_researcher_batch.build_researcher_batch_report(
                source_files=[source_file],
                output_dir=tmp_path,
                temp_root=unsafe_temp_root,
            )
        except ValueError as exc:
            assert "temp_root" in str(exc)
        else:  # pragma: no cover - assertion clarity.
            raise AssertionError("unsafe temp_root was accepted")


def test_researcher_batch_current_league_uses_freshness_selection(monkeypatch):
    calls: list[str] = []

    def fake_fetch_json(url: str):
        calls.append(url)
        if url.endswith("build-index-state"):
            return {"leagueBuilds": [{"leagueUrl": "runesofaldur", "total": 1000}]}
        if url.endswith("index-state"):
            return {
                "buildLeagues": [
                    {"name": "Runes of Aldur", "url": "runesofaldur", "hardcore": False}
                ],
                "oldBuildLeagues": [],
                "snapshotVersions": [
                    {
                        "url": "runesofaldur",
                        "version": "2026-20260707-00000",
                        "passiveTree": "PassiveTree-0.5",
                    }
                ],
            }
        raise AssertionError(url)

    monkeypatch.setattr(run_phase45_researcher_batch, "_fetch_json", fake_fetch_json)

    assert run_phase45_researcher_batch._resolve_league_url("current") == "runesofaldur"
    assert len(calls) == 2


def test_researcher_batch_fetch_json_uses_browser_like_json_headers(monkeypatch):
    captured = {}

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"ok": true}'

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(run_phase45_researcher_batch.urllib.request, "urlopen", fake_urlopen)

    assert run_phase45_researcher_batch._fetch_json(
        "https://poe.ninja/poe2/api/data/index-state"
    ) == {"ok": True}
    request = captured["request"]
    assert captured["timeout"] == 60
    assert request.full_url == "https://poe.ninja/poe2/api/data/index-state"
    assert "Mozilla/5.0" in request.headers["User-agent"]
    assert request.headers["Accept"] == "application/json"
    assert request.headers["Referer"] == "https://poe.ninja/poe2/builds"


def test_researcher_batch_current_league_does_not_fall_back_to_standard_hc_or_ssf(monkeypatch):
    def fake_fetch_json(url: str):
        if url.endswith("build-index-state"):
            return {
                "leagueBuilds": [
                    {"leagueUrl": "standard", "total": 9000},
                    {"leagueUrl": "hc-runesofaldur", "total": 8000},
                    {"leagueUrl": "ssf-runesofaldur", "total": 7000},
                    {"leagueUrl": "runesofaldur", "total": 1000},
                ]
            }
        if url.endswith("index-state"):
            return {
                "buildLeagues": [
                    {"name": "Standard", "url": "standard", "hardcore": False},
                    {"name": "HC Runes of Aldur", "url": "hc-runesofaldur", "hardcore": True},
                    {"name": "SSF Runes of Aldur", "url": "ssf-runesofaldur", "hardcore": False},
                    {"name": "Runes of Aldur", "url": "runesofaldur", "hardcore": False},
                ],
                "oldBuildLeagues": [],
                "snapshotVersions": [
                    {
                        "url": url_token,
                        "version": "2026-20260707-00000",
                        "passiveTree": "PassiveTree-0.5",
                    }
                    for url_token in (
                        "standard",
                        "hc-runesofaldur",
                        "ssf-runesofaldur",
                        "runesofaldur",
                    )
                ],
            }
        raise AssertionError(url)

    monkeypatch.setattr(run_phase45_researcher_batch, "_fetch_json", fake_fetch_json)

    assert run_phase45_researcher_batch._resolve_league_url("current") == "runesofaldur"


def test_researcher_batch_skips_ledger_characters_and_paginates_to_new_limit(tmp_path):
    code_a = _sample_code("LightningArrowPlayer", ascendancy="Stormweaver", level=100)
    code_b = _sample_code("SparkPlayer", ascendancy="Stormweaver", level=100)
    code_c = _sample_code("PlasmaBlastPlayer", ascendancy="Stormweaver", level=100)
    page1_url = "https://poe.ninja/poe2/builds/runesofaldur?min-level=90&max-level=100"
    page2_url = "https://poe.ninja/poe2/builds/runesofaldur?min-level=90&max-level=100&page=2"
    browser = _FakeBrowser(
        {
            page1_url: """
<html><body>
  <tr><td><a href="/poe2/builds/runesofaldur/character/acctA/CharA">CharA</a></td>
      <td><div>100<img alt="Stormweaver" /></div></td></tr>
  <tr><td><a href="/poe2/builds/runesofaldur/character/acctB/CharB">CharB</a></td>
      <td><div>100<img alt="Stormweaver" /></div></td></tr>
</body></html>
""",
            page2_url: """
<html><body>
  <tr><td><a href="/poe2/builds/runesofaldur/character/acctC/CharC">CharC</a></td>
      <td><div>100<img alt="Stormweaver" /></div></td></tr>
</body></html>
""",
            "https://poe.ninja/poe2/builds/runesofaldur/character/acctA/CharA": _build_page(code_a),
            "https://poe.ninja/poe2/builds/runesofaldur/character/acctB/CharB": _build_page(code_b),
            "https://poe.ninja/poe2/builds/runesofaldur/character/acctC/CharC": _build_page(code_c),
        }
    )
    from server.knowledge import research_intake_ledger

    ledger_path = tmp_path / "ledger.sqlite"
    research_intake_ledger.record_case(
        ledger_path,
        league="runesofaldur",
        character_ref=research_intake_ledger.character_ref("acctA", "CharA"),
        source_hash="already-researched",
    )
    stats: dict = {}

    cases = run_phase45_researcher_batch._cases_from_ninja(
        league_url="runesofaldur",
        limit=2,
        level_min=90,
        level_max=100,
        ascendancies=[],
        browser_driver=browser,
        intake_ledger_path=ledger_path,
        collector_stats=stats,
    )

    assert [case["sampleId"] for case in cases] == [
        "case:phase45-researcher-001",
        "case:phase45-researcher-002",
    ]
    assert [case["ascendancy"] for case in cases] == ["Stormweaver", "Stormweaver"]
    assert all(case["characterRef"].startswith("character-hash:") for case in cases)
    assert stats["pagesFetched"] == 2
    assert stats["skippedAlreadyResearched"] == 1
    detail_fetches = [url for url in browser.urls if "/character/" in url]
    assert detail_fetches == [
        "https://poe.ninja/poe2/builds/runesofaldur/character/acctB/CharB",
        "https://poe.ninja/poe2/builds/runesofaldur/character/acctC/CharC",
    ]


def test_researcher_batch_without_ledger_fetches_previously_seen_characters(tmp_path):
    code_a = _sample_code("LightningArrowPlayer", ascendancy="Stormweaver", level=100)
    list_url = "https://poe.ninja/poe2/builds/runesofaldur?min-level=90&max-level=100"
    browser = _FakeBrowser(
        {
            list_url: """
<html><body>
  <tr><td><a href="/poe2/builds/runesofaldur/character/acctA/CharA">CharA</a></td>
      <td><div>100<img alt="Stormweaver" /></div></td></tr>
</body></html>
""",
            "https://poe.ninja/poe2/builds/runesofaldur/character/acctA/CharA": _build_page(code_a),
        }
    )

    cases = run_phase45_researcher_batch._cases_from_ninja(
        league_url="runesofaldur",
        limit=1,
        level_min=90,
        level_max=100,
        ascendancies=[],
        browser_driver=browser,
    )

    assert len(cases) == 1
    assert cases[0]["sampleId"] == "case:phase45-researcher-001"
    assert cases[0]["characterRef"].startswith("character-hash:")


def test_researcher_batch_pagination_never_exceeds_requested_limit(tmp_path):
    page1_url = "https://poe.ninja/poe2/builds/runesofaldur?min-level=95&max-level=95"
    page2_url = "https://poe.ninja/poe2/builds/runesofaldur?min-level=95&max-level=95&page=2"
    pages: dict[str, str] = {}

    def _row(account: str, name: str) -> str:
        return (
            f'<tr><td><a href="/poe2/builds/runesofaldur/character/{account}/{name}">{name}</a></td>'
            f'<td><div>95<img alt="Deadeye" /></div></td></tr>'
        )

    page1_rows = "".join(_row(f"acctA{i}", f"CharA{i}") for i in range(4))
    page2_rows = "".join(_row(f"acctB{i}", f"CharB{i}") for i in range(6))
    pages[page1_url] = f"<html><body>{page1_rows}</body></html>"
    pages[page2_url] = f"<html><body>{page2_rows}</body></html>"
    for account, name in (
        *[(f"acctA{i}", f"CharA{i}") for i in range(4)],
        *[(f"acctB{i}", f"CharB{i}") for i in range(6)],
    ):
        pages[f"https://poe.ninja/poe2/builds/runesofaldur/character/{account}/{name}"] = (
            _build_page(_sample_code(f"Skill{account}{name}", ascendancy="Deadeye", level=95))
        )
    browser = _FakeBrowser(pages)
    stats: dict = {}

    cases = run_phase45_researcher_batch._cases_from_ninja(
        league_url="runesofaldur",
        limit=5,
        level_min=95,
        level_max=95,
        ascendancies=["Deadeye"],
        browser_driver=browser,
        collector_stats=stats,
    )

    assert len(cases) == 5
    assert [case["sampleId"] for case in cases] == [
        f"case:phase45-researcher-{i:03d}" for i in range(1, 6)
    ]
    assert stats["pagesFetched"] == 2
    detail_fetches = [url for url in browser.urls if "/character/" in url]
    assert len(detail_fetches) == 5
    assert detail_fetches[-1].endswith("/character/acctB0/CharB0")


def test_researcher_batch_stops_when_a_page_repeats_already_seen_characters():
    code_a = _sample_code("LightningArrowPlayer", ascendancy="Deadeye", level=95)
    code_b = _sample_code("SparkPlayer", ascendancy="Deadeye", level=95)
    page1_url = "https://poe.ninja/poe2/builds/runesofaldur?min-level=95&max-level=95"
    page2_url = "https://poe.ninja/poe2/builds/runesofaldur?min-level=95&max-level=95&page=2"
    same_rows = """
<html><body>
  <tr><td><a href="/poe2/builds/runesofaldur/character/acctA/CharA">CharA</a></td>
      <td><div>95<img alt="Deadeye" /></div></td></tr>
  <tr><td><a href="/poe2/builds/runesofaldur/character/acctB/CharB">CharB</a></td>
      <td><div>95<img alt="Deadeye" /></div></td></tr>
</body></html>
"""
    browser = _FakeBrowser(
        {
            page1_url: same_rows,
            page2_url: same_rows,
            "https://poe.ninja/poe2/builds/runesofaldur/character/acctA/CharA": _build_page(code_a),
            "https://poe.ninja/poe2/builds/runesofaldur/character/acctB/CharB": _build_page(code_b),
        }
    )
    stats: dict = {}

    cases = run_phase45_researcher_batch._cases_from_ninja(
        league_url="runesofaldur",
        limit=5,
        level_min=95,
        level_max=95,
        ascendancies=[],
        browser_driver=browser,
        collector_stats=stats,
    )

    assert [case["sampleId"] for case in cases] == [
        "case:phase45-researcher-001",
        "case:phase45-researcher-002",
    ]
    assert stats["pagesFetched"] == 2
    assert stats["skippedAlreadyResearched"] == 0
    assert not any("page=3" in url for url in browser.urls)


def test_researcher_batch_keeps_paginating_after_an_all_ledger_skipped_page(tmp_path):
    code_a = _sample_code("LightningArrowPlayer", ascendancy="Deadeye", level=95)
    code_d = _sample_code("PlasmaBlastPlayer", ascendancy="Deadeye", level=95)
    page1_url = "https://poe.ninja/poe2/builds/runesofaldur?min-level=95&max-level=95"
    page2_url = "https://poe.ninja/poe2/builds/runesofaldur?min-level=95&max-level=95&page=2"
    page3_url = "https://poe.ninja/poe2/builds/runesofaldur?min-level=95&max-level=95&page=3"

    def _rows(*names: str) -> str:
        return "".join(
            f'<tr><td><a href="/poe2/builds/runesofaldur/character/acct{name}/Char{name}">Char{name}</a></td>'
            f'<td><div>95<img alt="Deadeye" /></div></td></tr>'
            for name in names
        )

    browser = _FakeBrowser(
        {
            page1_url: f"<html><body>{_rows('A')}</body></html>",
            page2_url: f"<html><body>{_rows('B', 'C')}</body></html>",
            page3_url: f"<html><body>{_rows('D')}</body></html>",
            "https://poe.ninja/poe2/builds/runesofaldur/character/acctA/CharA": _build_page(code_a),
            "https://poe.ninja/poe2/builds/runesofaldur/character/acctD/CharD": _build_page(code_d),
        }
    )
    from server.knowledge import research_intake_ledger

    ledger_path = tmp_path / "ledger.sqlite"
    for name in ("B", "C"):
        research_intake_ledger.record_case(
            ledger_path,
            league="runesofaldur",
            character_ref=research_intake_ledger.character_ref(f"acct{name}", f"Char{name}"),
            source_hash=f"seen-{name}",
        )
    stats: dict = {}

    cases = run_phase45_researcher_batch._cases_from_ninja(
        league_url="runesofaldur",
        limit=2,
        level_min=95,
        level_max=95,
        ascendancies=[],
        browser_driver=browser,
        intake_ledger_path=ledger_path,
        collector_stats=stats,
    )

    assert [case["sampleId"] for case in cases] == [
        "case:phase45-researcher-001",
        "case:phase45-researcher-002",
    ]
    assert stats["pagesFetched"] == 3
    assert stats["skippedAlreadyResearched"] == 2
    assert any("page=3" in url for url in browser.urls)
    assert browser.urls[-1].endswith("/character/acctD/CharD")


def _sample_code(skill_id: str, *, ascendancy: str, level: int) -> str:
    return pob_code.encode_code(_sample_xml(skill_id, ascendancy=ascendancy, level=level))


def _sample_xml(skill_id: str, *, ascendancy: str, level: int) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<PathOfBuilding2>
  <Build level="{level}" className="Ranger" ascendClassName="{ascendancy}" mainSocketGroup="1" />
  <Skills>
    <Skill mainActiveSkillCalcs="{skill_id}">
      <Gem nameSpec="{skill_id}" skillId="{skill_id}" enabled="true" />
    </Skill>
  </Skills>
</PathOfBuilding2>
"""


def _build_page(code: str) -> str:
    return f"""
<html>
  <head><title>Builds - Fixture - Path of Exile 2 - poe.ninja</title></head>
  <body>
    <input aria-label="Import code for Path of Building" type="text" value="{escape(code, quote=True)}" />
  </body>
</html>
"""
