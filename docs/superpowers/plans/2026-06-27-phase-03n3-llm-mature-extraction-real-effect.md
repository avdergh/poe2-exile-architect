# Phase 3N.3 LLM 成熟 BD 抽取与真实效果验证 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立一个真实热门成熟 BD 学习闭环：先探测来源，再让 LLM 在 copy-safe 合同下抽取技巧候选，最后用 creator/evaluator split 做真实效果验证。

**Architecture:** 3N.3 不继续旧的 retrieval-first 方向。新增 source probe、LLM extraction contract 和 real-effect evaluation 三个小边界；现有 SQLite mature-learning store、sanitizer、candidate/evidence 表继续作为安全底座。LLM 在本阶段参与抽取，但当前代码切片先定义 prompt/schema/guard 合同，不绑定具体模型 provider key，也不实现候选/evidence 导入。

**Tech Stack:** Python 3、SQLite、pytest、PowerShell、现有 `.tools\uv\uv.exe` / `scripts\verify.ps1` 验证入口。

**实施状态:** 计划已创建，正在按风险分级测试策略实施。执行本计划时必须保持 `docs/PROJECT_SPEC.md` 和 `docs/PROJECT_ARCHITECTURE.md` 真实更新。

**测试策略更新:** 简单确定性逻辑不强制 RED/GREEN TDD，可以直接实现后跑 targeted tests。涉及安全边界、evidence/visibility 边界、DB schema/migration、LLM 输出合同、route synthesis、engine/PoB 数值或 bug 回归时，仍优先先写测试或使用严格 TDD。

---

## 文件结构

- 已创建/维护：`docs/architecture/phase-03n3-llm-mature-extraction-real-effect.md`
  - 记录 3N.3 的目标、硬前置门禁、LLM 信息预算、split 边界和 out-of-scope。
- 创建：`server/live/mature_sources.py`
  - 网络来源探测与响应 shape 摘要；不保存 raw 页面或 raw JSON。
- 创建：`tests/test_mature_sources.py`
  - 网络无关的 source probe 单测，使用 fake transport。
- 创建：`server/knowledge/mature_llm_extraction.py`
  - LLM prompt package、输出 schema validation、copyability guard。候选/evidence 导入已改为后续任务，当前不实现。
- 创建：`tests/test_mature_llm_extraction.py`
  - LLM 输出合同、redaction、creator/evaluator 边界测试。
- 创建：`server/knowledge/mature_eval.py`
  - 真实效果验证 run/gap/reflection 的轻量结构与 contamination guard。
- 创建：`tests/test_mature_eval.py`
  - creator 输入不得包含 holdout/evaluator-only/raw 信息。
- 计划后续创建（尚未创建）：`docs/evaluations/templates/mature-real-effect-evaluation-template.md`
  - 每轮真实效果验证报告模板；当前 Task 6 尚未执行，不要把它当成已完成文件。
- 后续可创建：`docs/research/poe-ninja-source-probe-YYYY-MM-DD.md`
  - source probe 运行结果。只记录 shape 和结论，不记录 raw 响应全文。
- 修改：`docs/PROJECT_SPEC.md`
  - 同步 3N.3 active plan 和真实状态。
- 修改：`docs/PROJECT_ARCHITECTURE.md`
  - 同步新增模块职责和 active 文档。

## Task 0：预检与工作区保护

**Files:**
- Read: `docs/PROJECT_SPEC.md`
- Read: `docs/PROJECT_ARCHITECTURE.md`
- Read: `docs/architecture/phase-03n3-llm-mature-extraction-real-effect.md`
- Read: `server/knowledge/mature_learning.py`
- Read: `tests/test_mature_learning.py`

- [ ] **Step 1: 确认当前分支和 dirty worktree**

运行：

```powershell
git branch --show-current
git status --short
```

Expected:

- 分支为 `codex/phase-3-lifecycle` 或用户指定分支。
- 只看到预期文档/代码变更；如果有用户未说明的业务代码改动，先停下确认。

- [ ] **Step 2: 发起新需求开发前预审**

给 subagent 发送项目目标、当前阶段目标、需求目标和本计划摘要，要求只读审查：

