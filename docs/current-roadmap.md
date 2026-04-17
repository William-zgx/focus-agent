# Focus Agent 当前完整规划（唯一保留的迭代规划文档）

这份文档基于 2026-04-14 的规划框架整理，并在 2026-04-18 按当前仓库状态补充了关键进展说明；状态判断以“代码已经落了什么、还缺什么”为准。

仓库只保留这一份整体迭代计划。阶段性拆解、执行批次和临时推进清单不再长期保存在 `docs/` 中，而应放到 issue、PR 或项目管理工具里维护。

更新时间：2026-04-18

## 0. 最近状态补记

相较于最初整理这份路线图时，仓库已经新增了几项需要默认纳入基线的变化：

- `apps/web` React Web App 已经接管 `/app` 主入口，旧的 Python 单文件内嵌页面实现已经删除
- FastAPI 现在支持同时服务构建后的前端产物，并在配置 `WEB_APP_DEV_SERVER_URL` 时把 `/app` 重定向到本地 Vite dev server
- `frontend-sdk` 已补齐 conversation、branch tree、branch action、merge review 等 typed client 方法，不再只是最小流式层
- merged branch 现在在前后端两侧都被视为只读，不能继续发送新 turn，也不能再从已合并分支继续 fork

下面各阶段规划仍然保留，用于描述后续优先级；但阅读时请以上述实现基线为准，而不是把 React 前端接入本身再当成未开始工作。

## 1. 规划结论

当前项目已经不是“从 0 到 1 的 skeleton”，而是已经完成了以下第一层基础：

- 对话状态治理已经落了第一版
- context assembly 已经从 graph 节点中抽离
- memory package 与 branch/main namespace 基础链路已经接好
- Skill System 第一版已经落地
- React Web App 已经具备 branch tree、archive/activate、merge review、会话切换等主路径
- `frontend-sdk` 已经具备 typed client、parser、reducer，以及 conversation / branch / merge 相关 JSON helper

因此新的规划不应该再把这些部分当成“未开始”，而应该分成四层：

1. 核心语义收口
2. 产品接入层补齐
3. 生产化与治理
4. 评测、调试与扩展能力

## 2. 当前状态总览

### A. 已完成

- `AgentState` 分层字段与 `prompt_mode`
- `core/context_policy.py` 上下文装配
- `memory/` package：`models / scorer / dedupe / retriever / writer / extractor / policy / assembler`
- `storage/namespaces.py` 与 branch/main memory namespace
- `engine/runtime.py`、`engine/graph_builder.py` 的 memory 基础接线
- `services/branches.py` 的基础 branch findings / imported findings / promote 流程
- Skill Registry、Tool Registry、内置技能、默认工具
- React Web App 的 branch tree、archive/activate、merge review、conversation toolbar 主路径
- `frontend-sdk`：client / parser / reducers / guards / types，以及 conversation / branch / merge request helpers
- 基础 tracing metadata / tags
- `/healthz` 端点

### B. 部分完成

- Branch memory import 仍有旧 helper 残留，尚未完全收敛到 `MemoryWriter`
- Merge review 已可用，但仍偏“现有 merge 能力增强版”
- Trace 已有基础字段，但缺少 `prompt_mode`、`merge_status`、`conclusion_policy` 等统一字段
- README / API / SDK / i18n 已围绕现有 merge flow 补过一轮，但新 contract 还没完全对齐

### C. 未完成

- `ConclusionPolicy` 全链路
- `merge_records` 审计闭环
- frontend-sdk React hook / 组件层
- migration 体系与 Postgres 仓储
- 正式权限模型、限流、审计日志
- Eval / Replay / Metrics
- MCP System

## 3. 重新定义后的阶段规划

### Phase 1：核心语义收口

目标：
把“branch 可以怎么回带、怎么审阅、怎么导入、怎么追踪”这条主链打通。

包含主题：

- `ConclusionPolicy` 全链路
- merge review 正式模型
- `merge_records`
- `import_memory -> MemoryWriter` 收口

