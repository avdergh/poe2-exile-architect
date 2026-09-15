from __future__ import annotations

from pathlib import Path
import json
import shutil

import pytest

from scripts import adapt_skills_for_dsh as adapt
from scripts import install_dsh_preset as installer


ROOT = Path(__file__).resolve().parents[1]


def _write_source_preset(root: Path, *, marker: str = "new") -> Path:
    source = root / "source-preset"
    source.mkdir(parents=True)
    (source / "agent.cordis.yml").write_text(
        f"cwd: !!js \"process.env.POE_BD_CREATOR_ROOT ?? '{installer.ROOT_TOKEN}'\"\n"
        f"uv: !!js \"process.env.POE_BD_UV ?? '{installer.UV_TOKEN}'\"\n"
        f"marker: {marker}\n",
        encoding="utf-8",
    )
    # Fixture compositions name no plugin rows, so an empty row snapshot keeps the
    # row-resolution gate meaningful without pinning a real DSH version here.
    (source / installer.ROW_SNAPSHOT_FILE).write_text(
        json.dumps({"dshVersion": "fixture", "rowNames": []}), encoding="utf-8"
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
    create = (out / "poe-bd-create" / "SKILL.md").read_text(encoding="utf-8")
    assert "`mcp__poe_knowledge__*`" in create
    assert "`mcp__poe_build__*`" in create
    assert "`poe-knowledge-mcp`" not in create
    controller = (out / "poe-bd-research" / "SKILL.md").read_text(encoding="utf-8")
    worker = (out / "poe-bd-research-worker" / "SKILL.md").read_text(encoding="utf-8")
    assert not (out / "poe-bd-research-loop").exists()
    assert "subagent" in controller and "send_message" in controller
    assert "mcp__poe_research__start_research_run" in controller
    assert "queue 由 DSH shell" not in controller
    assert "`fork_turns=none`" not in controller
    assert "wait_agent(" not in controller
    assert "必须 fork" not in controller
    assert "DSH Worker" in worker
    assert "skill` 工具加载本 skill" in worker
    assert "mcp__poe_research__claim_research_case" in worker
    assert "取得 runDir 后用 shell" not in worker
    assert "`enableGlobal1` / `enableGlobal2` 是单颗 gem 的 granted-effect 开关" in worker
    assert "`weaponSetScope` 才是技能组级字段" in worker
    assert "`global` / `weapon_set_1` /\n  `weapon_set_2`" in worker
    assert "不得根据任一 gem 的 global-effect 开关推断武器切换" in worker


def test_generated_learning_loop_body_uses_dsh_subagents():
    """The generated loop driver carries DSH semantics.

    Codex thread primitives may survive only inside the adapter note.
    """
    text = (
        ROOT
        / "dsh"
        / "agent-presets"
        / "poe-bd"
        / "skills"
        / "poe-bd-learning-loop"
        / "SKILL.md"
    ).read_text(encoding="utf-8")
    body = "\n".join(line for line in text.splitlines() if not line.startswith(">"))
    for primitive in ("create_thread", "send_message_to_thread", "## 可见任务初始化"):
        assert primitive not in body
    for required in ("`subagent`", "`send_message`", "claim_learning_phase"):
        assert required in body
    assert "task_id` 与 `thread_id" in body


def test_every_source_skill_is_adapted_or_explicitly_excluded():
    assert adapt.skill_coverage_problems(adapt.SOURCE_SKILLS) == []
    adapted = set(adapt.EXTRA_NOTES)
    excluded = set(adapt.SKILL_EXCLUSIONS)
    assert adapted.isdisjoint(excluded)
    present = {path.name for path in adapt.SOURCE_SKILLS.iterdir() if path.is_dir()}
    assert adapted | excluded == present
    # The three workflows the project presents to users ship with their worker.
    assert {
        "poe-bd-research",
        "poe-bd-research-worker",
        "poe-bd-create",
        "poe-bd-learn",
    } <= adapted


def test_skill_coverage_reports_an_unadapted_source_skill(tmp_path):
    source = tmp_path / "skills"
    (source / "poe-bd-newmode").mkdir(parents=True)
    (source / "poe-bd-newmode" / "SKILL.md").write_text(
        "---\nname: poe-bd-newmode\n---\n", encoding="utf-8"
    )

    problems = adapt.skill_coverage_problems(source)

    assert problems
    assert any("poe-bd-newmode" in problem for problem in problems)


def test_polish_rules_still_match_their_source_sentences():
    assert adapt.polish_problems(adapt.SOURCE_SKILLS, adapt.load_tool_names()) == []


def test_polish_gate_reports_a_rule_that_stopped_matching(monkeypatch):
    monkeypatch.setitem(adapt.POLISH, "poe-bd-create", [("sentence that was reworded", "x")])

    problems = adapt.polish_problems(adapt.SOURCE_SKILLS, adapt.load_tool_names())

    assert problems
    assert any("POLISH rule 1" in problem for problem in problems)


def test_polish_gate_fails_the_check_and_write_paths(monkeypatch, tmp_path):
    monkeypatch.setitem(adapt.POLISH, "poe-bd-create", [("sentence that was reworded", "x")])

    assert adapt.main(["--check"]) == 1
    out = tmp_path / "skills"
    assert adapt.main(["--out", str(out)]) == 1
    assert not out.exists()


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


def test_force_reinstall_rotates_the_kept_backup(tmp_path):
    target = tmp_path / "home" / ".agent-presets" / "poe-bd"

    def place(marker: str) -> str:
        source = _write_source_preset(tmp_path / f"src-{marker}", marker=marker)
        return str(
            installer.install_preset(
                source=source, target=target, repo_root=None, uv_command="uv"
            )["status"]
        )

    assert place("v1") == "installed"
    # Second install has no kept backup yet, so it just creates one.
    assert place("v2") == "installed"
    assert "marker: v1" in (
        target.with_name("poe-bd.bak") / installer.COMPOSITION_FILE
    ).read_text(encoding="utf-8")

    source = _write_source_preset(tmp_path / "src-v3", marker="v3")
    conflict = installer.install_preset(
        source=source, target=target, repo_root=None, uv_command="uv"
    )
    assert conflict["errorCode"] == "backup_already_exists"

    forced = installer.install_preset(
        source=source, target=target, repo_root=None, uv_command="uv", force=True
    )

    assert forced["status"] == "installed"
    rotated = Path(str(forced["rotatedBackup"]))
    assert rotated.is_dir()
    assert rotated.name.startswith("poe-bd.bak.")
    assert "marker: v1" in (rotated / installer.COMPOSITION_FILE).read_text(encoding="utf-8")
    current_backup = target.with_name("poe-bd.bak")
    assert "marker: v2" in (current_backup / installer.COMPOSITION_FILE).read_text(encoding="utf-8")
    assert "marker: v3" in (target / installer.COMPOSITION_FILE).read_text(encoding="utf-8")


def test_force_never_swallows_an_orphan_backup(tmp_path):
    source = _write_source_preset(tmp_path)
    target = tmp_path / "home" / ".agent-presets" / "poe-bd"
    _write_installed_preset(target.with_name("poe-bd.bak"), marker="orphan")

    result = installer.install_preset(
        source=source, target=target, repo_root=None, uv_command="uv", force=True
    )

    assert result["status"] == "conflict"
    assert result["errorCode"] == "orphan_backup_exists"
    assert not target.exists()


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
        assert text.count("process.env.POE_BD_UV ?? '__POE_BD_UV__'") == 4
        assert text.count("process.env.POE_BD_CREATOR_ROOT") == 8
        assert text.count(installer.ROOT_TOKEN) == 8
        # No machine-specific checkout path or bundled-uv platform branch.
        assert installer.DEFAULT_ROOT_LITERAL not in text
        assert "process.platform === 'win32' ? (process.env.POE_BD_CREATOR_ROOT" not in text
    # The patch file carries only the four MCP rows, so it needs no platform branch.
    assert "process.platform" not in patch


def test_real_preset_template_installs_without_placeholder_tokens(tmp_path):
    target = tmp_path / "home" / ".agent-presets" / "poe-bd"

    result = installer.install_preset(
        source=installer.SOURCE_PRESET,
        target=target,
        repo_root=None,
        uv_command="uv",
    )

    assert result["status"] == "installed"
    composition = (target / installer.COMPOSITION_FILE).read_text(encoding="utf-8")
    assert installer.unresolved_tokens(composition) == []
    assert installer._js_path(str(installer.ROOT)) in composition
    patch = (target / installer.EMITTED_PATCH_NAME).read_text(encoding="utf-8")
    assert installer.unresolved_tokens(patch) == []
    assert "- insert:" in patch and "serverName: poe_build" in patch
    doctor = installer.doctor_preset(source=installer.SOURCE_PRESET, target=target)
    assert doctor["status"] == "healthy"
    assert doctor["checks"]["tokensResolved"] is True
    assert doctor["checks"]["emittedPatch"] is True


def test_install_rejects_a_template_without_placeholder_tokens(tmp_path):
    source = _write_source_preset(tmp_path)
    (source / installer.COMPOSITION_FILE).write_text("cwd: /some/machine/path\n", encoding="utf-8")
    target = tmp_path / "home" / ".agent-presets" / "poe-bd"

    result = installer.install_preset(
        source=source, target=target, repo_root=None, uv_command="uv"
    )

    assert result["status"] == "error"
    assert result["errorCode"] == "incomplete_source"
    assert not target.exists()


def test_install_reports_conflict_before_missing_uv(tmp_path, monkeypatch):
    source = _write_source_preset(tmp_path)
    target = tmp_path / "home" / ".agent-presets" / "poe-bd"
    _write_installed_preset(target)
    backup = target.with_name("poe-bd.bak")
    _write_installed_preset(backup, marker="backup")
    monkeypatch.setattr(installer, "resolve_uv", lambda *args, **kwargs: None)

    result = installer.install_preset(
        source=source, target=target, repo_root=None, uv_command=None
    )

    assert result["status"] == "conflict"
    assert result["errorCode"] == "backup_already_exists"


def test_dsh_bundle_manifest_and_patch_are_installable():
    """`dsh plugin add` needs a dsh.bundle manifest plus a patch that inserts
    exactly the four domain servers, and the patch must stay machine-independent."""
    import json

    bundle = ROOT / "dsh" / "bundle"
    manifest = json.loads((bundle / "package.json").read_text(encoding="utf-8"))
    patch_name = manifest["dsh"]["bundle"]["patch"]

    assert patch_name == "./cordis.patch.yml"
    patch_path = bundle / patch_name.lstrip("./")
    assert patch_path.is_file()
    # The community plugin index discovers repositories by this topic keyword.
    assert "dsh-plugin" in manifest["keywords"]
    assert manifest["license"] == "MIT"

    patch = patch_path.read_text(encoding="utf-8")
    assert patch.count("- insert:") == 1
    for server, domain in {
        "poe_knowledge": "knowledge",
        "poe_build": "build",
        "poe_research": "research",
        "poe_learning": "learning",
    }.items():
        assert f"serverName: {server}" in patch
        assert f"server.mcp.{domain}_server" in patch
    assert patch.count("name: '@deepseek-ai/dsh-mcp-client'") == 4
    # A published bundle must not carry one machine's path or an unsubstituted
    # template token; it reads both facts from the environment instead.
    assert installer.DEFAULT_ROOT_LITERAL not in patch
    assert installer.TOKEN_PREFIX not in patch
    assert "process.env.POE_BD_CREATOR_ROOT" in patch
    assert "process.env.POE_BD_UV" in patch
    # The preset keeps its own MCP rows, so the two registration paths are
    # mutually exclusive and both documents must say so.
    assert "二选一" in (bundle / "README.md").read_text(encoding="utf-8")


def test_preset_rows_match_the_recorded_dsh_version():
    """A row copied from another DSH version makes the whole preset unmountable."""
    version, known = installer.snapshot_row_names()
    assert version and known

    assert installer.row_name_problems() == []
    names = installer.row_names_in(installer.SOURCE_PRESET / installer.COMPOSITION_FILE)
    # The toolset and the persona that carry the poe-bd behaviour are present...
    assert {"@deepseek-ai/dsh-mcp-client", "@deepseek-ai/dsh-persona"} <= names
    # ...and every package row is one this DSH version provides.
    package_rows = {
        name
        for name in names
        if not name.startswith(("cordis:", ".", "file:"))
    }
    assert package_rows <= known
    # The delegation group must use this version's workflow row.
    assert "@deepseek-ai/dsh-workflow-ptc" in names


def test_row_snapshot_gate_rejects_a_row_from_another_version(tmp_path):
    source = tmp_path / "preset"
    shutil.copytree(installer.SOURCE_PRESET, source)
    composition = source / installer.COMPOSITION_FILE
    composition.write_text(
        composition.read_text(encoding="utf-8").replace(
            "name: '@deepseek-ai/dsh-workflow-ptc'",
            "name: '@deepseek-ai/dsh-workflow-worker-thread'",
        ),
        encoding="utf-8",
    )

    problems = installer.row_name_problems(source)

    assert problems and "dsh-workflow-worker-thread" in problems[0]
    result = installer.install_preset(
        source=source,
        target=tmp_path / "home" / ".agent-presets" / "poe-bd",
        repo_root=None,
        uv_command="uv",
    )
    assert result["status"] == "error"
    assert result["errorCode"] == "incomplete_source"
    assert not (tmp_path / "home" / ".agent-presets" / "poe-bd").exists()


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
