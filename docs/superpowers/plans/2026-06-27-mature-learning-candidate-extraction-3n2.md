# Phase 3N.2 成熟 BD 候选技巧抽取实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从 Phase 3N.1 已净化的成熟 BD 案例中，确定性抽取 `technique_candidates`，并用 `candidate_evidence` 记录每条候选技巧的证据来源。

**Architecture:** SQLite 仍是唯一事实源；抽取器只读取 `mature_build_cases` 中的安全字段，生成非可复刻的候选技巧摘要，并把证据边界写入 `candidate_evidence`。候选的 `source_count`、`support_count`、`contradiction_count` 必须由 evidence 表回算，不能由调用方手填。

**Tech Stack:** Python 3、SQLite、pytest、现有 `.tools\uv\uv.exe` 测试入口。

**实施状态:** 已按本计划完成实现、测试、代码审查和窄规格复审；checkbox 保留为原始执行计划结构，后续请以
`docs/PROJECT_SPEC.md` 的当前状态为准。

---

## 文件结构

- 修改：`server/knowledge/mature_learning.py`
  - 新增 Phase 3N.2 抽取常量。
  - 新增 `extract_technique_candidates(db_path=None)` 公共函数。
  - 新增内部候选构建、标签归一、前置条件/风险/转型门槛推导、evidence upsert、计数回算 helper。
  - 保持不触碰 route synthesis、MCP 工具注册、检索层。
- 修改：`tests/test_mature_learning.py`
  - 先新增 RED 测试覆盖候选 ID 确定性、evidence 桥接、重复抽取幂等、计数回算、holdout 不 creator-visible、隔离 quarantined。
- 创建：`docs/architecture/phase-03n2-mature-candidate-extraction.md`
  - 中文说明 Phase 3N.2 的抽取模型、边界、字段推导和 out-of-scope。
- 修改：`docs/PROJECT_SPEC.md`
  - 中文同步 Phase 3N.2 当前状态与验证策略。

## Task 1：中文局部技术文档和项目 spec 更新

**Files:**
- Create: `docs/architecture/phase-03n2-mature-candidate-extraction.md`
- Modify: `docs/PROJECT_SPEC.md`

- [ ] **Step 1: 写 Phase 3N.2 技术文档**

创建 `docs/architecture/phase-03n2-mature-candidate-extraction.md`，内容必须说明：

```markdown
# Phase 3N.2 成熟 BD 候选技巧抽取

Last updated: 2026-06-27

## 目标

Phase 3N.2 将已净化的 `mature_build_cases` 转成低信任候选技巧。
候选技巧只是研究材料，不会直接影响 BD 生成、路线排序、记忆晋升或知识过期。

## 输入和输出

输入只允许读取 3N.1 保存的安全字段，包括职业、升华、主技能、宽泛标签、阶段、预算、
PoB 可建模性、补丁/天赋树/赛季元数据和净化 keypoints。

输出包括：

- `technique_candidates`
- `candidate_evidence`

## 边界

- 不读取原始 PoB、完整天赋树、完整装备、完整技能连接或攻略全文。
- 不把 `evaluator_only` / `eval_holdout` evidence 暴露为 creator-visible。
- 不让 `quarantined` 案例产生可用候选。
- 不做 FTS、向量召回、图数据库、自动晋升、主动过期、teacher-student loop。

## 确定性规则

候选 ID 由规范化后的语义 key 生成，语义 key 至少包含：

- creator/evaluator/quarantine 边界 bucket；
- knowledge scope；
- class、ascendancy、main skill；
- lifecycle stage、budget band；
- category tags、mechanism role；
- league、game patch、passive tree version。

evidence ID 由 case ID、relation 和 extraction method 生成；`candidate_id` 和 `extractor_version`
存在字段中但不参与主键。
这样未来抽取器升级会更新同一条 evidence，而不会因为版本变化导致重复计数。
重复运行抽取器必须保持行数稳定，只更新 last_seen / extractor_version 字段和回算计数。

## 计数规则

`source_count`、`support_count`、`contradiction_count` 必须从 `candidate_evidence` 回算：

- `source_count`: 支持证据中的 distinct `source_group_id` 数量；
- `support_count`: relation = `supports` 的 evidence 数量；
- `contradiction_count`: relation = `contradicts` 的 evidence 数量。

## 生命周期字段推导

抽取器需要为每个候选写入：

- `required_prerequisites`
- `starter_risk_reason`
- `transition_gate_summary`
- `unsafe_before_stage`

这些字段是粗粒度提醒，不是可执行 BD 方案。
```

