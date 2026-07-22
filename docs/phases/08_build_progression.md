# Phase 8 - 可验证的完整 BD 成长流程

## 阶段状态

进行中。首个合同切片已开始：用多个可信 `FinalBuildArtifact` 组成可加载的成长路线。

## 问题

Phase 5 当前能把用户要求的单一目标阶段做成完整、可 Judge、可导出的 PoB，但开荒到目标阶段的
过程主要仍是文字 `StagePlan`。这会导致技能切换、洗点、装备门槛和资源变化没有独立 PoB 状态，
也无法证明某个中间阶段真的合法、可玩。

## 目标

输出一条从早期里程碑到用户目标等级的可验证构筑链：

- 每个重要里程碑都有独立、可加载、Judge 通过的 `FinalBuildArtifact`；
- 相邻里程碑之间有 typed 技能、辅助、天赋、装备、升华、配置和资源变化；
- 每次切换有明确的等级、任务、技能可用性、装备、Spirit、属性、抗性、预算或 Judge 门槛；
- 用户可以加载任一阶段的真实 PoB，而不是只能阅读目标装备和文字说明；
- 最终交付同时包含阶段路线和各阶段 PoB 文件；官方 `.build` 的多阶段表达只有 provider 能忠实
  支持时才加入，不能伪造 `level_interval`。

## 核心边界

- 不从终局 PoB 自动删点、降级装备来猜早期构筑；Agent 必须分别创造每个阶段。
- 仍由 Agent 决定技能、天赋、装备、轮转和转型；程序只验证合同、可信 artifact 和阶段关系。
- 职业是跨阶段唯一硬锁；升华、技能、辅助、天赋和装备允许改变，但必须记录 delta 与 gate。
- 一个文字阶段不能冒充已验证阶段。没有独立 artifact 的内容只能标记为 `textOnly`。
- 每个阶段复用 Phase 5 的完整性、Judge 和 FinalBuildArtifact 安全边界；不新增第二套数值引擎。
- 阶段 XML 继续只存在本地私有 artifact，不能进入聊天、Memory、Research 或 Git。

## 产品流程

```text
用户目标
  -> Agent 规划 2~8 个有意义的里程碑
  -> 对每个里程碑独立运行 Phase 5 Create/Judge/保存 artifact
  -> 校验等级递增、阶段顺序、职业一致、版本一致、快照不重复
  -> Agent 填写相邻阶段的 typed delta 与 transition requirements
  -> 保存 ProgressionRouteArtifact
  -> 可按阶段加载、复审和导出完整成长包
```

里程碑数量由实际机制决定，不机械要求每个 lifecycle enum 都有一份 PoB。只有技能、装备、升华、
资源模型或主要玩法发生实质变化时才新增里程碑。

## 数据合同

### ProgressionStage

- lifecycle stage 与目标等级；
- 对应可信 `FinalBuildArtifact`；
- 当前阶段用途与实际操作循环；
- 相对上一阶段的有界 typed changes；
- 进入本阶段的 typed transition requirements；
- 获取优先级与 caveats。

### ProgressionRouteArtifact

- 路线名、职业壳和最终 artifact；
- 2~8 个等级严格递增、生命周期顺序严格递增的阶段；
- 每个 artifact 的安全 hash/class/level/ascendancy/main-skill/version 事实；
- 创建时间、本地私有标志和无 raw PoB 保证。

## 实施顺序

1. 实现 ProgressionRoute typed schema、本地 manifest、可信 artifact 绑定和阶段加载工具。
2. 把 progression mode 接入 `$poe-bd-create`，由一个可见控制任务串行创建多个阶段 run。
3. 增加阶段设计 packet，明确哪些阶段需要真实 snapshot、哪些只是文字过渡说明。
4. 增加相邻阶段 delta 辅助提取和人工/Agent 复核，避免让 Agent重复抄完整构筑。
5. 增加完整成长包导出：路线文档、每阶段 PoB XML/import code、最终单阶段 `.build`。
6. 用至少一个开荒到 80 级案例做真实验收，逐阶段加载并检查合法性、可获得性和切换门槛。

## 当前首个切片验收

- prose-only stage 无法保存为 verified progression；
- 每阶段必须引用可重新校验的可信 FinalBuildArtifact；
- 等级和 lifecycle stage 严格递增；
- 所有阶段职业一致，版本与 route context 一致；
- 后续阶段必须包含 typed changes 和 transition requirements；
- 任一阶段可按 route id + lifecycle stage 安全加载，响应不含 raw PoB。

## 后续验收

- `$poe-bd-create` 能在用户明确要求完整成长流程时创建多个真实阶段，而不是只扩写描述；
- 阶段技能、天赋、装备和资源在对应等级可用；
- 路线说明可以从 typed delta 生成，但不能反向取代 artifact；
- 原有单阶段 Create、Phase 7 对照学习和 Phase 6 最终导出无回归。
