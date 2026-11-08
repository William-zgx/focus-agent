# 项目文档校准记录（2026-11-01）

本轮按当前源码、OpenAPI、迁移链和实验结果更新维护文档。文档校准前的代码基线为
`e4e6c22`；该分支已包含分支导入修复 `1c4ed81`，复测使用其等价提交 `f40ec6b`。
本记录说明检查范围与可复核依据，不代表重新完成生产部署验收。
后续运行时删除不改写这份历史审计；已删除模块路径和功能描述仅表示上述基线，
不作为当前能力或有效链接的声明。

## 范围与方法

五个 DeepSeek 执行者并行只读检查 46 份文档：40 份维护文档，以及
`docs/multi_agent_refactor/` 下的 6 份历史材料。检查路径、命令、配置、API、SDK、
事件名、持久化边界及相对链接；每条候选问题给出文档原文、代码依据与最小替换建议。
Lead 对照源码核实后编辑文档，修正了部分建议中遗漏的条件和不准确措辞。

另由 lead 同步根目录中英文 README、路线图、能力地图、当前实验记录和数据集说明。
带日期的旧规划、历史验收报告、冻结任务和评分样例保留原始内容；内置 Skill 指令、
财务 Skill 参考资料及 GitHub 模板不属于本次产品文档事实校准范围。

| 审计组 | 文档数 | 确认问题数 | 主要修正 |
|---|---:|---:|---|
| 入门与开发 | 10 | 18 | 兼容库存 89、SQLite 本地持久化、登录按钮名称、embedding 自动拉取条件 |
| 架构与协议 | 5 | 12 | 实际 graph 入口与节点、任务 API、后台组件名、压缩触发和不存在的 SSE 事件 |
| 记忆与工具 | 6 | 11 | memory usage API、Zvec 优先检索、已实现工具与 Skill 清单 |
| Agent Team、前端与 SDK | 14 | 14 | SQLite Team repository、实际 SDK 方法、rollback 事件、导航开关、先授权后回填 |
| 运维、发布与评测 | 11 | 13 | readiness 条件、OTel/Prometheus 区分、schema v19、Alembic head、生命周期信号与 smoke 数量 |
| 合计 | 46 | 68 | 第一组 18 条已在 `e4e6c22` 校正，其余在本次更新中收口 |

执行者的原始报告在本地 `reports/branch_ab/ds-work/docaudit/{a,b,c,d,e}/`，
未作为仓库文档依赖。关键事实的权威来源如下。

## 权威来源与修改边界

| 主题 | 权威来源 | 文档采用的事实 |
|---|---|---|
| 本地 Agent Team 持久化 | [`runtime_persistence.py`](../../src/focus_agent/engine/runtime_persistence.py)、[`sqlite_agent_team_repository.py`](../../src/focus_agent/repositories/sqlite_agent_team_repository.py) | 无 `DATABASE_URI` 时使用共享 `BRANCH_DB_PATH` 的 SQLite repository |
| 图结构 | [`graph/builder.py`](../../src/focus_agent/engine/graph/builder.py) | `retrieve_memory → context_pipeline → assemble_context`；旧 `graph_builder.py` 是 re-export |
| 线程访问 | [`chat/threads.py`](../../src/focus_agent/services/chat/threads.py) | 先无副作用读取，再 `_ensure_access`，最后回填导入记录 |
| API 与 SDK | [`openapi.json`](../api/openapi.json)、[`admin.ts`](../../frontend-sdk/src/client/admin.ts)、[`stream.ts`](../../frontend-sdk/src/types/stream.ts) | 没有任务单项 GET 或 `refreshAdminSkillConfig()`；包含三类 rollback 事件 |
| 压缩与返回状态 | [`chat/service.py`](../../src/focus_agent/services/chat/service.py)、[`replay_streaming.py`](../../src/focus_agent/api/routers/harness_runs/replay_streaming.py)、[`chat.py`](../../src/focus_agent/api/contract_models/chat.py) | V2 流式路径无发送前压缩、无专用 compaction SSE；内部元数据与公开 thread state 字段分别说明 |
| 监控与 readiness | [`readiness.py`](../../src/focus_agent/api/route_utils/readiness.py)、[`metrics.py`](../../src/focus_agent/api/route_utils/metrics.py)、[`OTel metrics`](../../src/focus_agent/observability/metrics.py) | pending/retrying 不自动等于不就绪；durable worker 检查有配置条件；OTel 指标不能当作 `/metrics` 指标名 |
| 迁移与关闭 | [`migrations/versions`](../../migrations/versions)、[`postgres_schema.py`](../../src/focus_agent/repositories/postgres_schema.py)、[`lifespan.py`](../../src/focus_agent/api/route_utils/lifespan.py) | schema v19；Alembic head 为 `20260713_agent_team_v2_schema`；API 让 Uvicorn 管理进程信号 |
| 工具与 Skill | [`default_tool_modules`](../../src/focus_agent/capabilities/default_tool_modules)、[`builtin skills`](../../src/focus_agent/skills/builtin) | 文档清单只列实际工具和内置 Skill；保留 `run_skill_entrypoint` 残余暴露限制 |