- [ ] **Step 2: 更新 `docs/PROJECT_SPEC.md`**

在 Phase 3N 当前工作下增加中文状态：

```markdown
Current Phase 3N.2 target:

- 从已净化成熟案例中确定性抽取 `technique_candidates`。
- 为每个候选写入 `candidate_evidence`，保留 visibility/split/knowledge_scope 边界。
- 从 evidence 表回算 source/support/contradiction 计数。
- 推导前置条件、开荒风险、转型门槛摘要和 unsafe-before-stage。
- 不改变 route synthesis、MCP 输出、检索、自动晋升或知识过期行为。
```

- [ ] **Step 3: 检查文档没有把 Phase 3N.2 扩大到未确认范围**

运行：

```powershell
rg "vector|graph database|auto-promot|expiration|route synthesis|teacher-student" docs/architecture/phase-03n2-mature-candidate-extraction.md docs/PROJECT_SPEC.md
```

Expected: 这些词只出现在 out-of-scope、confirmation gate 或“不做”的上下文中。

## Task 2：RED 测试——候选抽取和 evidence 桥接

**Files:**
- Modify: `tests/test_mature_learning.py`

- [ ] **Step 1: 添加失败测试**

在 `tests/test_mature_learning.py` 末尾添加测试：

```python
def _extract_rows(con: sqlite3.Connection, table: str) -> list[sqlite3.Row]:
    con.row_factory = sqlite3.Row
    return con.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()


def test_extract_technique_candidates_creates_candidates_and_evidence(tmp_path):
    db_path = tmp_path / "mature.sqlite"
    result = mature_learning.import_fixture_file(db_path=db_path)
    assert result["ok"] is True

    extract = mature_learning.extract_technique_candidates(db_path=db_path)

    assert extract["ok"] is True
    assert extract["casesScanned"] == 4
    assert extract["candidatesUpserted"] == 4
    assert extract["evidenceUpserted"] == 4
    con = mature_learning.connect(db_path)
    candidates = _extract_rows(con, "technique_candidates")
    evidence = _extract_rows(con, "candidate_evidence")
    assert len(candidates) == 4
    assert len(evidence) == 4
    assert {row["support_count"] for row in candidates} == {1}
    assert {row["contradiction_count"] for row in candidates} == {0}
    assert {row["source_count"] for row in candidates} == {1}
    assert all(row["promotion_status"] in {"candidate", "quarantined"} for row in candidates)
```

- [ ] **Step 2: 添加边界和幂等测试**

继续添加：

```python
def test_extract_technique_candidates_is_idempotent_and_deterministic(tmp_path):
    db_path = tmp_path / "mature.sqlite"
    assert mature_learning.import_fixture_file(db_path=db_path)["ok"] is True

    first = mature_learning.extract_technique_candidates(db_path=db_path)
    second = mature_learning.extract_technique_candidates(db_path=db_path)

    assert first["ok"] is True
    assert second["ok"] is True
    con = mature_learning.connect(db_path)
    candidate_ids = [
        row[0]
        for row in con.execute("SELECT candidate_id FROM technique_candidates ORDER BY candidate_id")
    ]
    evidence_ids = [
        row[0]
        for row in con.execute("SELECT evidence_id FROM candidate_evidence ORDER BY evidence_id")
    ]
    assert len(candidate_ids) == len(set(candidate_ids)) == 4
    assert len(evidence_ids) == len(set(evidence_ids)) == 4
    assert con.execute("SELECT count(*) FROM technique_candidates").fetchone()[0] == 4
    assert con.execute("SELECT count(*) FROM candidate_evidence").fetchone()[0] == 4


def test_extract_technique_candidates_preserves_creator_visibility_boundaries(tmp_path):
    db_path = tmp_path / "mature.sqlite"
    assert mature_learning.import_fixture_file(db_path=db_path)["ok"] is True

    mature_learning.extract_technique_candidates(db_path=db_path)

    con = mature_learning.connect(db_path)
    rows = con.execute(
        """
        SELECT visibility, split, creator_visible
        FROM candidate_evidence
        ORDER BY visibility, split
        """
    ).fetchall()
    assert ("creator_visible", "train_context", 1) in [tuple(row) for row in rows]
    assert ("evaluator_only", "eval_holdout", 0) in [tuple(row) for row in rows]
    assert ("quarantined", "quarantine", 0) in [tuple(row) for row in rows]
```

