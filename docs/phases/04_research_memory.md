# Phase 4 - Researcher 语义记忆

## 当前内容评估进度（2026-09-13，正式工具只读核验）

`research-run:20260909-113411-84d6`的3例现均accepted，接受回执分别为24/34/18条记录，合计76条；
这不是全库唯一记录数或提取质量得分。effectiveComplete=0，3例均needs_followup，共4个open gap。
旧“第三例未接受”和“先定位source_unavailable”属于下文历史状态，不再作为当前待办。

3例各有1个supports覆盖缺口，Poisonburst Arrow另有1个deferred辅助关系缺口。Ice Shot具备补证
关闭资格；Twister与Poisonburst Arrow的原来源身份/provenance不完整，不可直接关闭或补写旧回执。
原料保留期至2026-09-16 03:34 UTC。本次只读核验，未执行补研、接受、关闭或cleanup。

原始聊天已确认9月9日首轮Research实跑、内容问题审计、接受与逐条召回核验已执行；不能因4个gap
仍存在就把这轮工作重新列为未完成。gap属于阶段1B补研遗留项，保留真实状态，不强求旧案全部clean。
完整独立覆盖/泛化与受控增益评估本次未查到完成证据，单独列为后续专项；不扩大首轮完成结论，
也不追溯增加新的退出门槛。剩余专项盘点及S6-01缓存隔离修复已完成，安装与验证状态见Phase 5；
混合长期压力与持久事务崩溃恢复仍单列，不恢复旧Phase7或重生成已有成品。

## 当期内容审计与通用诊断修复（2026-09-09）

冻结已安装插件`0.5.0+codex.20260908182655`后，真实采集3例成功，覆盖三个职业/升华；
本次未复现`source_unavailable`，未为采集器加入过滤特判。来源为0.5.5，PoB/语料仍为0.5.4，
freshness保持`blocked_conflict`。旧Phase7不恢复，本批不生成新BD或声称质量改善。

用户批准后，Twister与Ice Shot两例分别新增24/18条记录、各2条边和1条Family来源证据，
更新历史记录为0。42条均可读回，projection与正式回执逐项一致；39条满足当前Create召回资格，
另3条`sourceStateScope=unknown`的open_question仅供Research诊断，不进入Create必读前提。
两例均`partial_with_deferred / needs_followup`，各1个正式supports覆盖gap保留；Twister原来源
scope不足，gap当前不能关闭。第三例27条提案因自动诊断过长被阻断，未接受；因此本run
accepted=2、claimed=1、effectiveComplete=0，不cleanup，也不把接受安全子集当成整案完成。

本批独立来源清单暴露资源生成/消费/保留方向、Life/Mana支付域、地面与异常条件的历史误用，
以及辅助效果正文缺失、特殊词缀实例投影遗漏。新来源记录明确条件与验证任务，旧知识/旧反向边
仍待正式复核。自动辅助诊断长文问题已在仓库通用修复：只限自然语言预览，完整失败配对及证据
保留，原拒绝与copy-safety不变；5/12配对反例及165项相关回归通过。修复已随
`0.5.0+codex.20260909050959`安装并核验，用户重启后已确认新工具行为。新Worker合法接管第三例，
完整重读9个分区，保存35条新提案、2条边、16组审阅和17条机制审计；旧27条未被当作已验证对象。
全案再次被`full_support_link_like`阻断：完整五辅助包切片可通过，多效果宿主组的自动诊断却在
队列回传中再次被拒绝。无全案ready/净可写数量或completion结论，未接受第三例。

本次工程修复将validate/accept/retry的末端回传限定为已有的durable知识规则，保留完整核心机制
诊断及拒绝状态；queue/control继续严格，raw/角色链接/禁用字段/长文门槛不变。回归使用合成
多效果与不同技能来源，覆盖四类核心机制文本、partial/blocked、accept/retry和原料反例，
不加入升华或技能名称特判；23项新增场景、320项相关回归及132项quick检查通过。
`0.5.0+codex.20260909063203`已安装启用，实际cache的3550个文件、165工具、PoB启动和诊断探针
均核验通过，用户存储与安装前备份一致。当前任务仍须重新加载新版MCP；之后对保留的完整35条
对象重验，lease过期须合法重新领取，不能重放旧token。详见本地审计
`tmp/research-content-20260909/AUDIT.md`及`tmp/release-install-20260909c/INSTALL_REPORT.md`。

## 审查后优化进度（2026-09-06）

### R1–R4修改复审：修复与交叉复验完成

按用户要求，在C1/C2前增加一轮独立复审。五个子agent分域审查后，主agent逐项重新阅读代码、执行
反例并补交叉复现，确认9项（3项P1、6项P2）。这9项现已修复，反例已转正式回归；主agent另核验
并修复交叉审查发现的同类遗漏：status复活空queue、resume dry-run清理旁路、full-case省略目标
却关闭缺口，以及公开search遗漏config-sets枚举。
详细证据与逐项核对见[复审报告](../../tmp/review-r1-r4/REVIEW.md)。

新主题默认并存，跨主题修订通过sourceClaimRevision精确CAS；所有可发布种子版本共用安全检查。
URL入队只解析一次并冻结材料，claim/resume核验完整hash与packet；旧URL不能重新抓取后沿用旧身份。
缺口resolved必须有原组件实际解决证据，旧缺口缺少组件身份时不能借full-case省略目标关闭。
结构提取与数值读回复用活动身份选择器，config-sets明细及响应wrapper纳入预算。
V08影响限定为审计诊断；V09属于保留兼容入口的遗留问题。218项集成回归及quick通过后，已进入
C1/C2；最终全量与计算层验证合并记录在Phase 5本轮验收。以下历史测试计数保留原批次含义。

追加阻断项V10（P1，C1整态回退复验发现）：PoB把customMods多行值直接保存在XML属性内，
通用ET解析将换行折为空格，导致配置视图失真以及不同数值状态的build_state_hash碰撞。
合成Fireball实测原多行为Mana2150/DPS249.667，折为单行为Mana50/DPS124.833，旧hash相同。
R4原始sourceSnapshotHash仍能拒绝跨packet数值绑定，不能把该问题扩大成全部保护失效。
本轮已修复共享PoB语义读取，状态hash与Research配置提取共同保留真实属性值；101项focused
通过，主agent独立复跑36项语义测试及C1/C2整合258项与3个subtest通过；最终full通过2829项与
14个subtest及发布合同；compute全套123项分批覆盖通过，清单无漏项，详见Phase 5最终验收。
受影响旧回执重新查询/验证，不批量重标来源或提升权限。

Skills收敛已先行完成：Controller/Worker减少重复说明，区分运行态与知识工具，产品review合同移除
重复顶层空模板和legacy CLI/文件编辑协议。DSH同步、42项聚焦测试与quick通过；这不代表
学习效果已经验证；知识实现与实际内容效果分别验收。

| 修复包 | 状态 | 范围 |
| --- | --- | --- |
| 1A：R1/R2知识身份与来源修订 | 复审修复与交叉复验完成 | V01/V02/V08正式反例通过；真实库切换和语义整理未执行 |
| 1B：R3a缺口保留与安全清理 | 复审修复与交叉复验完成 | V03/V05/V09及status/resume dry-run旁路已覆盖 |
| 1B：R3b缺口关闭与受控重取 | 复审修复与交叉复验完成 | V03/V04/V05及full-case省略目标反例通过；实际数据补研未执行 |
| 1B：R4配置身份 | 修复与最终验收完成 | V03/V06/V07及多行配置/hash正式回归、full与全套compute通过；详情见Phase 5 |
| K1：召回资格与receipt | 已修复并验收 | 统一coverage、可深读集合及可信分页receipt，旧资格回执须重查；Create深读与决定消费、noncompute/quick通过 |

### K1召回合同修复与知识质量工作（2026-09-08）

Create的覆盖、索引、前提和实际深读共用资格过滤，排除待复核、已被替代、非standard availability
和不支持schema的记录；诊断计数与实际可读集合一致。每页可信回执保存该页coverage，完整页链
合并后执行必读及采用决定检查。`deepRecordEligibilityVersion=1`区分新资格语义，旧raw查询、
旧session及缺coverage的授权回执不得仅补标记恢复。普通Research仍保留待复核诊断读回。

首轮反例为5失败/1通过；修复后的资格、旧会话、旧回执及Create消费聚焦已通过。最终64项聚焦、
noncompute的3126项及静态检查、quick的132项及静态检查通过；主agent固定六维复核完成。
日志与矩阵见`tmp/k1-d1-20260908/`。未改PoB/Lua/optimizer，不重复运行compute；未修改真实
知识库正文、发布种子或已安装插件。

