# Focus Agent 项目定位与现状

更新时间：2026-11-11；整体能力说明承接 `718be87`，本轮按当前源码重新统计体量并校正模块路径。

本文是 Focus Agent **产品定位、体量、适用边界与运行主路径** 的 canonical 文档。
根目录 README 只保留轻量入口；架构细节见 [architecture.md](architecture.md)；
已验证基线与下一阶段见 [roadmap.md](roadmap.md)。

This document is the canonical source for product positioning, scale, fit/non-fit,
and runtime spines. Root READMEs stay lightweight; architecture detail lives in
[architecture.md](architecture.md); verified baseline and next steps live in
[roadmap.md](roadmap.md).

---

## 1. 一句话定位 / One-line Positioning

Focus Agent 是一个 **自托管、branch-aware 的 Agent 工作台与平台参考实现**：
主线程保持可共享进展，探索进入临时分支，结论成熟后再受控 merge 回主线。

Focus Agent is a **self-hosted, branch-aware Agent workbench and platform
reference**: keep the main thread focused, explore in temporary branches, and
merge conclusions only after review.

它 **不是**：

- 托管式 SaaS 产品
- “装上即用的企业 Agent 员工”
- 仅含单页 chat 的最小 LangGraph 模板
- 已证明消费级 PMF 的垂直应用

它 **是**：

- 面向长任务研究 / 调试 / 写作 / 审查的 Web-first 应用平台
- 带流式协议、typed SDK、鉴权、Admin、可观测、记忆检索、发布证据链的 monorepo；部分 runtime 能力仍默认关闭或只提供 preview
- 可被团队 fork 后改造成自有 AI 工作台的参考实现

---

## 2. 核心命题 / Core Thesis

多数 Agent demo 默认“一问一答”。Focus Agent 的假设不同：

| 假设 | 产品含义 |
|------|----------|
| 长任务不是线性的 | 需要可丢弃的探索路径，而不是把所有 detour 塞进一条嘈杂主线程 |
| 主线必须可共享、可审计 | root thread 沉淀结论；child branch 承载临时工作 |
| 分支控制不得静默执行 | pre-turn recommendation 只生成待确认 Branch Action；用户确认后才 fork / navigate |
| 合并必须受控 | merge proposal / adoption review / memory promotion 是一等能力 |
| 运行过程可回放 | trajectory、stream contract、eval 与 release evidence 共同支撑“可验证” |

**证据状态（2026-11-01）。** “分支工作流在长任务上优于线性对话”用配对实验检验：冻结的 32 个任务
（研究 / 调试 / 写作 / 审查，中英各半），同一组用户消息分别跑线性与分支两组，各 3 次，
两位盲评评委（Claude Sonnet 5.5、DeepSeek V4.1 Flash）；DeepSeek 同时是被测模型，Sonnet 提供独立交叉判断。

- 基线（被测模型 DeepSeek V4.1 Flash）：分支组**显著差于**线性组，评委总分差 −0.69 / −0.87（两评委 95% CI 均不含 0），
  岔路里定下的细节召回 0.58 对 0.96；原因是导入结论以 system 通知呈现时模型多半忽略，以及合并门拒绝用户已批准的结论。
- 修复后（导入结论改为用户确认的决定、合并门只拒绝被证据否定的结论）192 次复测均正常完成，两位评委各 192 条评分齐全。Sonnet 总分：线性 3.677、分支 3.552，差 −0.125 [95% CI −0.333, +0.073]；DeepSeek：线性 4.208、分支 4.073，差 −0.135 [−0.438, +0.156]。
- 复测中岔路细节召回为 0.979 对线性组 0.995，分支组全流程输入 token 少约 19.8%。这是 token 用量比较，不能直接换算为账单或延迟收益。
- **当前未证明分支质量更优，也未证明质量等效。** 两位评委总分差的区间均跨过 0，只说明本次评分未检出总体显著差异；尚未设定非劣界值。任务均为合成、文本内给定事实、catalog 工具关闭，结论不能外推到真实工具任务。

方法、数据和逐项数字见 [branch_ab 实验记录](plans/2026-10-31-branch-ab/status.md)。

相关专题：

- [branch-decisions.md](branch-decisions.md)
- [streaming-contract.md](streaming-contract.md)

---

## 3. 当前体量（代码事实） / Scale Snapshot

以下数字来自 **2026-11-11 的仓库快照**，用于校准“脚手架” vs “平台”的预期，
不是对外 SLA。

