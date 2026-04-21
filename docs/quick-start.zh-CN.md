# 快速开始

这份文档承接根目录 README 里的最短启动路径，补充完整的本地运行说明。

## 1. 本地初始化

```bash
uv venv
source .venv/bin/activate
uv pip install -e '.[openai,dev]'
cp .env.example .env
make setup-local
pnpm install --registry=https://registry.npmjs.org
```

`make setup-local` 会在缺失时创建 `.focus_agent/` 下的默认本地配置：

- `.focus_agent/local.env`
- `.focus_agent/models.toml`
- `.focus_agent/tools.toml`

Provider 凭据请放在 `.focus_agent/local.env` 或其他未跟踪的本地配置文件里。

## 2. 启动 API

```bash
pnpm web:build
make api
```

启动后可访问：

- `http://127.0.0.1:8000/app`
- `http://127.0.0.1:8000/app/observability/trajectory`
- `http://127.0.0.1:8000/healthz`

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

## 4. 前端开发模式

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

## 5. 一键本地模式

- `make serve` / `make serve-dev`：启动前端 Vite dev server 和带热重载的后端 API
- `make serve-prod`：先构建静态前端，再以非 reload 模式启动后端
- `make dev`：只启动后端，并启用 `API_RELOAD=1`

## 6. 本地鉴权

本地开发可先创建 demo token：

```bash
curl -X POST http://127.0.0.1:8000/v1/auth/demo-token \
  -H 'content-type: application/json' \
  -d '{"user_id": "researcher-1"}'
```

## 7. 下一步文档

- [开发指南](development.zh-CN.md)
- [Docker 部署说明](docker-deployment.md)
- [架构说明](architecture.md)