阶段产出：

- branch 创建可选 `local_only / review_to_parent`
- `local_only` 在后端真正受限
- merge 导入行为可解释、可追踪
- memory 导入路径统一

状态：

- 未完成，但这是当前最高优先级

### Phase 2：产品接入层补齐

目标：
让现有能力不仅能在内置 React Web App 跑通，也能被外部前端稳定复用。

包含主题：

- `frontend-sdk` React hook 层
- branch tree / merge review 组件化
- 前端流式状态模型固化
- tracing 字段标准化
- README / SDK 类型 / React Web App 与服务端 contract 对齐

阶段产出：

- React 客户端无需手写 SSE 和 merge 管线
- SDK 与内置 React Web App 使用同一套字段和交互模型
- trace 可以按模式、分支、状态筛选

状态：

- 有基础实现，但整体仍属部分完成

### Phase 3：生产化与治理

目标：
把当前单机/本地可跑架构推进到可部署、可演进、可控的服务化形态。

包含主题：

- migration 体系
- Postgres 仓储
- Auth / Access Model
- Rate Limit 与 Budget Guard
- Audit Log

阶段产出：

- schema 演进有机制
- 数据存储不依赖 SQLite 默认实现
- 多用户访问有权限边界
- 系统有基础防滥用与审计能力

状态：

- 基本未开始

### Phase 4：评测、调试与扩展能力

目标：
提升后续演进效率，而不是直接增加用户可见功能。

包含主题：

- Eval 场景集
- Replay / Debug API
- `readyz` / `metrics`
- MCP System
- API / SSE 扩展与完整测试补齐

阶段产出：

- prompt / graph / merge 规则可以稳定回归
- 问题 turn 能复现和排查
- 系统具备最小部署观测能力
- Memory / Skill / MCP 三层架构更完整

状态：

- 除 `/healthz` 外基本未开始

## 4. 每个阶段的详细规划

### Phase 1：核心语义收口

#### 1.1 `ConclusionPolicy` 落地

要做什么：

- 新增 `ConclusionPolicy`
- 写入 `BranchMeta`、`BranchRecord`、`BranchTreeNode`
- fork API 支持 `conclusion_policy`
- SQLite 增加 `conclusion_policy` 列并兼容旧数据
- branch tree、thread state、trace、context 透出该字段

完成标准：

- policy 不再只是文档概念，而是系统 contract

#### 1.2 merge review 收口

要做什么：

- proposal / merge 行为按 policy 生效
- 明确导入目标、导入模式、状态流转
- 补 proposal 字段缺口，如 `risk_notes`、`discardable_items`
- 明确 reject / defer 的契约

完成标准：

- merge 是正式审阅流程，而不是“点一下就导回”

#### 1.3 `merge_records`

要做什么：

- 新建 merge 记录表
- repo 提供按 branch / parent thread 查询
- merge 成功后写记录
- 为后续 replay、audit、UI 历史视图留基础数据

完成标准：

- 任意导入都能回答“谁在什么时候导回了什么”

#### 1.4 收口 memory 导入实现

要做什么：

- imported conclusion 与 findings promote 统一走 `MemoryWriter`
- `storage/import_memory.py` 退化为兼容 shim
- nested branch 和 root main 的 promote 规则固定下来

完成标准：

- 不再存在双轨 memory 写入逻辑

### Phase 2：产品接入层补齐

#### 2.1 frontend-sdk React hook 层

要做什么：

- `useFocusAgentStream`
- `useBranchTree`
- `useMergeReview`
- README 示例补齐

完成标准：

- React 客户端能直接消费 SDK

#### 2.2 branch tree / merge review 组件化

要做什么：

- 将内置 React Web App 已验证过的交互抽成 SDK 组件
- 对齐 props、状态模型、事件回调

完成标准：

- branch tree 与 merge review 具备可复用组件

#### 2.3 tracing 标准化

要做什么：

- metadata/tags 统一包含 `prompt_mode`、`merge_status`、`conclusion_policy`
- chat / branch / merge 相关 run 使用同一 builder