导航说明没有照抄执行者的“全部无条件展示”：管理入口由全局导航渲染，Team 入口还受
`appEnv.features.agentTeam` 控制，Android 默认不展示 Team。压缩说明也没有采用
“公开 thread state 包含 context_compaction”的建议，因为公开契约只提供
`rolling_summary` 和 `context_usage` 等字段。

## 实验证据的同步

当前 [branch_ab 记录](../plans/2026-10-31-branch-ab/status.md)保留修复前基线和提示词对照，
并新增完整复测：192 次运行全部正常，两位评委各 192 条评分成功。DeepSeek 首轮 8 条超时已补齐，原先成功的 184 条评分保持不变。

- Sonnet 总分：线性 3.677、分支 3.552；差 −0.125，任务级 bootstrap 95% CI [−0.333, +0.073]。
- DeepSeek 总分：线性 4.208、分支 4.073；差 −0.135，95% CI [−0.438, +0.156]。两评委通过判定一致率 88.0%。
- 岔路细节召回：线性 0.995、分支 0.979；分支全流程输入 token 少约 19.8%。
- 未检出显著总分差异不能解释为质量等效或非劣，也没有证明分支优于线性。
- 自评偏差、同一集合反复开发、合成文本任务、catalog 工具关闭但仍有残余工具暴露、本地报告未入库均明确列为限制。
- 评委 rubric 条目数可能变化；排除条目数不符的配对后，两位评委的总分区间仍跨 0。冻结正则未改；4 个分支细节未命中项中，3 个为措辞/单位变体，1 个为真实遗漏。

路线图同步为“深化分支主路径、失败驱动、同集回归、行为保持后简化”。已有 B01–B07
基础修复不再列为待建功能；其余平台能力规划保留为候选。兼容库存的描述性 policy/exit criteria
同步为先迁移仓库调用方再删除；出现外部采用方后再增加 telemetry 和迁移窗口。
`max_total`、逐类计数和全部 89 个 item ID 均未调整。

## 本轮验证

- 维护文档的本地链接和 heading anchor 检查：479 个目标均有效，heading anchor 无缺失。
- 仓库、启动、容器、Chat、答案验证、分支导入、eval、ownership 和 compaction 相关回归：**142 passed**。
- Alembic、生命周期、Agent Team readiness/repository、runtime outcome 回归：**47 passed，8 skipped**。
- 兼容库存报告回归：**12 passed**；实际命令片段中的 **54 个 Make target** 均存在。
- `.venv/bin/alembic -c alembic.ini heads`：`20260713_agent_team_v2_schema (head)`。
- `git diff --check`：通过。
- 冻结任务集 SHA-256 保持 `a42e82ecd2ef1eff86a6f6d4ac07420fc85a1a981c33f5f1e28c9b234b351931`。

本次没有新增测试，也没有重复执行真实部署、浏览器交互或整套产品测试。
跳过的测试不计作已验证的数据库环境路径；历史报告继续保留各自的版本和环境边界。