知识质量准备已开始：只读发布种子冻结副本仍为679记录/54Family，来源全为0.5.4。首个
Stormweaver Spark Family默认摘要展开10/12条，按精确ID深读12/12条并核对持久coverage。
已读到资源冲突、换武器条件与Boss失效场景；对“以选中载荷推断其他效果无辅助归属”的表述
登记优先复核任务，尚未判机制错误或修改知识。具体初读与safe record refs见
`tmp/k1-d1-20260908/CONTENT_AUDIT.md`。缺独立原料时不计算完整提取率，也不把旧记录认证为
当期样本。随后同Family的12条知识已在真实Create run内重新深读并落实到95级Spark技术候选，
artifact保存与受管review完成，数值与机制限制见Phase 5。当期来源采样返回source_unavailable，
没有可研究案例，已停止且未计研究成功；当期内容提取质量审计仍未完成。

用户已确认将Research内容质量与真实Create基线前移。K1/D1验收后的首批工作按以下合同执行：

1. 先冻结评估使用的runtime、PoB、图/语料、知识快照、模型与目标场景；新Research只采当期来源，
   历史知识保留版本和targetApplicability。旧Phase7维持6/10暂停，不重跑已比较案例。
2. 内容审计先独立列出来源应解释的输出职责、核心联动、启动/稳态、资源、防御、失败条件和验证
   任务，再对照Research提出、接受和可召回内容。缺原材料时只能评价现有记录的可用性，不能
   声称完整提取率；不以record数量或全部adopted为质量目标。
3. 首批覆盖不同机制与条件的代表性来源，按证据需要确定样本规模和深读范围；不将全库重研、
   全量语义整理或大型评估集作为起步条件。安全的局部机制包保留必要配套，整角色材料不入库。
4. 与Create基线联动追踪“应提取→已提出→安全接受→可召回→实际深读→正确决定→artifact落实”。
   各环节独立计分母，将缺知识、漏召回、误用知识、工具失败和模型缺口分别归因。
5. 按高影响缺口修Research流程、知识组织或Create采用方式，定向补研后用新评估批次复验。
   D4/E1在正式比较统计前完成，未知和证据缺失不得记为质量改善。

### R1/R2既有验收记录

修复前的R1/R2反例现已转为正式回归。实现采用同主题多结论、精确投影共享record、来源声明六列键
及record/hash显式绑定；共享来源修订写时复制，独占旧锚点保留兼容ID。已覆盖写入、召回、Family
整理、typed merge、patch review、发布种子和Create消费，不放宽projection授权。

75项专门回归已通过；最终full通过2163项测试、迁移回放、种子校验、打包、四域MCP及PoB Research
读回smoke（不含重型compute）。schema6发布种子的隔离副本保留679记录、54个Family和
681条声明，全部可精确绑定；修正23条派生缓存（22条安全引用、1条来源计数2→1），不改正文、ID、
版本和projection。迁移审计保存在meta的research_claim_migration_v7_report，只含安全标识及计数。
真实用户库、原发布种子和已安装插件均未由本次修改。新发布输出严格schema7，bundle允许经验证的
旧种子输入，并在用户副本初始化时迁移；这种输入兼容不提升legacy/unknown知识权限。

后续步骤：实际升级在无旧进程写入的受管窗口进行，初始化先备份再迁移，原种子不覆盖用户库；
全库语义整理与实际缺口补研仍分别验收。当前已转入计算工具C1/C2，详见Phase 5。

### 1B本轮边界与验证

R3a修复“安全子集accepted被当作整案完成”的P1问题：接受诊断与知识在同一事务保存；两条恢复与
响应重放使用同一receipt。旧receipt缺诊断时不升级权限，仍存的queue/安全报告缺口单独保留。
默认清理只接收complete；explicit abandon先保存不含原料的审计，清理后原runRef仍可读状态。
accepting必须先恢复；旧延迟清理须重验。Windows连接及时关闭，避免等待GC；锁外初始化避免文件锁
重入。部分删除失败保留精确queue以便重试，不假称已删原料恢复。

R4为配置条目保存身份、活动标志和值类型，Input/Placeholder分开；读回v4绑定来源及PoB实际
skill/item/passive/config组合、sourceRef与精确sourceSnapshotHash。缺失、重复、无效、跨来源或
状态漂移时不提供可采纳数值，legacy单配置保持上游默认语义。真实pinned PoB双配置smoke已验证
不同配置的读数随身份一起变化；未修改Lua或数值引擎。

原R3拆为R3a/R3b实施：R3a先防止不可逆丢失；R3b现已接入逐项关闭、受控重取与期限策略。
保留原始researchCompletion，另算effectiveResearchCompletion；后续关闭不会改写原receipt。
补录clean本身不关闭父案，必须逐gap明确审核并绑定可信新证据。旧来源版本不重标。

R3b当前合同与验收边界：

- `get_research_followup_status`分页返回稳定缺口、追加事件或重取历史；默认页只给重取摘要，
  UTF-8响应超过预算时续页，不静默省略条目。明细抵扣统计数，已完整定位的未解析/未建知识身份问题
  不再重复生成aggregate；真正未定位的余项与unknown继续保留。
- `submit_research_gap_review`以CAS revision和稳定request ID追加处置，核对新receipt的同完整
  sourceHash、版本、场景范围和当前精确record/claim投影。真实sourceHashRef通常只有16位，不能
  从短引用补造64位hash；新接受回执保存服务端sourceContext，旧缺证据不升级权限。支持后来被修订
  或撤销时有效缺口重开，历史关闭事件保留。
- 原quarantine仍可用时支持局部supplement或显式`re_research_scope=full_case`。后者必须明确
  parent与sample IDs，新run完整读取与复核，保留来源/Family身份，可证明真正unknown/aggregate；
  不要求为完成审核制造知识改动。原run期限和receipt均不刷新。
- `reacquire_research_source`按指定character-hash在线重新发现，原子预留绑定parent/sample/
  fingerprint/request/child，禁止超时抢占。仅目标可越过角色去重，不改旧accepted ledger；
  未找到只表示当前检索范围未命中。精确快照与后继快照分开记录，新hash/patch/场景不证明旧案。
  队列与归档恢复逐项核对lineage、完整hash/短ref、league/patch与可信接受receipt；已释放请求不得
  继续collector，同请求并发只产生一份子run。
- 新run创建时锁定默认7天（可选1–30天）原料期限，resume/claim不续期；新claim最多24小时，
  packet与lease期限一致。到期停止新claim，已有有效lease与accepting/finalization优先保护。
  cleanup调用时按期限处置并保留安全审计，不后台运行模型或定时删除；离线期不承诺准点物理清理。
  legacy无policy继续明确处置。删除恢复还重核有效缺口，不能仅凭缓存revision授权。

本轮只实现并隔离验证上述能力；尚未对真实历史库批量补研、执行在线重取、发布或安装插件。
旧归档缺角色定位/完整hash时明确不可定向恢复，需用户提供真实来源材料；没有伪造旧数据缺失证据。
R3b验证完成：348项主要集成回归、quick及两个Skill校验通过；最终全量2470项与14个subtest通过。
初次full的打包后烟测发现旧工具总数162未同步，已改成与打包manifest逐工具比较，并补同数量错工具、
重复声明和域重叠反例；12项相关复验通过。随后完整重跑静态检查及full发布合同，迁移回放、种子校验、
DSH、插件构建、四域MCP和pinned PoB读回全部通过。当前公开工具165个，新工具归research域；
知识schema仍为7，跟进状态使用独立user-data SQLite，不修改发布种子。
日志为tmp/r3b-full.log、tmp/r3b-release-completion.log；没有重复运行重型compute，也没有启动真实
在线研究或更新已安装插件。此处记录修复烟测后的完整验收结果，不把第一次full命令描述为成功退出。

新增85项专项回归通过，覆盖事务回滚/提交后中断、历史诊断保真、缺失计数、清理锁与部分删除，
以及多配置/活动组合/缓存漂移。quick与两个Skill校验通过，DSH已同步。
全量2248项首次运行2247通过，唯一失败是Research bootstrap新增文本超过2400字符；已收敛至2345，
相关MCP/Skills及最终R3回归83项复验通过。随后完成full剩余静态检查、迁移回放、种子校验、打包、
四域MCP和pinned PoB读回检查，全部通过（不含重型compute）。日志为tmp/r34-full.log与
tmp/r34-full-completion.log；此处记录分步完成的验收矩阵，不描述成第一次full命令全部通过。
真实用户库、发布种子与已安装插件不在本轮操作范围。

1A验收：不同条件并存；A/B共享正文后仅修订A，B原正文与lane不变；新结论不虚计B证据；两源再次
收敛可复用内容；跨补丁复核、global/local隔离及分页绑定不退化。Family stable key和来源补丁保持
不变；旧库先在隔离副本做迁移、幂等及回滚验证，不伪造恢复已丢正文。验证按focused→quick及跨范围
noncompute推进；实际数据发布/安装另行验收。

