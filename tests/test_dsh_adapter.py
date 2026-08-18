from __future__ import annotations

from pathlib import Path
import shutil

import pytest

from scripts import adapt_skills_for_dsh as adapt
from scripts import install_dsh_preset as installer


ROOT = Path(__file__).resolve().parents[1]


def _write_source_preset(root: Path, *, marker: str = "new") -> Path:
    source = root / "source-preset"
    source.mkdir(parents=True)
    (source / "agent.cordis.yml").write_text(
        f"cwd: {installer.DEFAULT_ROOT_LITERAL}\nmarker: {marker}\n",
        encoding="utf-8",
    )
    (source / "preset.yml").write_text(f"name: {marker}\n", encoding="utf-8")
    for skill in installer.REQUIRED_SKILLS:
        skill_dir = source / "skills" / skill
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            f"---\nname: {skill}\ndescription: fixture\n---\n\n# {skill}\n",
            encoding="utf-8",
        )
    return source


def _write_installed_preset(target: Path, *, marker: str = "old") -> None:
    target.mkdir(parents=True)
    (target / "agent.cordis.yml").write_text(f"marker: {marker}\n", encoding="utf-8")
    (target / "preset.yml").write_text(f"name: {marker}\n", encoding="utf-8")
    (target / "old.txt").write_text(marker, encoding="utf-8")


def test_adapt_skills_regenerates_the_checked_in_tree(tmp_path):
    out = tmp_path / "skills"

    assert adapt.main(["--out", str(out)]) == 0
    assert adapt.main(["--out", str(out), "--check"]) == 0

    checked_in = ROOT / "dsh" / "agent-presets" / "poe-bd" / "skills"
    expected_files = adapt.expected_skill_files(adapt.SOURCE_SKILLS)
    assert {
        path.relative_to(out).as_posix() for path in out.rglob("*") if path.is_file()
    } == expected_files
    for rel in expected_files:
        assert (out / rel).read_text(encoding="utf-8") == (checked_in / rel).read_text(
            encoding="utf-8"
        )


def test_adapt_check_reports_stale_generated_files(tmp_path):
    out = tmp_path / "skills"
    assert adapt.main(["--out", str(out)]) == 0
    (out / "stale.md").write_text("stale", encoding="utf-8")

    assert adapt.main(["--out", str(out), "--check"]) == 1


def test_tool_mapping_rejects_cross_server_name_collision():
    with pytest.raises(SystemExit, match="more than one DSH server"):
        adapt.tool_to_prefixed({"poe_build": ["same_tool"], "poe_research": ["same_tool"]})


def test_rewrite_preserves_longer_tool_names_and_converts_legacy_prefix():
    mapping = {"poe_build": ["get_build", "get_build_stats"]}

    rewritten = adapt.rewrite_text(
        "get_build get_build_stats poe_build_mcp__get_build",
        mapping,
        "fixture",
    )

    assert rewritten == (
        "mcp__poe_build__get_build mcp__poe_build__get_build_stats mcp__poe_build__get_build"
    )


def test_install_dry_run_never_removes_existing_backup(tmp_path):
    source = _write_source_preset(tmp_path)
    target = tmp_path / "home" / ".agent-presets" / "poe-bd"
    _write_installed_preset(target)
    backup = target.with_name("poe-bd.bak")
    _write_installed_preset(backup, marker="backup")

    result = installer.install_preset(
        source=source,
        target=target,
        repo_root=None,
        dry_run=True,
    )

    assert result["status"] == "conflict"
    assert result["errorCode"] == "backup_already_exists"
    assert (backup / "old.txt").read_text(encoding="utf-8") == "backup"
    assert (target / "old.txt").read_text(encoding="utf-8") == "old"


def test_install_stages_then_swaps_and_doctor_accepts_result(tmp_path):
    source = _write_source_preset(tmp_path)
    target = tmp_path / "home" / ".agent-presets" / "poe-bd"
    _write_installed_preset(target)

    result = installer.install_preset(
        source=source,
        target=target,
        repo_root="F:\\portable\\poe-bd-creator",
    )

    backup = target.with_name("poe-bd.bak")
    assert result["status"] == "installed"
    assert (backup / "old.txt").read_text(encoding="utf-8") == "old"
    assert "F:/portable/poe-bd-creator" in (target / "agent.cordis.yml").read_text(encoding="utf-8")
    assert not target.with_name("poe-bd.next").exists()
    doctor = installer.doctor_preset(source=source, target=target)
    assert doctor["status"] == "healthy"
    # The kept backup of the previous version is informational, not gating.
    assert doctor["checks"]["backupKept"] is True