- [ ] **Step 3: 添加聚合计数测试**

添加一个双来源同 archetype fixture，证明计数来自 evidence 回算：

```python
def test_extract_technique_candidates_derives_counts_from_evidence_rows(tmp_path):
    fixture_path = tmp_path / "fixtures.json"
    first = _raw_case(sourceRef="fixture://spark-a")
    second = _raw_case(
        sourceRef="fixture://spark-b",
        keypoints=["Another coarse Spark mature-case summary from a separate source."],
    )
    fixture_path.write_text(
        json.dumps({"schemaVersion": 1, "fixtureSet": "counting", "cases": [first, second]}),
        encoding="utf-8",
    )
    db_path = tmp_path / "mature.sqlite"
    assert mature_learning.import_fixture_file(fixture_path, db_path=db_path)["ok"] is True

    mature_learning.extract_technique_candidates(db_path=db_path)

    con = mature_learning.connect(db_path)
    candidate = con.execute("SELECT * FROM technique_candidates").fetchone()
    assert candidate["support_count"] == 2
    assert candidate["source_count"] == 2
    assert candidate["contradiction_count"] == 0
```

- [ ] **Step 4: 验证 RED**

运行：

```powershell
.\.tools\uv\uv.exe run pytest tests/test_mature_learning.py::test_extract_technique_candidates_creates_candidates_and_evidence tests/test_mature_learning.py::test_extract_technique_candidates_is_idempotent_and_deterministic tests/test_mature_learning.py::test_extract_technique_candidates_preserves_creator_visibility_boundaries tests/test_mature_learning.py::test_extract_technique_candidates_derives_counts_from_evidence_rows -q
```

Expected: FAIL，失败原因是 `extract_technique_candidates` 尚不存在。

## Task 3：实现确定性候选抽取器

**Files:**
- Modify: `server/knowledge/mature_learning.py`

- [ ] **Step 1: 添加 Phase 3N.2 常量和 JSON helper**

在 `SANITIZER_VERSION` 下方新增：

```python
EXTRACTOR_VERSION = "phase3n2-v1"
EXTRACTION_METHOD = "deterministic_mature_case_summary"
```

在 `_stable_hash` 下方新增：

```python
def _json_loads(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(str(value))
    except (TypeError, ValueError):
        return default
```

- [ ] **Step 2: 添加候选语义推导 helper**

在 sanitizer helper 后新增：

```python
def _candidate_visibility_bucket(row: sqlite3.Row) -> str:
    if row["visibility"] == "creator_visible" and row["split"] == "train_context":
        return "creator_context"
    if row["visibility"] == "evaluator_only" and row["split"] == "eval_holdout":
        return "evaluator_holdout"
    return "quarantine"


def _candidate_knowledge_scope(row: sqlite3.Row) -> str:
    bucket = _candidate_visibility_bucket(row)
    if bucket != "creator_context":
        return "eval_ephemeral"
    return row["knowledge_scope"]
```

继续添加 `_candidate_category_tags(row)`、`_mechanism_role(row)`、`_required_prerequisites(row)`、
`_starter_risk_reason(row)`、`_transition_gate_summary(row, prerequisites)`、
`_unsafe_before_stage(stage)`。这些 helper 只使用已净化字段，并在代码注释中说明“粗粒度研究提示，不是可执行 BD”。

标签/list 进入 semantic key 前必须 lower/trim/sort/dedupe，避免同语义但顺序不同的 mature case
被拆成多个候选。

- [ ] **Step 3: 添加候选构建和 evidence 构建**

新增 `_candidate_from_case(row)`：