### 1A设计约束：Family稳定，知识可并存，召回不按来源堆叠

本节是设计与验收边界。1A已实现来源/结论分离和exact-content范围的复用；语义同义整理、条件匹配
及完整比较视图仍待后续Agent审核与评估，不把存储修复当成语义整理完成。

**Family不随细微条件扩张。** 维持既有升华与规范化主输出技能集合的身份，以及既有别名/包含关系
处理；条件、正文措辞、来源、补丁、普通辅助及utility变化不能成为新Family键。相似名称不授权合并，
仍需stable key与角色证据；同一BD的副技能误标primary也要作为身份质量问题检查，不能靠扩大Family
定义掩盖。R1/R2新增的是Family内部的来源声明与修订，不是一份来源或一种条件建一个Family。

**分清三种增长。** 来源证据可以随独立样本增长；逻辑知识结论只随新的条件/结论增长；需要Agent
比较的机制方案只随影响采用决定的实质差异增长。正文去重只用于完全一致的内容；语义同义、条件
蕴含或冲突由外部Research Agent阅读后作typed审核，字符串差异、关键词表或向量相似度不能授权
合并、扩大适用范围或改变来源证据权重。

| 差异 | 存储与展示建议 | Create如何使用 |
| --- | --- | --- |
| 同一来源重复提交，内容未变 | 幂等，不重复计证据 | 不产生新决策项 |
| 独立来源支持相同结论/条件 | 保留独立授权；相同正文共享，等价关系经审核后合并展示 | 读一份有来源索引的结论，证据数按独立支持计，不按提及次数计 |
| 数值/措辞有差别，但不改变机制与适用边界 | 保留来源差异，不自动创建机制方案 | 需要精确装备/等级判断时再展开；不能仅凭数值相近判等价 |
| 成立/失败条件不同，例如击杀与无击杀场景 | 同一机制问题下保存条件分支，禁止抹平或取并集泛化 | 与当前目标/状态比对，显示满足、未满足或未知及对应证据 |
| 支付域、触发链或必需组件配套发生实质改变 | 同Family内展示有依赖关系的候选机制方案 | 比较配套、机会成本、失败窗口；跨来源采纳仍需完整crossCase计划 |
| 相同条件下结论相反或当期补丁否定 | 独立保留、显式冲突/失效状态 | 不以多数票或来源数量消除冲突；展示与当前任务相关的反证并验证 |

**召回先给可比较的差异，再做所选方案深读。** Family发现后按伤害投送、资源、防御、轮转等问题
组织“已支持结论及其边界、条件差异、实质方案差异、冲突与未验证项”，每项可追到具体record/source/
content revision。共同观察不自动升级为Family通用规律；代表摘要不能授权未读记录。

条件对照由Agent结合目标等级/补丁、所选职责及活动PoB事实进行：满足时进入采用候选；未满足时说明
需要什么配套改变或为何不适用，不等同永远不可用；未知时列精确查询/PoB验证任务，不能按缺失字段
当作满足。筛选先遵守Family/scope/版本/来源状态权限，再比较适用性、证据和互补差异；不能仅按记录
数量挑选案例，也不能让大量近义记录挤掉少数关键失败证据。

**聚合只改变呈现，不合并授权。** Create继续锁定一条authoritative source lane；代表摘要必须标明
该lane可用的来源声明。其他来源仍是comparison，采纳其完整机制仍走crossCase合同。相同正文的另一
来源回执不能代替本lane深读，也不能写进premise resolution。选中方案的必需机制/失败premise完整
覆盖、完整分页回执与state/version绑定继续保留。来源索引可增长并分页，禁止静默截断。

1A保留精确相同结论的共享record，所以同版本等价来源不增加package。跨版本exact unit已由权威
lane提供时，对照来源挂为comparisonRecordBindings，仍使用权威recordId与深读要求；条件差异及
comparison-only独有包保持各自权限。完整目标排序与语义比较视图仍归后续阶段。

新增验收：同身份多来源/细微条件变化不增加canonical Family数；同源重放不增证据；新增多个等价
来源只增加真实来源支持，不使首层摘要正文和必要设计决策数按来源数线性增长；条件分支和冲突不能
被等价摘要吞掉；只有条件未知时如实保留未知；同Family下不同资源/触发方案不会被拼成无来源的
“全都有效”方案。Family数、逻辑结论数、来源数、决策数分别统计，不用限制入库数量掩盖膨胀。

每次优化或范围调整同步更新本节的状态、原因、验证与未覆盖项，以及首轮审查报告中的同名问题编号。
以下既有“已完成”项描述底座能力，不表示本节后续发现的缺陷已经关闭。

### 1A旧数据处理：保真迁移、分批整理、缺口补研

迁移代码已在隔离副本验证，尚未修改真实知识库或发布种子。2026-09-06只读检查仓库发布种子：679条
schema2/valid记录、679份现存正文、681条来源证据，来源补丁均为0.5.4；613条active_state、66条
state_agnostic，无缺失projection的记录，来源证据均存在匹配的现存projection。这只是当前发布种子的
结构盘点，不是用户本地库盘点，也不能证明过去没有被覆盖、清理或拒绝入库的知识。

| 旧数据情况 | 新方案处理 | 保留的权限边界 |
| --- | --- | --- |
| 正文、来源与指纹完整一致 | 确定性迁移到来源声明/正文绑定；完全相同正文共享 | 保留Family、来源补丁、scope、状态和证据等级，不算新研究 |
| 多来源明确支持同一现存正文 | 拆分独立来源授权，共享正文 | 以后A修订只换A绑定；B授权不随之改变；计数不因拆行重复增加 |
| 近义表述、条件重叠或实质变体 | 保留原声明，由Agent阅读现有净化知识后作typed等价/条件/冲突审核，生成可追溯比较索引 | 不用向量/关键词直接归并，不改原正文凑统一，不将共同观察自动泛化 |
| 旧schema、来源状态未知、指纹缺失/不匹配 | 保留为待复核的历史知识，列出精确缺口 | 不自动补造指纹/状态，不升级Create权限；仅限制有问题的来源声明，不无差别禁用整个Family |
| 正文已覆盖且无可匹配旧版本，或曾拒绝的变体根本未入库 | 从合法备份或已保留安全验收材料核对；有精确匹配才恢复，否则标记不可恢复/待补研 | 哈希不能还原正文，不能把当前A正文复制给B并重写指纹 |

程序迁移只改变结构和索引，不承担语义改写。历史内容的语义整理是对已有知识的复核，不应伪装成
新的成熟BD研究；正常Research仍只研究最新版本。需要新增实证时优先取当前版本对应Family样本，
新来源/新补丁独立存证，历史记录及其来源版本保留。补丁兼容只走追加复核，不批量把0.5.4改成0.5.5。

迁移与验收顺序：

1. 只读盘点待迁库，分类统计可直接迁移、待语义复核、证据缺口、可能不可恢复项；对多来源与历史
   覆盖风险优先抽查。发布种子与local_user分别处理，不能用新版种子覆盖用户库。
2. 建立一致性备份，在隔离副本迁移。保留旧recordId可追溯映射、原正文指纹与patch-review绑定；
   旧ID映射多个新声明时不能静默猜来源，也不能把原review无条件复制到所有新声明。
3. 比较迁移前后Family、来源、正文、条件/失败条件、授权与精确查询结果，验证A/B独立修订、幂等、
   回滚和引用完整性。已知错误证据计数的修正单独报告，不以总行数相等作为无损的唯一证明。
4. 程序正确性通过后，按高召回Family、多来源、资源/Boss/关键失败条件和冲突风险分批做Agent整理；
   审核前保留可用原记录的既有权限，聚合索引只有被审核的结论范围，不能把未审内容标成已合并。
5. 实际切换安排在无活动写入的受管窗口，增加memory revision；旧查询receipt保持原绑定而失效，
   后续Create重新查询，不能篡改回执延续权限。保留迁移报告和备份，schema/内容迁移失败可回滚；
   新版发布种子另走copy-safety/provenance/release校验。

迁移完成只表示旧知识在新结构下保真可用，不表示全部内容经过新一轮语义复核、当期数值认证或
历史缺口已经恢复。三项进度分别记录：结构迁移覆盖率、语义整理覆盖率、缺口补研关闭率。

持续研究积累维护在：

- `docs/research/BD_KNOWLEDGE.md`：成熟 BD 中提取的可复用知识与技巧；
- `docs/research/EXTRACTION_METHOD.md`：每批样本反向总结的深度挖掘方法，后续用于调整本阶段的
  schema、prompt、工具和验收标准。

