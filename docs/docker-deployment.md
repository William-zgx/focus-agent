# Docker 部署方案

更新时间：2026-04-21

这份文档定义当前仓库推荐的 Docker 部署方式。目标是把 **本机开发启动链**、**本地容器联调**、以及 **生产部署** 明确分层，避免把开发便利逻辑和正式部署逻辑混在一起。

## 推荐分层

### 1. 本机开发

- 使用 `make api` / `make dev` / `make serve-dev` / `make serve-prod`
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
- [docker/entrypoint.sh](../docker/entrypoint.sh)：准备 `/data` 下的默认配置文件并导出运行时路径

## 本地 Docker 联调

`compose.yaml` 的默认行为：

- 启动 `postgres:16-bookworm`
- 启动 `focus-agent`
- 应用等待 Postgres healthcheck 成功后再启动
- 使用 named volume 保存：
  - 应用数据：`focus_agent_data`
  - PostgreSQL 数据：`focus_agent_pgdata`
- 默认 `DATABASE_URI` 指向 `postgres` service

启动：

```bash
docker compose up --build
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
- `http://127.0.0.1:8000/healthz`

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
export FOCUS_AGENT_IMAGE=registry.example.com/focus-agent:2026-04-21
export FOCUS_AGENT_DATABASE_URI=postgresql://focus_agent:secret@postgres.internal:5432/focus_agent
export FOCUS_AGENT_AUTH_JWT_SECRET=replace-with-a-strong-secret
export FOCUS_AGENT_AUTH_DEMO_TOKENS_ENABLED=false

docker compose -f compose.prod.yaml up -d
```

生产规范：

- `AUTH_DEMO_TOKENS_ENABLED=false`
- `API_RELOAD=0`
- `DATABASE_URI` 必须指向外部 PostgreSQL
- provider secrets 不写入镜像
- 应用容器只保留 `/data` 作为本地文件目录（artifact 正文、默认配置拷贝等）

## 数据与迁移

当前结构化数据在启用 PostgreSQL primary persistence 后进入 PG：

- `focus_conversations`
- `focus_thread_access`
- `focus_branches`
- `focus_artifacts`
- LangGraph checkpoint/store
- trajectory 观测表

artifact 正文文件继续保留在文件系统，不直接入库。

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
- 部署前至少执行：
  - `make ci`
  - 一轮 API smoke
- 发布后检查：
  - `/healthz`
  - 会话创建
  - `/v1/chat/turns`
  - trajectory 入库

## 不推荐的做法

- 不要把本机 shell 启动脚本里的“自动托管本地 PostgreSQL”逻辑搬进生产容器
- 不要在生产环境开启 demo token
- 不要把 repo 工作目录整体挂进生产容器
- 不要把 artifact 正文直接塞进 PostgreSQL