```python
def _candidate_from_case(row: sqlite3.Row) -> dict[str, Any]:
    damage = _json_loads(row["damage_types"], [])
    delivery = _json_loads(row["delivery_tags"], [])
    defenses = _json_loads(row["defense_tags"], [])
    mechanics = _json_loads(row["mechanic_tags"], [])
    keypoints = _json_loads(row["sanitized_keypoints"], [])
    category_tags = _candidate_category_tags(row)
    mechanism_role = _mechanism_role(row)
    prerequisites = _required_prerequisites(row)
    semantic_key = {
        "bucket": _candidate_visibility_bucket(row),
        "scope": _candidate_knowledge_scope(row),
        "class": row["class"],
        "ascendancy": row["ascendancy"],
        "main_skill": row["main_skill"],
        "damage": damage,
        "delivery": delivery,
        "defenses": defenses,
        "mechanics": mechanics,
        "stage": row["lifecycle_stage"],
        "budget": row["budget_band"],
        "category_tags": category_tags,
        "mechanism_role": mechanism_role,
        "league": row["league"],
        "game_patch": row["game_patch"],
        "passive_tree_version": row["passive_tree_version"],
    }
    candidate_id = f"tc-{_stable_hash(semantic_key)[:16]}"
    statement = (
        f"{row['ascendancy']} {row['main_skill']} mature cases suggest a "
        f"{mechanism_role} pattern for {row['lifecycle_stage']}."
    )
    summary = (
        f"Research candidate only: {row['class']}/{row['ascendancy']} using "
        f"{row['main_skill']} with tags {', '.join(category_tags[:8])}. "
        f"Validate with lifecycle gates and PoB before recommendation."
    )
    if keypoints:
        summary += f" Sanitized note count: {len(keypoints)}."
    return {...}
```

`return` 字典必须包含所有 `technique_candidates` 插入字段，`promotion_status` 对 quarantine bucket 写
`quarantined`，其他写 `candidate`，`confidence` 初始为 `low`。

- [ ] **Step 4: 添加 upsert 和计数回算**

新增 `_upsert_candidate(con, candidate, now)`、`_upsert_candidate_evidence(con, row, candidate_id, now)`、
`_refresh_candidate_counts(con)`。

关键 SQL：

```sql
INSERT INTO technique_candidates(...) VALUES (...)
ON CONFLICT(candidate_id) DO UPDATE SET
    statement = excluded.statement,
    summary_for_llm = excluded.summary_for_llm,
    category_tags = excluded.category_tags,
    lifecycle_stage = excluded.lifecycle_stage,
    mechanism_role = excluded.mechanism_role,
    evidence_type = excluded.evidence_type,
    confidence = excluded.confidence,
    promotion_status = excluded.promotion_status,
    freshness_status = excluded.freshness_status,
    compatibility_status = excluded.compatibility_status,
    required_prerequisites = excluded.required_prerequisites,
    starter_risk_reason = excluded.starter_risk_reason,
    transition_gate_summary = excluded.transition_gate_summary,
    unsafe_before_stage = excluded.unsafe_before_stage,
    last_seen_at = excluded.last_seen_at
```

计数 SQL 必须从 `candidate_evidence` 子查询回写。

- [ ] **Step 5: 添加公共入口**

新增：

```python
def extract_technique_candidates(db_path: Path | None = None) -> dict[str, Any]:
    initialize_store(db_path)
    con = connect(db_path)
    try:
        rows = con.execute(
            "SELECT * FROM mature_build_cases ORDER BY case_id"
        ).fetchall()
        now = _now()
        candidate_ids: set[str] = set()
        evidence_ids: set[str] = set()
        for row in rows:
            candidate = _candidate_from_case(row)
            _upsert_candidate(con, candidate, now)
            evidence_id = _upsert_candidate_evidence(con, row, candidate["candidate_id"], now)
            candidate_ids.add(candidate["candidate_id"])
            evidence_ids.add(evidence_id)
        _refresh_candidate_counts(con)
        con.commit()
    finally:
        con.close()
    return {
        "ok": True,
        "casesScanned": len(rows),
        "candidatesUpserted": len(candidate_ids),
        "evidenceUpserted": len(evidence_ids),
        "extractorVersion": EXTRACTOR_VERSION,
    }
```