这两份文档是滚动研究记录，不替代本阶段的正式实现合同。运行态（`/poe-bd-research`）禁止修改
仓库文档（见下方产品化入口），样本知识与方法学的回填由两条通道承担：`poe-bd-research-loop`
的 review/fix 通道把每案修正沉淀到外部 orchestrator 的 `research-notes/`；需要进仓库的通用
知识/方法则在开发态手动回填本文档。`research-notes/` 与这两份文档是不同产物，不再互为替身。
继续遵守单样本 observation、组内 pattern 和跨来源通用规律的证据分层。

当前 0.5.0 深度 memory 采用两层持久化：一次研究先按知识单元保存一组聚焦、安全的
`DeepResearchRecord`，再提炼 fragment/semantic edge/build pattern 作为召回索引。同一案例通过
`research_group_id` 聚合，完整性由记录组共同保证；单条记录不能膨胀成整份案例报告。现有 fragment
schema 不能反向限制 Researcher 分析深度；新维度即使尚未结构化，也应先进入聚焦记录，后续再决定
是否升级为 record kind、typed payload 或索引字段。详细设计见
`docs/research/MEMORY_SYSTEM_DESIGN.md`。

当前实现进度：

- SQLite schema 7、`ResearcherOutput` 4/5 双读与 6 新写、`DeepResearchRecord` schema 1 双读与
  schema 2 新写：已完成；
- 机制主题以 `(knowledge_scope, knowledge_key)` 隔离；identity v2纳入gearSubjects与
  skill/support/host topology，同主题不同结论并存；同源同claim/版本的同批冲突在写入前拒绝：已完成；
- BuildFamily 的可变元数据/evidence 以 `(knowledge_scope, build_family_key)` 隔离；resolver、merge、
  查询统计和 seed 均不得让 Local 改写 Global：已完成；
- evidence 保存 accepted projection hash 与 source state；Create 授权单位固定为
  `(knowledgeScope, sourceCaseRef)`，还必须有同 scope source provenance 与 scoped Family，
  active/state-agnostic 才可用：已完成；
- `create_compact` 使用唯一 retrieval session、单 cursor、固定 memory revision 和 ≤64 KiB page；
  完整 `0..terminal` receipt 链才授权 Create；任意位置单项超限在写 session 前失败：已完成；
- 单案例 acceptance 以 `BEGIN IMMEDIATE` 将 pattern/deep/edge/write receipt/一次 revision 原子提交，
  queue 与 intake ledger 从 receipt 幂等收尾：已完成；
- `propose_deep_research_records` MCP 候选校验工具：已完成；队列研究只由 `accept` 入库；
- `query_research_memory(detail_level=summary|record)` 两级召回：已完成；
- `BuildFamily`（升华 + 核心主/副技能）归类、kind-specific `knowledge_key`、跨 source canonical
  knowledge upsert 和逐来源 evidence：已完成；support、装备、防御和资源方案保留为 Family 内知识；
- 历史 `DeepResearchRecord` 默认 schema1/projection unknown/state unknown，不授权 Create。旧 Family
  backfill 只允许纯 legacy global 集合；存在 schema2 或 local lane 时失败关闭，恢复走 v3
  supplement/revalidation：已完成；
- `/poe-bd-research` Controller、显式 `/poe-bd-research-worker` 单案流程、lease-bound worker brief
  和提交期 review contract：已完成；
- 发布插件的 queue/claim/read/review/accept 产品链路已改为 typed Research MCP：新 run 位于
  user-data `research/runs/<runId>`，对 Agent 只返回 opaque `runRef`；当前项目、源码仓库和插件 cache
  均不承载运行态，Worker 不再用 shell/file tool 修改 queue/review/Research DB；
- Controller 只保留队列/编排；Worker 只保留单案命令顺序和补充边界。16 项强制检查与精确
  schema/枚举由 typed `get_research_review_contract` 从同一事实源渐进披露；CLI `workerPrompt`
  仅为仓库开发兼容传输：已完成；
- Researcher 顺序为“先独立分析当前案例，再查 memory 对照/查重，最后写入”，避免旧经验锚定新
  案例发现：已完成；
- fallback worker 可提交组件名称、角色和 resolver 查询词，由 accept gate 解析并回填稳定 ID：已完成；
- safe review acceptance 对深度记录的 resolver/schema/copy-safety/版本验收，以及“整案至少一条
  具体组件机制记录”的最低深度门槛：已完成；
- 研究队列与 MCP 查询统一使用用户数据目录中的正式 mature-learning SQLite；队列创建时注入应用
  当前 patch/tree 和 PoB 版本枚举，accept 时把缺失/`unknown` 归一为当前值并覆盖 worker 自填值：
  已完成；
- accept/status 按 typed reason 区分 schema、resolver、图源覆盖和提取深度问题：已完成；其中
  `unresolved_jewel_sockets` 覆盖“已分配珠宝槽无珠宝物品且 review 未声明珠宝状态”，
  `tree_data_missing` 不阻塞只提示：已完成；
- `validate_research_review` 复用正式 acceptance 逻辑，返回具体字段路径、提交值与 canonical 枚举，
  且不写 durable memory、不改变 lease；Agent 必须自行修复后再提交完整 safe review 正式 accept：已完成；
- fragment/edge/pattern 继续作为短召回索引：已完成；
- 更多职业样本回放、字段扩展候选和真实生成质量对照：等待后续案例验证。

运行时信息按以下边界维护，压缩重复时不得删除其唯一事实源。工具顺序与 review 约束的执行事实源是
`/poe-bd-research` Controller、`/poe-bd-research-worker` 与 typed review contract；本节只维护运行时
语义边界，不复述命令：

- MCP `ASSISTANT_GUIDE`：保留工具能力地图、选择条件、权威边界和安全边界；
- `/poe-bd-research` skill：只保留用户输入、typed queue/resume、Worker 编排、回访、汇总与 cleanup；
- 未完成 run 默认继续失败关闭；只有用户明确放弃时，cleanup 才可启用 `abandon_incomplete`，按
  run 内 safe identity 精确释放仍为 `queued` 的 intake-ledger 占位并原子删除 runtime；accepted
  ledger 与 Research Memory 永久保留，身份不匹配或删除失败必须回滚；
- `/poe-bd-research-worker` skill：显式专用的一案一 Worker typed-tool 流程，不提供 queue 或用户菜单；
  它继续维护研究质量优先、`nextCursor` 连续分页、案例证据/推断/模型记忆边界、机制校对顺序、
  permission preflight、compact 失败回退和 contract-upgrade 同 lease 分流，传输方式变化不得删弱这些
  业务语义；
- `get_research_review_contract`：在写 artifact 前提供精确 JSON 形状、canonical 枚举及跨字段规则；
  产品响应不再重复返回顶层空对象或文件编码要求，当前review对象由 `initialize_research_review`
  唯一返回，含已有内容的恢复不覆盖；legacy CLI仍保留自己的模板和文件编码协议。
- `initialize_research_review`：返回当前 lease 的内存 safe review 对象，已有对象不覆盖；
- `validate_research_review`：保存并校验调用方提交的完整 safe review，返回可修复错误；
- `accept_research_review`：对相同 lease 下调用方再次提交的完整 safe review 执行正式验收。
- canonical role 表达 BD 功能，通过兼容矩阵与 resolver 的物理 node type 对照；它不是 node type
  alias。生成/兑现、被动转换器和武器职责可以由不同合法实体类型承担，但 stable key 仍必须唯一解析。
- `readyForAccept` 表示安全子集可接收；`fullyResolvedForAccept` 与 `acceptanceMode=clean` 才表示无候选
  暂缓和组件解析缺口。`partial_with_deferred` 先修复当前证据可解决的 role/type/query 问题。
- `unresolvedDeepRecordMentionCount` 统计未解析提及次数，`unresolvedUniqueComponentCount` 统计去重
  组件；兼容字段 `unresolvedDeepRecordComponentCount` 继续表示 mention 次数。
- `createdDeepRecordCount`、`updatedDeepRecordCount` 与 `addedDeepRecordEvidenceCount` 分开报告；
  同一 Family 的同知识再次出现时优先追加证据，不重复制造近义正文。