| 维度 | 量级（2026-11-11 快照） |
|------|----------|
| Python 包版本 | `1.0.0`（`pyproject.toml`） |
| 后端 Python 源文件 | ~453 个（`src/focus_agent/**/*.py`） |
| 后端 Python 行数 | ~10.0 万行 |
| 测试 Python 文件 | ~245（`tests/**/*.py`） |
| Web 前端 TS/TSX | ~225（`apps/web/src`） |
| Frontend SDK TS | ~40（`frontend-sdk/src`，另含 1 个 generated types 文件） |
| OpenAPI paths / schemas | 107 paths / 187 schemas（`docs/api/openapi.json`） |
| 兼容债务 baseline | **43** 项（`docs/compat-debt-baseline.json`，`scripts/compat_report.py`） |
| 架构债务 baseline | 非生成文件 **800 行上限**；生产代码零豁免，13 个既有测试只减不增 |
| App Postgres schema | **v19**（`SCHEMA_VERSION` in `postgres_schema.py`） |
| CI workflows | `ci`、`browser-smoke`、`eval`、`nightly-regression`、`release-gate`、`dependency-drift` |

结论：仓库已超过“周末 demo 脚手架”体量，应按 **中型自托管平台 monorepo** 维护。

---

## 4. 产品面分层 / Product Surfaces

```text
┌─────────────────────────────────────────────────────────────┐
│  Clients                                                     │
│  React Web (/app) · Frontend SDK · Capacitor Android         │
├─────────────────────────────────────────────────────────────┤
│  Product surfaces                                            │
│  Chat + Branch · Agent APIs · Productivity                   │
│  Admin · Observability · Memory console · Auth/Account       │
├─────────────────────────────────────────────────────────────┤
│  Runtime spine                                               │
│  FastAPI · AppRuntime · Harness Runs (V2) · LangGraph graph  │
│  Tool/Skill/Sandbox · Memory · Retrieval (Zvec) · Trajectory │
├─────────────────────────────────────────────────────────────┤
│  Persistence & ops                                           │
│  PostgreSQL (prod canonical) · local SQLite fallback         │
│  Filesystem artifacts · Release gate / evidence / eval       │
└─────────────────────────────────────────────────────────────┘
```

| 层级 | 主要内容 | 默认重要程度 |
|------|----------|--------------|
| **Core** | branch-aware chat、SSE stream contract、typed SDK、鉴权与 owner 边界 | 必选理解 |
| **Platform** | memory、Zvec retrieval、tools/skills/sandbox、Admin、observability/trajectory | 完整工作台需要 |
| **Collaboration** | multi-agent coordination primitives | 由独立配置控制 |
| **Mobile** | Android Capacitor + `android-local-runtime` | 可选；与 server-backed Web 并行 |
| **Release** | release-gate、evidence pack、nightly、eval harness | 生产采用需要 |

Android 与 Web 不是同一集成模型：

- **Web**：默认 HTTP `/v1` + `/v2`，服务端 runtime 权威
- **Android**：SDK local transport + App 内 `android-local-runtime`，单用户设备内 runtime；不假设连接本仓库 HTTP 后端

详见 [android.md](android.md)。

---

## 5. 运行主路径 / Runtime Spines

读代码时优先认清 **权威路径**，避免把兼容 facade 当成实现。

### 5.1 默认聊天（服务端）

1. Client → `POST /v2/threads/{thread_id}/runs` 或 `.../runs/stream`
2. Harness run API（`api/routers/harness_runs/`）做鉴权与 preflight
3. 可选：显式 Branch Action 执行，或 pre-turn branch recommendation → pending action
4. `ChatService` / harness 编排 → v2 LangGraph tool loop（`engine/loop/builder.py`；`engine/graph_builder.py` 为统一入口）
5. Tool runtime、memory、retrieval、trajectory 写入
6. Canonical SSE events → frontend-sdk parser/reducers → Web UI

### 5.2 Branch 控制

- 决策与推荐：`branch_decision/` + [branch-decisions.md](branch-decisions.md)
- 生命周期与 merge：`services/branches/`
- Canonical 实现路径：`services/chat/`、`services/branches/`；顶层 `branch_service.py`、`chat_service.py` 等已删除的 shim 不再作为导入入口

### 5.3 Multi-Agent Coordination

- 保留的 multi-agent coordination primitives 由独立配置控制。

### 5.4 装配点

`engine/runtime.py` 中的 `create_runtime()` / `AppRuntime` 是后端运行态装配入口，挂载：

- graph / harness / stream bridge / run manager
- branch / branch-decision / user / productivity services
- memory pipeline、retrieval index、skill/tool registries
- trajectory、background worker、coordination backend、OTel