```text
项目目标：可靠 PoE2 BD Creator，能研究、生成、解释并迭代 starter -> transition -> endgame 生命周期 BD。
当前阶段：Phase 3N.3，LLM-assisted mature build extraction and real-effect validation。
需求目标：实现 source probe、LLM extraction contract、copyability validation、creator/evaluator split 和首轮真实效果验证报告。
拟做事项：按本计划和风险分级测试策略实施，不接 route synthesis、不自动晋升 memory、不做自动 live fetcher。
```

Expected:

- subagent 返回“方向合理”或具体修改建议。
- 如果建议涉及接口/安全边界变化，先更新本计划和 `PROJECT_SPEC`。

## Task 1：Source probe spike，先证明热门样本来源是否可用

**Files:**
- Create: `server/live/mature_sources.py`
- Create: `tests/test_mature_sources.py`
- Create after manual/live run: `docs/research/poe-ninja-source-probe-YYYY-MM-DD.md`

- [ ] **Step 1: 写 RED 测试：ascendancy-only payload 不能伪装成 build-level**

在 `tests/test_mature_sources.py` 写入：

```python
from __future__ import annotations

from server.live import mature_sources


def test_probe_reports_ascendancy_only_payload_as_unavailable():
    payload = {
        "leagueBuilds": [
            {
                "leagueName": "Runes of Aldur",
                "leagueUrl": "runesofaldur",
                "total": 124302,
                "statistics": [{"class": "Stormweaver", "percentage": 22.0}],
            }
        ]
    }

    report = mature_sources.shape_build_level_probe(
        url="https://poe.ninja/poe2/api/data/build-index-state",
        status_code=200,
        payload=payload,
    )

    assert report["ok"] is False
    assert report["sourceType"] == "poe_ninja"
    assert report["hasBuildLevelRows"] is False
    assert "ascendancy" in report["unavailableReason"].lower()
    assert "rawPayload" not in report
```

- [ ] **Step 2: 验证 RED**

运行：

```powershell
.\.tools\uv\uv.exe run pytest tests/test_mature_sources.py::test_probe_reports_ascendancy_only_payload_as_unavailable -q
```

Expected: FAIL，失败原因是 `server.live.mature_sources` 或函数尚不存在。

- [ ] **Step 3: 实现最小 source probe shaper**

创建 `server/live/mature_sources.py`：

```python
"""Mature build source probing helpers.

This module summarizes response shapes only. It must not persist raw build pages,
raw JSON dumps, PoB codes, full item tables, passive trees, or gem links.
"""

from __future__ import annotations

from typing import Any


def shape_build_level_probe(*, url: str, status_code: int, payload: Any) -> dict[str, Any]:
    """Return a copy-safe source probe report for possible mature build samples."""
    if status_code != 200:
        return {
            "ok": False,
            "sourceType": "poe_ninja",
            "url": url,
            "httpStatus": status_code,
            "hasBuildLevelRows": False,
            "unavailableReason": f"HTTP {status_code}",
        }
    if not isinstance(payload, dict):
        return {
            "ok": False,
            "sourceType": "poe_ninja",
            "url": url,
            "httpStatus": status_code,
            "hasBuildLevelRows": False,
            "unavailableReason": "payload is not a JSON object",
        }
    rows = _candidate_rows(payload)
    if not rows:
        return {
            "ok": False,
            "sourceType": "poe_ninja",
            "url": url,
            "httpStatus": status_code,
            "hasBuildLevelRows": False,
            "responseShape": sorted(payload.keys()),
            "unavailableReason": (
                "payload appears to expose ascendancy or league metadata only; "
                "no explicit build-level sample rows were found"
            ),
        }
    return {
        "ok": True,
        "sourceType": "poe_ninja",
        "url": url,
        "httpStatus": status_code,
        "hasBuildLevelRows": True,
        "rowCount": len(rows),
        "rowShape": sorted(rows[0].keys()),
    }


def _candidate_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in ("builds", "characters", "rows", "samples", "archetypes"):
        value = payload.get(key)
        if isinstance(value, list):
            rows.extend(row for row in value if isinstance(row, dict))
    return rows
```

- [ ] **Step 4: GREEN**

运行：

```powershell
.\.tools\uv\uv.exe run pytest tests/test_mature_sources.py::test_probe_reports_ascendancy_only_payload_as_unavailable -q
```

Expected: PASS。

- [ ] **Step 5: 增加失败原因和 raw 防泄漏测试**

追加测试：