- Family 身份 = 升华 + 主输出技能**集合**（研究者声明的 `primary_damage` 角色技能，可多个）。
  自动副技能（clear/boss/triggered-payload）、trigger-host（同一 payload 换 host 视为变体）、
   `familyCoreSkillKeys` 一律**不参与身份**，只作 Family 内元数据。技能名按 gem 等价规范化后比较
   （同一宝石授予的弹药/直击变体视为同一技能，见 `skill_equivalence.py`）。
   独特宝石变体（如 `UniqueBreachLightningBoltPlayer`）与普通版共享同一家族身份 token
   （同显示名归一到同一 `gem:` token），这是**有意语义**：同名技能的不同形态是一个 Family，
   其机制差异（cooldown/triggered）由记录层精确 component key 保留，绝不通过拆分身份表达；
   无显示名映射的独特变体（如部分 `UniqueSkillGem*`）保持独立 `key:` token，除非模型确认等价行。
   不得把"加等价行"当作修复——对已确定性归一的变体写行是零行为变化。
   `skill_package` / `mechanic_chain` 记录必须声明至少一个 `primary_damage` 组件；
  身份相同的新研究自动归入既有 Family（不新建 sibling 档案），超集主技能集合会扩展既有 Family
  并合并其记录。schema2 的任何记录只要结构化包含 resolved support，就用 `supportPackages` 把每个
  support 放入来源导出明确给出的根技能 socket package；同技能不同辅助包保持不同知识单元。无图节点的资源方式用
  `resourceMechanisms` 形成轻量身份。
  `unkeyedDeepRecordCount > 0` 时只能报告 partial，不能报告 clean。
- 签名词缀（极端掷骰 "Rolls only the minimum or maximum Damage value"、最低抗性伤害、元素地面
  交互、implicit "Allocates <passive>"、"Grants Skill: Level N"、Surpassing 额外投射、充能保留
  概率词缀）驱动记录因果结论时，必须独立成记录或进入 mechanicAudit，不能只出现在 content 字符串。
- 跨设计轴罕见同现（如混沌伤害节点、荆棘与中毒机会并存）无法闭环时建 `open_question` 记录结构化
  疑点；`modelability_caveat` 只用于“机制存在但 PoB 未建模/未证实”的情况。`read` 输出的
  cross-axis advisory 只作提示，不参与验收 gate。
- Family 归并（2026-08 起）：`scripts/merge_build_families.py` 按集合包含规则全量重构存量档案
  （dry-run → validate → apply，迭代到收敛，apply 前整库备份，合并写 `family_merge_log`；
  回滚 = apply 前快照恢复，日志仅审计）。入库自动归入与合并共用 `_resolve_family_target` /
  `_merge_family_records`；merge 后必须 bump `BUILD_FAMILY_BACKFILL_VERSION` 触发
  `backfill_deep_research_knowledge` 重推 knowledge_key（记录迁移保留原 knowledge_key，
  由 backfill 统一重算 canonical）。**backfill 重推会用新身份公式重建档案，可能与既有档案
  产生同 canonical 重复（同一宝石的不同变体技能 key 不同但等价），因此完整顺序是
  merge → backfill → 再跑一次 merge 收敛**；收敛后用
  `scripts/reconcile_orphan_records.py` 处理孤儿记录（join 挂回 / new 建档 / 无身份降级为
  待复核，expand 不自动执行；可疑身份组用 `--skip-group` 跳过留人工确认）。任何 key
  变更必须先跑 backfill 迁移并覆盖测试，不得静默自动合并身份。
- 已知数据缺口（unique jewels）：语料 unique 表来自 `pob/PathOfBuilding-PoE2/src/Data/Uniques/*.lua`
  的非递归 glob 摄入，存在三个具体缺口：
  1. **PoE2 Time-Lost 系列缺失**——其 unique 条目位于 `Uniques/Special/Generated.lua`
     （Time-Lost Diamond 等），提取器未摄入且 item_type 会是 "Generated"，因此
     `get_unique` / `search_uniques` 拿不到 Time-Lost 文本；
  2. **Historic timeless jewels**（Heroic Tragedy、Undying Hate，base "Timeless Jewel"，PoE2
     条目）被 `relevant_uniques.uniqueJewels` 排除出候选——因为 pinned 引擎的
     "Passives in radius are Conquered" 词缀是空规则（`ModParser.lua` 中 `= { }`），评估无意义；
     该排除依赖引擎实现状态，若未来引擎实现 conquered 规则应移除该过滤；
  3. **Grand Spectrum 变体被 name 去重丢弃**（只保留 Ruby）。
  执行层约束：即使补齐数据，研究提取侧也无法重建可评估的 PoB item text——research packet 只
  保留解析后的词缀摘要（`research_packet._parse_item_text` 丢弃原始文本），Time-Lost Jewel 的
  完整文本只能人工维护。PoB 引擎对 Time-Lost Jewel 的 radius 计算支持完整（词缀
  "Small/Notable Passive Skills in Radius also grant X" 按半径内已分配天赋生效，已实测验证），
  Create 侧用 `evaluate_jewel_socket` 做位置化评估。数据修复需上游 PoB-PoE2 更新
  Uniques/jewel.lua 或人工维护（另开数据维护任务）。
- `source_specific_random` 随机实例知识只解释来源案例，默认不进入 Create 召回或 planner Pattern。
- supports 覆盖要求每个核心技能组有至少两个结构化辅助；passiveAscendancy 覆盖要求升华壳和具体
  `ascendancyResponsibilities`，不能由任意普通 notable/keystone 代替。
- `query_research_memory` 支持 `ascendancy_key` / `primary_skill_key` 精确 Family 身份、
  `build_family_keys` / `record_kinds` 定向读取，并在 `buildFamilies` 返回 `recordKindCounts`；自然语言
  目标只对精确 Family 内记录排序，不会把已有 Family 过滤掉。未使用精确身份参数时仍保留文本、
  组件和 Family 主/副技能兼容召回。

## 状态

Phase 4 基础闭环已完成：项目已经具备把外部 Researcher Agent 提交的
copy-safe、resolver-backed、versioned mature-build knowledge 写入长期记忆和 advisory
semantic graph 的能力。

Phase 4.5 继续维护在本文档内，作为进入 Phase 5 前的补课阶段，目前也已完成产品化收口。
它补的是知识覆盖和提取深度：让系统能从成熟 BD 中抽取升华壳、技能包、关键天赋、暗金、
资源/Spirit、防御层、机制链、阶段切换和失败条件，而不是只存零散技能联动。

用户-facing 入口统一叫 `/poe-bd-research` / `$poe-bd-research`。`phase45` 只作为内部阶段名
和 legacy 兼容名保留，不再作为推荐用户命令。

## Phase 4 已交付

- `ResearcherOutput schema_version=4` 基础合同、strict proposal schema、typed `context_requirements`
  和 structured rejection envelope。
- 当前深度新写使用 `schema_version=6` + record schema 2；schema 4/5 与 record schema 1 继续双读。
- `build_research_packet` transient packet helper：raw PoB code/XML 只允许临时使用，支持
  tempfile 前缀目录、TTL 和清理。
- `query_research_memory`、`propose_research_fragments`、`append_evidence_to_fragment`、
  `propose_semantic_edges`、`propose_build_patterns`、`submit_revalidation_result` 等 MCP /
  service gate。
- SQLite mature-learning schema：clean fragments、fragment evidence、semantic edges、
  build design observations、build patterns、rejected proposals、patch revalidation。
- semantic edge gate：endpoint 必须来自 Phase 3 resolver，proposal 必须携带 resolver
  evidence、typed context、version 和 copy-safety fields。
- patch decay / revalidation：memory item、semantic edge、build pattern 可进入
  `needs_revalidation`，复核后可恢复或产生 successor。

0.5.5 起采用目标版本适用性复核：`inspect_research_patch_review_targets` 分页提供完整安全断言，
`submit_research_patch_review` 追加绑定原指纹、补丁证据及独立 review 的决定。历史来源正文、
版本和状态保留，复核不是新赛季样本。0.5.5 继续召回 0.5.4，目标版本不适用的记录只退出目标
Create 授权，普通 Research 仍可读取诊断。Family identity 跨版本稳定；0.5.5 及之后的
record/evidence key 包含来源 patch，`knowledgeConceptKey` 用于比较同一知识主题。
正常 Research 只研究最新版本 BD，历史知识继续召回。DB schema 7 保留历史record/evidence可追溯身份
作为版本授权绑定，把完全相同的深度知识正文移入不可变 `research_content_revisions`，
以兼容视图保留旧字段、ID 与复核指纹。正文、条件和 typed payload 精确相同才共享；不同条件
独立保存。来源过滤后的正文、Family coverage／premise 与 ExecutionContract 共用去重选择，
当期证据优先；明确 record ID 深读仍保持原记录身份。正文共享不增加独立样本数量。
`scripts/apply_research_patch_reviews.py` 仅供仓库维护，以先完整验证、整库备份、事务应用的方式
导入已完成独立复核的决定；不生成模型结论。发布种子保留绑定有效的 global_seed 审查，并剔除
local_user 与已移除目标的审查，防止安装后丢失已确认的目标版本限制。
语义边冲突检测的逆边、递归起点和每一层路径统一检查目标补丁及树版本；复核为不适用的旧边
只退出目标版本冲突判断，原始记录继续保留。Research packet、PoB 读回和 review contract
共享来源／模型补丁上下文，缺失模型信息保持 unknown，不因读取到数值就提升认证。
- Phase 5 handoff：`build_phase4_architect_research_context.py` 输出 creator-visible、
  planner-visible、copy-safe context，并包含 `usedFragmentIds`、`usedSemanticEdgeIds`、
  `usedPatternIds` 和 verification tasks。

