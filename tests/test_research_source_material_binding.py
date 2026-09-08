"""V03：取证必须绑定冻结材料，不能把新内容挂在旧来源hash下。"""

from contextlib import closing
import hashlib
import json
import sqlite3

import pytest

from scripts import research_mature_builds as runs
from server import paths
from server.compute import pob_code
from server.knowledge import research_workflow as workflow


def _xml(level=95):
    return f'''<PathOfBuilding2><Build level="{level}" className="Ranger" ascendClassName="Deadeye" mainSocketGroup="1"/>
    <Skills activeSkillSet="1"><SkillSet id="1"><Skill enabled="true"><Gem nameSpec="Lightning Arrow" skillId="LightningArrowPlayer" enabled="true"/></Skill></SkillSet></Skills>
    <Items activeItemSet="1"><ItemSet id="1"/></Items><Tree activeSpec="1"><Spec treeVersion="0_5" nodes=""><Sockets/></Spec></Tree><Config/></PathOfBuilding2>'''


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    root = tmp_path / "user-data" / "research"
    monkeypatch.setattr(paths, "research_runtime_dir", lambda: root)
    monkeypatch.setattr(paths, "mature_learning_path", lambda: tmp_path / "memory.sqlite")
    monkeypatch.setattr(runs, "DEFAULT_INTAKE_LEDGER_PATH", tmp_path / "intake.sqlite")
    monkeypatch.setattr(runs, "_identity_resolvability_hint", lambda **_: {})
    monkeypatch.setattr(runs.research_readback, "build_safe_readback", lambda *_args, **_kwargs: {"status": "unavailable", "errorCode": "synthetic_readback_unavailable"})

    def queue(material):
        source = tmp_path / "source.txt"
        source.write_text(material, encoding="utf-8")
        report = workflow.start_run(source_files=[str(source)], source_game_patch="0.5.4", limit=1)
        directory = root / "runs" / report["runId"]
        db = directory / runs.QUEUE_DB_FILENAME
        row = runs._fetch_cases(db)[0]
        quarantine = directory / "quarantine" / (row["sourceHash"] + ".json")
        return report, directory, db, row, quarantine

    return queue


def test_mutable_url_is_resolved_once_and_claim_uses_the_frozen_content(runtime, monkeypatch):
    url = "https://example.invalid/current-build"
    remote = {"xml": _xml(), "calls": 0}
    original = runs.legacy_batch._source_to_xml

    def resolve(value):
        if value == url:
            remote["calls"] += 1
            return remote["xml"]
        return original(value)

    monkeypatch.setattr(runs.legacy_batch, "_source_to_xml", resolve)
    report, _, db, row, quarantine = runtime(url)
    assert remote["calls"] == 1
    frozen = quarantine.read_bytes()
    assert row["sourceHash"] == hashlib.sha256(_xml().encode()).hexdigest()
    assert url not in frozen.decode()
    remote["xml"] = _xml(96)
    claim = workflow.claim_case(run_ref=report["runRef"])
    page = workflow.read_case(run_ref=report["runRef"], lease_token=claim["leaseToken"], section="build")
    assert page["items"][0]["level"] == 95
    assert remote["calls"] == 1
    assert quarantine.read_bytes() == frozen
    assert runs._fetch_cases(db)[0]["sourceHash"] == row["sourceHash"]


@pytest.mark.parametrize("field,value", [
    ("rawImportCode", pob_code.encode_code(_xml(96))),
    ("rawXml", _xml(96)), ("sampleId", "case:other"),
    ("sourceHash", "f" * 64), ("sourceHashRef", "source-hash:" + "f" * 16),
])
def test_claim_rejects_drifted_quarantine_without_changing_identity(runtime, field, value):
    report, _, db, before, quarantine = runtime(pob_code.encode_code(_xml()))
    stored = json.loads(quarantine.read_text(encoding="utf-8"))
    stored[field] = value
    quarantine.write_text(json.dumps(stored), encoding="utf-8")
    result = workflow.claim_case(run_ref=report["runRef"])
    assert result["status"] == "claim_packet_failed"
    assert result["leaseReleased"] is True
    after = runs._fetch_cases(db)[0]
    assert after["status"] == "queued"
    assert after["sourceHash"] == before["sourceHash"]
    assert after["packetSafeHash"] == before["packetSafeHash"]


def test_read_does_not_trust_a_packets_declared_hash_after_content_changes(runtime):
    report, directory, _, _, _ = runtime(pob_code.encode_code(_xml()))
    claim = workflow.claim_case(run_ref=report["runRef"])
    packet_path = next((directory / runs.DEFAULT_TEMP_DIRNAME).glob("*/packet.json"))
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    packet["rawContext"]["rawXml"] = _xml(96)
    packet_path.write_text(json.dumps(packet), encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="transient packet not found"):
        workflow.read_case(run_ref=report["runRef"], lease_token=claim["leaseToken"], section="build")


def test_legacy_url_quarantine_is_not_refetched_or_relabelled(runtime, monkeypatch):
    report, directory, db, row, quarantine = runtime(pob_code.encode_code(_xml()))
    url = "https://example.invalid/legacy-link"
    old_hash = hashlib.sha256(url.encode()).hexdigest()
    stored = json.loads(quarantine.read_text(encoding="utf-8"))
    stored.update(rawImportCode=url, sourceHash=old_hash, sourceHashRef="source-hash:" + old_hash[:16])
    legacy = directory / "quarantine" / f"{old_hash}.json"
    legacy.write_text(json.dumps(stored), encoding="utf-8")
    with closing(sqlite3.connect(db)) as con, con:
        con.execute("UPDATE cases SET source_hash=?,source_hash_ref=?", (old_hash, stored["sourceHashRef"]))
    monkeypatch.setattr(runs.legacy_batch, "_source_to_xml", lambda *_: pytest.fail("legacy source must not be fetched"))
    result = workflow.claim_case(run_ref=report["runRef"])
    assert result["status"] == "claim_packet_failed"
    assert legacy.is_file() and quarantine.is_file()


def test_legacy_inline_code_without_cached_xml_remains_verifiable(runtime):
    report, _, _, _, quarantine = runtime(pob_code.encode_code(_xml()))
    stored = json.loads(quarantine.read_text(encoding="utf-8"))
    stored.pop("rawXml")
    quarantine.write_text(json.dumps(stored), encoding="utf-8")
    assert workflow.claim_case(run_ref=report["runRef"])["status"] == "claimed"
