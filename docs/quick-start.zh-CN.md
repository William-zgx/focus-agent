# 快速开始

这份文档承接根目录 README 里的最短启动路径，补充完整的本地运行说明。

```mermaid
flowchart LR
    Setup["本地初始化"] --> Config[".focus_agent 配置"]
    Config --> Build["构建 Web bundle"]
    Build --> Start["make api / make serve-dev"]
    Start --> Postgres{"是否已设置 DATABASE_URI?"}
    Postgres -- "否" --> Managed["托管 repo-local PostgreSQL"]
    Postgres -- "是" --> External["使用外部数据库"]
    Managed --> App["打开 /app"]
    External --> App
    App --> Ready["检查 /readyz"]
    Ready --> Observe["打开 /metrics 和观测页面"]
```

## 1. 本地初始化

```bash
uv venv
source .venv/bin/activate
uv pip install -e '.[openai,dev]'
make setup-local
pnpm install --registry=https://registry.npmjs.org
```

`make setup-local` 会在缺失时创建 `.focus_agent/` 下的默认本地配置：

- `.focus_agent/local.env`
- `.focus_agent/models.toml`
- `.focus_agent/tools.toml`

Provider 凭据请放在 `.focus_agent/local.env` 或其他未跟踪的本地配置文件里。根目录 `.env.example` 主要供 Docker Compose 或手动 shell export 参考；本地 API 启动路径读取 `.focus_agent/local.env` 和进程环境变量。

如果只是给某个部署新增 OpenAI-compatible chat 模型，请在 `.focus_agent/models.toml` 里增加 provider/model 元数据，并只把密钥和 endpoint 放到 `.focus_agent/local.env`。只有当模型需要成为所有新环境的内置默认支持时，才修改 `src/focus_agent/defaults/models.toml`。

## 2. 启动 API

```bash
pnpm web:build
make api
```

启动后可访问：

- `http://127.0.0.1:8000/app`
- `http://127.0.0.1:8000/app/agent-team`
- `http://127.0.0.1:8000/app/agent/memory`
- `http://127.0.0.1:8000/app/admin/users`
- `http://127.0.0.1:8000/app/admin/audit-events`
- `http://127.0.0.1:8000/app/observability/overview`
- `http://127.0.0.1:8000/app/observability/trajectory`
- `http://127.0.0.1:8000/healthz`
- `http://127.0.0.1:8000/readyz`
- `http://127.0.0.1:8000/metrics`

其中 `/healthz` 是简单存活检查，`/readyz` 返回运行态组件 readiness；配置了 PostgreSQL memory embedding 时会包含 `memory_embedding_backend` 和 `memory_pgvector`。`/metrics` 输出 Prometheus 文本指标。Web observability 页面会基于 Postgres 中的 trajectory 数据支持 request/trace 关联排障。

## 3. 本地托管 PostgreSQL

如果启动前没有设置 `DATABASE_URI`，本地启动命令（`make api`、`make dev`、`make serve`、`make serve-dev`、`make serve-prod`）会自动管理一个 repo 内本地 PostgreSQL，并把生成的 `DATABASE_URI` 注入到 API 进程里。

这条托管路径：

- 需要本机可用的 PostgreSQL CLI/服务端工具，例如 `initdb`、`pg_ctl`、`createdb`、`psql`
- 会随着服务一起停止并清理临时运行态
- 会保留 repo-local Postgres 数据目录，方便下次继续复用

如果你在启动前已经显式设置了 `DATABASE_URI`，启动命令会保留该值，不再覆盖，也不会再做托管本地 Postgres 的注入。

如果你更希望直接运行 `.venv/bin/focus-agent-api`，请先自行准备并导出 `DATABASE_URI`。裸跑二进制不会帮你启动这套托管本地 PostgreSQL。

启动脚本会把运行态写入 `.focus_agent/postgres/runtime.env`，方便另一条 shell 连接同一套数据库：

```bash
source .focus_agent/postgres/runtime.env
psql "$DATABASE_URI"
```

## 4. Memory Embedding 与 pgvector

PostgreSQL memory 是生产 canonical memory store。Postgres-backed 运行默认启用 Memory Embedding：

- `AGENT_MEMORY_EMBEDDING_ENABLED=true`
- `AGENT_MEMORY_EMBEDDING_BACKEND=auto`
- `AGENT_MEMORY_EMBEDDING_MODEL=embeddinggemma`
- `AGENT_MEMORY_EMBEDDING_DIMENSIONS=768`
- `AGENT_MEMORY_VECTOR_SEARCH_MODE=hybrid`

