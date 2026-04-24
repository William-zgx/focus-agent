# Focus Agent 文档索引

更新时间：2026-04-24

这份索引是 `docs/` 的唯一导航入口。根目录 README 保持轻量；更完整的说明集中到这里，并按使用场景分组。

## 快速使用

- [../README.md](../README.md) / [../README.zh-CN.md](../README.zh-CN.md)：项目介绍、最短启动路径和核心入口。
- [quick-start.md](quick-start.md) / [quick-start.zh-CN.md](quick-start.zh-CN.md)：本地初始化、repo-local PostgreSQL、Vite 开发模式和本地鉴权。
- [development.md](development.md) / [development.zh-CN.md](development.zh-CN.md)：日常开发命令、验证矩阵和常见工作流。

## 理解系统

- [architecture.md](architecture.md)：整体架构、核心请求链路、持久化边界、前端/SDK、部署和验证总览。
- [roadmap.md](roadmap.md)：当前基线、下一阶段重点和仍在推进的方向。

## 核心专题

- [agent-role-routing.md](agent-role-routing.md)：Agent Governance、role routing、tool routing、delegation、context、task ledger、critic gate 和 eval gate。
- [memory-system.md](memory-system.md)：记忆生命周期、namespace、检索、写入、去重、冲突和 branch promotion。
- [tool-skill-design.md](tool-skill-design.md)：Tool / Skill / Connector / Storage 的边界、运行时策略和扩展检查项。

## 运维发布

- [docker-deployment.md](docker-deployment.md)：本地 Docker 联调、生产/预发模板、外部 PostgreSQL 和迁移边界。
- [observability-runbook.md](observability-runbook.md)：overview、trajectory workbench、request/trace pivot、replay 和 promote 操作手册。
- [release-checklist.md](release-checklist.md)：发布前检查清单。

## 配置示例

- [local.env.example](local.env.example)：本地环境变量示例。
- [models.example.toml](models.example.toml)：模型目录示例。
- [tools.example.toml](tools.example.toml)：工具目录示例。

## 维护原则

- 同一主题只保留一个 canonical 文档，其他文档只做摘要和跳转。
- 根目录 README 只做轻入口，不承载长篇操作说明。
- `architecture.md` 讲整体结构和跨模块路径；专题细节分别放到 Agent Governance、Memory、Tool / Skill、Docker 和 Observability 文档。
- 阶段性方案、执行记录和草稿不要长期堆在 `docs/`，应放到 issue、PR 或项目管理工具。
