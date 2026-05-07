# Docker 部署方案

更新时间：2026-05-05

这份文档定义当前仓库推荐的 Docker 部署方式。目标是把 **本机开发启动链**、**本地容器联调**、以及 **生产部署** 明确分层，避免把开发便利逻辑和正式部署逻辑混在一起。

```mermaid
flowchart LR
    Dev["Local make commands"] --> LocalPG["Managed repo-local PostgreSQL"]
    Compose["compose.yaml"] --> App["focus-agent container"]
    Compose --> PG["postgres service"]
    Prod["compose.prod.yaml"] --> ProdApp["focus-agent container"]
    ProdApp --> ExternalPG["External PostgreSQL"]
    App --> Data["/data volume"]
    ProdApp --> DataProd["/data volume"]
```

## 推荐分层

部署文档按运行环境分层阅读：本机开发强调速度和热更新，本地 Docker 强调镜像与容器入口验证，生产/预发强调外部依赖显式注入和安全默认值。

```mermaid
flowchart TD
    Change["Code or config change"] --> Local["Local make commands"]
    Change --> Compose["compose.yaml"]
    Change --> Prod["compose.prod.yaml"]
    Local --> FastFeedback["Fast feedback and hot reload"]
    Compose --> ContainerCheck["Image, entrypoint, and Postgres check"]
    Prod --> ProdBoundary["External PostgreSQL and production auth"]
    FastFeedback --> Promote{"Need deployment confidence?"}
    ContainerCheck --> Promote
    Promote -- "Ready" --> Prod
    ProdBoundary --> Release["Staging or production release"]
```

### 1. 本机开发

- 使用 `make api` / `make dev` / `make serve` / `make serve-dev` / `make serve-prod`
- 启动脚本会自动管理 repo 内本地 PostgreSQL，并注入 `DATABASE_URI`
- 适合快速开发、调试和热更新

### 2. 本地容器联调

- 使用 `compose.yaml`
- 由 Compose 显式管理：
  - `focus-agent`
  - `postgres`
- 适合验证镜像、入口脚本、容器内依赖和 PostgreSQL primary persistence

### 3. 生产/预发部署

- 使用 `compose.prod.yaml`
- 只部署 `focus-agent`
- `DATABASE_URI` 指向外部托管 PostgreSQL
- 不把数据库生命周期绑在应用容器里

## 文件职责

- [Dockerfile](../Dockerfile)：多阶段构建镜像，前端静态资源打包进运行镜像
- [compose.yaml](../compose.yaml)：本地 Docker 联调，包含应用与 Postgres
- [compose.prod.yaml](../compose.prod.yaml)：生产/预发参考模板，应用连接外部 PostgreSQL
- [docker/entrypoint.sh](../docker/entrypoint.sh)：准备 `/data` 下的默认配置文件并导出运行时路径；首次启动会从 `docs/local.env.example`、`docs/models.example.toml` 和 `docs/tools.example.toml` 拷贝初始 `/data/local.env`、`/data/models.toml`、`/data/tools.toml`

## 本地 Docker 联调

`compose.yaml` 的默认行为：

- 启动 `postgres:16-bookworm`
- 启动 `focus-agent`
- 应用等待 Postgres healthcheck 成功后再启动
- 使用 named volume 保存：
  - 应用数据：`focus_agent_data`
  - PostgreSQL 数据：`focus_agent_pgdata`
- 默认 `DATABASE_URI` 指向 `postgres` service

注意：官方 `postgres:16-bookworm` 镜像通常不预装 `pgvector`。当前 Memory v2 在 Postgres-backed 运行下默认启用 pgvector embedding/hybrid；如果继续使用该默认 Compose 数据库，请选择下面之一：

- 换成已包含 `vector` extension 的 PostgreSQL 镜像或自建镜像。
- 在外部 PostgreSQL 预装 `vector`，并通过 `FOCUS_AGENT_DATABASE_URI` 指向它。
- 本地容器只验证非 embedding 路径时，在 `/data/local.env` 中临时设置 `AGENT_MEMORY_EMBEDDING_ENABLED=false`、`AGENT_MEMORY_EMBEDDING_BACKEND=disabled`，并把 `AGENT_MEMORY_VECTOR_SEARCH_MODE=off`。

