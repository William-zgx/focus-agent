# Focus Agent 文档索引

更新时间：2026-04-21

这份索引只保留当前推荐入口，并明确哪些文档是“现状/路线图”，哪些文档更适合作为设计背景或历史参考。

## 当前优先阅读

- [architecture.md](architecture.md)：当前工程架构、部署方式、安全与性能加固现状
- [docker-deployment.md](docker-deployment.md)：本机启动、本地 Docker 联调、生产模板的边界和迁移方式
- [roadmap.md](roadmap.md)：当前总路线图，只保留仍在推进的主线和下一阶段重点
- [agent-roadmap.md](agent-roadmap.md)：Agent 能力侧现状、已完成进展、后续优先级

## 设计文档

- [tool-skill-design.md](tool-skill-design.md)：Tool 与 Skill 的职责边界设计
- [skill-system-design.md](skill-system-design.md)：Skill System 的运行时设计

## 历史背景

- [frontend-refactor-design.md](frontend-refactor-design.md)：前端重构期间的设计决策与迁移回顾；现阶段主要作为背景资料

## 运维与发布

- [release-checklist.md](release-checklist.md)：发布前检查项
- [license-guide.md](license-guide.md)：许可证说明
- [local.env.example](local.env.example)：本地环境变量示例
- [models.example.toml](models.example.toml)：模型目录示例
- [tools.example.toml](tools.example.toml)：工具目录示例

## 整理说明

- 旧的 `docs/current-roadmap.md` 已收敛到 [roadmap.md](roadmap.md)
- 根目录阶段性规划文档已集中到 `docs/`
- 历史方案尽量不再新增平行入口，优先在索引里标注“当前/历史”角色