```python
def test_probe_report_summarizes_shape_without_raw_payload():
    payload = {"builds": [{"skill": "Spark", "items": ["raw item must not leak"]}]}

    report = mature_sources.shape_build_level_probe(
        url="https://example.test/builds",
        status_code=200,
        payload=payload,
    )

    assert report["ok"] is True
    assert report["hasBuildLevelRows"] is True
    assert report["rowShape"] == ["items", "skill"]
    assert "raw item must not leak" not in str(report)
    assert "rawPayload" not in report
```

运行：

```powershell
.\.tools\uv\uv.exe run pytest tests/test_mature_sources.py -q
```

Expected: PASS。

- [ ] **Step 6: 做一次真实来源探测并写研究报告**

在实现网络 probe 命令前，可以先用一次手工/临时脚本探测，不把脚本输出 raw 内容写入仓库。报告保存为：

```text
docs/research/poe-ninja-source-probe-YYYY-MM-DD.md
```

报告必须包含：

```markdown
# poe.ninja build-level source probe

Date:
URLs probed:
HTTP statuses:
Response shape summary:
Build-level rows available: yes/no/unknown
Requires browser headers: yes/no/unknown
Failure reasons:
Fallback plan:
Raw content persisted: no
```

Expected:

- 若 build-level 数据不可用，报告明确 fallback。
- 不保存 raw JSON、raw HTML、PoB code、完整装备或完整 gem links。

## Task 2：样本 manifest 与 sanitized brief 合同

**Files:**
- Create: `server/knowledge/mature_sample_contract.py`
- Create: `tests/test_mature_sample_contract.py`
- Modify if needed: `data/mature_build_learning/seed_cases.json`

- [ ] **Step 1: 写 RED 测试：热门样本 manifest 必须有来源、流行度、新鲜度和多样性**

创建 `tests/test_mature_sample_contract.py`：

```python
from __future__ import annotations

from server.knowledge import mature_sample_contract


def test_sample_manifest_requires_popularity_freshness_and_diversity():
    manifest = {
        "sourceType": "poe_ninja",
        "sourceRef": "https://poe.ninja/poe2/builds/runesofaldur",
    }

    result = mature_sample_contract.validate_sample_manifest(manifest)

    assert result["ok"] is False
    assert "popularity" in result["missing"]
    assert "freshness" in result["missing"]
    assert "diversityBucket" in result["missing"]
```

Expected RED:

```powershell
.\.tools\uv\uv.exe run pytest tests/test_mature_sample_contract.py::test_sample_manifest_requires_popularity_freshness_and_diversity -q
```

FAIL，模块尚不存在。

- [ ] **Step 2: 实现最小 manifest validator**

创建 `server/knowledge/mature_sample_contract.py`：

```python
"""Contracts for mature-build sample manifests.

The manifest proves why a sanitized case represents a popular mature sample.
It is not a place to store raw builds.
"""

from __future__ import annotations

from typing import Any

REQUIRED_SAMPLE_MANIFEST_KEYS = {
    "sourceType": "sourceType",
    "sourceRef": "sourceRef",
    "popularity": "popularity",
    "freshness": "freshness",
    "diversityBucket": "diversityBucket",
}


def validate_sample_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    missing = [
        label
        for key, label in REQUIRED_SAMPLE_MANIFEST_KEYS.items()
        if key not in manifest or manifest[key] in (None, "", {})
    ]
    if missing:
        return {"ok": False, "error": "sample_manifest_incomplete", "missing": missing}
    return {"ok": True}
```

- [ ] **Step 3: GREEN**

运行：

```powershell
.\.tools\uv\uv.exe run pytest tests/test_mature_sample_contract.py -q
```

Expected: PASS。

- [ ] **Step 4: 增加 copyable manifest 拒绝测试**

manifest 不得包含 raw PoB、完整树、完整装备或完整 links。测试示例：

```python
def test_sample_manifest_rejects_raw_copyable_fields():
    manifest = {
        "sourceType": "pobb_in",
        "sourceRef": "https://pobb.in/example",
        "popularity": {"basis": "forum replies", "rank": 1},
        "freshness": {"league": "Runes of Aldur", "gamePatch": "0.5.4", "tree": "0_5"},
        "diversityBucket": "stormweaver-lightning-spell",
        "pobCode": "eNrt" + "A" * 180,
    }

    result = mature_sample_contract.validate_sample_manifest(manifest)

    assert result["ok"] is False
    assert result["error"] == "copyable_manifest_field"
```

