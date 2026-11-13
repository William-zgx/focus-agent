# Agent 论文与开源实践调研（第一轮）

日期：2026-11-12
状态：外部证据与候选实验，**不是已实现能力、实施承诺或上线验收报告**。

## 1. 目标与维护边界

本文件只维护两件事：可核查的一手资料，以及由证据解锁的小实验。

- 当前能力以 [agent-capability-map](../../architecture/agent-capability-map.md) 为准；已有差距与 C01–C07 见 [2026-09-28 调研](../2026-09-28-agent-capabilities/research.md)，不在此重复建设状态表。
- 现有评测、Memory v2、Tool/Skill 和 branch A/B 仍以各自 canonical 文档为准。本文件只补充外部证据和实验 ID，避免形成第二份产品规格。
- C01 恢复、C02 环境验收、C04 预算和 C06 记忆修订的正式设计归 [capability design](../2026-09-28-agent-capabilities/design.md)；merge-back 字段归 [architecture](../../architecture.md)、运行时结果归 [runtime-outcomes](../../runtime-outcomes.md)、发布门禁归 [agent-evaluation](../../agent-evaluation.md) 与 [validation-runbook](../../validation-runbook.md)。此处只写相对这些契约的新增实验，若采纳先更新对应 canonical 契约。
- 优先使用论文原文、官方文档和官方仓库。论文数字只属于其指定模型、任务和版本，不是本项目预期收益；本轮未运行新的外部 benchmark。
- 部分官方页面受域名校验限制，使用官方索引片段或 SDK 源码核验；末段共享 WebSearch 配额耗尽后停止扩展。未核实细节不写成事实。
- 来源只在证据地图登记一次，后续章节用实验 ID 引用，避免同一结论在多处漂移。
- 既有 branch A/B 的当前结论、19.8% token 口径及后续工作直接引用[实验记录](../2026-10-31-branch-ab/status.md)，本文件不另存一份状态快照；本轮未重跑该实验。

## 2. 当前执行取舍

**Now（最多两项）**

1. **AR-ENV-01：一个代码任务的环境 oracle 与独立验收。** 先验证确定性环境证据，不引入新框架。
2. **AR-RECOVER-01：一种普通 run 的 startup hydration/requeue。** 先证明现有 job/lease/receipt 能恢复一条固定路径，不同时改 followup、审批和预算。

**Next（由 Now 的结果解锁）**

- AR-CONTEXT-01：只做 provider token shadow 校准，不改变 compaction 行为。
- AR-TOOL-01：静态工具检索对照，只有离线胜出的方案才进入端到端测试。
- AR-MEM-01：只在 replay overlay 中验证不可变记忆 revision 与反馈效用。
- AR-RECOVER-02：AR-RECOVER-01 成立后的 durable followup / 审批 continuation。

**Later（必须有明确失败证据）**

- 新的 merge 保真失败与增量 packet、持久化 memory revision、统一 turn-preparation/pre-send、fresh-first 子任务修订、只读受控浏览器、observation 重排和一跳关联检索。

## 3. 证据地图

### 3.1 分支、规划与 merge

