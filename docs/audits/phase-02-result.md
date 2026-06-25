# 第二阶段结果：Live freshness runtime

Status: DONE

## 审计日期

- 执行日期：2026-06-25 Asia/Hong_Kong
- 最终 live smoke `evaluated_at`：2026-06-25T09:04:55.441206+00:00（2026-06-25
  17:04:55 Asia/Hong_Kong）

## 已完成

1. 新增 `scripts/smoke_freshness.py`，从 repo root 插入 `sys.path` 后调用
   `server.freshness.service.get_freshness_report(force_refresh=True)`。
2. smoke 输出顶层 decision、evaluated_at、blockers、warnings、provider
   cache states/duration/diagnostics，以及 evidence component/source/status/version/claims。
3. smoke 对诊断文本折叠换行、清理控制字符、遮盖明显 secret/query/header 值并截断长文本，
   避免在日志里打印完整 upstream body、token 或过长 URL。
4. smoke 对 `blocked_stale`、`blocked_unknown` 和网络不可用等正常 freshness 结果返回退出码 0；
   只有脚本内部错误或 service 抛异常时返回非零。
5. `PACKAGING.md` 补充 live freshness cache 位置、`POE2_MCP_DATA`、`POE2_MCP_NO_AUTOUPDATE`
   与 `force_refresh=True` 的运行语义，以及 smoke 命令示例。
6. 对前序 freshness 文件执行 Ruff 格式化，使第二阶段离线 format gate 达到全绿。

## RED/GREEN 与 targeted tests

```powershell
.\.tools\uv\uv.exe run pytest tests/test_smoke_freshness.py -q
```

- RED：在 `scripts/smoke_freshness.py` 创建前失败，报错为
  `ImportError: cannot import name 'smoke_freshness' from 'scripts'`。
- GREEN：实现脚本后同一命令通过；code-quality 修复补齐 sanitizer/exit 语义覆盖后，当前结果为
  `5 passed`。

## 离线验证

执行前设置：

```powershell
$env:POE2_MCP_DATA='E:\poe-bd-creator\.runtime-data'
$env:POE2_MCP_NO_AUTOUPDATE='1'
```

| 命令 | 结果 |
| --- | --- |
| `.\.tools\uv\uv.exe run pytest -q --ignore=tests/test_compute.py` | PASS，退出码 0，所有非 compute 测试通过。 |
| `.\.tools\uv\uv.exe run ruff check server scripts pipeline tests` | PASS，退出码 0，`All checks passed!` |
| `.\.tools\uv\uv.exe run ruff format --check server scripts pipeline tests` | PASS，退出码 0，`65 files already formatted`。 |
| `.\.tools\uv\uv.exe run mypy server/freshness` | PASS，退出码 0，`Success: no issues found in 10 source files`。 |
| `npx --yes @anthropic-ai/mcpb validate manifest.json` | PASS，退出码 0，manifest schema validation passes；仅有图标建议尺寸 warning。 |

## Live smoke

执行命令：

```powershell
$env:POE2_MCP_DATA='E:\poe-bd-creator\.runtime-data'
.\.tools\uv\uv.exe run python scripts/smoke_freshness.py
```

结果：退出码 0，decision 为 `blocked_stale`。

### Provider cache states

| Provider | Cache state | Duration | Diagnostics |
| --- | --- | ---: | --- |
| `local` | `fresh` | 0 ms | none |
| `ggg-patch` | `refreshed` | 1844 ms | none |
| `ggg-tree` | `fallback` | 313 ms | `transport returned HTTP 403` |
| `poe-ninja` | `refreshed` | 688 ms | `sample_size=124287`; `snapshot_date=2026-06-25` |
| `pob` | `fallback` | 296 ms | `transport returned HTTP 403`; local PoB `v0.1.39` / `a82a33b4`; latest release `v0.21.1` / `dc409a7073e4` |

### Evidence observed

| Component | Source | Status | Version | Claims |
| --- | --- | --- | --- | --- |
| `pob_engine` | `validated-release-engine` | `current` | `a82a33b4` | `passive_tree=0_5` |
| `pob_data` | `validated-release-pob-data` | `current` | `a82a33b4` | `passive_tree=0_5` |
| `corpus` | `validated-release-corpus` | `current` | `v0.1.39` | `passive_tree=0_5` |
| `game_patch` | `ggg-patch` | `current` | `0.5.3 Hotfix 9` | `game_patch=0.5.3` |
| `league` | `ggg-tree` | `current` | `Runes of Aldur` | `league=runes-of-aldur` |
| `passive_tree` | `ggg-tree` | `current` | `1e9eb2d8c1946398c3aaaacfbaead5c75c0d1fa6` | `passive_tree=0_5` |
| `meta_snapshot` | `poe-ninja` | `current` | `0816-20260625-12461` | `league=runes-of-aldur`; `passive_tree=0_5` |
| `pob_engine` | `pob` | `stale` | `v0.1.39` | none |
| `pob_data` | `pob` | `stale` | `v0.1.39` | none |

### Blockers observed

- `pob reports stale pob_engine version v0.1.39`
- `pob reports stale pob_data version v0.1.39`
- `validated-release-engine is missing required claim game_patch for pob_engine`
- `validated-release-pob-data is missing required claim game_patch for pob_data`
- `validated-release-corpus is missing required claim game_patch for corpus`
- `ggg-tree is missing required claim game_patch for passive_tree`
- `pob is missing required claim game_patch for pob_engine`
- `pob is missing required claim passive_tree for pob_engine`
- `pob is missing required claim game_patch for pob_data`
- `pob is missing required claim passive_tree for pob_data`

Warnings：none。

## Remaining blockers

1. PoB provider reports local `v0.1.39` / `a82a33b4` as stale versus upstream `v0.21.1` /
   `dc409a7073e4`; Task7 needs to import and certify the newer PoB release.
2. Local validated release evidence still lacks `game_patch` claims for PoB engine, PoB data,
   and corpus compatibility.
3. GGG tree evidence currently asserts `passive_tree=0_5` but does not assert `game_patch`; that is
   expected because the official tree source is a passive-tree authority, not a patch authority.
4. The final smoke run used valid fallback cache for `ggg-tree` and `pob` after HTTP 403 responses;
   this did not change the decision, but it confirms fallback diagnostics should remain visible.