实现时可复用 `mature_learning.sanitize_mature_case` 的 forbidden field 思路，避免复制太多逻辑。

## Task 3：LLM extraction schema 与 copy-safe prompt package

**Files:**
- Create: `server/knowledge/mature_llm_extraction.py`
- Create: `tests/test_mature_llm_extraction.py`

- [ ] **Step 1: 写 RED 测试：有效 LLM 输出通过 schema**

创建 `tests/test_mature_llm_extraction.py`：

```python
from __future__ import annotations

from server.knowledge import mature_llm_extraction


def _valid_output():
    return {
        "schemaVersion": 1,
        "sourceCaseId": "case-safe-spark",
        "league": "Runes of Aldur",
        "gamePatch": "0.5.4",
        "passiveTreeVersion": "0_5",
        "techniques": [
            {
                "techniqueName": "Lightning projectile crit scaling shell",
                "mechanismSummary": "Uses projectile spell coverage plus crit/shock scaling as an endgame identity.",
                "whyItWorks": "Coverage handles clear while crit and ailment scaling concentrate investment for bosses.",
                "requiredComponents": ["projectile spell", "crit foundation", "shock scaling"],
                "thresholdsOrBreakpoints": ["requires stable crit and endgame passive budget"],
                "lifecycleApplicability": "starter_then_transition",
                "starterRisks": ["damage and sustain may be weak before crit foundation"],
                "transitionGates": ["switch only after first endgame gear/passive package is online"],
                "skillLinksSummary": "main skill plus damage and coverage supports; no full link list",
                "passiveTreeAnchors": ["projectile spell cluster family", "crit cluster family"],
                "gearOrUniqueRoles": ["gear provides scaling roles, no full item table"],
                "defensePlan": "energy shield and recovery identity",
                "pobModelability": "partial",
                "evidenceRefs": ["case-safe-spark"],
                "confidence": "medium",
                "copyabilityRisk": "low",
            }
        ],
    }


def test_validate_llm_extraction_accepts_non_copyable_output():
    result = mature_llm_extraction.validate_llm_extraction_output(_valid_output())

    assert result["ok"] is True
    assert result["techniqueCount"] == 1
```

Expected RED:

```powershell
.\.tools\uv\uv.exe run pytest tests/test_mature_llm_extraction.py::test_validate_llm_extraction_accepts_non_copyable_output -q
```

FAIL，模块尚不存在。

- [ ] **Step 2: 实现 schema validator 最小版本**

创建 `server/knowledge/mature_llm_extraction.py`：

```python
"""LLM-assisted mature build extraction contract.

LLM output is treated as an untrusted candidate. It must pass schema validation
and copyability checks before any later candidate/evidence import is allowed.
"""

from __future__ import annotations

import re
from typing import Any

VALID_LIFECYCLE = {
    "starter_to_endgame",
    "starter_then_transition",
    "endgame_only",
    "starter_only",
    "unknown_lifecycle",
}
VALID_MODELABILITY = {"full", "partial", "not_modelable", "unknown"}
VALID_CONFIDENCE = {"low", "medium", "high"}
VALID_COPYABILITY = {"low", "medium", "high"}


def validate_llm_extraction_output(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"ok": False, "error": "payload_must_be_object"}
    if payload.get("schemaVersion") != 1:
        return {"ok": False, "error": "unsupported_schema_version"}
    techniques = payload.get("techniques")
    if not isinstance(techniques, list) or not techniques:
        return {"ok": False, "error": "techniques_required"}
    copyable = _copyability_flags(payload)
    if copyable:
        return {"ok": False, "error": "copyability_guard_failed", "flags": copyable}
    for technique in techniques:
        error = _validate_technique(technique)
        if error:
            return {"ok": False, "error": error}
    return {"ok": True, "techniqueCount": len(techniques)}


def _validate_technique(technique: Any) -> str | None:
    if not isinstance(technique, dict):
        return "technique_must_be_object"
    required = {
        "techniqueName",
        "mechanismSummary",
        "whyItWorks",
        "requiredComponents",
        "thresholdsOrBreakpoints",
        "lifecycleApplicability",
        "starterRisks",
        "transitionGates",
        "pobModelability",
        "evidenceRefs",
        "confidence",
        "copyabilityRisk",
    }
    missing = [key for key in required if key not in technique or technique[key] in (None, "", [])]
    if missing:
        return "technique_missing_required_fields"
    if technique["lifecycleApplicability"] not in VALID_LIFECYCLE:
        return "invalid_lifecycle_applicability"
    if technique["pobModelability"] not in VALID_MODELABILITY:
        return "invalid_pob_modelability"
    if technique["confidence"] not in VALID_CONFIDENCE:
        return "invalid_confidence"
    if technique["copyabilityRisk"] not in VALID_COPYABILITY:
        return "invalid_copyability_risk"
    return None


def _copyability_flags(value: Any) -> list[str]:
    text = _all_text(value)
    flags: list[str] = []
    if re.search(r"\b(?:eNrt|pobb\.in/|pastebin\.com/)[A-Za-z0-9+/_=-]{80,}", text):
        flags.append("pob_code_like_blob")
    if re.search(r"supports?\s*:\s*[^.\n,]+(?:,\s*[^.\n,]+){4,}", text.lower()):
        flags.append("full_support_link_like")
    if len(text) > 4000:
        flags.append("long_raw_text_like")
    return flags


def _all_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return "\n".join(_all_text(child) for child in value.values())
    if isinstance(value, list):
        return "\n".join(_all_text(child) for child in value)
    return ""
```