本地 auto 模式优先使用 Ollama `embeddinggemma`。应用不会自动执行 `ollama pull`，需要你显式安装：

```bash
ollama pull embeddinggemma
```

Chat provider 可以继续使用 `OLLAMA_BASE_URL=http://127.0.0.1:11434/v1`；embedding provider 会把它规范化为 Ollama native `http://127.0.0.1:11434`，并调用 `/api/tags` 和 `/api/embed`。

如果使用云端 embedding，请显式配置 OpenAI-compatible embedding backend，不要依赖 chat model provider：

```env
AGENT_MEMORY_EMBEDDING_BACKEND=openai_compatible
AGENT_MEMORY_EMBEDDING_MODEL=text-embedding-3-small
AGENT_MEMORY_EMBEDDING_DIMENSIONS=1536
AGENT_MEMORY_EMBEDDING_BASE_URL=https://api.openai.com/v1
AGENT_MEMORY_EMBEDDING_API_KEY_ENV=OPENAI_API_KEY
# 也可以在本地 secret 文件中直接设置 AGENT_MEMORY_EMBEDDING_API_KEY
```

维护 CLI 可用于只读诊断和受控重建：

```bash
focus-agent-memory-embedding doctor --database-uri "$DATABASE_URI"
focus-agent-memory-embedding rebuild --database-uri "$DATABASE_URI" --confirm-delete-index --backfill
```

`rebuild` 只会删除并重建 `focus_memory_embeddings`，不会删除 `focus_memories`、audit events、tombstones、candidates 或 checkpoints。

生产环境建议由 DBA 或迁移账号预装 Postgres `vector` extension，并让应用以校验模式启动：

```env
AGENT_MEMORY_PGVECTOR_EXTENSION_MODE=required
```

## 5. Runtime 协调

默认本地协调是 local-first：

- `BACKGROUND_JOB_EXECUTION=best_effort`
- `BACKGROUND_JOB_BACKEND=memory`
- `RUNTIME_THREAD_LOCK_TTL_SECONDS=300`
- `RUNTIME_THREAD_LOCK_HEARTBEAT_SECONDS=30`
- `BACKGROUND_JOB_CLAIM_TTL_SECONDS=300`

共享 Postgres 部署可以开启 durable background execution，必须同时配置：

```env
BACKGROUND_JOB_EXECUTION=durable
BACKGROUND_JOB_BACKEND=postgres
DATABASE_URI=postgresql://user:pass@host:5432/focus_agent
```

Durable jobs 使用 claim token 和 claim heartbeat；chat/branch 写操作使用 per-thread lease。首轮 branch title/metadata refresh 会在 chat turn lease release 后再调度，避免 immediate background worker 和当前 turn lock 竞争。

## 6. 分支推荐

Branch decision 自动化默认关闭。若只想收集推荐证据、不改变聊天行为，可配置：

```env
AGENT_BRANCH_DECISION_ENABLED=true
AGENT_BRANCH_DECISION_MODE=shadow
AGENT_BRANCH_RECOMMENDATION_ENABLED=true
AGENT_BRANCH_RECOMMENDATION_MODE=shadow
```

若希望高置信度的发送前推荐展示为需要用户确认的 Branch Action 卡片，可配置：

```env
AGENT_BRANCH_RECOMMENDATION_ENABLED=true
AGENT_BRANCH_RECOMMENDATION_MODE=suggest
AGENT_BRANCH_RECOMMENDATION_MIN_CONFIDENCE=0.72
```

`suggest` 模式仍不会静默 fork；用户需要在聊天卡片里确认或取消。完整配置、API、SDK 和验证口径见 [分支决策与推荐](branch-decisions.md)。

## 7. 前端开发模式

如果你要本地联调前端：

```bash
make web-dev
```

然后在 `.focus_agent/local.env` 里设置：

```env
WEB_APP_DEV_SERVER_URL=http://127.0.0.1:5173/app
```

此时：

- 前端：`http://127.0.0.1:5173/app/`
- API：`http://127.0.0.1:8000`

Web App 默认把 `VITE_FOCUS_AGENT_API_BASE_URL` 解析为 `window.location.origin`。只有当 Vite 页面需要调用另一个 API origin 时才显式设置。

## 8. 一键本地模式

