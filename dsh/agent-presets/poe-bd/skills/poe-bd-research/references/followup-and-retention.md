# 补研、重取与期限

仅在案例有缺口、用户要求补研/重取或原料到期时读取。本流程由外部Agent判断知识是否解决了问题，
工具只校验身份、证据、状态和安全边界，不代替研究推理。

## 逐项关闭

1. 用`mcp__poe_research__get_research_followup_status(run_ref, sample_id)`分页读取缺口，保留`gapRef`、`revision`、
   原始诊断和`closureEligible`。`view="events"`读取追加历史；原回执不会因后续处置被改成clean。
2. 原料仍在时，用主流程的`re_research_run_ref + supplement_sample_ids + supplement_focus`建立
   新assignment。focus写明目标gapRef与实际问题，要求Worker报告解决范围和新writeReceipt的记录映射。
   `completionScope=supplement`只证明本轮补录；unknown/未定位汇总缺口需要完整新案证据，不能靠局部增益关闭。
   原料保留时可加`re_research_scope="full_case"`完整复核选定案例；必须明确sample IDs并重新读取/审核
   全部要求证据，不能复制旧验收结论。默认仍为supplement，完整复核不要求制造知识改动。
3. 读取`mcp__poe_knowledge__get_research_write_receipt`及其选中记录详情，核对新证据是否真正回答原问题与适用场景；
   通过`mcp__poe_research__submit_research_gap_review`提交稳定`request_id`和当前`expected_revision`，逐gap给出
   `resolved/not_applicable/successor_evidence/reopen`、简短理由及对应新receipt/record IDs。
   修订冲突先重新读取状态；同请求重放复用相同内容，不换ID掩盖失败。
4. 只关闭有证据的具体缺口。工具会核对完整source hash、patch/tree、scope、活动场景及当前精确
   projection；短sourceRef、同一角色、记录存在或created/updated计数都不能替代这些证据。
   支持证据后来失效时，当前缺口重新显示open，关闭历史保留。重新查询有效状态后再判断cleanup。

新组件/候选缺口以安全subject指纹定位；局部闭合必须在匹配的typed记录中证明该项实际resolved，
不能引用仍missing或同一deferred的记录。另一独立缺口可以继续存在。主题/条件已纠正时，完整case
仍须找到原组件的实际resolved证据；旧组件目录仅有序号、缺身份指纹时不猜resolved，也不能用
not_applicable冒充已解决。组件/候选的真实not_applicable需要完整case，coverage使用其
已有typed not_applicable状态。回执的claimBindingStatus与recordLaneEligibility含义不同，不能借同源
兄弟声明证明原精确声明仍有效。

`closureEligible=false`时按原因补证或记录后继研究，不补造旧hash/场景信息。`not_applicable`也需
新证据证明；它不是放弃研究的替代。计数余项不能因为可见条目已处理就被当成不存在。

## 受控在线重取

用户授权重取时，调用`mcp__poe_research__reacquire_research_source(run_ref, sample_id, request_id)`。工具仅重新发现
选定的character-hash，使用当前已核实联盟/版本，新建独立run；旧accepted ledger保留原记录。
成功返回新runRef后，按普通Worker调度。`exact_source`仍需逐gap审查才能闭合；
`successor_snapshot`是新快照，只记录`successor_evidence`，不倒推原案事实已证明。

重复请求先用同一工具`action="status"`检查，不再次启动collector。重取历史由
`mcp__poe_research__get_research_followup_status(view="reacquisitions")`分页读取。已接受并完成收尾的子run会结束
预留；中断但queue已提交时由同一请求恢复关联。确认旧collector停止且子run已清理后，才可
`action="release"`释放占位，再以新request发起重试。身份漂移或`recoveryRequired`先处理诊断，不能
换ID、删除SQLite或抢占预留绕过。状态停留时间本身不授权释放。

`not_found_within_search_scope`只表示本次检索范围未找到，不能声称角色已删除，也不补入其他样本。
旧归档缺characterRef或完整hash时不能反推账号；改用用户提供的新source文件与实际来源版本研究。

## 原料期限与结果

新run默认7天，可在创建时设1–30天；resume/claim不延长原deadline。旧run没有policy时保持
unconfigured，不按文件时间套期限。到期后不再领取新案例，已有有效lease仍可完成研究；新lease最多24小时。

状态查询只显示到期；没有后台模型或定时删除。`retention.expiredCleanupAllowed=true`且没有用户要求
保留的待确认事项时，可调用普通`mcp__poe_research__cleanup_research_run`按锁定策略清理。活动lease、accepting和待
finalization优先保护。清理前保存安全缺口/版本/来源定位与处置审计，删除失败按返回的恢复状态处理。

到期或放弃只结束原料保留，不等于研究完成。清理后仍可用runRef查询归档与缺口历史；
业务成功根据`effectiveResearchCompleteCount`判断，不能用“已清理”或“已接受”代替。
