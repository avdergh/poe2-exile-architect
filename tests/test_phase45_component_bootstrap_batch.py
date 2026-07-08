from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json

from scripts import run_phase45_component_bootstrap_batch
from server.compute import pob_code
from server.knowledge import mature_learning
from server.knowledge import physical_graph as pg


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
)


def test_component_bootstrap_batch_writes_one_low_trust_case_observation_per_source(tmp_path):
    source_one = _write_source(tmp_path, "one.txt", _sample_code("HollowFocusPlayer"))
    source_two = _write_source(tmp_path, "two.txt", _sample_code("BarragePlayer"))
    manifest = _write_manifest(tmp_path, [source_one, source_two])
    report = run_phase45_component_bootstrap_batch.write_phase45_component_bootstrap_batch_report(
        source_files=[source_one, source_two],
        manifest_file=manifest,
        graph_snapshot_index=_write_snapshot_index(tmp_path),
        db_path=tmp_path / "memory.sqlite",
        json_output=tmp_path / "report.json",
        md_output=tmp_path / "report.md",
    )

    assert report["status"] == "accepted"
    assert report["sampleCount"] == 2
    assert report["acceptedPatternCount"] == 2
    assert report["acceptedObservationCount"] == 2
    assert report["deferredSampleCount"] == 0
    assert all(sample["confidenceTier"] == "case_observation" for sample in report["samples"])
    assert all(sample["dedupeQueryRef"].startswith("dq-") for sample in report["samples"])

    serialized = json.dumps(report, ensure_ascii=False)
    assert not any(marker in serialized for marker in RAW_MARKERS)
    assert "common" not in serialized.casefold()
    assert "usually" not in serialized.casefold()
    assert "常见" not in serialized

    con = mature_learning.connect(tmp_path / "memory.sqlite")
    try:
        assert con.execute("SELECT count(*) FROM research_build_patterns").fetchone()[0] == 2
        rows = con.execute(
            "SELECT confidence_tier, sample_count FROM research_build_patterns"
        ).fetchall()
        assert {row["confidence_tier"] for row in rows} == {"case_observation"}
        assert {row["sample_count"] for row in rows} == {1}
    finally:
        con.close()

    assert "Phase 4.5 Programmatic Component Bootstrap" in (tmp_path / "report.md").read_text(
        encoding="utf-8"
    )
    assert "Deep MCP" not in (tmp_path / "report.md").read_text(encoding="utf-8")


def test_component_bootstrap_batch_dedupes_duplicate_source_files(tmp_path):
    source_one = _write_source(tmp_path, "one.txt", _sample_code("HollowFocusPlayer"))
    manifest = _write_manifest(tmp_path, [source_one])

    report = run_phase45_component_bootstrap_batch.write_phase45_component_bootstrap_batch_report(
        source_files=[source_one, source_one],
        manifest_file=manifest,
        graph_snapshot_index=_write_snapshot_index(tmp_path),
        db_path=tmp_path / "memory.sqlite",
        json_output=tmp_path / "report.json",
        md_output=tmp_path / "report.md",
    )

    assert report["status"] == "accepted"
    assert report["sampleCount"] == 1
    assert report["duplicateInputCount"] == 1
    assert report["acceptedPatternCount"] == 1


def test_component_bootstrap_batch_keeps_distinct_sources_with_same_components_as_cases(tmp_path):
    source_one = _write_source(tmp_path, "one.txt", _sample_code("HollowFocusPlayer"))
    variant_code = _sample_code("HollowFocusPlayer", level=93)
    source_two = _write_source(tmp_path, "two.txt", variant_code)
    manifest = _write_manifest(tmp_path, [source_one, source_two])

    report = run_phase45_component_bootstrap_batch.write_phase45_component_bootstrap_batch_report(
        source_files=[source_one, source_two],
        manifest_file=manifest,
        graph_snapshot_index=_write_snapshot_index(tmp_path),
        db_path=tmp_path / "memory.sqlite",
        json_output=tmp_path / "report.json",
        md_output=tmp_path / "report.md",
    )

    assert report["status"] == "accepted"
    assert report["sampleCount"] == 2
    assert report["acceptedPatternCount"] == 2
    assert len({sample["patternIds"][0] for sample in report["samples"]}) == 2

    con = mature_learning.connect(tmp_path / "memory.sqlite")
    try:
        assert con.execute("SELECT count(*) FROM research_build_patterns").fetchone()[0] == 2
    finally:
        con.close()


def test_component_bootstrap_batch_dedupes_whitespace_variants_after_decode(tmp_path):
    code = _sample_code("HollowFocusPlayer")
    source_one = _write_source(tmp_path, "one.txt", code)
    spaced_code = code[:12] + "\n \t" + code[12:]
    source_two = _write_source(
        tmp_path,
        "two.txt",
        spaced_code,
    )
    manifest = _write_manifest(tmp_path, [source_one])

    report = run_phase45_component_bootstrap_batch.write_phase45_component_bootstrap_batch_report(
        source_files=[source_one, source_two],
        manifest_file=manifest,
        graph_snapshot_index=_write_snapshot_index(tmp_path),
        db_path=tmp_path / "memory.sqlite",
        json_output=tmp_path / "report.json",
        md_output=tmp_path / "report.md",
    )

    assert report["status"] == "accepted"
    assert report["sampleCount"] == 1
    assert report["duplicateInputCount"] == 1
    assert report["acceptedPatternCount"] == 1