## 语义边回填与每案建边

存量语义边通过 `scripts/backfill_semantic_edges.py` 做确定性 T1 回填，只写以下可证明的
关系形状，且全部走 `propose_semantic_edges`（copy-safety / resolver / 冲突门禁）：

- transition_gate pattern → `requires_transition_gate`（target 优先级：transition_gate role >
  keystone_transformer > unique_enabler > weapon_base）；
- mechanic_chain record → `enables_mechanic`（generator→payoff、unique_enabler→primary_damage/payoff，
  每记录 ≤2）；
- failure_mode record → `creates_failure_risk_for`；
- modelability_caveat record → `has_modelability_caveat`（每记录 ≤3）。

脚本从当前注册物理图快照节点直接构建 resolver evidence；候选生成前先对 DB 做只读一致性
快照副本（运行中的 MCP server 可能并发维护 store），保证单次运行确定性；离线做逆边/短环
预检后分块（25）提交，`ON CONFLICT(edge_id) DO UPDATE` 幂等。单案例 cooccurrence pattern
不提升为边（无跨 Family 证据）。全部回填边为 low/medium 置信度 advisory，使用前需
PoB/Judge 复核。

后续每案研究强制建边：worker brief 强制检查要求每案至少提交 2 条 resolver-backed
semantic edge 写入 safe review 的 `semanticEdges`；acceptance gate（
`run_phase4_deep_review_acceptance.py`）在正式 accept 时通过持久化版
`propose_semantic_edges` 写入，报告 `acceptedSemanticEdgeCount` 并计入 queue case 状态。
无法推导时必须说明原因，不得为凑数发明关系。MCP 的 `propose_semantic_edges` 仍是
validate-only（acceptance 是唯一持久化写入方）。

## 安全边界

- 项目不新增内部 OpenAI / Claude / Gemini provider loop；研究推理由 Codex、Claude Code、
  Gemini 等外部成熟 agent 执行。
- raw mature-build material 只能出现在 quarantine-only transient packet 中，不能进入 durable
  report、state、memory、creator-visible context 或普通聊天输出。
- 禁止持久化或暴露 PoB code、raw XML、raw account/character details、完整 URL、长篇复制攻略文本，
  或把全部装备槽、整棵已分配天赋、全部技能组和完整配置共同保存成第三方整角色镜像。
- 允许完整保存可复用核心机制包，包括关键技能与辅助组合、局部核心天赋连接、暗金/装备与技能、
  天赋、资源系统的联动。不得按辅助数量或局部节点数量机械拒绝。
- 没有 static source，不能创建 physical graph node。
- 没有 resolver-backed physical endpoint，不能创建 semantic edge。
- mature BD semantic edges 和 build patterns 都是 advisory research context，不是 hard
  legality、PoB 数值证明或 reward weight。
- unresolved / ambiguous / source coverage gap endpoint 不能被自动选中；它们应进入 manual
  mapping、static source refresh 或 verification task。

## 产品化入口

研究运行态由 Controller 建立/恢复队列并编排最多 5 个普通 Research subagent。目标宿主总容量为
6 个活动槽位（Controller 1 + Subagent 5）；回访和其他 Subagent 与 Research 共享后 5 个槽位，
超出部分排队。Research 补位优先，回访在当前 run 全部案例结算后再续聊原 agent。等待采用
300 秒事件窗口，无变化心跳最多每 5 分钟一次，超时不反复查询 status。Controller 不领取或
读取案例；每个 subagent 显式加载 `poe-bd-research-worker`，使用同一 opaque runRef，通过 Research
MCP claim 且只处理一案。fork 必须包含用户本轮真实请求/授权；无共享 Research MCP 的宿主在 queue
前失败关闭，不回退主会话研究。
Research 任务连接 `poe_knowledge_mcp` + `poe_research_mcp` 两个按域拆分的 server（工具面约 48 个），
不触发 Codex 数量上限；历史遗留的聚合入口 `poe2-build-mcp`（`server/main.py`）仍注册，仅保留供
测试与旧宿主配置兼容（见 AGENTS.md），产品运行入口是四个按域拆分的 server。
工具未直接显示时应先用宿主标准 tool discovery / tool search 按精确名称查找，再判断是否真的不可用。

`/poe-bd-research` 是会话里的 skill invocation，不是要求用户在 Codex 输入框里执行 shell 命令；
宿主 Agent 应直接调用 Research MCP typed 工具，不运行内部脚本或编辑运行态文件。

**显式意图优先于预检菜单**：用户明确给出案例数量或分析意图（例如“抓 5 个案例来分析”）时，
直接按 `--limit N` 执行完整流程（真实入队、并发 worker 研究、accept），不得推荐或执行 `--dry-run`
预检——预检不产生任何知识，只用于用户无参数且明确想先验证链路时。

Controller 参数/编排事实源是 `poe-bd-research/SKILL.md`，单案工具事实源是
`poe-bd-research-worker/SKILL.md` 与当前 lease 的动态合同。流程骨架：Controller typed queue → Worker
typed claim → inspect/read/search → contract → initialize in-memory review → validate/accept →
Controller status。CLI 只保留仓库开发和 legacy 兼容入口。

`/poe-bd-research` 是产品运行态，不是开发任务。运行期间 agent 不得修改仓库源码、测试、
文档、schema、安装脚本或 plugin manifest；collector / source / runtime 失败时只报告
safe error 并停止。

所有 Research workflow 工具只输出 safe metadata/结构化 evidence。完整 raw-rich material 只保留在
user-data run quarantine 与 lease-bound packet，不进入聊天。Worker 通过有界分页工具读取各分区；
`initialize_research_review` 返回内存对象，Agent 不直接编辑任何运行态文件。`validate_research_review`
保存并校验完整 safe review，`accept_research_review` 对调用方提交的完整 safe review 再次执行正式
验收，是队列研究唯一 durable
write 路径；公开 `propose_*` 仍只验证候选。

产品默认 durable memory 是 `paths.mature_learning_path()` 指向的用户数据数据库，与 MCP
`query_research_memory` 使用同一文件。仓库根的 `phase4_real_research_memory.sqlite` 仅是旧开发脚本
历史路径，不再是 `/poe-bd-research` 默认写入目标。

### 公开知识种子与本地增量

开源分发不依赖中央 Research API，也不直接发布维护者的 mutable 数据库。发布流程从维护者本地库
筛选 `creator_visible + train_context + (global_seed/local_user) + copy_safety_state=passed` 的有效知识，清空
quarantine、来源原材料、查询回执、拒绝提案和维护事件，再生成带 schema、release version 与
SHA-256 的只读 SQLite seed。发布前先运行 `scripts/audit_public_research_memory.py`，该审计只输出
计数、版本覆盖和安全 ID，不输出记录正文。

Git checkout 与 release bundle 都携带 `data/mature_build_learning/release.sqlite`。新用户第一次初始化
且本地数据库不存在时，从已验证 seed 安装；已有数据库绝不覆盖。`local_user` 仍是运行时作用域，
但维护者当前通过安全审计的内容也进入发布种子。Research 运行状态、Judge 快照与最终
artifact 始终只在用户数据目录。中央服务只用于未来明确 opt-in 的投稿、撤回或跨设备同步，不能
成为 Create/Research 的硬依赖。

## 提取目标

Phase 4.5 的 mature BD 设计观察包括：

- 升华 + 主技能：作为 shell suitability，不作为技能合法性；
- 主技能 + secondary skill：标明 clear、boss、generator、payoff、movement、trigger host 等
  role；
- 技能 + key passive / notable / keystone：必须 resolver-backed；
- 暗金 + 天赋点 / 技能：区分 enabling、optional / chase、budget substitute；
- support + active skill：单 pair 可以作为小粒度关系；若多个 supports 共同决定机制行为，允许将完整
  关键组合和技能归属保存在 `supportPackages` 中；
- skill / archetype + scaling axis、weapon/base/stat priority；
- Spirit / reservation package + build shell；
- defense layer package + content goal；
- mechanic chain：generator -> transformer -> payoff；
- transition gate、failure mode、variant relation、modelability caveat。

