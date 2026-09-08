"""发布烟测按实际manifest逐工具核对，不能维护第二份容易过期的总数。"""

import json
from types import SimpleNamespace

import pytest

from scripts import smoke_staged_mcp_domains as smoke


@pytest.fixture
def stage(tmp_path, monkeypatch):
    (tmp_path / "server").mkdir()
    (tmp_path / "server" / "main.py").write_text("# stage fixture", encoding="utf-8")
    domains = {
        smoke.MODULES[0]: {"get_research_write_receipt"},
        smoke.MODULES[1]: {"new_build"},
        smoke.MODULES[2]: {"get_research_followup_status", "submit_research_gap_review", "reacquire_research_source"},
        smoke.MODULES[3]: {"get_learning_campaign_status"},
    }
    monkeypatch.setattr(smoke.sys, "argv", ["smoke", "--stage", str(tmp_path)])
    monkeypatch.setattr(smoke.sys, "path", list(smoke.sys.path))
    monkeypatch.setattr(smoke.importlib, "import_module", lambda name: SimpleNamespace(
        _TOOLS=[SimpleNamespace(__name__=tool) for tool in domains[name]]
    ))
    return tmp_path, domains


def _manifest(path, names):
    (path / "manifest.json").write_text(json.dumps({"tools": [{"name": name} for name in names]}), encoding="utf-8")


def test_smoke_accepts_manifest_declared_expansion_without_a_parallel_count(stage):
    path, domains = stage
    _manifest(path, sorted(set.union(*domains.values())))
    assert smoke.main() == 0


def test_smoke_rejects_same_count_wrong_tool(stage):
    path, domains = stage
    names = set.union(*domains.values()) - {"new_build"} | {"missing_tool"}
    _manifest(path, sorted(names))
    with pytest.raises(RuntimeError, match="missing=.*missing_tool.*undeclared=.*new_build"):
        smoke.main()


def test_smoke_rejects_duplicate_manifest_declarations(stage):
    path, domains = stage
    names = sorted(set.union(*domains.values()))
    _manifest(path, [*names, names[0]])
    with pytest.raises(RuntimeError, match="duplicate"):
        smoke.main()


def test_smoke_still_rejects_overlapping_domains(stage):
    path, domains = stage
    domains[smoke.MODULES[3]].add("new_build")
    _manifest(path, sorted(set.union(*domains.values())))
    with pytest.raises(RuntimeError, match="overlap"):
        smoke.main()
