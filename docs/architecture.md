# Focus Agent 架构现状

更新时间：2026-04-22

本文描述当前已经落地的工程架构、部署边界和运维观测能力。路线图和后续优先级请看 [roadmap.md](roadmap.md)。

## 1. 项目概览

**Focus Agent** 是一个 Python AI 应用框架，核心能力是分支式对话、流式响应、受控 merge-back、访问控制、React Web App 和 TypeScript SDK。

当前整体形态是 **FastAPI + LangGraph 后端、React + Vite 前端、Postgres primary persistence、本地 fallback persistence**：

- Python 后端：FastAPI、LangGraph、LangChain、Pydantic
- Web App：React 19、Vite、TanStack Router、TanStack Query、Zustand
- SDK：`frontend-sdk` 提供 typed browser / Node client
- 持久化：Postgres primary path；未配置 `DATABASE_URI` 时，本机启动脚本会托管 repo-local PostgreSQL，裸跑二进制时仍可使用本地 fallback
- 测试：pytest 后端/API/运行时测试，前端 SDK 类型检查与构建检查

## 2. 当前架构

```text
FastAPI
├── middleware
│   ├── request id
│   ├── CORS
│   └── sliding-window rate limit
├── API routes
│   ├── /healthz
│   ├── /readyz
│   ├── /metrics
│   ├── /v1/auth/*
│   ├── /v1/conversations/*
│   ├── /v1/chat/*
│   ├── /v1/branches/*
│   ├── /v1/observability/overview
│   └── /v1/observability/trajectory*
├── services
│   ├── ChatService
│   └── BranchService
├── engine
│   ├── LangGraph runtime
│   ├── Plan-Act-Reflect path
│   ├── memory read/write pipeline
│   └── tool runtime metadata
├── repositories
│   ├── Postgres conversation / branch / artifact metadata
│   ├── LangGraph Postgres checkpoint/store
│   └── Postgres trajectory repository
└── web
    ├── React build serving
    └── Vite dev-server redirect in local mode
```

```text
apps/web
├── app/                      shell, routing, providers
├── pages/
│   ├── thread/               chat, branch tree, merge review route
│   └── observability/        trajectory review console
├── features/
│   ├── branch-tree
│   ├── conversations
│   ├── merge-review
│   ├── thread-stream
│   └── trajectory-observability
└── shared/                   SDK provider, UI primitives, query keys, styles
```

## 3. 已落地能力

### 3.1 分支会话与 merge-back

- branch tree、fork、archive、rename、merge review 已接入 Web App 和 SDK
- merged branch 在前后端都按只读处理，不能继续追加 turn 或继续 fork
- branch role 会在第一轮分支交互后刷新，用于区分 execute / verify / deep dive / alternatives 等语义
- imported conclusion 会写回父线程可见状态，并可进入 memory pipeline

### 3.2 Web App 与 SDK

- `/app` 由 React Web App 接管；开发模式可重定向到 Vite dev server
- Web App 覆盖会话列表、聊天、流式响应、分支树、merge review、模型状态、observability overview、trajectory review console
- `frontend-sdk` 覆盖 conversation、thread state、branch action、merge review、trajectory observability 等 typed client 能力
- Vite bundle 分割已配置，React / router / query / state / app 代码分块构建

### 3.3 安全与 API 契约

- CORS、请求 ID、限流和统一错误信封已落地
- 认证默认走 Bearer token，demo token bootstrap 仅适合本地与演示
- 线程和会话操作走 owner / access 检查
- API contract 通过 Pydantic schema、SDK 类型和 API shape 测试保持对齐

### 3.4 持久化

配置 `DATABASE_URI` 后，主运行态数据走 Postgres primary persistence：

- conversation / branch / thread access
- LangGraph checkpoint/store
- artifact metadata
- trajectory turn / step observability tables

artifact 正文仍保留在文件系统，避免把大文件直接塞进数据库。

本机启动命令（`make api`、`make dev`、`make serve-dev`、`make serve-prod`）会在未显式设置 `DATABASE_URI` 时自动托管 repo-local PostgreSQL，并把运行态写入 `.focus_agent/postgres/runtime.env`。直接运行 `.venv/bin/focus-agent-api` 时需要自行设置 `DATABASE_URI`，否则会使用本地 fallback 路径。

历史 `.focus_agent` 状态可通过 `focus-agent-migrate-local-state` 显式迁入 Postgres；服务启动时不会自动迁移历史数据。

### 3.5 Agent 主路径

- Plan-Act-Reflect 已接入主链，并保留退化到 ReAct 的路径
- memory retrieve / extract / write 已接图
- context budget 与长工具观察裁剪已落地
- tool runtime 支持并行安全分组、缓存、fallback metadata 和观察裁剪
- eval framework 支持 rule / LLM / trajectory judge、报告聚合、trajectory replay / promote

记忆系统的完整设计、生命周期、promotion 语义和 memory tools 对齐规则见 [memory-system.md](memory-system.md)。

### 3.6 Observability

当前可观测性分三层：

