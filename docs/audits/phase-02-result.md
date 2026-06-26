# 第二阶段结果：Live freshness runtime

Status: DONE for the 2026-06-25 certification snapshot; 2026-06-26 live smoke is
currently blocked by a real upstream patch drift (`GGG=0.5.4`, certified PoB/local
release=`0.5.3`).

## 审计日期

- 执行日期：2026-06-25 Asia/Hong_Kong
- 最终 live smoke `evaluated_at`：2026-06-25T14:54:07.303768+00:00（2026-06-25
  22:54:07 Asia/Hong_Kong）
- 追踪复核：2026-06-26 Asia/Hong_Kong 发现 GGG patch 已推进到 `0.5.4 Hotfix 2`。

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
9. Task8 最终独立审查修复：
   - MCP 报告增加 `provider_status`，保留 `providers` 兼容 alias；
   - poe.ninja 拆为 `ninja-index.json` / `ninja-build-index.json` 双缓存；
   - PoB release cache 使用 `pob-release.json`；
   - local validated-release claims 必须由 `data/compatibility/pob.json` 授权；
   - cache / provider diagnostics 去除本地路径和原始异常文本；
   - 全局 pytest timeout 设为 300s，慢 compute 认证测试显式 900s 覆盖。

## RED/GREEN 与 targeted tests

```powershell
.\.tools\uv\uv.exe run pytest tests/test_smoke_freshness.py -q
```

- RED：在 `scripts/smoke_freshness.py` 创建前失败，报错为
  `ImportError: cannot import name 'smoke_freshness' from 'scripts'`。
- GREEN：实现脚本后同一命令通过；code-quality 修复补齐 sanitizer/exit 语义覆盖后，当前结果为
  `5 passed`。
- Task8 RED/GREEN：
  - `provider_status`、8s/5s 超时、cache 文件名、poe.ninja 双缓存、compat manifest 授权
    local claims、cache I/O 诊断脱敏均先由 focused tests 复现失败，再修复转绿；
  - unexpected provider `RuntimeError` 不再被转成 `blocked_unknown`，而是向上暴露为编程错误；
  - expected provider/cache/transport failures 使用固定诊断，不回传原始 path/query/body/header 文本；
  - `tests/test_project_config.py` 保护全局 `pytest-timeout` 配置。

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
| `.\.tools\uv\uv.exe run pytest tests/test_smoke_freshness.py tests/test_server.py tests/test_freshness_service.py tests/test_freshness_ninja.py tests/test_freshness_cache.py tests/test_freshness_pob.py tests/test_update.py tests/test_project_config.py -q` | PASS，退出码 0，Task8 focused regression tests 通过。 |
| `.\.tools\uv\uv.exe run ruff check server scripts pipeline tests` | PASS，退出码 0，`All checks passed!` |
| `.\.tools\uv\uv.exe run ruff format --check server scripts pipeline tests` | PASS，退出码 0，`66 files already formatted`。 |
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
| `ggg-patch` | `refreshed` | 2092 ms | none |
| `ggg-tree` | `refreshed` | 1905 ms | none |
| `poe-ninja` | `refreshed` | 922 ms | `sample_size=124292`; `snapshot_date=2026-06-25` |
| `pob` | `refreshed` | 1250 ms | compatibility manifest matched PoB commit `dc409a7073e4e2752e9a642db7544af53551d006` |

### Evidence observed

| Component | Source | Status | Version | Claims |
| --- | --- | --- | --- | --- |
| `pob_engine` | `validated-release-engine` | `current` | `dc409a7073e4e2752e9a642db7544af53551d006` | `passive_tree=0_5`; `game_patch=0.5.3` |
| `pob_data` | `validated-release-pob-data` | `current` | `dc409a7073e4e2752e9a642db7544af53551d006` | `passive_tree=0_5`; `game_patch=0.5.3` |
| `corpus` | `validated-release-corpus` | `current` | `v0.1.39` | `passive_tree=0_5`; `game_patch=0.5.3` |
| `game_patch` | `ggg-patch` | `current` | `0.5.3 Hotfix 9` | `game_patch=0.5.3` |
| `league` | `ggg-tree` | `current` | `Runes of Aldur` | `league=runes-of-aldur` |
| `passive_tree` | `ggg-tree` | `current` | `1e9eb2d8c1946398c3aaaacfbaead5c75c0d1fa6` | `passive_tree=0_5` |
| `meta_snapshot` | `poe-ninja` | `current` | `1430-20260625-36766` | `league=runes-of-aldur`; `passive_tree=0_5` |
| `pob_engine` | `pob` | `current` | `dc409a7073e4e2752e9a642db7544af53551d006` | `game_patch=0.5.3`; `passive_tree=0_5` |
| `pob_data` | `pob` | `current` | `dc409a7073e4e2752e9a642db7544af53551d006` | `game_patch=0.5.3`; `passive_tree=0_5` |

### Blockers observed

- none

Warnings：none。

## 2026-06-26 follow-up live smoke

执行命令：

```powershell
$env:POE2_MCP_DATA='E:\poe-bd-creator\.runtime-data'
.\.tools\uv\uv.exe run python scripts/smoke_freshness.py
```

结果：退出码 0，decision 为 `blocked_conflict`。

Freshness evaluator 报告的冲突为：

- GGG patch provider：`0.5.4 Hotfix 2`，claim `game_patch=0.5.4`；
- local validated release / PoB provider / certified corpus：仍为
  `dc409a7073e4e2752e9a642db7544af53551d006` / `v0.1.39`，claim `game_patch=0.5.3`。

这不是实现回归，而是预期的 fail-closed 行为：当前上游游戏补丁已经超过本地认证过的
PoB/data release。下一步必须认证 PoB `0.5.4` 候选（截至复核时，PoB `dev` 已出现
`0.5.4 Export` commit），并发布或安装新的 validated release 后，live smoke 才能重新
达到 `verified_current`。

## Remaining blockers

None for the Phase 2 implementation itself. Current live verification is blocked by the
2026-06-26 upstream `0.5.4` patch drift until a new PoB/data certification is completed.