提取采用两段式：先形成 `BuildDesignObservation`，再把 resolver-backed、copy-safe、证据足够的
部分提升为 semantic edge / cooccurrence pattern / planner hint。单样本只能写
`case_observation`；自然语言范围由外部 Research Agent 在 `claimScopeReview` 中作 typed 语义审核，
后端不维护任何语言关键词/否定词表。跨样本 pattern 必须由样本数、family count、source diversity
和 resolver-backed evidence 支撑，typed `confidenceTier` 永远高于正文措辞；中间置信档的 Agent
审核必须明确是 Family 范围或多 Family 总体范围，不能继续携带 current-case/case-only 审核。

Pattern 的 `component` 作用域表示在 Family 知识之上授予有条件的跨 Family 迁移资格，不是与
Family 归属互斥的低权重分类。它在 `origin_family_keys` 对应 Family 内按 Family 权重召回，在其他
Family 才进入较低权重公用通道。单案 Researcher 只有在候选解决可重复设计问题、具有明确因果链，
并提交适用条件、排除条件、迁移理由和验证任务时，才能将其标成 `component`；单案例不能声明
`global`。后端使用 pattern type、核心稳定组件/职责和适用轴生成确定性
transfer key：同一 Family 的重复来源只增强 Family 内证据，不授权跨 Family 晋升；第二个独立 Family
出现同一结构后才晋升为 `recurring_observation`。公用知识最高为 `likely_pattern`，
`common_within_archetype` / `strong_ranking_hint` 只保留给 Family/Archetype 内排序。

机制校对同样由 Agent 主导：`explain_mechanic` / `lookup_mechanic` 的全文命中只返回候选；Agent 按
精确页面读取有界内容后，在 `mechanicAudit.wiki` 写 `matchKind`、`relevanceReason` 和
`supports/contradicts/silent`。除 unavailable 外，任何内容判断都必须绑定精确页面标题与 pinned
revision；页面身份与 revision 只绑定证据，不代替语义判断。

validate-only 的 Family 回执使用现有库的只读 `join/expand/new` 解析，分别返回 inferred key、resolved
target key 与 relation；正式 accept 在写事务中重新解析。组件 discovery 对 Unicode 重音作 NFKD 折叠，
但 exact resolver、stable key 和 external ID 不放宽。珠宝闭合按活动 passive spec 的逐槽状态区分
filled、empty、socketed-unallocated 与 other-spec，装备珠宝孔不能抵扣树槽。

调试与上下文成本合同：copy-safety 派生错误带安全 originLoc；`--only-record` 同步裁剪关联 audit、
candidate 与 edge；Worker 使用 full 响应做跨案例对照并按 record ID 深读；create_compact 只供
Create 的单 lane 授权。clean
validate/accept 使用 compact 摘要，任何 deferred/unresolved/gap/failure 自动回退完整报告。

实际 skill 保留 `docs/research/EXTRACTION_METHOD.md` 的精简执行版，并带一个脱敏合格机制链示例和
一个浅层反例；worker prompt 不重复整套方法和 schema。没有 resolver 工具时，worker 仍应提交具体组件名称、职责和查询词；
accept gate 负责解析稳定 ID。`skill_package`、`mechanic_chain`、`rotation`、`gear_synergy`、
`passive_package`、资源/防御引擎等具体记录没有可解析组件时会被暂缓；整案只有泛泛属性共现、通用
警告或工具 caveat 时会被拒绝且不写入 durable memory。

`pob_version_or_commit` 保留旧字段名以兼容已有 schema，但新写入语义是应用维护的 PoB 版本枚举，
例如当前 `0.22.0`，不再默认保存 commit。新赛季/新认证 PoB 到来时更新
`data/compatibility/pob.json` 和发布 runtime；来源案例没有声明版本或 worker 提交 `unknown` 时按应用
当前值处理，只有显式提交不在兼容清单中的版本才拒绝。

## Create 精确 Family 召回合同

Family discovery 以 class/ascendancy 为入口；用户指定技能仅作为同时匹配 primary/secondary 的
`related_skill_key`。响应显式区分 `no_family` 与 `known_family_not_authorized`，并返回
`primarySkillKeys/createEligibility`。选中 Family 后的授权查询只用稳定 `buildFamilyKey`。

Family discovery 仍只返回适合比较的轻量摘要。`supportingRecordIds` 不是简单取 evidence 排名前几
条，而是优先覆盖 `mechanic_chain / rotation / resource_engine / failure_mode` 等不同机制职责，
避免高证据的装备记录把关键轮转或失败场景完全挤出候选摘要。

选中 Family 后，Create 查询在固定 memory revision 上建立 actual-content manifest，按单一 cursor
分页；每页最终 UTF-8 JSON 不超过 65,536 bytes。`limit` 只影响候选选择，不代表完整授权；只有
同一 session 的 `0..terminal` 页链才完整。精确 Family 响应还必须返回：

- `familyRecordCoverage`：所选来源和目标版本下合格记录总数、已展开数量、各 record kind 数量和是否完整；
- `requiredDeepReadRecordIds`：从支持包、非 optional 装备职责、资源机制、失败条件和核心机制代表
  记录派生；Create draft 缺读任一项都会失败；
- `familyRecordIndex`：本轮未展开记录的安全索引，包含 ID、类型、标题、摘要和稳定组件 key；
- `familyPremiseCatalog`：`mechanic_chain / rotation / resource_engine / failure_mode` 中的条件与
  失败条件，每项使用稳定 `premiseId`；
- `premiseAuditVersion`：当前前提审计合同版本。

调用方可以先用 coverage/index 发现缺口，再按同一 Family、组件 key、record kind、record ID 或
失败文本继续定向查询；不设置总查询次数或深读条数上限。作为解决方案采用的深度记录必须通过
`detail_level="record"` 真正读过，摘要中只看到 ID 不算采用。

typed query receipt 的 `result_contract` 保存本轮 `familyRecordCoverage`、
`familyPremiseCatalog`、`premiseAuditVersion` 和实际 `deepReadRecordIds`。这样后续 Create 审计
依据的是查询当时的安全快照。分页回执逐页保存本页coverage，完整页链共同覆盖必读义务；
不能只保留目录却丢失可信回执里的义务。运行中memory revision或深读资格版本改变须重查，
不改写已经完成运行的历史证据。

## Legacy 兼容

旧脚本 `scripts/run_phase45_researcher_batch.py` 和
`scripts/phase45_accept_single_review.py` 仅作为兼容 wrapper 保留。它们会向 `stderr` 输出
deprecation warning，`stdout` 保持机器可读，避免污染 JSON。公共 README、MCP guide 和 skill
不再推荐这些旧命令。

之前程序化写入的 30 条浅层 `case_observation` 保留审计记录，但不作为 Deep Researcher 结果：
它们应保持 `needs_revalidation` / `planner_visible=0`，不进入 Phase 5 默认 handoff。

## 验收

Phase 4 已完成工程链路；Phase 4.5 已完成产品化入口收口：用户可以用一个产品入口启动
批量队列，在本地外部 agent 环境中逐案例完成 deep Researcher 提取，并通过 MCP/service
gates 写入 durable memory。

Focused 验证：

```powershell
.\.tools\uv\uv.exe run pytest tests/test_research_mature_builds.py tests/test_research_productization_docs.py -q
.\.tools\uv\uv.exe run pytest tests/test_research_prompt.py tests/test_research_memory.py -q
```

阶段级验证：

```powershell
.\scripts\verify.ps1 quick
```

### 研究上下文传输真实验收（2026-07-15）

使用独立验收目录从当前 poe.ninja 来源串行研究两条 100 级 Witch 案例。两案均通过
`claim -> inspect -> read/search -> safe review -> accept`，未通过 prompt 或终端输出 raw XML、
PoB code 或临时路径。

- Abyssal Lich 案：`skills=13`、`gear=15`、`passives=159`、`config=17`、`build=1`；按默认
  `limit=20` 分别读取 2、1、8、1、1 页，全部 `complete=true`，无遗漏或重复。最终接受 6 条
  深度记录、3 条 observation、3 条 pattern，五个覆盖维度全部 `covered`。
- Blood Mage 案：`skills=12`、`gear=15`、`passives=136`、`config=17`、`build=1`；分别读取
  2、1、7、1、1 页，全部 `complete=true`，无遗漏或重复。校准后接受 7 条深度记录、3 条
  observation、3 条 pattern，五个覆盖维度全部 `covered`，无 deferred 或未解析组件。
- 两案分页响应的最大字符数约为 11.3K，低于 12K 目标。导入标签 `Blasphemy` / `Spellslinger`
  未遮蔽实际多技能组；研究结果恢复了触发宿主、载荷、supports、装备职责、核心天赋、轮转和资源防御。
