"""Cross-run research intake ledger unit tests."""

from __future__ import annotations

import sqlite3

from server.knowledge import research_intake_ledger
from server import paths


def test_default_ledger_path_lives_in_user_data(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path)
    assert research_intake_ledger.default_ledger_path() == tmp_path / "research_intake.sqlite"


def test_character_ref_is_stable_casefolded_and_never_contains_raw_names():
    first = research_intake_ledger.character_ref("Acct A", "ChärA")
    second = research_intake_ledger.character_ref("  acct a ", "chära")
    assert first == second
    assert first.startswith("character-hash:")
    assert "Acct" not in first and "ChärA" not in first
    assert len(first) == len("character-hash:") + 16
    assert research_intake_ledger.character_ref("a", "b") != research_intake_ledger.character_ref(
        "b", "a"
    )


def test_character_ref_decodes_path_segment_encoding_without_treating_plus_as_space():
    assert research_intake_ledger.character_ref("acctA", "Char%20A") == (
        research_intake_ledger.character_ref("acctA", "Char A")
    )
    assert research_intake_ledger.character_ref("acctA", "X+Y") == (
        research_intake_ledger.character_ref("acctA", "X+Y")
    )
    assert research_intake_ledger.character_ref("acctA", "X+Y") != (
        research_intake_ledger.character_ref("acctA", "X Y")
    )


def test_record_seen_and_summary_roundtrip(tmp_path):
    ledger = tmp_path / "ledger.sqlite"
    ref_a = research_intake_ledger.character_ref("acctA", "CharA")
    ref_b = research_intake_ledger.character_ref("acctB", "CharB")

    assert research_intake_ledger.seen_character_refs(ledger, "league-x") == set()
    assert (
        research_intake_ledger.record_case(
            ledger,
            league="league-x",
            character_ref=ref_a,
            source_hash="h1",
            level=95,
            ascendancy="Deadeye",
            main_skill="LightningArrowPlayer",
            sample_id="case:poe-bd-research-abc",
        )
        is True
    )
    assert (
        research_intake_ledger.record_case(
            ledger,
            league="league-x",
            character_ref=ref_a,
            source_hash="h1-new",
            level=96,
            sample_id="case:poe-bd-research-abc",
        )
        is False
    )
    research_intake_ledger.record_case(
        ledger,
        league="league-y",
        character_ref=ref_b,
        source_hash="h2",
    )

    assert research_intake_ledger.seen_character_refs(ledger, "league-x") == {ref_a}
    assert research_intake_ledger.seen_character_refs(ledger, "league-y") == {ref_b}
    assert research_intake_ledger.seen_character_refs(ledger, "league-z") == set()

    summary = research_intake_ledger.summary(ledger)
    assert summary["totalRecords"] == 2
    assert summary["byStatus"] == {"queued": 2}
    assert summary["leagues"] == {"league-x": 1, "league-y": 1}

    league_summary = research_intake_ledger.summary(ledger, league="league-x")
    assert league_summary["totalRecords"] == 1
    assert league_summary["byStatus"] == {"queued": 1}
    assert "leagues" not in league_summary


def test_mark_accepted_promotes_and_preserves_status(tmp_path):
    ledger = tmp_path / "ledger.sqlite"
    ref = research_intake_ledger.character_ref("acctA", "CharA")
    research_intake_ledger.record_case(
        ledger, league="league-x", character_ref=ref, source_hash="h1"
    )

    assert (
        research_intake_ledger.mark_accepted(ledger, league="league-x", character_ref=ref) is True
    )
    assert (
        research_intake_ledger.mark_accepted(ledger, league="league-x", character_ref=ref) is False
    )
    assert research_intake_ledger.summary(ledger)["byStatus"] == {"accepted": 1}

    research_intake_ledger.record_case(
        ledger, league="league-x", character_ref=ref, source_hash="h1"
    )
    assert research_intake_ledger.summary(ledger)["byStatus"] == {"accepted": 1}


