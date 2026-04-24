# Focus Agent 文档索引

更新时间：2026-04-24

这份索引只保留当前推荐入口。

## 当前优先阅读

- [../README.md](../README.md) / [../README.zh-CN.md](../README.zh-CN.md)：项目介绍、快速开始和常用入口
- [quick-start.md](quick-start.md) / [quick-start.zh-CN.md](quick-start.zh-CN.md)：完整的本地启动、repo-local PostgreSQL 和开发模式说明
- [development.md](development.md) / [development.zh-CN.md](development.zh-CN.md)：开发命令矩阵、验证口径和常见工作流
- [observability-runbook.md](observability-runbook.md)：overview 与 trajectory 复盘台的排障顺序、pivot 方式和 replay/promote 路径
- [architecture.md](architecture.md)：当前工程架构、部署方式、持久化与 observability 现状
- [agent-role-routing.md](agent-role-routing.md)：Agent role routing v2 的行为边界与 eval gate
- [memory-system.md](memory-system.md)：当前记忆系统设计、生命周期、promotion 语义与后续扩展方向
- [docker-deployment.md](docker-deployment.md)：本机启动、本地 Docker 联调、生产模板的边界和迁移方式
- [roadmap.md](roadmap.md)：当前总路线图，只保留仍在推进的主线和下一阶段重点

## 设计文档

- [memory-system.md](memory-system.md)：记忆系统设计、检索/写入/promotion 规则与测试面
- [tool-skill-design.md](tool-skill-design.md)：Tool 与 Skill 的职责边界、运行时设计和后续 backlog

## 运维与发布

- [release-checklist.md](release-checklist.md)：发布前检查项
- [agent-role-routing.md](agent-role-routing.md)：role routing / helper model / memory preview 回归门禁
- [local.env.example](local.env.example)：本地环境变量示例
- [models.example.toml](models.example.toml)：模型目录示例
- [tools.example.toml](tools.example.toml)：工具目录示例

## 整理说明

- 旧的 `docs/current-roadmap.md` 已收敛到 [roadmap.md](roadmap.md)
- 根目录阶段性规划文档已集中到 `docs/`
- 根 README 现在只保留项目介绍、最短启动路径和文档导航
- Agent 能力路线图已合并进 [roadmap.md](roadmap.md)
- Skill System 设计已合并进 [tool-skill-design.md](tool-skill-design.md)
- 前端重构迁移回顾和独立 License 说明已删除；当前事实分别以 [architecture.md](architecture.md) 和根目录 [LICENSE](../LICENSE) 为准