def test_component_bootstrap_batch_defers_bad_source_without_leaking_raw_error(tmp_path):
    bad_source = _write_source(tmp_path, "bad.txt", "not a valid import")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "reportId": "phase4-pattern-bootstrap-manifest-v1",
                "safeArtifactOnly": True,
                "sampleCount": 0,
                "samples": [],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    report = run_phase45_component_bootstrap_batch.write_phase45_component_bootstrap_batch_report(
        source_files=[bad_source],
        manifest_file=manifest,
        graph_snapshot_index=_write_snapshot_index(tmp_path),
        db_path=tmp_path / "memory.sqlite",
        json_output=tmp_path / "report.json",
        md_output=tmp_path / "report.md",
    )

    assert report["status"] == "partial"
    assert report["sampleCount"] == 1
    assert report["deferredSampleCount"] == 1
    assert report["samples"][0]["deferReason"] == "transient_decode_failed"
    serialized = json.dumps(report, ensure_ascii=False)
    assert not any(marker in serialized for marker in RAW_MARKERS)


def _sample_code(active_skill_id: str, *, level: int = 92) -> str:
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<PathOfBuilding2>
  <Build level="{level}" className="Monk" ascendClassName="Martial Artist" mainSocketGroup="1" />
  <Skills>
    <Skill mainActiveSkillCalcs="{active_skill_id}">
      <Gem nameSpec="{active_skill_id}" skillId="{active_skill_id}" enabled="true" />
      <Gem nameSpec="Cooldown Recovery II" gemId="Metadata/Items/Gems/SupportGemIngenuityTwo" enabled="true" />
    </Skill>
  </Skills>
  <Tree>
    <Spec nodes="45918" />
  </Tree>
  <Items>
    <Item>Rarity: Unique
Rite of Passage
Diamond
--------</Item>
  </Items>
</PathOfBuilding2>
"""
    return pob_code.encode_code(xml)


def _write_source(tmp_path, filename: str, source: str):
    path = tmp_path / filename
    path.write_text(source, encoding="utf-8")
    return path


def _write_manifest(tmp_path, source_files):
    samples = []
    for index, source_file in enumerate(source_files, start=1):
        source = source_file.read_text(encoding="utf-8").strip()
        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()[:12]
        samples.append(
            {
                "sampleId": f"case:fixture-{index:03d}",
                "buildFamilyKey": "fixture-family",
                "sourceDiversityKey": f"source:{digest}",
                "guideVariantKey": f"variant:{digest}",
            }
        )
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "reportId": "phase4-pattern-bootstrap-manifest-v1",
                "safeArtifactOnly": True,
                "sampleCount": len(samples),
                "samples": samples,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def _write_snapshot_index(tmp_path):
    source = pg.GraphSource(
        source_id="fixture:phase45_component_bootstrap",
        kind="test_fixture",
        source_file="tests/test_phase45_component_bootstrap_batch.py",
        claims=(pg.SourceClaim("passive_tree_version", "0_5"),),
    )
    nodes = (
        pg.GraphNode(
            "ascendancy:monk:martial_artist",
            "ascendancy",
            "Martial Artist",
            (source.source_id,),
        ),
        pg.GraphNode(
            "skill:HollowFocusPlayer",
            "active_skill",
            "Hollow Focus",
            (source.source_id,),
        ),
        pg.GraphNode(
            "skill:BarragePlayer",
            "active_skill",
            "Barrage",
            (source.source_id,),
        ),
        pg.GraphNode(
            "support:Metadata/Items/Gems/SupportGemIngenuityTwo",
            "support_gem",
            "Cooldown Recovery II",
            (source.source_id,),
        ),
        pg.GraphNode(
            "keystone:pob:0_5:45918",
            "keystone",
            "Mind Over Matter",
            (source.source_id,),
        ),
        pg.GraphNode(
            "unique:pob:rite_of_passage",
            "unique",
            "Rite of Passage",
            (source.source_id,),
        ),
    )
    aliases = (
        pg.GraphAlias("Martial Artist", "ascendancy:monk:martial_artist", (source.source_id,)),
        pg.GraphAlias("Hollow Focus", "skill:HollowFocusPlayer", (source.source_id,)),
        pg.GraphAlias("Barrage", "skill:BarragePlayer", (source.source_id,)),
        pg.GraphAlias(
            "Cooldown Recovery II",
            "support:Metadata/Items/Gems/SupportGemIngenuityTwo",
            (source.source_id,),
        ),
        pg.GraphAlias("Mind Over Matter", "keystone:pob:0_5:45918", (source.source_id,)),
        pg.GraphAlias("Rite of Passage", "unique:pob:rite_of_passage", (source.source_id,)),
    )
    snapshot = pg.GraphSnapshot(
        snapshot_id="snapshot:phase45-component-bootstrap",
        created_at=datetime(2026, 7, 6, tzinfo=UTC),
        sources=(source,),
        nodes=nodes,
        edges=(),
        aliases=aliases,
    )
    snapshot_path = tmp_path / "snapshot.json"
    index_path = tmp_path / "snapshot_index.sqlite"
    pg.save_snapshot(snapshot, snapshot_path)
    pg.register_snapshot(index_path, snapshot, snapshot_path)
    return index_path