- `make serve` / `make serve-dev`：启动前端 Vite dev server 和带热重载的后端 API
- `make serve-prod`：先构建静态前端，再以非 reload 模式启动后端
- `make dev`：只启动后端，并启用 `API_RELOAD=1`

## 9. 本地鉴权

内置 `/app` 会把未登录用户引导到 `/app/auth/login`，并通过 `return_to` 保留原本要访问的受保护页面。本地开发最快的浏览器路径是：

1. Vite 模式打开 `http://127.0.0.1:5173/app/`，或打开后端托管 bundle 的 `http://127.0.0.1:8000/app/`。
2. 点击 `Demo 登录` 创建默认本地 demo 用户，并回到原目标页面。
3. 用左侧栏账号区域的 `退出登录` 回到未登录态。
4. 切换账号时先退出，再用用户名密码、`Demo 登录` 或 Bearer Token 面板重新登录。

如果要测试 token 登录，可先创建本地 demo access token：

```bash
curl -X POST http://127.0.0.1:8000/v1/auth/demo-token \
  -H 'content-type: application/json' \
  -d '{"user_id": "researcher-1"}'
```

把返回的 `access_token` 粘贴到登录页 `使用 Bearer Token` 面板，并点击 `继续`。`清空` 会移除本地保存的 token。注册用户名密码会创建持久化本地账号，只在明确需要验证账号密码流程时使用。

注册和测试账号注意点：

- 用户名会先 trim 并转小写，再做唯一性校验。
- 密码至少 8 位，并且必须同时包含字母和数字。
- 自助注册会创建 active `member`，不会自动成为 admin。
- `AUTH_DEMO_TOKENS_ENABLED=true` 是本地默认值；非开发部署必须关闭 demo token。
- 本地/开发模式下，首个非匿名用户可以 bootstrap 为 admin。也可以用 `AUTH_BOOTSTRAP_ADMIN_USER_IDS` 显式指定本地 admin ID。生产数据库部署应显式配置管理员。
- 在 `/app/admin/users` 创建用户只会创建用户记录；验证用户名密码登录前，需要先为该用户 reset password。
- 退出登录会清掉 Web App 本地 token、清掉 auth cookie，并撤销 refresh session。Access token 和 demo token 是无状态 token，已经复制出去的 token 在过期或密钥轮换前仍可再次粘贴使用。

Admin Console 本地检查入口：

- `/app/admin/users` 是用户目录、创建用户抽屉和用户详情抽屉。
- `/app/admin/audit-events` 是管理员审计事件浏览器。
- 状态、角色、会话撤销和密码重置动作都需要填写 reason，并写入审计事件。
- Bearer token scope 不能单独授予 admin 权限；必须有持久化用户角色支持。

## 10. 浏览器 Smoke 测试

`make ui-smoke` 默认使用 `scripts/ui_smoke_test.py` 中配置的 app URL，通常对应 Vite dev server。当你想验证后端托管的静态 bundle，或本地调试时临时关闭鉴权，可以显式启动 API 并传入页面地址：

```bash
AUTH_ENABLED=false WEB_APP_DEV_SERVER_URL= API_PORT=8001 ./scripts/run-api.sh
uv run python scripts/ui_smoke_test.py \
  --app-url http://127.0.0.1:8001/app/ \
  --health-url http://127.0.0.1:8001/healthz \
  --message '最近一周华钰矿业这只A股股票的表现怎么样？请联网查询并用中文简要说明。'
```

如果改动涉及 streaming、transport validation 或 web search，不要只用默认 OK 消息；应使用真实工具调用问题。Smoke 脚本会等待流式 assistant 回复稳定后再断言最终文本。

如果使用 Vite dev server，请保留 `http://127.0.0.1:5173/app/` 末尾的斜杠；`http://127.0.0.1:5173/app` 在 dev server 下可能有不同处理。Smoke 脚本会用临时 Chrome profile，避免本地 localStorage、扩展和个人 profile 中的登录态影响结果。如果手动浏览器打开空白登录页而 smoke 通过，请先清理 `127.0.0.1` 站点数据或使用干净 profile，再判断是否是 UI 回归。

## 11. 下一步文档

- [Memory System v2](memory-system-v2.md)
- [分支决策与推荐](branch-decisions.md)
- [Observability Runbook](observability-runbook.md)
- [Auth / Access](auth-access.md)
- [管理员控制台](admin-console.md)
- [开发指南](development.zh-CN.md)
- [Docker 部署说明](docker-deployment.md)
- [架构说明](architecture.md)
