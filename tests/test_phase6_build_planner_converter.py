from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from server.build_planner import converter
from server.compute.pob_code import decode_code
from server.runtime.node import resolve_node_executable


def _provider(tmp_path: Path, runner: str) -> Path:
    root = tmp_path / "provider"
    (root / "dist").mkdir(parents=True)
    (root / "dist" / "runner.cjs").write_text(runner, encoding="utf-8")
    (root / "LICENSE").write_text("MIT", encoding="utf-8")
    (root / "provider.json").write_text(
        json.dumps(
            {
                "providerId": converter.PROVIDER_ID,
                "providerVersion": converter.PROVIDER_VERSION,
                "providerCommit": converter.PROVIDER_COMMIT,
                "upstream": "https://example.invalid/provider",
                "license": "MIT",
                "licensePath": "LICENSE",
                "runnerPath": "dist/runner.cjs",
                "officialFormat": "GGG Build Planner v1 experimental",
                "gameDataPatch": "4.5.4.3",
            }
        ),
        encoding="utf-8",
    )
    return root


def _node_or_skip() -> str:
    node = resolve_node_executable()
    if not node:
        pytest.skip("Node.js is not available")
    return str(node)


def _valid_runner(extra: str = "") -> str:
    return f"""
const readline = require('node:readline');
const rl = readline.createInterface({{ input: process.stdin }});
rl.on('line', (line) => {{
  const request = JSON.parse(line);
  const payload = {{
    status: 'ok', requestId: request.requestId, sourceHash: request.sourceHash,
    build: {{
      name: request.metadata.name || 'Test Build', ascendancy: 'Mercenary2',
      passives: ['duelist597'],
      skills: [{{ id: 'Metadata/Items/Gems/SkillGemDetonateLiving',
        support_skills: ['Metadata/Items/Gems/SupportGemBrutality'] }}]
    }},
    warnings: [], stats: {{ passiveCount: 1, skillCount: 1 }}
  }};
  {extra}
  process.stdout.write(JSON.stringify(payload) + '\\n');
}});
"""


def test_converter_status_and_success(tmp_path, monkeypatch):
    node = _node_or_skip()
    root = _provider(tmp_path, _valid_runner())
    monkeypatch.setenv("POE_BD_BUILD_CONVERTER_DIR", str(root))
    monkeypatch.setenv("POE_BD_NODE_EXECUTABLE", node)

    status = converter.converter_status()
    result = converter.convert_pob_xml(
        "<PathOfBuilding/>", source_hash="abc123", metadata={"name": "Agent Build"}
    )

    assert status["status"] == "ready"
    assert result["status"] == "ok"
    assert result["build"]["name"] == "Agent Build"
    assert json.loads(result["serializedBuild"])["name"] == "Agent Build"
    assert result["schemaValidation"] == {"status": "passed", "errors": []}


def test_converter_reads_utf8_provider_output_on_non_utf8_windows_locale(tmp_path, monkeypatch):
    node = _node_or_skip()
    root = _provider(
        tmp_path,
        _valid_runner("payload.build.description = 'Rare — Arc • guidance';"),
    )
    monkeypatch.setenv("POE_BD_BUILD_CONVERTER_DIR", str(root))
    monkeypatch.setenv("POE_BD_NODE_EXECUTABLE", node)

    result = converter.convert_pob_xml("<PathOfBuilding/>", source_hash="abc123")

    assert result["status"] == "ok"
    assert result["build"]["description"] == "Rare — Arc • guidance"


def test_converter_rejects_missing_provider(tmp_path, monkeypatch):
    monkeypatch.setenv("POE_BD_BUILD_CONVERTER_DIR", str(tmp_path / "missing"))

    result = converter.convert_pob_xml("<PathOfBuilding/>", source_hash="abc123")

    assert result["status"] == "error"
    assert result["errorCode"] == "converter_provider_unavailable"
    assert "provider_marker_missing" in result["issues"]


@pytest.mark.parametrize(
    ("runner", "error_code"),
    [
        ("process.stdout.write('not json\\n')", "converter_protocol_error"),
        ("process.exit(2)", "converter_process_failed"),
    ],
)
def test_converter_normalizes_provider_failures(tmp_path, monkeypatch, runner, error_code):
    node = _node_or_skip()
    root = _provider(tmp_path, runner)
    monkeypatch.setenv("POE_BD_BUILD_CONVERTER_DIR", str(root))
    monkeypatch.setenv("POE_BD_NODE_EXECUTABLE", node)

    result = converter.convert_pob_xml("<PathOfBuilding/>", source_hash="abc123")

    assert result == {
        "status": "error",
        "errorCode": error_code,
        "provider": result["provider"],
    }


def test_converter_rejects_source_hash_mismatch(tmp_path, monkeypatch):
    node = _node_or_skip()
    root = _provider(tmp_path, _valid_runner("payload.sourceHash = 'wrong';"))
    monkeypatch.setenv("POE_BD_BUILD_CONVERTER_DIR", str(root))
    monkeypatch.setenv("POE_BD_NODE_EXECUTABLE", node)

    result = converter.convert_pob_xml("<PathOfBuilding/>", source_hash="abc123")

    assert result["errorCode"] == "converter_response_mismatch"


def test_single_stage_schema_rejects_level_interval_and_bad_ids():
    errors = converter.validate_single_stage_build(
        {
            "name": "Bad",
            "passives": [{"id": "bad id", "level_interval": [1, 100]}],
            "skills": ["not-a-gem-id"],
            "inventory_slots": [{"inventory_id": "Unknown"}],
        }
    )

    assert errors == [
        "invalid_inventory_id",
        "invalid_passive_id",
        "invalid_skill_id",
        "single_stage_level_interval_present",
    ]


def test_pinned_provider_converts_real_pob_fixture_without_level_intervals(monkeypatch):
    node = _node_or_skip()
    root = Path(__file__).resolve().parents[1] / "providers" / "poe2-build-converter"
    if not (root / "dist" / "runner.cjs").is_file():
        pytest.skip("Pinned converter provider is not prepared")
    monkeypatch.setenv("POE_BD_BUILD_CONVERTER_DIR", str(root))
    monkeypatch.setenv("POE_BD_NODE_EXECUTABLE", node)
    code = (Path(__file__).parent / "fixtures" / "witchhunter_detonate.pobcode").read_text()
    xml = decode_code(code.strip())
    source_hash = hashlib.sha256(xml.encode()).hexdigest()

    result = converter.convert_pob_xml(
        xml, source_hash=source_hash, metadata={"name": "Fixture Smoke"}
    )

    assert result["status"] == "ok"
    assert result["build"]["ascendancy"] == "Mercenary2"
    assert result["stats"]["passiveCount"] == 6
    assert result["stats"]["skillCount"] == 1
    assert "level_interval" not in json.dumps(result["build"])
    assert result["schemaValidation"]["status"] == "passed"