- [ ] **Step 6: 运行 GREEN 测试**

运行：

```powershell
.\.tools\uv\uv.exe run pytest tests/test_mature_learning.py::test_extract_technique_candidates_creates_candidates_and_evidence tests/test_mature_learning.py::test_extract_technique_candidates_is_idempotent_and_deterministic tests/test_mature_learning.py::test_extract_technique_candidates_preserves_creator_visibility_boundaries tests/test_mature_learning.py::test_extract_technique_candidates_derives_counts_from_evidence_rows -q
```

Expected: PASS。

## Task 4：边界补充测试和快速验证

**Files:**
- Modify: `tests/test_mature_learning.py`

- [ ] **Step 1: 添加生命周期字段测试**

新增测试：

```python
def test_extract_technique_candidates_records_lifecycle_risk_fields(tmp_path):
    db_path = tmp_path / "mature.sqlite"
    assert mature_learning.import_fixture_file(db_path=db_path)["ok"] is True

    mature_learning.extract_technique_candidates(db_path=db_path)

    con = mature_learning.connect(db_path)
    row = con.execute(
        """
        SELECT required_prerequisites, starter_risk_reason, transition_gate_summary,
               unsafe_before_stage
        FROM technique_candidates
        WHERE lifecycle_stage = 'endgame_final'
        LIMIT 1
        """
    ).fetchone()
    assert json.loads(row["required_prerequisites"])
    assert "starter" in row["starter_risk_reason"].lower()
    assert "transition" in row["transition_gate_summary"].lower()
    assert row["unsafe_before_stage"] in {"maps_entry", "endgame_budget", "endgame_final"}
```

- [ ] **Step 2: 添加同语义跨边界不聚合测试**

新增测试：

```python
def test_extract_technique_candidates_keeps_same_semantic_holdout_in_separate_bucket(tmp_path):
    fixture_path = tmp_path / "fixtures.json"
    creator = _raw_case(sourceRef="fixture://same-semantic-creator")
    evaluator = _raw_case(
        sourceRef="fixture://same-semantic-evaluator",
        visibility="evaluator_only",
        split="eval_holdout",
    )
    quarantined = _raw_case(
        sourceRef="fixture://same-semantic-quarantine",
        visibility="quarantined",
        split="quarantine",
    )
    fixture_path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "fixtureSet": "same-semantic-boundary",
                "cases": [creator, evaluator, quarantined],
            }
        ),
        encoding="utf-8",
    )
    db_path = tmp_path / "mature.sqlite"
    assert mature_learning.import_fixture_file(fixture_path, db_path=db_path)["ok"] is True

    mature_learning.extract_technique_candidates(db_path=db_path)

    con = mature_learning.connect(db_path)
    rows = con.execute(
        """
        SELECT tc.candidate_id, tc.knowledge_scope, tc.promotion_status, tc.source_count,
               ce.visibility, ce.split, ce.creator_visible
        FROM technique_candidates tc
        JOIN candidate_evidence ce ON ce.candidate_id = tc.candidate_id
        ORDER BY ce.visibility, ce.split
        """
    ).fetchall()
    assert len({row["candidate_id"] for row in rows}) == 3
    assert all(row["source_count"] == 1 for row in rows)
    by_visibility = {row["visibility"]: row for row in rows}
    assert by_visibility["creator_visible"]["knowledge_scope"] == "global_seed"
    assert by_visibility["creator_visible"]["creator_visible"] == 1
    assert by_visibility["evaluator_only"]["knowledge_scope"] == "eval_ephemeral"
    assert by_visibility["evaluator_only"]["creator_visible"] == 0
    assert by_visibility["quarantined"]["knowledge_scope"] == "eval_ephemeral"
    assert by_visibility["quarantined"]["promotion_status"] == "quarantined"
    assert by_visibility["quarantined"]["creator_visible"] == 0
```

- [ ] **Step 3: 添加 evaluator 候选 scope 测试**

新增测试：