- [ ] **Step 3: GREEN**

运行：

```powershell
.\.tools\uv\uv.exe run pytest tests/test_mature_llm_extraction.py::test_validate_llm_extraction_accepts_non_copyable_output -q
```

Expected: PASS。

- [ ] **Step 4: 增加 redaction/copyability 测试**

追加测试：

```python
def test_validate_llm_extraction_rejects_pob_code_like_output():
    payload = _valid_output()
    payload["techniques"][0]["whyItWorks"] = "eNrt" + "A" * 180

    result = mature_llm_extraction.validate_llm_extraction_output(payload)

    assert result["ok"] is False
    assert result["error"] == "copyability_guard_failed"
    assert "pob_code_like_blob" in result["flags"]


def test_validate_llm_extraction_rejects_full_support_link_like_output():
    payload = _valid_output()
    payload["techniques"][0]["skillLinksSummary"] = "Supports: A, B, C, D, E"

    result = mature_llm_extraction.validate_llm_extraction_output(payload)

    assert result["ok"] is False
    assert result["error"] == "copyability_guard_failed"
```

运行：

```powershell
.\.tools\uv\uv.exe run pytest tests/test_mature_llm_extraction.py -q
```

Expected: PASS。

- [ ] **Step 5: 生成 copy-safe prompt package**

新增测试：

```python
def test_prompt_package_warns_llm_not_to_copy_raw_build_details():
    package = mature_llm_extraction.build_extraction_prompt_package(
        sanitized_case={
            "case_id": "case-safe-spark",
            "class": "Sorceress",
            "ascendancy": "Stormweaver",
            "main_skill": "Spark",
            "sanitized_keypoints": ["Endgame lightning caster scaling fixture."],
        }
    )

    text = "\n".join(package["messages"])
    assert "do not output PoB code" in text
    assert "do not output full gear" in text
    assert "JSON" in text
    assert "Endgame lightning caster scaling fixture." in text
```

实现 `build_extraction_prompt_package` 时只接受 sanitized case，prompt 必须明确禁止复制 raw 内容。

## Task 4：后续任务（暂缓）：将 LLM extraction 导入候选层，但不影响 route synthesis

**当前状态：本任务不属于已实现切片。** 首轮审查后，本计划已收窄为：

- 已实现：LLM prompt package、输出 schema validation、copyability guard；
- 已实现：creator/evaluator contamination guard；
- 未实现：LLM extraction output 到 `technique_candidates` / `candidate_evidence` 的导入；
- 未实现：LLM provider runner、teacher-student 自动循环、route synthesis 接入。

以下步骤保留为下一轮候选/evidence 导入的设计草稿。执行前必须重新做新需求开发前 subagent 预审，并再次确认 evidence/visibility 边界。

**Files:**
- Modify: `server/knowledge/mature_llm_extraction.py`
- Modify: `tests/test_mature_llm_extraction.py`
- Modify if needed: `server/knowledge/mature_learning.py`

- [ ] **Step 1: 写 RED 测试：LLM extraction 写入 candidate/evidence**