def test_install_copy_failure_preserves_current_target(tmp_path, monkeypatch):
    source = _write_source_preset(tmp_path)
    target = tmp_path / "home" / ".agent-presets" / "poe-bd"
    _write_installed_preset(target)

    def fail_copytree(source_path, staging_path, **kwargs):
        del source_path, kwargs
        Path(staging_path).mkdir(parents=True)
        raise OSError("copy failed")

    monkeypatch.setattr(installer.shutil, "copytree", fail_copytree)
    result = installer.install_preset(source=source, target=target, repo_root=None)

    assert result["status"] == "error"
    assert result["errorCode"] == "install_failed"
    assert (target / "old.txt").read_text(encoding="utf-8") == "old"
    assert not target.with_name("poe-bd.bak").exists()
    assert not target.with_name("poe-bd.next").exists()


def test_install_swap_failure_restores_backup(tmp_path, monkeypatch):
    source = _write_source_preset(tmp_path)
    target = tmp_path / "home" / ".agent-presets" / "poe-bd"
    _write_installed_preset(target)
    real_move = shutil.move

    def fail_staging_move(source_path, destination_path, *args, **kwargs):
        if Path(source_path).name == "poe-bd.next":
            raise OSError("swap failed")
        return real_move(source_path, destination_path, *args, **kwargs)

    monkeypatch.setattr(installer.shutil, "move", fail_staging_move)
    result = installer.install_preset(source=source, target=target, repo_root=None)

    assert result["status"] == "error"
    assert result["errorCode"] == "install_failed"
    assert (target / "old.txt").read_text(encoding="utf-8") == "old"
    assert not target.with_name("poe-bd.bak").exists()
    assert not target.with_name("poe-bd.next").exists()


def test_install_rejects_orphan_backup(tmp_path):
    source = _write_source_preset(tmp_path)
    target = tmp_path / "home" / ".agent-presets" / "poe-bd"
    backup = target.with_name("poe-bd.bak")
    _write_installed_preset(backup, marker="orphan")

    result = installer.install_preset(source=source, target=target, repo_root=None)

    assert result["status"] == "conflict"
    assert result["errorCode"] == "orphan_backup_exists"
    assert not target.exists()
    assert (backup / "old.txt").read_text(encoding="utf-8") == "orphan"


def test_dsh_compositions_register_all_domain_servers():
    patch = (ROOT / "dsh" / "poe-bd.mcp.cordis.yml").read_text(encoding="utf-8")
    agent = (ROOT / "dsh" / "agent-presets" / "poe-bd" / "agent.cordis.yml").read_text(
        encoding="utf-8"
    )
    for server, module in {
        "poe_knowledge": "server.mcp.knowledge_server",
        "poe_build": "server.mcp.build_server",
        "poe_research": "server.mcp.research_server",
        "poe_learning": "server.mcp.learning_server",
    }.items():
        for text in (patch, agent):
            assert f"serverName: {server}" in text
            assert module in text
    for text in (patch, agent):
        assert text.count("process.env.POE_BD_UV") == 4
        assert text.count("process.platform === 'win32'") >= 4
        assert text.count(": 'uv')") == 4


def test_doctor_reports_staging_residue(tmp_path):
    source = _write_source_preset(tmp_path)
    target = tmp_path / "home" / ".agent-presets" / "poe-bd"
    assert (
        installer.install_preset(source=source, target=target, repo_root=None)["status"]
        == "installed"
    )
    target.with_name("poe-bd.next").mkdir()

    result = installer.doctor_preset(source=source, target=target)

    assert result["status"] == "unhealthy"
    assert result["checks"]["stagingResidue"] is False


def test_doctor_reports_orphan_backup_when_target_missing(tmp_path):
    source = _write_source_preset(tmp_path)
    target = tmp_path / "home" / ".agent-presets" / "poe-bd"
    _write_installed_preset(target.with_name("poe-bd.bak"), marker="orphan")

    result = installer.doctor_preset(source=source, target=target)

    assert result["status"] == "unhealthy"
    assert result["checks"]["installed"] is False
    assert result["checks"]["orphanBackup"] is False


def test_doctor_does_not_crash_on_partial_install(tmp_path):
    source = _write_source_preset(tmp_path)
    target = tmp_path / "home" / ".agent-presets" / "poe-bd"
    # agent.cordis.yml present but the skills/ tree is missing entirely.
    _write_installed_preset(target)

    result = installer.doctor_preset(source=source, target=target)

    assert result["status"] == "unhealthy"
    assert result["checks"]["skillsInstalled"] is False
    assert result["checks"]["frontmatter"] is False
