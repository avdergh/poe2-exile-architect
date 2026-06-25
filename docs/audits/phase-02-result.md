# 第二阶段结果：Live freshness runtime

Status: DONE

## 审计日期

- 执行日期：2026-06-25 Asia/Hong_Kong
- 最终 live smoke `evaluated_at`：2026-06-25T10:40:04.599124+00:00（2026-06-25
  18:40:04 Asia/Hong_Kong）

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
7. Task7 将 PoB-PoE2 pin 升级并认证到 `v0.21.1` /
   `dc409a7073e4e2752e9a642db7544af53551d006`，并把认证结果写入
   `data/compatibility/pob.json`。
8. self-update 安装元数据现在持久化 `game_patch` / `passive_tree` claims；freshness
   evaluator 接受 GGG patch 与 GGG tree 的分源证明。

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
| `.\.tools\uv\uv.exe run python -m pipeline.build_corpus` | PASS，构建 `data/corpus.sqlite`，items 4926，gems 1110，mods 8259，uniques 433。 |
| `.\.tools\uv\uv.exe run pytest tests/test_compute.py -q --timeout=300` | PASS，退出码 0；`test_optimize_build_crafting_keeps_resists_capped` 使用显式 900s per-test timeout 并完整通过。 |
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

结果：退出码 0，decision 为 `verified_current`。

### Provider cache states

| Provider | Cache state | Duration | Diagnostics |
| --- | --- | ---: | --- |
| `local` | `fresh` | 0 ms | none |
| `ggg-patch` | `refreshed` | 1563 ms | none |
| `ggg-tree` | `refreshed` | 1750 ms | none |
| `poe-ninja` | `revalidated` | 250 ms | `sample_size=124304`; `snapshot_date=2026-06-25` |
| `pob` | `revalidated` | 546 ms | compatibility manifest matched PoB commit `dc409a7073e4e2752e9a642db7544af53551d006` |

### Evidence observed

| Component | Source | Status | Version | Claims |
| --- | --- | --- | --- | --- |
| `pob_engine` | `validated-release-engine` | `current` | `dc409a7073e4e2752e9a642db7544af53551d006` | `passive_tree=0_5`; `game_patch=0.5.3` |
| `pob_data` | `validated-release-pob-data` | `current` | `dc409a7073e4e2752e9a642db7544af53551d006` | `passive_tree=0_5`; `game_patch=0.5.3` |
| `corpus` | `validated-release-corpus` | `current` | `v0.1.39` | `passive_tree=0_5`; `game_patch=0.5.3` |
| `game_patch` | `ggg-patch` | `current` | `0.5.3 Hotfix 9` | `game_patch=0.5.3` |
| `league` | `ggg-tree` | `current` | `Runes of Aldur` | `league=runes-of-aldur` |
| `passive_tree` | `ggg-tree` | `current` | `1e9eb2d8c1946398c3aaaacfbaead5c75c0d1fa6` | `passive_tree=0_5` |
| `meta_snapshot` | `poe-ninja` | `current` | `1020-20260625-36791` | `league=runes-of-aldur`; `passive_tree=0_5` |
| `pob_engine` | `pob` | `current` | `dc409a7073e4e2752e9a642db7544af53551d006` | `game_patch=0.5.3`; `passive_tree=0_5` |
| `pob_data` | `pob` | `current` | `dc409a7073e4e2752e9a642db7544af53551d006` | `game_patch=0.5.3`; `passive_tree=0_5` |

### Blockers observed

- none

Warnings：none。

## Remaining blockers

None for Phase 2 / Task7. Final smoke reached `verified_current` with no blockers or warnings.