测试应先导入 3N.1 seed fixture，再将一个 valid LLM output 映射为 candidate：

```python
from server.knowledge import mature_learning


def test_import_llm_extraction_creates_low_trust_candidate_and_evidence(tmp_path):
    db_path = tmp_path / "mature.sqlite"
    assert mature_learning.import_fixture_file(db_path=db_path)["ok"] is True
    output = _valid_output()

    result = mature_llm_extraction.import_llm_extraction_output(output, db_path=db_path)

    assert result["ok"] is True
    assert result["candidatesUpserted"] == 1
    con = mature_learning.connect(db_path)
    candidate = con.execute(
        """
        SELECT confidence, promotion_status, evidence_type
        FROM technique_candidates
        WHERE statement LIKE '%Lightning projectile crit scaling shell%'
        """
    ).fetchone()
    assert candidate["confidence"] in {"low", "medium"}
    assert candidate["promotion_status"] == "candidate"
    assert candidate["evidence_type"] == "generated_eval_gap"
```

Expected RED:

```powershell
.\.tools\uv\uv.exe run pytest tests/test_mature_llm_extraction.py::test_import_llm_extraction_creates_low_trust_candidate_and_evidence -q
```

FAIL，导入函数尚不存在。

- [ ] **Step 2: 实现导入函数**

`import_llm_extraction_output` 必须：

- 先调用 `validate_llm_extraction_output`；
- 查找对应 sanitized case；
- 根据 case 的 visibility/split 继承 creator/evaluator/quarantine 边界；
- 写入 `technique_candidates`；
- 写入 `candidate_evidence`，`extraction_method = "llm_mature_technique_v1"`；
- 不注册 MCP 工具；
- 不改变 lifecycle route synthesis。

关键注释必须说明：

```python
# LLM findings are untrusted research candidates. They enter the same evidence
# boundary as deterministic candidates and must not influence route synthesis
# until a later user-approved phase wires creator-visible retrieval.
```

- [ ] **Step 3: 增加 evaluator-only 不污染 creator 测试**

追加测试：

```python
def test_import_llm_extraction_preserves_evaluator_only_boundary(tmp_path):
    db_path = tmp_path / "mature.sqlite"
    assert mature_learning.import_fixture_file(db_path=db_path)["ok"] is True
    output = _valid_output()
    output["sourceCaseId"] = "the evaluator-only fixture case id used by seed data"

    result = mature_llm_extraction.import_llm_extraction_output(output, db_path=db_path)

    assert result["ok"] is True
    con = mature_learning.connect(db_path)
    rows = con.execute(
        """
        SELECT creator_visible, visibility, split
        FROM candidate_evidence
        WHERE extraction_method = 'llm_mature_technique_v1'
        """
    ).fetchall()
    assert rows
    assert all(row["creator_visible"] == 0 for row in rows)
```

执行时不要硬编码不稳定 case id；如果 seed fixture 没有可读 id helper，先新增只读 helper
`list_mature_cases(db_path)` 或在测试里查询 evaluator-only case。

- [ ] **Step 4: Targeted GREEN**

运行：

```powershell
.\.tools\uv\uv.exe run pytest tests/test_mature_llm_extraction.py tests/test_mature_learning.py -q
```

Expected: PASS。

## Task 5：Creator/Evaluator contamination guard

**Files:**
- Create: `server/knowledge/mature_eval.py`
- Create: `tests/test_mature_eval.py`

- [ ] **Step 1: 写 RED 测试：creator input 不能包含 holdout/evaluator/raw**

创建 `tests/test_mature_eval.py`：

```python
from __future__ import annotations

from server.knowledge import mature_eval


def test_creator_input_rejects_evaluator_only_and_raw_material():
    creator_input = {
        "goal": "给我一个强力 BD",
        "evidence": [
            {"visibility": "creator_visible", "split": "train_context", "summary": "safe"},
            {"visibility": "evaluator_only", "split": "eval_holdout", "summary": "holdout"},
        ],
        "pobCode": "eNrt" + "A" * 180,
    }

    result = mature_eval.validate_creator_research_input(creator_input)

    assert result["ok"] is False
    assert "evaluator_only" in result["flags"]
    assert "raw_pob_code" in result["flags"]
```

Expected RED:

```powershell
.\.tools\uv\uv.exe run pytest tests/test_mature_eval.py::test_creator_input_rejects_evaluator_only_and_raw_material -q
```

FAIL，模块尚不存在。

- [ ] **Step 2: 实现 guard**

创建 `server/knowledge/mature_eval.py`：

```python
"""Real-effect evaluation helpers for mature-build learning.

Creator inputs must stay separated from evaluator-only evidence. This guard is
small by design so it can be used before any LLM call.
"""

from __future__ import annotations

import re
from typing import Any


def validate_creator_research_input(payload: dict[str, Any]) -> dict[str, Any]:
    flags: list[str] = []
    if _contains_evaluator_only(payload):
        flags.append("evaluator_only")
    if re.search(r"\b(?:eNrt|pobb\.in/|pastebin\.com/)[A-Za-z0-9+/_=-]{80,}", str(payload)):
        flags.append("raw_pob_code")
    if flags:
        return {"ok": False, "error": "creator_input_contamination", "flags": sorted(flags)}
    return {"ok": True}


def _contains_evaluator_only(value: Any) -> bool:
    if isinstance(value, dict):
        if value.get("visibility") == "evaluator_only" or value.get("split") == "eval_holdout":
            return True
        return any(_contains_evaluator_only(child) for child in value.values())
    if isinstance(value, list):
        return any(_contains_evaluator_only(child) for child in value)
    return False
```

- [ ] **Step 3: GREEN**

运行：

```powershell
.\.tools\uv\uv.exe run pytest tests/test_mature_eval.py -q
```

Expected: PASS。

- [ ] **Step 4: 增加 gap 类型测试**

新增 `classify_evaluator_gap` 或常量集合，至少覆盖：

- `missing_core_mechanism`
- `wrong_lifecycle_classification`
- `unsafe_transition`
- `numeric_underperformance`
- `defense_gap`
- `sustain_gap`
- `budget_unrealistic`
- `pob_modelability_missed`
- `copyability_risk`
- `stale_or_unknown_freshness`
- `novice_explanation_gap`

测试要求未知 gap 被拒绝。

## Task 6：真实效果验证报告模板与第一轮小样本执行

**Files:**
- Create: `docs/evaluations/templates/mature-real-effect-evaluation-template.md`
- Create after run: `docs/evaluations/YYYY-MM-DD-phase-03n3-first-real-effect.md`
- Modify if needed: `server/knowledge/mature_eval.py`
- Modify if needed: `tests/test_mature_eval.py`

- [ ] **Step 1: 创建报告模板**

模板内容：

```markdown
# Mature Build Learning Real-Effect Evaluation

Date:
Evaluator:
League / patch / passive tree:
Source freshness:

## Sample set

- Sample count:
- Classes / ascendancies:
- Source types:
- Popularity basis:
- Holdout policy:

## Creator task

User-style input:
Creator-visible evidence summary:
Forbidden evidence excluded:

## Creator output summary

Lifecycle route:
Starter:
Transition:
Endgame:
Engine-computed fields:
Caveats:

## Evaluator comparison

Held-out mature evidence used:
Mechanism alignment:
Lifecycle correctness:
Transition gate quality:
Defense/sustain quality:
Copy-safety:

## Gaps

| Gap type | Severity | Evidence | Fix idea |
| --- | --- | --- | --- |

## Reflection

What should become a candidate technique:
What stays local/episodic:
What requires user confirmation:

## Decision

- Promote durable memory: no
- Allow route synthesis integration: no
- Next action:
```

- [ ] **Step 2: 用 4～8 个样本跑通小闭环**

如果 source probe 找不到稳定 poe.ninja build-level 样本，使用 fallback：

- poe.ninja freshness / league / sample-size 作为 meta evidence；
- pobb.in/forum/guide/手工 curated sanitized samples 作为成熟案例；
- 报告必须写明“build-level source unavailable”。

小样本执行至少覆盖 3 个不同职业/升华；达不到时报告标注“不足，不能作为质量结论”。

- [ ] **Step 3: 抽取至少 1 条非平庸技巧候选**

候选必须包含：

- mechanism；
- why it works；
- lifecycle applicability；
- transition gate；
- starter risk；
- pob modelability；
- evidence refs；
- copyability risk。

只有标签摘要不算通过。

- [ ] **Step 4: evaluator gap 不能只是自然语言泛评**

gap 必须使用 Task 5 的 gap type，并带 severity。