生产/预发不建议让应用账号创建 extension；应先由 DBA 或迁移账号执行 `CREATE EXTENSION IF NOT EXISTS vector`，再在应用环境中设置 `AGENT_MEMORY_PGVECTOR_EXTENSION_MODE=required`。

启动：

```bash
docker compose up --build
```

Makefile 包装命令：

```bash
make docker-up
make docker-rebuild
make docker-restart
make docker-logs
```

后台运行：

```bash
docker compose up -d --build
```

查看日志：

```bash
docker compose logs -f focus-agent postgres
```

访问：

- `http://127.0.0.1:8000/app`
- `http://127.0.0.1:8000/app/observability/overview`
- `http://127.0.0.1:8000/app/observability/trajectory`
- `http://127.0.0.1:8000/healthz`
- `http://127.0.0.1:8000/readyz`
- `http://127.0.0.1:8000/metrics`

### 本地 Docker 关键环境变量

- `FOCUS_AGENT_MODEL`
- `FOCUS_AGENT_HELPER_MODEL`
- `FOCUS_AGENT_AUTH_JWT_SECRET`
- `FOCUS_AGENT_AUTH_DEMO_TOKENS_ENABLED`
- `FOCUS_AGENT_CORS_ALLOWED_ORIGINS`
- `FOCUS_AGENT_PUBLISHED_PORT`
- `FOCUS_AGENT_DATABASE_URI`
- `FOCUS_AGENT_PG_DB`
- `FOCUS_AGENT_PG_USER`
- `FOCUS_AGENT_PG_PASSWORD`
- `FOCUS_AGENT_DATA_MOUNT`
- `FOCUS_AGENT_PGDATA_MOUNT`

说明：

- 未显式设置 `FOCUS_AGENT_DATABASE_URI` 时，Compose 默认连接本文件内的 `postgres` service
- 如果显式设置 `FOCUS_AGENT_DATABASE_URI`，应用会优先使用该值
- provider 密钥和 Base URL 默认来自 `/data/local.env`，新增 OpenAI-compatible provider 通常只需要在 `/data/models.toml` 和 `/data/local.env` 增加对应配置；如果想临时覆盖内置常用 provider，可在宿主机导出 Compose 会透传的变量，例如 `ANTHROPIC_API_KEY`、`OPENAI_API_KEY`、`OPENAI_BASE_URL`、`MOONSHOT_API_KEY`、`MOONSHOT_BASE_URL`、`MIMO_API_KEY`、`MIMO_BASE_URL`、`OLLAMA_API_KEY`、`OLLAMA_BASE_URL`、`TAVILY_API_KEY`
- 本地 embedding auto 模式优先 Ollama `embeddinggemma`。如果 Ollama 跑在宿主机上，容器内通常需要把 `/data/local.env` 里的 `OLLAMA_BASE_URL` 指到宿主机可达地址，例如 Docker Desktop 的 `http://host.docker.internal:11434/v1`；embedding provider 会规范化成 native Ollama base URL 并调用 `/api/tags`、`/api/embed`
- Memory embedding、pgvector、runtime lease 和 durable jobs 读取的是应用内 `AGENT_MEMORY_*`、`RUNTIME_THREAD_LOCK_*`、`BACKGROUND_JOB_*` 变量。默认容器入口会从 `/data/local.env` 读取这些变量；如果要通过 Compose host env 控制它们，需要在 `compose.yaml` 的 `environment` 中显式增加映射
- 如果要在 readiness、metrics 和 trajectory correlation 中标记版本或部署批次，可在 Compose environment 中显式传入 `APP_VERSION`、`APP_ENVIRONMENT` 或 `DEPLOYMENT_NAME`
- 本地 Docker 路径下建议继续保留 demo token，方便 Web App 直接调试

## 生产/预发部署

`compose.prod.yaml` 的目标是把部署边界做干净：

- 不内置 Postgres service
- 不依赖 repo 内 `.focus_agent`
- 必须显式提供：
  - `FOCUS_AGENT_IMAGE`
  - `FOCUS_AGENT_DATABASE_URI`
  - `FOCUS_AGENT_AUTH_JWT_SECRET`

