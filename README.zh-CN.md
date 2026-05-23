# Focus Agent

---

[English](README.md) | **中文**

[![CI](https://github.com/William-zgx/focus-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/William-zgx/focus-agent/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)
![Node.js 20+](https://img.shields.io/badge/node.js-20%2B-339933?logo=node.js&logoColor=white)

![Focus Agent 展示图](docs/assets/focus-agent-readme-hero.zh-CN.svg)

Focus Agent 是一个 branch-aware、Web-first 的 Agent 应用骨架，面向长任务 AI 工作流。它的核心思想很简单：主线程保持专注，探索过程进入临时分支，结论成熟后再受控合并回主线。

围绕这条分支工作流，项目提供流式聊天 API、React Web App、类型化 frontend SDK、访问控制、管理员运维、可观测性、记忆链路、Productivity 工具和 Agent Team 协作流程作为支撑能力。

## 项目状态

Focus Agent 是一个开源应用骨架和参考实现，不是托管式 SaaS 产品。它适合本地开发、产品原型验证，以及改造成团队自有的 branch-aware AI 工作台。

分支工作流、后端 API、SSE stream contract、frontend SDK 和已记录的 Web 功能面会通过 contract、build 和 smoke checks 保护。模型 provider、鉴权策略、PostgreSQL 托管方式、observability backend 和发布流程等部署选择，仍然由采用方显式配置。

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
- 提供仓库读写、git、网页、artifact、memory 和 productivity 工具，并对 workspace 命令执行做保护

## 仓库结构

| 路径 | 用途 |
|------|------|
| `src/focus_agent/` | Python 后端 runtime、API、service、持久化、工具、memory 和 observability 模块 |
| `apps/web/` | 挂载在 `/app` 下的 React Web App |
| `frontend-sdk/` | 覆盖 API、SSE 和 stream reducer 集成的类型化 TypeScript SDK |
| `docs/` | 架构、启动、部署、功能、契约和运维文档 |
| `migrations/` | 面向 PostgreSQL 部署的 Alembic 迁移 |
| `scripts/` | 本地启动、验证、发布、截图和维护脚本 |
| `tests/` | Python、contract、integration、eval 和前端回归测试 |
| `compose.yaml`, `compose.prod.yaml` | 本地和生产取向的 Docker Compose 入口 |

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

## 开发与验证

使用 `make help` 查看当前维护的本地命令。覆盖面最广的本地 CI parity 检查是：

```bash
make ci
```

按改动范围收敛的验证路径见 [docs/development.zh-CN.md](docs/development.zh-CN.md)。常用的局部检查包括：

```bash
make lint-strict
make contract-check
pnpm sdk:check
pnpm web:check
pnpm web:build
```

如果改动影响用户可见行为、stream 事件、鉴权、存储或 SDK 类型，请在同一个 PR 中补齐相关测试和文档。

## 贡献与支持

欢迎提交能让 runtime 更清楚、更可验证、更容易适配的贡献。开发环境、PR 预期和 issue 提交流程见 [CONTRIBUTING.md](CONTRIBUTING.md)。

Bug、功能请求和文档改进请优先使用 GitHub issue templates。安全漏洞或敏感问题请按 [SECURITY.md](SECURITY.md) 处理，不要先创建公开 issue。

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

## 许可证

本项目采用 MIT License。详情见根目录 [`LICENSE`](LICENSE)。
