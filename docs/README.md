# Focus Agent 文档索引

更新时间：2026-04-18

这份索引用来说明 `docs/` 目录里哪些是当前有效文档，哪些更偏历史背景，避免路线图和设计稿并存时出现多套说法。

## 当前优先阅读

- [architecture.md](architecture.md)：当前已落地的工程架构、部署方式与安全/性能加固说明
- [roadmap.md](roadmap.md)：当前唯一保留的总体路线图，整合近期实施计划与中长期规划
- [agent-roadmap.md](agent-roadmap.md)：Agent 能力侧的详细技术方案，聚焦 plan / memory / tools / eval

## 专项设计

- [tool-skill-design.md](tool-skill-design.md)：Tool 与 Skill 的职责边界设计
- [skill-system-design.md](skill-system-design.md)：Skill System 的运行时设计
- [frontend-refactor-design.md](frontend-refactor-design.md)：前端重构设计与迁移背景；其中迁移分期主要作为历史记录参考

## 运维与发布

- [release-checklist.md](release-checklist.md)：发布前检查项
- [license-guide.md](license-guide.md)：许可证说明
- [local.env.example](local.env.example)：本地环境变量示例
- [models.example.toml](models.example.toml)：模型目录示例
- [tools.example.toml](tools.example.toml)：工具目录示例

## 整理说明

- 旧的 `docs/current-roadmap.md` 已被 `docs/roadmap.md` 取代
- 根目录的阶段性规划文档已收敛到 `docs/`
- `OPTIMIZATION_SUMMARY.md` 的速览内容已并入 `architecture.md` 与 `roadmap.md`