```python
def test_evaluator_only_candidates_do_not_become_global_creator_context(tmp_path):
    db_path = tmp_path / "mature.sqlite"
    assert mature_learning.import_fixture_file(db_path=db_path)["ok"] is True

    mature_learning.extract_technique_candidates(db_path=db_path)

    con = mature_learning.connect(db_path)
    evaluator_candidate_ids = [
        row["candidate_id"]
        for row in con.execute(
            """
            SELECT DISTINCT candidate_id
            FROM candidate_evidence
            WHERE visibility = 'evaluator_only'
            """
        )
    ]
    assert evaluator_candidate_ids
    scopes = {
        row["knowledge_scope"]
        for row in con.execute(
            "SELECT knowledge_scope FROM technique_candidates WHERE candidate_id IN ({})".format(
                ",".join("?" for _ in evaluator_candidate_ids)
            ),
            evaluator_candidate_ids,
        )
    }
    assert scopes == {"eval_ephemeral"}
```

- [ ] **Step 4: 添加计数回算防伪测试**

新增测试：

```python
def test_extract_technique_candidates_recomputes_counts_from_evidence(tmp_path):
    db_path = tmp_path / "mature.sqlite"
    assert mature_learning.import_fixture_file(db_path=db_path)["ok"] is True
    assert mature_learning.extract_technique_candidates(db_path=db_path)["ok"] is True
    con = mature_learning.connect(db_path)
    con.execute(
        "UPDATE technique_candidates SET source_count = 99, support_count = 99, contradiction_count = 99"
    )
    con.commit()
    con.close()

    mature_learning.extract_technique_candidates(db_path=db_path)

    con = mature_learning.connect(db_path)
    counts = con.execute(
        "SELECT DISTINCT source_count, support_count, contradiction_count FROM technique_candidates"
    ).fetchall()
    assert {tuple(row) for row in counts} == {(1, 1, 0)}
```

- [ ] **Step 5: 运行 targeted 测试**

运行：

```powershell
.\.tools\uv\uv.exe run pytest tests/test_mature_learning.py -q
```

Expected: PASS。

- [ ] **Step 6: 运行 quick 验证**

运行：

```powershell
.\scripts\verify.ps1 quick
```

Expected: PASS。

## Task 5：审查、修复和提交

**Files:**
- Modify if review requires: `server/knowledge/mature_learning.py`
- Modify if review requires: `tests/test_mature_learning.py`
- Modify if review requires: `docs/PROJECT_SPEC.md`
- Modify if review requires: `docs/architecture/phase-03n2-mature-candidate-extraction.md`

- [ ] **Step 1: subagent 代码审查**

把 diff 和 Phase 3N.2 目标发给 subagent，要求检查：

- 是否越界影响 route synthesis / MCP / retrieval；
- 是否泄漏 holdout/quarantine 为 creator-visible；
- 是否有可复刻成熟 BD 的摘要风险；
- 是否计数真的由 evidence 表回算；
- 是否代码可读、关键位置有注释。

- [ ] **Step 2: 必要时做窄规格复审**

本切片改变 evidence 边界和候选输出合同，因此需要窄规格复审，重点检查：

- `candidate_evidence` 边界；
- `technique_candidates` 的 scope / promotion_status；
- out-of-scope 是否保持不变。

- [ ] **Step 3: 修复 review 问题并重跑测试**

至少重跑：

```powershell
.\.tools\uv\uv.exe run pytest tests/test_mature_learning.py -q
.\scripts\verify.ps1 quick
```

- [ ] **Step 4: 提交**

```powershell
git add server/knowledge/mature_learning.py tests/test_mature_learning.py docs/PROJECT_SPEC.md docs/architecture/phase-03n2-mature-candidate-extraction.md docs/superpowers/plans/2026-06-27-mature-learning-candidate-extraction-3n2.md
git commit -m "feat: extract mature learning candidates"
```

## 自检

- Spec coverage：Phase 3N.2 四项要求都有对应任务：候选抽取、evidence 桥接、计数回算、生命周期风险字段。
- Placeholder scan：没有 TBD/TODO/“以后实现”作为任务内容；out-of-scope 明确保留。
- Type consistency：计划中使用的函数名统一为 `extract_technique_candidates`，常量为 `EXTRACTOR_VERSION` / `EXTRACTION_METHOD`。
