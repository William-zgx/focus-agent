# Agent 能力补全调研

日期：2026-09-28；源码基线：`718be87`。状态：调研结论，**不是已实现能力或上线验收报告**。

现状入口：[能力地图](../../architecture/agent-capability-map.md)。后续阅读：[设计草案](design.md) → [实施规划](plan.md)。

## 1. 目标与方法

回答：在现有 Focus Agent 上，哪些补全最能提高真实任务完成率，而不是增加模块数量？

- 对照源码中的运行入口、默认配置、调用接线与持久化边界，不从类名、数据库表或 UI 可见性推断端到端可用。
- 外部参考限于可核查的一手工程资料和研究；以下是截至调研日选取的资料，不声称穷尽所有最新进展。
- 区分代码事实、已有测试入口、曾经的验证记录和本轮实际验证。本轮是文档校准，没有运行真实模型或生产故障演练。
- 保留现有 LangGraph/harness、任务仓储、Skill/工具策略和 eval 能力；不以外部产品架构为由重写。

## 2. 外部进展与适用判断

| 资料 | 可借鉴的结论 | 对本项目的建议 | 不直接照搬的部分 |
| --- | --- | --- | --- |
| [Anthropic：Scaling Managed Agents](https://www.anthropic.com/engineering/managed-agents)，2026-04-08 | 将持久会话事件、执行循环和执行环境分离，允许执行器失败后重建；凭据不暴露给生成代码所在环境 | 复用 journal/checkpoint/job，使任务恢复不依赖原进程；连接凭据由受控工具适配器持有 | 不要求现在拆成多个微服务，也不引入另一套 harness |
| [Anthropic：Harness design for long-running application development](https://www.anthropic.com/engineering/harness-design-long-running-apps)，2026-03-24 | 用可操作的完成标准与实际环境检查约束交付；模型能力变化后应重新评估额外规划/审查的价值 | 先补测试、页面、数据回读等验收证据，再决定是否需要独立模型评审 | 不默认给每个任务配置 planner/generator/evaluator 三角色 |
| [Google Research：When and why agent systems work](https://research.google/blog/towards-a-science-of-scaling-agent-systems-when-and-why-agent-systems-work/)，2026-01-28 | 在其受控任务与预算条件下，多 Agent 的收益取决于任务可并行性和协调方式，顺序任务可能受损 | 建立单 Agent 对照；仅对独立子任务启用协作，并衡量整合成本 | 不将研究中的收益比例外推为 Focus Agent 的预期收益 |
| [LangChain：Evaluating AI Agents at the Run, Trace, and Thread Level](https://www.langchain.com/resources/agent-evals)，2026-06-23 | 评测需要同时覆盖单次输出、工具轨迹和完整多轮任务 | 将现有 trajectory/replay 与任务级反馈、环境断言关联 | 不要求采购平台，也不让模型评分代替环境状态 |

这些资料支持的是设计方向，不是本项目的测试结果。多 Agent 的启用策略、连接器优先级、质量阈值仍需本项目任务数据决定。

## 3. 源码差距矩阵

| ID | 已有基础与源码入口 | 尚未闭合的能力 | 最小研究结论 |
| --- | --- | --- | --- |
| C01 持久任务 | [RunManager](../../../src/focus_agent/harness/runtime/runs.py)、[follow-up](../../../src/focus_agent/harness/runtime/run_followups.py)、[通用 background job 后端](../../../src/focus_agent/services/coordination_postgres.py)、[v19 Team jobs/leases/receipts](../../../src/focus_agent/repositories/postgres_schema.py) | 普通 run 的内存执行器不能仅靠 journal 元数据在重启后自动重建；follow-up 自动消费未在普通工厂接通；[审批 readiness](../../../src/focus_agent/services/agent_team_readiness.py) 明确不自动续跑 | 区分通用 background job 与要求 Team session/task 的 v19 job；先选一条路径接通恢复，不直接混用两套表 |
| C02 结果验收 | [execution contract](../../../src/focus_agent/engine/graph_execution_contract.py)、evidence ledger、task ledger、Critic | 当前契约验证主要针对 live-web/Skill；其他任务不具有通用环境验收 | 将“模型结束回答”与“用户目标被验证完成”分开 |
| C03 工具与交付 | [默认工具工厂](../../../src/focus_agent/capabilities/default_tool_modules/factory.py)、[工具策略](../../../src/focus_agent/capabilities/tool_router.py)、[聊天输入](../../../src/focus_agent/api/contract_models/chat.py) | 原生浏览器、图片/附件输入、用户授权的外部连接与通用成果交付未形成完整产品链路；[MCP 管理仍预留](../../tool-skill-design.md) | 首先打通一个实际浏览器验收或业务连接器场景；shell 间接操作不等于原生产品集成 |
| C04 任务预算 | [AgentBudget](../../../src/focus_agent/delegation/delegation_models.py) 已声明次数/费用等字段 | [real execution](../../../src/focus_agent/services/agent_team_real_execution.py) 主要传全局轮数，未把声明的任务预算完整传到模型/工具边界 | 在真实调用点扣预算，而不是只增加配置和 UI |
| C05 协作返工 | DAG、隔离任务、证据、revision 表和多 Agent 配置 | 默认执行受 flag/observe 限制；[revision commands](../../../src/focus_agent/services/agent_team/run.py) 明确不可用 | 跑通执行—整合—针对性返工，再通过同任务对照决定协作策略 |
| C06 可纠错记忆 | [MemoryRecord](../../../src/focus_agent/memory/models.py) 已有 evidence_refs、来源线程、namespace、删除状态 | [合并](../../../src/focus_agent/memory/dedupe.py) 覆盖同一记录，缺少不可变内容修订历史；有审计不等于能还原旧值 | 给重要规则/偏好补来源和可撤销修订，不先构建通用知识图谱 |
| C07 反馈改进 | trajectory、候选样例、[replay/promotion](../../agent-evaluation.md) | [反馈 API](../../../src/focus_agent/api/routers/agent_governance.py) 主要针对 Skill selection，未贯通任务失败到回归验证 | 将负反馈变成可审查的失败用例，不自动将单次反馈写成线上规则 |

## 4. 可靠性前置条件

上一阶段审查还识别了授权前回填写入、退出信号、readiness、环境断言、eval 验收/成本、只读 UI/handoff、SDK 构建顺序和部署恢复方面的问题。它们不是新的 Agent 功能，但会使“可恢复”“已验证”“安全执行”的承诺失真。

[实施规划](plan.md) 以 B01–B08 单独跟踪其验收；本轮仅记录与校准文档，不将问题描述写成已经修复，也不将某次部署的观察推广为所有部署的事实。

## 5. 取舍

优先顺序：可靠交付（C01/C02/C04）→ 实际操作与交付（C03）→ 可测量的长期改进（C05/C06/C07）。

- 不新增一套通用任务框架；普通 run 优先接现有 `focus_background_jobs` 后端和 checkpoint，Team 任务沿用有 session/task 归属的 v19 jobs、lease 和 side-effect receipt。它们不是可直接互换的同一张任务表。
- 不默认将所有功能开关打开；有代码、配置打开和端到端可用是三个不同条件。
- 不要求每个任务都调用 Critic；确定性检查优先，模型评审用于真实需要判断的部分。
- 不把 token 上下文压缩等同于目标保持。恢复时应检查目标、约束、未完成项和证据引用，但不另建平行聊天历史。
- 不承诺任意外部写操作 exactly-once；不确定是否成功的副作用需要查询、核对或人工处理。
- 不将“可追溯”解释为永久保留用户要求删除的数据；记忆修订要服从明确的保留和删除政策。

## 6. 尚待产品选择

1. C03 首个用例选择开发页面验收，还是企业业务连接器？设计保留两种入口，不同时实施两套平台。
2. 首个可恢复运行剖面建议限定 PostgreSQL；SQLite 是否需要同等级后台恢复，取决于实际使用场景。
3. 任务费用预算的价格来源和未知用量处理策略需要明确；未知成本不得算作零成本成功。
4. 记忆历史保留范围和期限需要确定，之后才决定修订存储与删除策略。

这些选择不阻塞本轮文档交付，但应在对应实施任务开始前确认。