- 请求层：request id、结构化请求日志、响应耗时、统一错误信封
- 运行态层：`/readyz` runtime readiness、`/metrics` Prometheus 文本指标、build/runtime labels
- agent trajectory 层：Postgres trajectory turn / step 记录、`request_id` / `trace_id` / `root_span_id` correlation 字段、`focus-agent-trajectory` CLI、API overview/list/detail/stats、Web review console、单条 replay / promote 动作预览

Web 入口：

- `/app/observability/overview`
- `/app/observability/trajectory`

API 入口：

- `GET /readyz`
- `GET /metrics`
- `GET /v1/observability/overview`
- `GET /v1/observability/trajectory`
- `GET /v1/observability/trajectory/stats`
- `GET /v1/observability/trajectory/{turn_id}`
- `POST /v1/observability/trajectory/{turn_id}/replay`
- `POST /v1/observability/trajectory/{turn_id}/promote`

`/readyz` 返回 runtime 组件状态、版本、环境和部署名；`/metrics` 输出 `focus_agent_runtime_*` 与 trajectory 聚合指标。trajectory list/stats/overview 支持按 `request_id` 和 `trace_id` 查询，复盘台支持 request/trace URL 深链、production pivots、correlation hooks 和 runtime signal 展示。

当前代码已提供轻量 span facade、运行时 OTel exporter 初始化、tool/runtime span 元数据和稳定 `trace_id` / `root_span_id` correlation handle。只要部署侧安装 OTel 依赖并提供 `OTEL_TRACES_EXPORTER` 与 `OTEL_EXPORTER_OTLP_*` 配置，就可以把 span 送到外部 collector；剩余工作主要是部署环境里的 collector 连通性、告警接入，以及更长时真实浏览器链路回归。

## 4. Docker / Compose 部署与本机启动边界

### 本机开发

- 推荐 `make api`、`make serve`、`make serve-dev`、`make serve-prod`
- 未设置 `DATABASE_URI` 时自动托管 repo-local PostgreSQL
- 前端开发可用 `make web-dev`，并通过 `WEB_APP_DEV_SERVER_URL=http://127.0.0.1:5173/app` 让 `/app` 跳转到 Vite

Docker 本地联调用 [compose.yaml](../compose.yaml)，生产/预发模板用 [compose.prod.yaml](../compose.prod.yaml)。部署、环境变量、demo token 和外部 PostgreSQL 边界集中维护在 [docker-deployment.md](docker-deployment.md)。

## 5. 当前限制

- 限流仍是进程内滑动窗口，不适合多副本共享额度；多副本部署应改用 Redis 等外部限流存储
- trajectory review console 和 overview 已有生产排障入口，但还需要更长时真实浏览器链路、对比/批量治理和告警接入
- context budget 仍以确定性裁剪和近似预算为主，tokenizer 精算与语义压缩仍在路线图中
- Model Routing 尚未接入 planner / executor / reflect 分工

## 6. 推荐验证

日常改动优先使用：

```bash
make ci-test
make web-check
make sdk-check
```

影响前端或 SDK 时补：

```bash
make web-build
make sdk-build
```

影响部署、持久化或 observability 时至少关注：

```bash
uv run pytest \
  tests/test_api_middleware.py \
  tests/test_containerization_scaffold.py \
  tests/test_local_startup_docs.py \
  tests/test_runtime_backend_selection.py \
  tests/test_api_trajectory_observability.py \
  tests/test_api_trajectory_actions.py \
  tests/test_trajectory_cli.py
```

如果本机 `.venv` 的 `psycopg` 缺少 `libpq` 导致测试收集阶段 `ImportError`，可先使用仓库当前测试约定的 stub 路径跑 focused observability 回归：

```bash
PYTHONPATH=/tmp/psycopg_stub .venv/bin/pytest \
  tests/test_api_middleware.py \
  tests/test_metadata.py \
  tests/test_trajectory_observability.py \
  tests/test_api_trajectory_observability.py \
  tests/test_chat_service.py
```

影响主 agent 路径时补：

```bash
uv run pytest \
  tests/eval/test_plan_act_reflect.py \
  tests/eval/test_context_budget.py \
  tests/test_memory_pipeline.py \
  tests/test_tool_runtime.py
```

## 7. 文件导航

- 后端 API：`src/focus_agent/api/main.py`
- 配置：`src/focus_agent/config.py`
- 运行时：`src/focus_agent/engine/runtime.py`
- 图构建：`src/focus_agent/engine/graph_builder.py`
- 分支服务：`src/focus_agent/services/branches.py`
- 聊天服务：`src/focus_agent/services/chat.py`
- Postgres schema：`src/focus_agent/repositories/postgres_schema.py`
- Trajectory repository：`src/focus_agent/repositories/postgres_trajectory_repository.py`
- Web App：`apps/web/src/`
- SDK：`frontend-sdk/src/`

## 8. 文档关系

- 本文：当前架构事实
- [docker-deployment.md](docker-deployment.md)：Docker、本机启动和生产模板边界
- [roadmap.md](roadmap.md)：统一路线图和下一阶段优先级