- Acceptance 报告计数与独立验收数据库实际行数逐项一致。公开 `propose_*` 返回
  `validationOnly=true` 且不返回 durable ID；只有 `accept` 写入 durable memory。

### 组件发现与图解析边界

- `search_graph_components` 用具体名称、预期节点类型做有界候选发现；后续可替换或补充向量召回。
- `resolve_graph_component` 只负责稳定 ID、名称、别名或已发现 stable key 的最终确认。
- `DeepResearchRecord` 可保存未唯一解析的 `component_mentions`，包括名称、角色、查询提示、预期类型和
  解析状态；解析失败不等于研究内容无效。
- `BuildPattern` 和 semantic edge 仍要求稳定端点。词法或向量相似度只能用于发现候选，不能自动写图。
- 声明类型下找不到组件时，acceptance 会做一次不限类型诊断。唯一同名组件若存在于其他节点类型，
  返回 `component_type_mismatch` 和建议角色；只有所有类型都找不到时才是 `source_coverage_gap`。
- 不限类型诊断优先完全同名候选，再考虑包含词匹配，避免 `Critical Strike` 被
  `Ballista Critical Strike` 等相关名称掩盖。功能 role 与该物理类型兼容时直接保留原功能角色，不要求
  Agent 把 `payoff` 机械改写成 `passive_anchor`。
- safe review 使用 UTF-8、两空格缩进的多行 JSON，保证 validate-only 后能对单个 role、query 或 key
  做有界修复；压缩单行不是安全失败，但不符合运行合同。

### 研究执行 checklist（2026-08-07 修订，防再犯）

以下条目已收口到 `RESEARCH_MANDATORY_CHECKS` 的 16 项中文单一事实源；workerPrompt 按该 tuple
动态编号，review-contract 以 JSON list 返回同一内容。Controller/Worker Skill 不再保存另一份清单。
本段只保留为阶段审查记录；执行时以当前 lease 的运行时合同为准。

以下条目来自真实案例审查（Monk/Martial Artist Hollow Palm 案例的补齐与修正），每个 deep
case 研究都应执行：

1. **Memory 对照必须用 stable key**：查询前先 `search_graph_components` +
   `resolve_graph_component` 解析 packet 的 ascendancy 与 class，再用
   `ascendancy:monk:martial_artist` / `class:monk` 形式过滤 `query_research_memory`；
   显示名（Martial Artist / Monk）不会命中存储 key，会静默返回空。必须检查返回的
   `familyRecordCoverage` / `familyRecordIndex` / `familyPremiseCatalog` 并逐条对照既有
   同升华/同技能 Family 知识（生成/消费角色、充能链、Combo 独立性等），避免重复或方向错误。
2. **Config 条件三栏检查表**：把 packet 每个 `condition*`（EnemyChilled / EnemyBleeding /
   EnemyBlinded / EnemyIgnited / CritRecently / BeenHitRecently / usePowerCharges 等）列成
   "条件 → 来源组件 → 验证状态"；无来源的假设（例如无点火来源却启用 Ignited）必须写成
   modelability caveat，不得静默采纳。
3. **装备全覆盖盘点**：14/14 件装备逐一在 records 中出现（结构化组件 / content 文本 /
   显式 not_applicable 三选一）；写 review 前成表自查，避免装备信息零命中。
4. **禁止猜 key 路径**：所有组件先 `search_graph_components` 再 `resolve_graph_component`；
   支持宝石的 metadata 路径可能有 `Items/Gem` 与 `Items/Gems` 两种形式，猜错会被判
   component_type_mismatch 或 missing。
5. **silent / unavailable 不丢结论**：Agent 阅读机制候选后判断为 silent，或工具返回 unavailable，直接以
   样本证据与引擎读回为准写入记录；不需要因 wiki silent 额外标注 caveat 或 verification task
   （wiki 佐证不是要求，论坛 BD 多数机制没有对应 wiki 页面）。
6. **所有启用技能组都要盘点**：每组写 `sourceSkillGroupReviews` 的 research/support disposition、
   affected record 与原因。Family 主技能、核心副技能以及结论依赖组用 `supportPackages` 的
   `sourceGroupRef + rootSkillRef` 保存精确根技能插槽关系，并让每个 `supportKey` 对应同序的
   `socketedItemRef`。不同根技能下的同类辅助以不同物理实例 ref 消歧；同一实例不得重复归属。
   这些 source-local refs 验收后丢弃，durable identity 仍只包含根技能与 support stable keys。
   新 review 的 `deliveryRole` 固定为 `direct`；socketed payload 的 host/payload 机制单独记录。
   低影响/internal-id 组可明确 `not_relevant` 或
   `source_has_no_supports`，但 `needs_followup/source_coverage_gap` 必须保持 partial，不能 clean。
7. **因果方向自查**：每个 resource_engine / mechanic_chain 写前核对生成 vs 消费方向（Rend 是
   Power Charge 消费者而非生成器）；与既有同组件 Family 记录对照。
8. **未解析组件逐个 search**：任何 unresolved 计数出现时，先对该组件名执行一次
   `search_graph_components` 再定性为 source gap（Nascent Hope 案例：图中实际存在
   `unique:pob:nascent_hope`，未 search 导致误报 gap）。

### 存量修正通道

Research Memory 的 durable writer 只有 accept。修正既有记录两条路径：

- **同 case 补录（新 research run + accept）**：用与最初完全相同的 PoB 文本重新 queue
  （sampleId/sourceHashRef 相同 → researchGroupId 相同）；产品工具使用
  `start_research_run(re_research_run_ref=..., supplement_sample_ids=[...], supplement_focus=...)`：
  优先只从旧 run 的 quarantine 重建获批 sampleId；省略 `supplement_sample_ids` 才重建全部案例。
  空、未知、未 accepted 或 quarantine 不可恢复的定向集合在新 run 创建前失败关闭。补充研究轮
  使用本地来源路径，绕过 already-studied
  跳过，case 标记 `supplement=true`，accept 要求 created+updated ≥ 1，否则判定补充轮无效
  不消耗验收）。补录记录保持旧记录的
  `title / recordKind / researchGroupId / source_case_refs` 不变时，`_persist_deep_record`
  会命中 `_existing_deep_record_id` 并原地 UPDATE 覆盖（`updatedDeepRecordCount` 计数）；
  knowledge identity 变化（`knowledge_key` 改变）时同一 UPDATE 会清理旧 key 的孤儿
  evidence，不产生双记录。`familyCoreSkillKeys` 修正只更新 Family secondary 元数据与相关记录
  内容，不改变由升华 + primary 技能集合生成的 Family key，也不会制造旧 Family 空壳。
- **维护脚本**：`server/knowledge/research_maintenance.py` 提供
  `calibrate_research_contract_v1`（按 source_ref spec 重建记录 + 旧记录
  `deprecated + superseded_by_id` + force backfill，带 backup 与原子事务），以及
  `remove_exclusive_research_sources` / `cleanup_legacy_research_memory`；CLI 入口
`scripts/calibrate_phase4_research_contract.py`。适合批量确定性修正（装备职责、support
归属、availability 标记），不适合需要重新推理的方向性修正。

需要重新推理的 deep-record 合并使用 `ResearchMergePlan v1`：模型先提出逐字段方案，独立 reviewer
复核，服务返回有界召回/evidence preview，用户批准后才按 Memory revision + plan hash CAS 写入。
代码不得按标题、embedding 或组件共现自动决定合并。Reviewer 对陌生、版本敏感或冲突机制必须联网
查 GGG、pinned PoB 或固定 revision Wiki；无法得到权威结论时保持 distinct。普通 partial case 仍按
记录粒度入库：有效记录可召回，失败 proposal 被 deferred，安全 open question/gap 可保留，不能因一颗
错误辅助禁用整个案例。

### 2026-08-07 修正记录（Tempest Flurry Hollow Palm 案例）

- 新 research run（同 source）重放 11 条记录，全部原地 UPDATE（updatedDeepRecordCount=11，
  createdDeepRecordCount=0），acceptanceMode=clean，unresolved 归零。
- 修正：Rend 从充能生成器改为消费者（payoff，ConsumesCharges→闪电 buff）；familyCoreSkillKeys
  移除 WyvernRendPlayer；Nascent Hope 解析为 `unique:pob:nascent_hope` 并结构化；7 件装备
  （Dread Curtain / Anarchy Spark / Demon Salvation / 生命瓶 / 2 魅力 / Golem Urge）补录进
  content；config 条件缺口（Ignited/Bleeding/Blinded）与 Innervate 补进 modelability caveat；
  Spirit 总预算补进暴击敲钟记录的 failureConditions；Overabundance I 的 key 修正为
  `support:Metadata/Items/Gems/SupportGemOverabundance`（复数 Gems）。