`AppRuntime` 字段较多；新增能力应优先走 typed port / 小型 helper，避免路由层直接拼接 runtime 细节。

---

## 6. 谁适合用 / 谁不适合 / Fit And Non-Fit

### 更适合

- 要自托管 AI 工作台，并在意 **审计、回放、发布证据** 的平台/基础架构团队
- 认同 branch / merge 工作流，愿意投入改造成本
- 需要 **typed stream SDK** 与可观测闭环，做产品原型到准生产路径
- 能接受 monorepo 复杂度，并按平台边界分模块维护

### 不太适合

- 只想要最小 LangGraph + 单页 chat 的周末项目
- 期望“装上即企业级 Agent 员工”、无改造即可交付业务
- 没有人专职维护鉴权、Postgres、stream contract 与发布门禁的小团队
- 需要开箱即用的企业 IdP / 多区域高可用（这些仍是采用方集成项）

---

## 7. 诚实边界 / Honest Boundaries

| 已较强 | 仍开放 |
|--------|--------|
| 如何严肃地跑 Agent 应用（协议、权限、持久化、回放、发布门禁） | Agent 任务成功率、成本/延迟画像、多 Agent 结果质量门槛 |
| 本地与 CI 可验证性 | 真实生产控制面绑定（deployment identity 不可伪造） |
| 安全默认与 fail-closed 路径 | 企业 IdP/JWKS、跨服务 logout、长时多实例演练 |
| 文档与 debt 计量 | 43 项兼容库存：先迁移仓库调用方，再删除；出现外部采用方后增加 telemetry 与迁移窗口 |
| 文本聊天、文本 Web search/fetch、路径型文本 artifact | 原生浏览器/DOM/截图、图片附件/多模态输入、通用 artifact 上传下载 |

平台完备度 **高于** 结果质量证据；此外，task budget 合同目前没有接入真实 runner 的
每任务 LLM/tool/cost/deadline enforcement，不能把 budget 字段当作运行时配额。CI 的
真实 Chrome 只证明 Web UI 交互，不证明 Agent 原生 browser 能力。
roadmap 以“仍缺的真实环境/规模/证据”描述未来项，而不是空泛的“继续优化”。

当前能力与未来能力研究、设计、计划分开维护：见
[capability research](plans/2026-09-28-agent-capabilities/research.md)、
[design](plans/2026-09-28-agent-capabilities/design.md) 和
[plan](plans/2026-09-28-agent-capabilities/plan.md)。

---

## 8. 文档地图 / Documentation Map

| 想做什么 | 读什么 |
|----------|--------|
| 5 分钟理解项目 | 本文 + 根 README |
| 本地跑起来 | [quick-start.zh-CN.md](quick-start.zh-CN.md) / [quick-start.md](quick-start.md) |
| 改代码与验证 | [development.zh-CN.md](development.zh-CN.md) / [development.md](development.md) |
| 理解模块与请求链路 | [architecture.md](architecture.md) |
| 看已完成 vs 风险 | [roadmap.md](roadmap.md) |
| 全面验收 | [validation-runbook.md](validation-runbook.md) |
| 全站导航 | [README.md](README.md)（docs 索引） |

维护原则：

1. 同一主题只保留一个 canonical 文档；其他文档摘要 + 跳转。
2. 根 README 不堆操作细节；操作细节进 `docs/`。
3. 宣称“已完成”必须有 contract / test / gate / smoke 之一保护。
4. 兼容 facade 只有在仓库内调用方迁移完成、且已从 `docs/compat-debt-baseline.json` 移除后，文档才可宣称已删除。
5. API / Pydantic / SDK 变化必须同步 OpenAPI、generated types 与 contract snapshot。

---

## 9. 相关入口 / Related Entry Points

- 包入口脚本：`focus-agent`、`focus-agent-api`、`focus-agent-demo`、`focus-agent-migrate-local-state`、
  `focus-agent-memory-embedding`、`focus-agent-retrieval-index`、`focus-agent-trajectory`、
  `focus-agent-prompts`（见 `pyproject.toml`）；除 `focus-agent-api`（`api/cli.py`）和
  `focus-agent-prompts`（`prompts/cli.py`）外，实现都在 `src/focus_agent/cli/`
- 本地常用：`make help`、`make api`、`make serve-dev`、`make ci`
- 安全：[`SECURITY.md`](../SECURITY.md)
- 贡献：[`CONTRIBUTING.md`](../CONTRIBUTING.md)