def test_mark_accepted_only_promotes_the_exact_character(tmp_path):
    ledger = tmp_path / "ledger.sqlite"
    ref_a = research_intake_ledger.character_ref("acctA", "CharA")
    ref_b = research_intake_ledger.character_ref("acctB", "CharB")
    shared_source_hash = "identical-build-xml"
    research_intake_ledger.record_case(
        ledger,
        league="league-x",
        character_ref=ref_a,
        source_hash=shared_source_hash,
    )
    research_intake_ledger.record_case(
        ledger,
        league="league-x",
        character_ref=ref_b,
        source_hash=shared_source_hash,
    )
    research_intake_ledger.record_case(
        ledger,
        league="league-y",
        character_ref=ref_a,
        source_hash=shared_source_hash,
    )

    assert (
        research_intake_ledger.mark_accepted(ledger, league="league-x", character_ref=ref_a) is True
    )
    summary = research_intake_ledger.summary(ledger)
    assert summary["totalRecords"] == 3
    assert summary["byStatus"] == {"accepted": 1, "queued": 2}
    assert research_intake_ledger.seen_character_refs(ledger, "league-x") == {ref_a, ref_b}
    assert research_intake_ledger.summary(ledger, league="league-x")["byStatus"] == {
        "accepted": 1,
        "queued": 1,
    }


def test_release_queued_case_requires_exact_owner_and_preserves_accepted(tmp_path):
    ledger = tmp_path / "ledger.sqlite"
    queued_ref = research_intake_ledger.character_ref("acctA", "CharA")
    accepted_ref = research_intake_ledger.character_ref("acctB", "CharB")
    research_intake_ledger.record_case(
        ledger,
        league="league-x",
        character_ref=queued_ref,
        source_hash="source-a",
        sample_id="case:a",
    )
    research_intake_ledger.record_case(
        ledger,
        league="league-x",
        character_ref=accepted_ref,
        source_hash="source-b",
        sample_id="case:b",
    )
    research_intake_ledger.mark_accepted(ledger, league="league-x", character_ref=accepted_ref)

    assert (
        research_intake_ledger.release_queued_case(
            ledger,
            league="league-x",
            character_ref=queued_ref,
            source_hash="wrong-source",
            sample_id="case:a",
        )
        == "ownership_mismatch"
    )
    assert (
        research_intake_ledger.release_queued_case(
            ledger,
            league="league-x",
            character_ref=accepted_ref,
            source_hash="source-b",
            sample_id="case:b",
        )
        == "accepted_preserved"
    )
    assert (
        research_intake_ledger.release_queued_case(
            ledger,
            league="league-x",
            character_ref=queued_ref,
            source_hash="source-a",
            sample_id="case:a",
        )
        == "released"
    )
    assert research_intake_ledger.seen_character_refs(ledger, "league-x") == {accepted_ref}
    assert research_intake_ledger.summary(ledger)["byStatus"] == {"accepted": 1}


def test_ledger_never_stores_raw_identities_or_import_material(tmp_path):
    ledger = tmp_path / "ledger.sqlite"
    research_intake_ledger.record_case(
        ledger,
        league="league-x",
        character_ref=research_intake_ledger.character_ref("acctA", "CharA"),
        source_hash="deadbeef",
        level=95,
        ascendancy="Deadeye",
        main_skill="LightningArrowPlayer",
    )
    with sqlite3.connect(ledger) as conn:
        row = conn.execute(
            "SELECT league, character_ref, source_hash, ascendancy, main_skill FROM intake_records"
        ).fetchone()
    assert row is not None
    league, character_ref, source_hash, ascendancy, main_skill = row
    assert "acctA" not in league and "CharA" not in league
    assert "acctA" not in character_ref and "CharA" not in character_ref
    assert source_hash == "deadbeef"
    assert ascendancy == "Deadeye"
    assert main_skill == "LightningArrowPlayer"
    raw_blob = ledger.read_bytes()
    assert b"acctA" not in raw_blob and b"CharA" not in raw_blob


def test_missing_ledger_reads_empty_without_creating_file(tmp_path):
    ledger = tmp_path / "does-not-exist.sqlite"
    assert research_intake_ledger.seen_character_refs(ledger, "league-x") == set()
    assert research_intake_ledger.summary(ledger)["totalRecords"] == 0
    assert not ledger.exists()


def test_corrupt_ledger_reads_empty_without_raising(tmp_path):
    ledger = tmp_path / "corrupt.sqlite"
    ledger.write_text("not a sqlite file", encoding="utf-8")
    assert research_intake_ledger.seen_character_refs(ledger, "league-x") == set()
    assert research_intake_ledger.summary(ledger)["totalRecords"] == 0


def test_schema_version_is_recorded():
    assert isinstance(research_intake_ledger.SCHEMA_VERSION, int)
    assert research_intake_ledger.SCHEMA_VERSION >= 1