示例：

```bash
export FOCUS_AGENT_IMAGE=registry.example.com/focus-agent:2026-04-22
export FOCUS_AGENT_DATABASE_URI=postgresql://focus_agent:secret@postgres.internal:5432/focus_agent
export FOCUS_AGENT_AUTH_ENABLED=true
export FOCUS_AGENT_AUTH_JWT_SECRET=replace-with-a-strong-secret
export FOCUS_AGENT_AUTH_JWT_ISSUER=https://issuer.example.com
export FOCUS_AGENT_AUTH_JWT_AUDIENCE=focus-agent-web
export FOCUS_AGENT_AUTH_ACCESS_TOKEN_TTL_SECONDS=900
export FOCUS_AGENT_AUTH_DEMO_TOKENS_ENABLED=false
export FOCUS_AGENT_RATE_LIMIT_ENABLED=true

docker compose -f compose.prod.yaml up -d
```

生产 memory embedding / pgvector / durable job 配置建议写入挂载卷里的 `/data/local.env`，或在 `compose.prod.yaml` 中显式映射为应用读取的变量：

```env
AGENT_MEMORY_EMBEDDING_ENABLED=true
AGENT_MEMORY_EMBEDDING_BACKEND=auto
AGENT_MEMORY_EMBEDDING_MODEL=embeddinggemma
AGENT_MEMORY_EMBEDDING_DIMENSIONS=768
AGENT_MEMORY_VECTOR_SEARCH_MODE=hybrid
AGENT_MEMORY_PGVECTOR_EXTENSION_MODE=required
BACKGROUND_JOB_EXECUTION=durable
BACKGROUND_JOB_BACKEND=postgres
```

如果你保留 `FOCUS_AGENT_AUTH_DEMO_TOKENS_ENABLED=false`，内置 `/app` 首次打开时不会再自动申请 demo token，而是会显示 Bearer Token 登录卡片。此时需要提供一个已有的访问令牌，或在你的部署层接入自定义登录 / JWT 分发能力。

生产 Auth / Access Model 边界：

- Focus Agent 当前接受 HS256 Bearer JWT，`sub` 作为 `Principal.user_id`，`tenant_id` 与 `scope` 会进入运行时 principal。
- `Principal.user_id` 是 conversation、thread、context、branch、merge 的 ownership 主键；`tenant_id` 只是后续多租户隔离扩展字段，不能替代 ownership；`scope` 只表达能力授权，不能让其他 `user_id` 访问已有线程。
- 跨 principal 访问 conversation、thread、context preview/compact、branch fork/tree/proposal/merge 应返回 403。
- repository 层的 thread ownership 校验会生成 allow / deny audit event；事件字段包括 principal、resource type、resource id、action、decision、reason、request id。当前不新增数据库 schema，事件可导出为 trajectory / observability 兼容的 `ownership.audit` 记录，后续可接入统一审计 sink。
- 生产环境应由部署层或外部登录服务签发 JWT，并与 `FOCUS_AGENT_AUTH_JWT_SECRET` 或 key set、`FOCUS_AGENT_AUTH_JWT_ISSUER`、可选 `FOCUS_AGENT_AUTH_JWT_AUDIENCE`、`FOCUS_AGENT_AUTH_ACCESS_TOKEN_TTL_SECONDS` 保持一致；`compose.prod.yaml` 会把这些 `FOCUS_AGENT_*` 外部变量映射为应用实际读取的 `AUTH_*` / `RATE_LIMIT_*` 环境变量。
- `FOCUS_AGENT_AUTH_JWT_ISSUER` 必须匹配 JWT `iss`；配置 `FOCUS_AGENT_AUTH_JWT_AUDIENCE` 后 JWT `aud` 必须存在且完全匹配；过期 `exp` 会被拒绝。
- `FOCUS_AGENT_AUTH_ACCESS_TOKEN_TTL_SECONDS` 建议按部署风险设置为较短窗口，例如 900 秒，并由外部登录层负责刷新或重新签发。
- JWT rotation 支持两种模式：简单部署仍可只用单个 `FOCUS_AGENT_AUTH_JWT_SECRET`；需要重叠窗口时，配置 `AUTH_JWT_KEY_ID` / `AUTH_JWT_KEYS`、`AUTH_JWT_SECRETS` 或 `AUTH_JWT_JWKS`，服务端会按 JWT header `kid` 选择 active key 校验。只要配置了 key set，`AUTH_JWT_KEY_ID` 必须匹配 active key，即使同时保留 legacy single secret 也不能 fallback 到错误 `kid`；wrong `kid` 不会 fallback 到其他 secret；旧 key 仅应在 rotation overlap window 内保持 active。
- demo token 仅用于 development/local/test；非开发环境必须设置 `FOCUS_AGENT_AUTH_DEMO_TOKENS_ENABLED=false`，否则应用会在启动期 fail-fast。

