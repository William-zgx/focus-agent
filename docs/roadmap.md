# Focus Agent 当前路线图

更新时间：2026-04-21

这份文档只回答两个问题：

1. 现在仓库已经完成到了哪一步。
2. 下一阶段还应该优先收口什么。

## 1. 当前基线

截至 2026-04-21，以下能力已经应视为默认基线，而不是待启动事项：

- `apps/web` React Web App 已接管 `/app` 主入口，FastAPI 负责托管构建产物，并可在开发模式下跳转到 Vite dev server
- `frontend-sdk` 已覆盖 conversation、branch tree、branch action、merge review 等核心 typed client 能力
- merged branch 在前后端都被视为只读，合并后不能继续追加 turn 或继续 fork
- 第一轮工程化加固已落地：CORS、限流、请求 ID、统一错误信封、前端 bundle 分割
- 本机启动链已统一到 `make api` / `make dev` / `make serve-dev` / `make serve-prod`，在 `DATABASE_URI` 未显式设置时会自动管理 repo-local PostgreSQL
- Docker 部署已分层：`compose.yaml` 用于本地 Docker 联调（`focus-agent + postgres`），`compose.prod.yaml` 用于生产/预发模板（外部 PostgreSQL）
- Agent 主路径已具备评测框架、Plan-Act-Reflect、记忆读写闭环、上下文预算一期、工具运行时并行/缓存/降级基础、Postgres trajectory 写入

这意味着接下来不再把“前端接管”“基础 Docker 路径”“记忆闭环接图”“Plan-Act-Reflect 起步版”当成主任务，而是围绕这些基线继续收口质量、运维和产品语义。

## 2. 两条主线

### 2.1 工程与产品主线

近期重点按优先级收敛为四组：

1. **核心语义收口**
   - merge review / conclusion policy 继续做一致性和审计补强
   - README、SDK 类型、前端文案、服务端 contract 持续对齐
2. **存储与运维收口**
   - Postgres 主持久化已覆盖 conversation / branch / checkpoint / store 的主读写路径；下一步重点补 trajectory 与运维侧的查询、导出、迁移链
   - 本机启动、本地 Docker、生产模板三条路径保持边界清晰
3. **生产化治理**
   - Auth / Access Model 继续完善
   - Audit / readiness / metrics 等运维接口补齐
4. **回归与发布**
   - UI smoke、API smoke、eval 回归样本继续扩充
   - 发布文档、迁移文档、运维清单保持可执行

### 2.2 Agent 能力主线

Agent 侧当前不再是从零设计，而是进入“已落地基础之上的二次收口”。详细现状见 [agent-roadmap.md](agent-roadmap.md)。

当前优先级从高到低建议为：

| 模块 | 当前状态 | 下一步重点 |
|------|----------|------------|
| Eval / Regression | 已有 `tests/eval/` 基线 | 扩 golden cases、补回归样本、把更多能力接入 CI 门禁 |
| Memory | 读写闭环已接图 | 继续做质量评估、冲突/提升策略、分支与主线的 promotion 规则 |
| Context Engineering | 一期已落地 | tokenizer 精算、语义压缩、长观察 artifact 化 |
| Model Routing | 尚未落地 | planner / executor / critic 分工与成本路由 |
| Observability | trajectory 写入、查询/导出 CLI、replay/promotion 闭环已落地 | 浏览器链路验证、OpenTelemetry 收尾、复盘视图 |
| Autonomy | 方案位 | 技能自选、分支建议、风险感知式工作流 |

## 3. 当前进展判断

### 已完成并进入维护期

- 前端主入口切换与 `/app` 托管
- 基础分支能力与 merged-branch 只读约束
- 第一轮安全与工程化加固
- repo-local PostgreSQL 启动链
- 本地 Docker / 生产模板分层
- Plan-Act-Reflect
- 记忆读写闭环第一版
- 上下文预算与工具观察裁剪一期
- 工具运行时并行/缓存/降级基础
- Postgres trajectory 落库
- trajectory 查询/导出 CLI 与 replay/promote 闭环

### 正在继续收口

- Postgres 运维链：主业务数据已走 Postgres，继续补 trajectory 查询/导出、迁移验证、长期运维策略
- trajectory 复盘体验：浏览器链路验证、复盘视图、OpenTelemetry tracing
- 文档与 contract 对齐：README、SDK、Web UI 文案、部署说明
- eval 数据集扩充与回归门禁覆盖面
- branch / merge / memory 之间的语义一致性

### 仍未开始或只在方案位

- 模型角色路由
- `readyz` / `metrics` 等更完整的运行态接口
- OpenTelemetry 全链路 tracing
- 技能自选与分支自主建议

## 4. 下一阶段重点

未来一段时间建议优先做下面四件事：

1. 在保持现有 Postgres 主读写路径不变的前提下，继续补浏览器链路验证、复盘视图和 OTel tracing，让 observability 从“能复盘”进一步走向“好复盘”。
2. 把模型角色路由接进现有图，先解决 planner / executor / reflect 的成本与质量分工。
3. 扩 memory / eval / UI smoke 的回归样本，确保已落地的 agent 基线不会回退。
4. 继续收口部署与文档，把本机启动、本地 Docker、生产模板、迁移 CLI 的使用边界说明清楚。

## 5. 文档分工

- [architecture.md](architecture.md)：描述已经落地的工程架构、部署与加固现状
- [docker-deployment.md](docker-deployment.md)：描述本机启动、本地 Docker、生产模板和迁移方式
- [agent-roadmap.md](agent-roadmap.md)：描述 agent 能力的当前进展与后续重点
- 本文：保留统一的路线图视角，只维护“现状 + 下一步”

## 6. 维护原则

- `docs/` 中同一主题只保留一个当前入口文档
- 阶段性拆解和执行细节放到 issue、PR 或项目管理工具里，不长期堆在路线图里
- 当架构现状变化时优先更新 `architecture.md` / `docker-deployment.md`
- 当优先级变化时优先更新本文，而不是再新增一份平行 roadmap
