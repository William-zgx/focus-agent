# Focus Agent

---

[English](README.md) | **中文**

![Focus Agent 展示图](docs/assets/focus-agent-readme-hero.zh-CN.svg)

Focus Agent 是一个 Web-first 的 Agent 应用骨架，当前已经发展成一个小型平台：支持分支式会话、实时输出、访问控制、管理员运维、可观测性、记忆链路、Agent Team 协作流程和类型完备的前端 SDK。

它面向的是这样一类团队：需要一个 local-first、可理解、可演进的长任务 AI 系统基础，同时希望平台边界保持清楚。它已经不只是最小 demo：后端运行时、Web App、SDK、持久化适配、发布/eval 工具和 Agent Team 协作模块都按独立维护区域管理。

## 为什么是 Focus Agent

很多 Agent Demo 默认只有“一问一答”。而 Focus Agent 的核心假设不同：真实的研究、调试、写作和审查过程并不是线性的。

与其把所有探索过程都塞进一条越来越嘈杂的主线程里，Focus Agent 把主线程当作共享进展，把分支当作临时工作区，用来做探索、验证和对比。

## 核心能力

- 支持分支式会话与受控 merge 回主线
- 支持 AI 辅助的分支决策与发送前分支推荐，并通过用户确认的 Branch Action 卡片执行
- 提供流式聊天 API 和内置 React Web 界面 `/app`
- 在发送栏展示当前上下文窗口占用，并支持非破坏式手动/自动压缩
- 提供基于 owner 的生产力工作台（笔记 + 任务），并保留来源追踪（`/app/productivity/notes`、`/app/productivity/tasks`）
- 提供 Agent Team Mission Runner，把目标拆成动态多 Agent 任务、回传证据并汇总最终答案
- 内置分层 observability 流程：`/app/observability/overview` 负责趋势与热点发现，`/app/observability/trajectory` 负责单条样本复盘
- 带有访问控制、管理员控制台、记忆链路和类型完备的前端 SDK
- 对工具/协议流做隔离，确保 `message.delta` 只承载确认可见的 assistant 正文
- 提供仓库、git、网页、artifact、memory 和 productivity 工具

## 快速开始

环境要求：

- Python 3.11+
- [`uv`](https://docs.astral.sh/uv/)
- 如果要构建 Web 前端和 SDK，需要 Node.js 20+

```bash
uv venv
source .venv/bin/activate
uv pip install -e '.[openai,dev]'
make setup-local
pnpm install --registry=https://registry.npmjs.org
pnpm web:build
make api
```

`make setup-local` 会创建 `.focus_agent/local.env`、`.focus_agent/models.toml` 和 `.focus_agent/tools.toml`。
根目录 `.env.example` 主要供 Compose 或手动 shell export 参考；本地 API 启动路径读取 `.focus_agent/local.env` 和进程环境变量。

模型和 provider 元数据会先读取包内默认 catalog，也可以通过
`.focus_agent/models.toml` 做本地覆盖；provider 密钥请放在
`.focus_agent/local.env`。新增自定义 OpenAI-compatible 模型的路径见
[docs/quick-start.zh-CN.md](docs/quick-start.zh-CN.md)。

PostgreSQL memory 可用时默认启用 Memory Embedding。本地 auto 模式优先 Ollama `embeddinggemma`，请显式执行 `ollama pull embeddinggemma`，或配置 OpenAI-compatible embedding endpoint。

启动后可访问：

- `http://127.0.0.1:8000/app`
- `http://127.0.0.1:8000/app/agent-team`
- `http://127.0.0.1:8000/app/agent/memory`
- `http://127.0.0.1:8000/app/admin/users`
- `http://127.0.0.1:8000/app/admin/audit-events`
- `http://127.0.0.1:8000/app/productivity/notes`
- `http://127.0.0.1:8000/app/productivity/tasks`
- `http://127.0.0.1:8000/app/observability/overview`
- `http://127.0.0.1:8000/app/observability/trajectory`
- `http://127.0.0.1:8000/healthz`
- `http://127.0.0.1:8000/readyz`
- `http://127.0.0.1:8000/metrics`

更完整的本地启动方式、repo-local PostgreSQL 自动托管、Vite 开发模式和本地鉴权说明见 [docs/quick-start.zh-CN.md](docs/quick-start.zh-CN.md)。内置登录页支持用户名密码、Demo 登录和 Bearer Token 登录；账号切换就是先退出再选择另一种登录方式。

## 容器化部署

- 本地 Docker：`compose.yaml`
- 生产/预发模板：`compose.prod.yaml`
- 完整部署说明：[docs/docker-deployment.md](docs/docker-deployment.md)

```bash
export FOCUS_AGENT_AUTH_JWT_SECRET=replace-with-a-strong-secret-at-least-32-chars
export OPENAI_API_KEY=replace-me
docker compose up --build
```

生产或预发部署请使用 `compose.prod.yaml`，并通过 `FOCUS_AGENT_DATABASE_URI` 指向外部 Postgres。

## 文档导航

- [文档索引](docs/README.md)
- [快速开始](docs/quick-start.zh-CN.md)
- [开发指南](docs/development.zh-CN.md)
- [架构说明与模块导航](docs/architecture.md)
- [Auth / Access](docs/auth-access.md)
- [Agent Team Workbench](docs/agent-team-workbench.md)
- [生产力工作台](docs/productivity-system.md)
- [管理员控制台](docs/admin-console.md)
- [分支决策与推荐](docs/branch-decisions.md)
- [流式事件契约](docs/streaming-contract.md)
- [发布检查清单](docs/release-checklist.md)
- [前端 SDK](frontend-sdk/README.md)
- [当前上下文窗口](docs/context-window.md)
- [Docker 部署说明](docs/docker-deployment.md)
- [贡献指南](CONTRIBUTING.md)
- [安全策略](SECURITY.md)

## License

本项目采用 MIT License。详情见根目录 [`LICENSE`](LICENSE)。