生产规范：

- `APP_ENVIRONMENT=production` 或其他非 development/local/test 值会启用应用启动期安全校验
- `FOCUS_AGENT_AUTH_ENABLED=true`
- `FOCUS_AGENT_AUTH_JWT_SECRET` 必须显式设置，且不能使用开发默认值
- `FOCUS_AGENT_AUTH_JWT_ISSUER` 与外部签发方 `iss` 保持一致
- 建议设置 `FOCUS_AGENT_AUTH_JWT_AUDIENCE`，将 token 限定给 Focus Agent Web/API 使用
- 建议显式设置 `FOCUS_AGENT_AUTH_ACCESS_TOKEN_TTL_SECONDS`，并配合外部登录层刷新策略
- `FOCUS_AGENT_AUTH_DEMO_TOKENS_ENABLED=false`
- `FOCUS_AGENT_RATE_LIMIT_ENABLED=true`
- `API_RELOAD=0`
- `DATABASE_URI` 必须指向外部 PostgreSQL
- 外部 PostgreSQL 必须完成应用需要的 schema migration；如果启用默认 Memory Embedding，必须已安装 `vector` extension，并保持 `focus_memory_embeddings.embedding` 维度与当前 embedding provider/model 一致
- provider secrets 不写入镜像
- 应用容器只保留 `/data` 作为本地文件目录（artifact 正文、默认配置拷贝等）
- 建议显式设置 `APP_VERSION`、`APP_ENVIRONMENT`、`DEPLOYMENT_NAME`，便于 `/readyz`、`/metrics` 和 trajectory 记录定位发布批次

## 数据与迁移

当前结构化数据在启用 PostgreSQL primary persistence 后进入 PG：

- `focus_conversations`
- `focus_thread_access`
- `focus_branches`
- `focus_artifacts`
- `focus_agent_team_sessions`
- `focus_agent_team_tasks`
- `focus_agent_team_outputs`
- LangGraph checkpoint/store
- trajectory 观测表
- Memory v2 业务表：`focus_memories`、`focus_memory_audit_events`、`focus_memory_tombstones`、`focus_memory_candidates`
- Memory embedding shadow：`focus_memory_embeddings`，只保存可重建向量索引，不是 canonical memory truth

artifact 正文文件继续保留在文件系统，不直接入库。

本地状态迁移到 PostgreSQL 时，脚本只负责把结构化状态和 artifact metadata 带入 primary persistence；artifact 正文仍通过扫描和 relative path 关联到文件系统：

```mermaid
flowchart LR
    LocalDir[".focus_agent source dir"] --> Migrator["focus-agent-migrate-local-state"]
    Migrator --> Checkpoints["Latest stable checkpoints"]
    Migrator --> AppState["Conversations and branches"]
    Migrator --> ArtifactScan["Artifact scan"]
    Checkpoints --> PG["External PostgreSQL"]
    AppState --> PG
    ArtifactScan --> PG
    ArtifactScan --> Files["Filesystem artifact bodies"]
    Migrator --> Report["Migration report JSON"]
```

如果要把现有 repo-local `.focus_agent` 数据迁入 PostgreSQL：