完成标准：

- LangSmith 可按主线/分支/状态筛选

#### 2.4 文档与类型对齐

要做什么：

- README / 中文 README 补 policy 与 merge review 用法
- frontend-sdk 类型与服务端 contract 对齐
- i18n 文案补 branch policy 相关表达

完成标准：

- 文档、UI、SDK 不再各说各话

### Phase 3：生产化与治理

#### 3.1 migration 体系优先

要做什么：

- 建立 schema migration 机制
- 把 `branches`、`merge_records`、后续 `thread_access` 纳入

完成标准：

- schema 变更不再靠 repo 内嵌 SQL 热修

#### 3.2 Postgres 仓储

要做什么：

- 抽统一 repo 接口
- 提供 Postgres 实现
- runtime 按配置切换仓储

完成标准：

- SQLite 不再承担默认生产后端职责

#### 3.3 Auth / Access Model

要做什么：

- owner / editor / viewer 角色
- thread read / write / fork / review merge 权限
- `/v1/chat/*` 与 `/v1/branches/*` 统一鉴权

完成标准：

- 多用户环境下有基本访问边界

#### 3.4 Limits 与 Audit

要做什么：

- 请求频率限制
- token / tool budget guard
- 关键动作审计日志

完成标准：

- 系统具备最小安全边界与责任追踪

### Phase 4：评测、调试与扩展能力

#### 4.1 Eval 场景集

要做什么：

- 长对话延续
- 多分支探索
- 用户拒绝 merge
- findings 部分导入
- 工具失败恢复
- interrupt resume

完成标准：

- 关键行为有稳定回归样本

#### 4.2 Replay / Debug API

要做什么：

- 线程历史查看
- checkpoint replay
- state snapshot 与事件摘要返回

完成标准：

- 出问题时可复现和诊断

#### 4.3 Metrics 与 readiness

要做什么：

- `readyz`
- `metrics`
- active streams / running turns / interrupted turns / merge pending count

完成标准：

- 部署层具备基本可观测性

#### 4.4 MCP System

要做什么：

- MCP server 配置与生命周期
- transport / stream event 接线
- 与 memory / skills 的协同

完成标准：

- Memory / Skill / MCP 三层能力具备一致架构

## 5. 推荐优先级

### P0

- `ConclusionPolicy`
- merge review 收口
- `merge_records`
- `import_memory -> MemoryWriter`

### P1

- tracing 标准化
- frontend-sdk React hook 层
- branch tree / merge review 组件化
- 文档、类型、i18n 对齐

### P2

- migration
- Postgres 仓储
- Auth / Access
- Limits / Audit

### P3

- Eval
- Replay / Debug API
- Metrics / readiness
- MCP System

## 6. 推荐执行顺序

按真实依赖关系，建议顺序如下：

1. `ConclusionPolicy`
2. merge review 收口
3. `merge_records`
4. `import_memory -> MemoryWriter`
5. tracing 标准化
6. frontend-sdk React hook
7. branch tree / merge review 组件化
8. 文档 / 类型 / i18n 对齐
9. migration
10. Postgres 仓储
11. Auth / Access
12. Limits / Audit
13. Eval
14. Replay / Debug API
15. Metrics / readiness
16. MCP System

## 7. 这份规划与旧规划的主要差异

- 不再把 Skill System 视为“未开始”，而是认定为“第一版已完成，后续再扩展”
- 不再把 frontend-sdk 视为“空白”，而是认定为“基础层已完成，React 层未做”
- 不再把 built-in Web UI 视为“只有 demo”，而是认定为“核心交互已验证，但组件化未完成”
- 不再把 `/healthz`、基础 tracing、memory package 忽略掉，而是作为已完成基线纳入
- 把真正阻塞主线的缺口重新收敛到 Phase 1

## 8. 一句话结论

新的完整规划应该建立在“基础层已经存在”这个事实上：现在最重要的不是重复铺底层，而是先把核心语义收口，再补产品接入层，最后推进生产化和评测扩展。