## Task 7：PROJECT_SPEC / PROJECT_ARCHITECTURE 同步更新

**Files:**
- Modify: `docs/PROJECT_SPEC.md`
- Modify: `docs/PROJECT_ARCHITECTURE.md`

- [ ] **Step 1: 更新 PROJECT_SPEC**

必须真实记录：

- 3N.3 source probe 是否完成；
- LLM extraction schema 是否实现；
- LLM extraction 是否已经用真实/近真实样本跑过；
- real-effect evaluation report 是否存在；
- route synthesis 是否仍未接入；
- durable memory 是否仍未自动晋升。

禁止写法：不要用任何“已完成自动学习 / 已接入推荐 / 已支持自动抓取”之类的表述，
除非这些能力确实完成并验证。

- [ ] **Step 2: 更新 PROJECT_ARCHITECTURE**

同步新增模块职责：

- `server/live/mature_sources.py`
- `server/knowledge/mature_llm_extraction.py`
- `server/knowledge/mature_eval.py`
- `docs/evaluations/templates/mature-real-effect-evaluation-template.md`

如果某模块尚未实现，只写“计划新增 / 尚未实现”，不要写成已完成。

- [ ] **Step 3: 文档级验证**

运行：

```powershell
git diff --check
rg -n "已完成自动学习|已接入推荐|已支持自动抓取" docs/PROJECT_SPEC.md docs/PROJECT_ARCHITECTURE.md
```

Expected:

- `git diff --check` 无输出。
- `rg` 无输出。

## Task 8：审查与验证

**Files:**
- All touched files

- [ ] **Step 1: targeted tests**

运行：

```powershell
.\.tools\uv\uv.exe run pytest tests/test_mature_sources.py tests/test_mature_sample_contract.py tests/test_mature_llm_extraction.py tests/test_mature_eval.py tests/test_mature_learning.py -q
```

Expected: PASS。

- [ ] **Step 2: quick 验证**

运行：

```powershell
.\scripts\verify.ps1 quick
```

Expected: PASS。

- [ ] **Step 3: subagent code review**

提交前发起代码审查，要求检查：

- source probe 是否保存 raw 内容；
- LLM 输出 validation 是否能挡住 PoB code、完整 links、长攻略文本；
- evaluator-only 是否可能污染 creator-visible；
- 是否越界影响 route synthesis；
- 文档是否把未实现能力写成已完成。

- [ ] **Step 4: 规格复审触发条件**

本阶段涉及接口、evidence 边界、安全边界和用户输出合同，因此实现完成后需要窄规格复审。

- [ ] **Step 5: 修复审查问题并重跑验证**

至少重跑：

```powershell
.\.tools\uv\uv.exe run pytest tests/test_mature_sources.py tests/test_mature_sample_contract.py tests/test_mature_llm_extraction.py tests/test_mature_eval.py tests/test_mature_learning.py -q
.\scripts\verify.ps1 quick
git diff --check
```

- [ ] **Step 6: 提交**

```powershell
git add server/live/mature_sources.py server/knowledge/mature_sample_contract.py server/knowledge/mature_llm_extraction.py server/knowledge/mature_eval.py tests/test_mature_sources.py tests/test_mature_sample_contract.py tests/test_mature_llm_extraction.py tests/test_mature_eval.py docs/PROJECT_SPEC.md docs/PROJECT_ARCHITECTURE.md docs/architecture/phase-03n3-llm-mature-extraction-real-effect.md docs/superpowers/plans/2026-06-27-phase-03n3-llm-mature-extraction-real-effect.md docs/evaluations/templates/mature-real-effect-evaluation-template.md
git commit -m "feat: add llm mature build extraction gate"
```

## 自检

- Spec coverage：source probe、LLM 信息预算、schema/copyability、creator/evaluator split、真实效果验证都有任务。
- Scope control：不接 route synthesis、不自动晋升 durable memory、不做自动 fetcher、不加 vector/graph DB。
- 测试策略：简单确定性逻辑允许直接实现后跑 targeted tests；高风险边界仍需先写测试或严格 TDD。
- 文档真实性：`PROJECT_SPEC` / `PROJECT_ARCHITECTURE` 必须随进度更新，且不得把计划写成已完成。
- 验证梯度：优先 targeted tests 和 quick，不在本阶段反复跑 compute/full。