```bash
focus-agent-migrate-local-state \
  --source-dir ./.focus_agent \
  --database-uri postgresql://user:pass@host:5432/focus_agent \
  --checkpoint-mode latest-stable \
  --artifact-scan \
  --report-path /tmp/focus-agent-migration.json
```

## 运维建议

- 用 CI 构建镜像，不要在部署机现场编译
- staging/prod 优先使用外部托管 PostgreSQL
- `/healthz` 只表示进程存活；负载均衡 readiness 建议优先看 `/readyz`
- `/metrics` 输出 Prometheus 文本，包含 runtime readiness、组件状态、build labels 和 trajectory 聚合指标；当前它仍经过默认 API middleware，若开启高频 scrape 需留意全局 rate limit 设置
- 如果要把 trace 上报给外部 collector，设置标准 OTel 环境变量：
  - `OTEL_TRACES_EXPORTER=otlp`
  - `OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318`
  - 或 `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://otel-collector:4318/v1/traces`
  - 可选：`OTEL_EXPORTER_OTLP_HEADERS`、`OTEL_EXPORTER_OTLP_TIMEOUT`
  - `/readyz` 与 `/metrics` 会把 `tracing_exporter` 组件状态暴露出来
- 生产发布证据建议附加三类机器报告：
  - `make production-smoke PRODUCTION_SMOKE_ARGS="--base-url https://focus-agent.example.com --web-base-url https://focus-agent.example.com --auth-token <token> --stream-events-json reports/release-gate/stream-events.json --report-json reports/release-gate/production-smoke.json"`
  - `make postgres-ops POSTGRES_OPS_ARGS="--database-uri postgresql://user:pass@host:5432/focus_agent --backup-command 'pg_dump --format=custom --file=/tmp/focus-agent.dump postgresql://user:pass@host:5432/focus_agent' --restore-command 'pg_restore --dbname=postgresql://user:pass@restore-host:5432/focus_agent_verify /tmp/focus-agent.dump' --restore-verification-query 'SELECT 1' --retention-cleanup-query 'SELECT 1' --report-json reports/release-gate/postgres-ops.json"`
  - `make otel-smoke OTEL_SMOKE_ARGS="--endpoint http://otel-collector:4318 --collector-health-url http://otel-collector:13133/healthz --trace-query-url 'https://traces.example.com/api/traces/{trace_id}' --report-json reports/release-gate/otel-smoke.json"`
  - `make agent-governance-report AGENT_GOVERNANCE_REPORT_ARGS="--report-json reports/agent-governance/latest.json --max-review-queue-backlog 10 --max-avg-cost-usd 0.05"`
  - 本地或预接入阶段仍可使用 `--dry-run` 生成计划报告；production evidence 必须使用真实 base URL、真实 auth token、stream event contract report、DB backup/restore drill、collector round-trip 和 governance threshold report。
- trajectory list/stats/overview 支持用 `request_id` 和 `trace_id` 过滤，Web 复盘台也支持 request/trace 深链排障
- 部署前至少执行：
  - `make ci`
  - 一轮 API smoke
  - 一轮 `make ui-smoke-observability`（如果当前环境允许真实浏览器 automation）
- 发布后检查：
  - `/healthz`
  - `/readyz`
  - `/metrics`
  - 会话创建
  - `/v1/chat/turns`
  - trajectory 入库
  - `/v1/observability/overview` 能返回 runtime 与 trajectory stats
  - `/app/observability/trajectory` 能读取 trajectory list / detail / stats

本机如果因为 `.venv` 中 `psycopg` 缺少 `libpq` 无法直接收集 observability 测试，可临时使用当前 focused test workaround：

```bash
PYTHONPATH=/tmp/psycopg_stub .venv/bin/pytest \
  tests/test_api_middleware.py \
  tests/test_metadata.py \
  tests/test_trajectory_observability.py \
  tests/test_api_trajectory_observability.py \
  tests/test_chat_service.py
```

## 不推荐的做法

- 不要把本机 shell 启动脚本里的“自动托管本地 PostgreSQL”逻辑搬进生产容器
- 不要在生产环境开启 demo token
- 不要把 repo 工作目录整体挂进生产容器
- 不要把 artifact 正文直接塞进 PostgreSQL
