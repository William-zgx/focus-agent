# Focus Agent 项目定位与现状

更新时间：2026-07-14

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
- 带流式协议、typed SDK、鉴权、Admin、可观测、记忆检索、Agent Team、发布证据链的完整 monorepo
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

相关专题：

- [branch-decisions.md](branch-decisions.md)
- [streaming-contract.md](streaming-contract.md)
- [agent-team-workbench.md](agent-team-workbench.md)
- [agent-team-v2-rollout.md](agent-team-v2-rollout.md)

---

## 3. 当前体量（代码事实） / Scale Snapshot

以下数字来自仓库当前树（约 2026-07-14），用于校准“脚手架” vs “平台”的预期，
不是对外 SLA。

| 维度 | 当前量级 |
|------|----------|
| Python 包版本 | `1.0.0`（`pyproject.toml`） |
| 后端 Python 源文件 | ~560 个（`src/focus_agent/**/*.py`） |
| 后端 Python 行数 | ~12.6 万行 |
| 测试 Python 文件 | ~230 |
| Web 前端 TS/TSX | ~250+（`apps/web/src`） |
| Frontend SDK TS | ~50（`frontend-sdk/src`，另含 generated types） |
| OpenAPI paths / schemas | ~159 paths / ~272 schemas（`docs/api/openapi.json`） |
| 兼容债务 baseline | **169** 项（`docs/compat-debt-baseline.json`） |
| 架构债务 baseline | 非生成文件 **800 行上限**，无 grandfather 大文件 |
| App Postgres schema | **v19**（`SCHEMA_VERSION` in `postgres_schema.py`） |
| CI workflows | `ci`、`browser-smoke`、`eval`、`nightly-regression`、`release-gate`、`agent-team-evidence` 等 |

结论：仓库已超过“周末 demo 脚手架”体量，应按 **中型自托管平台 monorepo** 维护。

---

## 4. 产品面分层 / Product Surfaces

```text
┌─────────────────────────────────────────────────────────────┐
│  Clients                                                     │
│  React Web (/app) · Frontend SDK · Capacitor Android         │
├─────────────────────────────────────────────────────────────┤
│  Product surfaces                                            │
│  Chat + Branch · Agent Team · Governance · Productivity      │
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
| **Collaboration** | Agent Team Mission Runner / v2 schema & flags | 多 Agent 任务需要；v2 默认 flag 关闭 |
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
4. `ChatService` / harness 编排 → LangGraph graph（`engine/graph_builder.py` + `engine/graph/`）
5. Tool runtime、memory、retrieval、trajectory 写入
6. Canonical SSE events → frontend-sdk parser/reducers → Web UI

### 5.2 Branch 控制

- 决策与推荐：`branch_decision/` + [branch-decisions.md](branch-decisions.md)
- 生命周期与 merge：`services/branches/`
- 兼容 re-export：顶层 `services/branch_*.py`、`services/chat_*.py` 等 **shim**（计入 compat baseline）

### 5.3 Agent Team

- 产品与 API：`services/agent_team*`、`api/routers/agent_team.py`、Web `features/agent-team/`
- v2 执行与 schema：Postgres v19 表 + feature flags（见 [agent-team-v2-rollout.md](agent-team-v2-rollout.md)）
- **默认不自动启用 v2 真实执行**；UI 可见 ≠ runtime ready

### 5.4 装配点

`engine/runtime.py` 中的 `create_runtime()` / `AppRuntime` 是后端运行态装配入口，挂载：

- graph / harness / stream bridge / run manager
- branch / branch-decision / agent-team / user / productivity services
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
| 文档与 debt 计量 | 169 项 1.x 兼容债的 telemetry 驱动退场 |

平台完备度 **高于** 结果质量证据；roadmap 以“仍缺的真实环境/规模/证据”描述未来项，
而不是空泛的“继续优化”。

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
4. 兼容 facade 未满足 2.0 exit criteria 前，不得文档宣称已删除。
5. API / Pydantic / SDK 变化必须同步 OpenAPI、generated types 与 contract snapshot。

---

## 9. 相关入口 / Related Entry Points

- 包入口脚本：`focus-agent-api`、`focus-agent-demo`、`focus-agent-migrate-local-state`、
  `focus-agent-memory-embedding`、`focus-agent-retrieval-index`、`focus-agent-trajectory`、
  `focus-agent-prompts`（见 `pyproject.toml`）
- 本地常用：`make help`、`make api`、`make serve-dev`、`make ci`
- 安全：[`SECURITY.md`](../SECURITY.md)
- 贡献：[`CONTRIBUTING.md`](../CONTRIBUTING.md)