| ID | 来源与证据边界 | 关联实验 |
| --- | --- | --- |
| BR-01 | [Context Branching](https://arxiv.org/abs/2512.13914)及[实现](https://github.com/glanzz/context-branching)：支持不可变分叉点、隔离与显式注入；实验主要证明减少污染，没有证明自动 merge 更好。 | AR-BRANCH-01/AR-BRANCH-02 |
| BR-02 | [Branch-Solve-Merge](https://aclanthology.org/2024.naacl-long.462/)：merge 也会漏概念，应分别测 solve 和 merge 遗漏。 | AR-BRANCH-01 |
| BR-03 | [Graph of Thoughts](https://arxiv.org/abs/2308.09687)及[实现](https://github.com/spcl/graph-of-thoughts)：聚合可保留多来源边。 | AR-BRANCH-02 |
| BR-04 | [Tree of Thoughts](https://arxiv.org/abs/2305.10601)、[LATS](https://arxiv.org/abs/2310.04406)、[Tree Search for Language Model Agents](https://arxiv.org/abs/2407.01476)：宽度、深度、评价和环境恢复都有成本，不可逆动作不适合自动搜索。 | 全局暂缓 |
| BR-05 | [Scaling Test-Time Compute](https://arxiv.org/abs/2408.03314)与[Self-Consistency](https://arxiv.org/abs/2203.11171)：顺序修订、Best-of-N 是必须保留的强基线，开放文本不能简单多数投票。 | AR-BRANCH-02 |

基线直接使用 [architecture 中的 MergeProposal / merge-back 契约](../../architecture.md)，不另写一套字段定义，也不能使用“扁平 summary”作为被人为削弱的基线。

### 3.2 子代理与持久执行

| ID | 来源与证据边界 | 关联实验 |
| --- | --- | --- |
| DU-01 | [Building effective AI agents](https://www.anthropic.com/engineering/building-effective-agents)：从最简单方案开始；已知 DAG 不需要自由编排，evaluator 只在可测量改善时使用。 | 全局原则 |
| DU-02 | [Towards a Science of Scaling Agent Systems](https://arxiv.org/abs/2512.08296)：协作收益依赖可并行性，顺序和工具密集任务可能承受协调税；不同版本的配置数不同，不写成统一常数。 | AR-MULTI-01 |
| DU-03 | [LangGraph Checkpointers](https://docs.langchain.com/oss/python/langgraph/checkpointers)与[Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)：checkpoint 在 super-step，恢复时受影响节点从头重跑；checkpointer 不是启动调度器或持久 timer。 | AR-RECOVER-01/AR-RECOVER-02 |
| DU-04 | [Temporal Workflow](https://docs.temporal.io/workflow-definition)与[Activity](https://docs.temporal.io/activity-definition)：确定性 replay、Task Queue 和 Timer 共同构成 durable execution；Activity 仍有 at-least-once 风险。 | 全局暂缓 |
| DU-05 | [OpenAI Agents SDK](https://openai.github.io/openai-agents-python/multi_agent/)、[Google ADK resume](https://google.github.io/adk-docs/runtime/resume/)、[LlamaIndex durable workflows](https://developers.llamaindex.ai/python/llamaagents/workflows/durable_workflows/)：恢复绑定原 invocation，未完成步骤可能重跑；agent-as-tool 保留控制权，handoff 暴露更多历史。 | AR-RECOVER-02/AR-MULTI-01 |
| DU-06 | [OpenHands Task Tool Set](https://docs.openhands.dev/sdk/guides/task-tool-set)及[LocalConversation 实现](https://github.com/OpenHands/software-agent-sdk/blob/main/openhands-sdk/openhands/sdk/conversation/impl/local_conversation.py)：文档支持稳定 task ID；对实现的代码审查显示 step 后预算停止不是调用前预留。 | AR-MULTI-01 |
| DU-07 | [Anthropic multi-agent research](https://www.anthropic.com/engineering/multi-agent-research-system)与[context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)：独立上下文适合可并行研究，但不保证总 token 降低，完整子历史不必进入父上下文。 | AR-MULTI-01 |

恢复、审批、副作用和预算的正式约束以 [C01/C04 设计](../2026-09-28-agent-capabilities/design.md) 与 [Runtime Outcomes](../../runtime-outcomes.md) 为准。本文件只新增两个研究风险：审批决策与 worker 执行的所有权混淆，以及 retry attempt 被错误纳入逻辑幂等键；通用未知结果处理直接引用 C01 设计中的副作用与审批协议，不另立规则。

### 3.3 工具、Skill 与浏览器

| ID | 来源与证据边界 | 关联实验 |
| --- | --- | --- |
| TO-01 | [Anthropic Tool Search](https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-search-tool)及[工程文章](https://www.anthropic.com/engineering/advanced-tool-use)：defer 延迟进入模型初始上下文，不等于减少请求体；稳定工具和缓存断点重要。 | AR-TOOL-01 |
| TO-02 | [ToolRet](https://arxiv.org/abs/2503.01763)及[代码/数据](https://github.com/mangopy/tool-retrieval-benchmark)：通用 IR 能力不等于工具检索和执行能力。 | AR-TOOL-01 |
| TO-03 | [ToolSandbox](https://doi.org/10.18653/v1/2025.findings-naacl.65)及[实现](https://github.com/apple/ToolSandbox)：milestone DAG 允许多种成功路径，minefield 检查禁止事件。 | AR-ENV-01 |
| TO-04 | [AgentDojo](https://openreview.net/forum?id=m1YYAQjO3w)及[AgentHarm](https://arxiv.org/abs/2410.09024)：良性效用、攻击下效用和 ASR 不同，全拒绝不是安全。 | AR-ENV-02/AR-EVAL-01 |
| TO-05 | [Agent Skills](https://agentskills.io/specification)与[MCP Tools/安全](https://modelcontextprotocol.io/specification/2026-07-28/server/tools)：渐进披露不是安全边界；annotations 不可信，outputSchema 需客户端验证。 | 仅列为全局 MCP adapter 的差距与候选实验；正式 schema/权限契约若采纳先扩展 [tool-skill-design](../../tool-skill-design.md)，AR-ENV-02 只消费该契约。 |
| TO-06 | [Playwright MCP/Locators](https://playwright.dev/docs/locators)与[WorkArena/BrowserGym](https://proceedings.mlr.press/v235/drouin24a.html)：ARIA 原语、setup/validate/teardown 和后端验收比自报成功可靠；ref 有代次，环境清理影响复现。 | AR-ENV-02 |
| TO-07 | [OpenHands](https://arxiv.org/abs/2407.16741)及[Software Agent SDK](https://github.com/OpenHands/software-agent-sdk)：不可变事件和 append-only log 有利于审计，但不等于副作用可安全重放。 | AR-RECOVER-01/AR-ENV-01 |
| TO-08 | [τ-bench](https://arxiv.org/abs/2406.12045)及[当前 tau2-bench](https://github.com/sierra-research/tau2-bench)：pass@k 与 pass^k 不同；最终状态不保证过程政策，重复试验需要独立 seed。 | AR-EVAL-01 |

### 3.4 上下文、记忆与反馈

| ID | 来源与证据边界 | 关联实验 |
| --- | --- | --- |
| ME-01 | [MemGPT](https://arxiv.org/abs/2310.08560)与[ReadAgent](https://proceedings.mlr.press/v235/lee24c.html)：分层记忆、gist 定位和原文回读有价值，但不等于长期反馈学习。 | AR-OBS-01；[现有非破坏压缩与原文回读](../../context-window.md)无需重复。 |
| ME-02 | [A-MEM](https://arxiv.org/abs/2502.12110)：语义链接和 evolution 在特定 QA 有帮助，但 helper 成本和原地改写风险不能外推。 | AR-MEM-01/AR-MEM-02 |
| ME-03 | [HippoRAG 2](https://arxiv.org/abs/2502.14802)：图关联检索改善特定多跳 QA，同时需要普通事实检索对照。 | AR-LINK-01 |
| ME-04 | [LongLLMLingua](https://aclanthology.org/2024.acl-long.91/)：question-aware 筛选和重排有帮助，但 token 删除会破坏 ID/代码/工具 JSON 并影响缓存。 | AR-OBS-01 |
| ME-05 | [LongMemEval](https://arxiv.org/abs/2410.10813)与[LoCoMo](https://arxiv.org/abs/2402.17753)：大窗口和高 summary recall 都不保证可靠利用，知识更新、时间、拒答和干扰历史需独立测量。 | AR-MEM-01/AR-EVAL-01 |
| ME-06 | [MemoryBench](https://arxiv.org/abs/2510.17281)：多类记忆系统不能稳定优于简单 raw-feedback RAG，反馈入库不保证后续效用。 | AR-MEM-01 |
| ME-07 | [Anthropic Token Counting](https://platform.claude.com/docs/en/build-with-claude/token-counting)与[Compaction](https://platform.claude.com/docs/en/build-with-claude/compaction)：provider count 按具体请求计算，server compaction 是可选能力，不能替代本地防溢出。 | AR-CONTEXT-01/AR-CONTEXT-02 |
| ME-08 | [RAPTOR](https://arxiv.org/abs/2401.18059)：递归摘要树有特定文档 QA 收益，也带来幻觉传播、增量失效和重建成本。 | 全局暂缓 |

### 3.5 评测与评委

| ID | 来源与证据边界 | 关联实验 |
| --- | --- | --- |
| EV-01 | [AgentBench](https://arxiv.org/abs/2308.03688)与[AgentBoard](https://arxiv.org/abs/2401.13178)：progress 适合诊断，但 best-so-far 不等于最终成功，也不惩罚后续破坏。 | AR-EVAL-01 |
| EV-02 | [GAIA](https://arxiv.org/abs/2311.12983)：公开 dev 与私有 test 分离，最终答案稳定，但不评价轨迹且开放证据会变化。 | AR-EVAL-01 |
| EV-03 | [BrowseComp](https://arxiv.org/abs/2504.12516)及[实现](https://github.com/openai/simple-evals/blob/main/browsecomp_eval.py)：搜索后端、预算、采样和 grader 都是成绩的一部分。 | AR-EVAL-01 |
| EV-04 | [SWE-bench Verified](https://openai.com/index/introducing-swe-bench-verified/)及[harness](https://github.com/SWE-bench/SWE-bench)：F2P 验证修复、P2P 防回归，真实测试比补丁相似度可靠。 | AR-ENV-01 |
| EV-05 | [Judging LLM-as-a-Judge](https://arxiv.org/abs/2306.05685)与[Self-preference](https://arxiv.org/abs/2404.13076)：位置、冗长和自我偏好影响评委，双评委或匿名化不能消除偏差。 | AR-EVAL-01 |
| EV-06 | [OpenAI Evals](https://github.com/openai/evals/blob/main/docs/build-eval.md)与[LangSmith 指标实践](https://docs.langchain.com/langsmith/fetch-perf-metrics-experiment)：评委需人工 meta-eval，系统与评委的成本、延迟、错误率分别记录。 | AR-EVAL-01 |
| EV-07 | [MultiAgentBench](https://aclanthology.org/2025.acl-long.421/)：协作过程分不保证任务分，拓扑和 Agent 数没有普遍最优。 | AR-MULTI-01 |

## 4. 实验清单

每项只保留一个主要假设、一个主对照和一个主判定指标；其余指标仅作失败诊断。先复用已有 rollout/replay，采用分阶段晋级，不做臂数 × 重复数 × 双向评委的全组合乘法预算。

| ID/状态 | 假设与最小改动 | 主对照与判定 | 必要护栏 |
| --- | --- | --- | --- |
| **AR-BRANCH-01 / Later** | 只有出现[既有提示词重放](../2026-10-31-branch-ab/status.md)未覆盖的新保真失败模式时，merge-only replay 才值得新增。 | 仅重放当前 MergeProposal，不引入新表示；主指标为新型失败的分阶段保留率。 | 静默无效导入率作为护栏指标，解析失败不得退化为回复片段；不占用 Now 名额，冻结结果供 AR-BRANCH-02 使用。 |
| **AR-RECOVER-01 / Now** | 现有 job/lease/receipt 足以恢复一种普通 run，无需第二平台。 | 当前进程内执行 vs 单 fixed-kind startup hydration；主指标为非终态 run 恢复率。 | 共享验收与未知结果处理沿用 [A1/A2 恢复计划及 C01 设计](../2026-09-28-agent-capabilities/plan.md)；仅在支持幂等/对账的 fake provider 要求每逻辑操作至多一次成功。 |
| **AR-ENV-01 / Now** | 独立环境 oracle/validator 能否减少“模型自报完成”误判。 | 以[现有 EnvironmentJudge assertions](../../agent-evaluation.md) 为基线，增加独立 oracle/validator；主指标为空补丁失败、gold 通过的验收一致性。 | 固定现有 preflight/cleanup 流程，judge 只读；环境无效与 Agent 失败分开；只有出现对应失败证据后才分别改 preflight 或 cleanup。 |
| **AR-CONTEXT-01 / Next** | provider shadow 能比本地估计更准确预测真实输入 token。 | 同一实际请求只做 estimate/provider 双计数，不改变行为；主指标为误差分布和漏报率。 | 记录 count p95、额外 TTFT 和无接口 provider 的显式 estimate；先不改变 compaction。 |
| **AR-TOOL-01 / Next** | 简单离线对照即可判断当前 lexical 是否真的是工具选择瓶颈。 | 静态查询集比较 lexical/BM25/oracle，eager 仅渲染计量；主指标为完整召回与 NDCG。 | eager schema/cache tokens 与执行成功分开；只有离线胜出才跑两组端到端实验。 |
| **AR-MEM-01 / Next** | append-only revision 只有在未见任务上超过 raw-feedback RAG 才值得持久化。 | replay overlay 中比较 memory-only/raw RAG/governed revision；主指标为 held-out 任务成功率。 | 以 [C06 与 Memory v2 的 revision 扩展点](../2026-09-28-agent-capabilities/design.md) 为契约基线；本轮不改生产 schema/API/Zvec，使用未见改写探针和干扰会话，失败即停止。 |
| **AR-RECOVER-02 / Next** | AR-RECOVER-01 的恢复协议可复用于 durable followup 或审批 continuation。 | AR-RECOVER-01 通过后，一次只选 followup 或审批；主指标为重启/异常后的恰好一次受理或续跑。 | 审批与恢复验收直接沿用 [A1/A2 及 C01 设计](../2026-09-28-agent-capabilities/plan.md)，不另列拒绝条件。 |
| **AR-EVAL-01 / Next** | 共享 split manifest 能否保证跨版本回归配对一致，而无需多层重复建集。 | 共享 manifest vs 多层重复建集；主指标为失败完整纳入时的版本配对一致性。 | 映射到 [agent-evaluation 的现有 suites](../../agent-evaluation.md)，不改变 release policy；评委校准与轮换 holdout 只在出现评委不一致或污染证据后另列实验。 |
| **AR-BRANCH-02 / Later** | 若 AR-BRANCH-01 证明现有表示本身丢失来源，增量 claim/source packet 才可能提高保真。 | 当前 MergeProposal vs 在同一 MergeProposal 上做最小增量扩展，复用现有 merge review/apply 协议；主指标为 merge 后来源覆盖率。 | 不另建重复 schema 或第二条合并路径；merge-only 胜出才进入完整 branch并另设隔离不导入臂；冻结复用 AR-BRANCH-01 的 replay 与完整 branch 基线，任务、模型和配置不变时不重跑基线。 |
| **AR-CONTEXT-02 / Later** | 只有 AR-CONTEXT-01 证明 estimate 误差确实影响触发，才值得用 provider count 作为 pre-send 门控。 | 统一 invoke/stream 请求构造作为前置重构，仅比较 estimate-gated vs provider-gated；主指标为溢出率。 | 计数与发送共享最终请求快照；lease、interrupt 和 semantic drift 沿用 [context-window 契约](../../context-window.md)，不叠加 pre-send 开关变量。 |
| **AR-CONTEXT-03 / Later** | 只有 AR-CONTEXT-02 证明门控有效后，才需要比较是否启用 pre-send compaction。 | 在统一请求快照和同一门控下比较启用/不启用 pre-send；主指标为溢出率与 semantic quality。 | 不改变计数策略；冻结复用 AR-CONTEXT-02 的请求快照、轨迹和基线，仅新增启用 pre-send 臂，配置变化才重跑基线；单独归因 TTFT、drift 和 interrupt/lease 冲突。 |
| **AR-MEM-02 / Later** | AR-MEM-01 胜出后才需要持久 revision 和最新 active 索引视图。 | replay overlay vs 持久化最小迁移；主指标为 held-out 效用保持率。 | 持久化规则直接扩展 [C06/C9/C10 设计与验收](../2026-09-28-agent-capabilities/plan.md)，不另立 lifecycle；冻结复用 AR-MEM-01 的 replay 轨迹与基线，配置不变时仅新增持久化臂；旧 revision 泄漏、遗忘复活、错误水合为 0，否则不迁移。 |
| **AR-ENV-02 / Later** | 在既有 B9/C03 浏览器交付边界内，独立 validator 能否比 Agent 自报更可靠地判定真实结果。 | 固定浏览器执行路径，独立 validator vs Agent 自报成功；主指标为后端结果一致率。 | 首个浏览器交付、安全、授权和回读要求直接沿用 [B9/C03 计划](../2026-09-28-agent-capabilities/plan.md)；本实验不比较动作原语。 |
| **AR-ENV-03 / Later** | 只有独立 validator 基线成立后，才比较高层 ARIA 原语与低层浏览器操作。 | 高层 ARIA 原语 vs 低层操作；主指标为任务成功率与误操作率。 | 固定同一 validator 和环境，单独归因导航、重渲染和陈旧 ref。 |
| **AR-MULTI-01 / Later** | 只有最简顺序修订被证明存在历史缺失时，稳定 task ID/子会话恢复才可能有益；预算独立挂在 root execution account。 | 先比较“fresh subtask + 上轮 answer/evidence/verifier feedback”与稳定子会话 revision；主指标为每被接受成果的质量与总成本。 | 不同时引入协作拓扑变更；预算验收沿用 [C04/C05](../2026-09-28-agent-capabilities/plan.md)，只有 fresh 基线明确失败才试验恢复子会话。 |
| **AR-OBS-01 / Later** | 只有 observation 查找失败是主因时，question-aware refs/gists 重排才可能有益。 | 当前顺序 vs question-aware 重排；主指标为最终任务成功率。 | 原文 hash 和 thread scope 不变，随后仍回读原文；总 token、缓存或 TTFT 恶化即停止。 |
| **AR-LINK-01 / Later** | 只有 canonical 多跳检索明确失败时，evidence/link 一跳扩展才可能有益。 | 普通检索 vs 一跳扩展；主指标为多跳回答正确率。 | 单跳任务不得回归，不引入完整 KG/PPR；索引成本或错误扩展过多即停止。 |

## 5. 全局暂缓项

- 不把产品分支改成推理时 MCTS/UCT，不引入自动 rollout、自动 backtracking 或自动 merge。
- 不引入第二套通用编排平台、群聊或更多默认 Agent 角色；Temporal 只作为远期控制面选项。
- 不先做完整 KG/PPR/RAPTOR、dense/hybrid reranker；先证明简单基线的具体失败。
- 不做破坏式 canonical transcript/tool observation token 删除，不用 summary 替代可追溯原文。
- 反馈晋升与 before/after replay 直接沿用 [C07 设计](../2026-09-28-agent-capabilities/design.md)，本文件不另设反馈入库或自动变更规则。
- 不在环境验收、安全代理和独立 validator 之前开放浏览器写操作、真实个人 profile 或更多连接器。
- 不把 provider-specific 能力变成所有模型的默认前提；原生 token count、tool search、compaction 通过可选 adapter 与本地 fallback 共存。

## 6. 后续维护与调研触发

1. 新资料先加入证据地图并注明版本与边界，再链接到实验 ID；不要在多个章节重复决策。
2. 实验出现明确失败、收益平台期或真实生产成本/延迟分布后，开展下一轮定向调研并重新排序。
3. 引入 provider 原生 compaction/tool search、浏览器写操作、原生附件或 durable revision 前，单独核验协议与安全边界。
4. 冻结 anchor 与轮换 holdout 结论不一致时，优先研究评测污染、分布漂移和评委偏差，而不是继续调参。
