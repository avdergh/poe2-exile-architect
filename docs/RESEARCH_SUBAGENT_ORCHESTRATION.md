# Research Subagent 编排

## 目标

Research 由 `poe-bd-research` Controller 建立/恢复队列，再显式派发
`poe-bd-research-worker`。默认最多 5 个案例研究 worker；回访和其他活动不计入该业务上限，宿主总
容量更低时按实际容量运行。

## 角色边界

- Controller 只负责 queue/resume、worker 编排、等待、status、可选回访和最终汇总；不 claim、不读取
  案例证据、不编辑 review、不 accept。派发显式点名 Worker Skill，并只携带绝对 runDir。
- Worker Skill 设为 explicit-only，自行原子 claim 一案，连续持有 lease、证据、safe review 和 accept
  责任；不得 queue、嵌套委派或领取第二案。claim 后所有结束路径返回 sampleId 与 safe outcome。
- 回访默认关闭。用户明确要求时，主会话续聊原 worker，只核对高价值内容是否充分入库、是否发现
  工具/流程缺陷，并要求只反馈不修改。反馈确认或放弃前保留 runDir；知识补录由 Controller 建新的
  supplement run 后续发给原 agent，开发修复则显式退出 Worker 运行态。

## 并发与写入

- queue SQLite 通过 `BEGIN IMMEDIATE` 和最多 5 个 active lease 防止重复领取；满载返回
  `worker_capacity_reached`。
- status 以 `dispatchableCount` 暴露 queued + 过期 claimed，以 `staleAcceptingCount` 诊断可能中断的
  验收；前者可重新派发，后者失败关闭且不自动恢复。
- inspect/read/search、Memory/Graph 查询和 validate-only 可并发。
- 正式 accept 与 retry-accept 共享进程级全局 RLock；跨进程文件锁按 Research Memory DB 派生。锁内
  完成 acceptance、queue 最终 CAS 和共享 intake ledger 晋升。review 与 packet 按 lease 隔离。
- 该锁只防止多个验收交错，不把 Research Memory、queue 和 ledger 变成跨库原子事务。进程被硬终止
  时仍保留现有显式恢复边界，不新增后台调度、自动抢占、WAL 或 provider loop。
- Windows 使用 msvcrt 文件锁；macOS/Linux 使用 `fcntl.flock`。macOS 目前属于设计兼容而非实机认证。

## 完成条件

全部请求案例均正式 accepted，最终 status 中没有 queued、claimed、accepting 或 rejected 案例，且
报告计数与持久化结果一致时，Research 才成功。启用回访时，还需先向用户汇总案例与原 subagent 的
对应反馈，再由用户决定修复或清理。
