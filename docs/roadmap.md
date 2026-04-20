# Focus Agent 当前路线图

更新时间：2026-04-20

这份文档是当前唯一保留的总路线图，用来统一近期实施节奏和中长期方向。它整合了此前分散的 `docs/current-roadmap.md`、`IMPLEMENTATION_ROADMAP.md` 与 `OPTIMIZATION_SUMMARY.md`，避免同一时间存在多份互相覆盖的规划说明。

## 1. 当前基线

截至 2026-04-18，仓库已经不再是“从 0 到 1”的空架子，以下能力应视为当前默认基线：

- `apps/web` React Web App 已接管 `/app` 主入口，旧的 Python 内嵌页面实现已移除
- FastAPI 已支持托管构建后的前端产物，并在开发模式下对接 Vite dev server
- `frontend-sdk` 已补齐 conversation、branch tree、branch action、merge review 等 typed client 能力
- merged branch 在前后端两侧都被视为只读，不能继续追加新 turn 或继续 fork
- 工程化加固已完成第一轮交付：CORS、限流、请求 ID、统一错误信封、前端 bundle 分割与对应测试
- 已补齐基础 Docker / Compose 容器化部署路径，默认以单容器 + volume 持久化作为当前部署基线

这意味着后续规划不应再把前端接管、基础 branch UI 或安全中间件当成“待启动工作”，而应围绕现有基线继续收口和增强。

## 2. 两条主线

当前路线图分成两条并行但不冲突的主线：

### 2.1 工程与产品主线

这条主线关注 branch / merge / SDK / 存储 / 治理等产品化问题，优先级从高到低分为四个阶段：

1. **核心语义收口**
   - `ConclusionPolicy` 全链路
   - merge review 正式模型
   - `merge_records` 审计闭环
   - memory 导入统一走 `MemoryWriter`
2. **产品接入层补齐**
   - `frontend-sdk` React hooks
   - branch tree / merge review 组件化
   - tracing 字段标准化
   - README / SDK 类型 / i18n 与服务端 contract 对齐
3. **生产化与治理**
   - migration 体系
   - Postgres 仓储
   - Auth / Access Model
   - Rate Limit、Budget Guard、Audit Log
4. **评测、调试与扩展能力**
   - Eval / Replay / Metrics
   - `readyz` / `metrics`
   - MCP System
   - API / SSE 扩展与回归测试补齐

### 2.2 Agent 能力主线

这条主线聚焦 agent 智能水平提升，详细方案见 [agent-roadmap.md](agent-roadmap.md)。推荐实施顺序如下：

```text
H (评估框架) -> C (记忆闭环) -> D (Context 工程) -> A (Plan-Act-Reflect)
                                                    |
                                                    v
                                 B (工具优化) -> F (模型路由)

                               G (可观测性) + E (自主性) 后期收尾
```

8 个模块及其重点如下：

| 模块 | 重点 | 优先级 |
|------|------|--------|
| H | 评估框架、golden case、回归守护 | 极高 |
| C | 基于现有 MemoryExtractor/Writer/Policy 的记忆闭环、命名空间隔离、去重/冲突、Eval 门禁 | 极高 |
| D | token 预算硬约束、工具观察裁剪已落地一期；语义压缩后续推进 | 高 |
| A | Plan-Act-Reflect 推理循环 | 高 |
| B | 工具并行、缓存、降级、参数校验 | 中高 |
| F | planner / executor / critic 模型路由 | 中高 |
| G | trajectory、指标、OpenTelemetry | 中 |
| E | 技能自选、分支自主建议 | 中 |

## 3. 近期 4 周实施节奏

下面的节奏用于指导近期推进顺序，而不是替代 issue / PR 级别的细化拆分。

### 第 1 周：建立评估与基线

- 评估框架骨架（`tests/eval/`）
- 记忆闭环第一版：在 LangGraph turn 末端接入提取/写入节点，先复用现有 memory 模块，不引入外部 provider
- Context budget 一期：确定性 prompt 预算、工具观察裁剪、相关回归样本
- 目标：先有衡量 agent 能力的尺子，再继续做行为优化

### 第 2 周：改造推理循环

- Plan-Act-Reflect 节点
- 工具层并行、缓存与降级
- 目标：让 agent 从单轮反应式执行升级为“规划-执行-自省”

### 第 3 周：成本与可观测性

- 模型角色路由
- trajectory 与指标
- 成本分析与评估框架联动
- 目标：在不牺牲质量的前提下降本，并让行为可追踪

### 第 4 周：自主性与整合

- 技能自选与分支建议
- 端到端冒烟测试
- 文档与 release notes 收口
- 目标：完成近期闭环，保证团队可以稳定理解并继续演进

## 4. 成功标志

### 工程基线

- 生产环境可配置 CORS、限流、请求追踪
- API 错误响应标准化
- 前端打包优化交付

### Agent 能力提升

- 有可运行的 golden case 评测集，并能在 CI 中守护回归
- task success 率相较 baseline 提升至少 5%
- token / 调用成本下降至少 30%
- 记忆闭环通过 memory eval 子集：用户偏好、项目事实、branch 隔离、merge promotion 与 prompt 注入样本均可复现
- agent 能主动建议分支，而不仅是被动接收分支操作

## 5. 文档分工

- [architecture.md](architecture.md)：描述已经落地的工程架构、部署与加固现状
- [agent-roadmap.md](agent-roadmap.md)：描述 agent 智能升级的详细技术设计
- 本文：保留统一的路线图视角，负责说明“现在先做什么、之后再做什么”

## 6. 维护原则

- `docs/` 中同一主题只保留一个当前入口文档
- 阶段性推进清单不长期堆积在仓库里，细粒度执行项放到 issue、PR 或项目管理工具里维护
- 当架构现状发生变化时，优先更新 `architecture.md`
- 当优先级顺序变化时，优先更新本文，而不是新增一份并列 roadmap
