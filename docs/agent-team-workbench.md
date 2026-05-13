# Agent Team Workbench 操作与实现手册

更新时间：2026-05-05

本文记录 Focus Agent 当前的 Multi-Agent Development Mode：用户输入一个目标后，由 Orchestrator 生成动态 Mission DAG，多 Agent 按依赖执行任务、回传证据与风险，最终汇总成面向用户目标的 `final_answer`。工程 merge bundle 仍保留为高级审查能力，但默认用户体验以“目标 -> 任务进度 -> Agent Team 最终答案”为主。

当前已落地的入口包括 `/app/agent-team` Mission Runner、`/v1/agent-team/*` API、frontend SDK 的 Agent Team client 方法、Postgres/SQLite repository、模型优先 planning service、DAG run service 和 legacy dispatch 兼容入口。本文不再作为历史方案草稿保存；新改动应把这里当作当前操作和验证手册维护。

## 1. 产品目标

Focus Agent 当前已经具备分支对话、merge review、memory、trajectory observability、artifact 和 eval 基础。Agent Team Workbench 的目标不是另起一套多 Agent 平台，而是复用这些基础，把“分支对话”升级为“多 Agent 协作开发空间”。

核心用户价值：

- 用户输入一个复杂目标后，系统能由模型或保守 fallback 拆成多个 Agent 子任务。
- 每个 Agent 在自己的 conversation branch 中工作，避免污染主线。
- 每个 Agent 的产出以 artifact、branch-local findings、trajectory 和 task ledger 记录下来。
- 主控 Agent 汇总各分支产物，生成用户可读的 Agent Team 最终答案。
- Reviewer / Verifier 证据不足时默认 `request_changes`，fake mode 只验证流程，不会被标为可交付。

## 2. 设计原则

### 2.1 主线只保留稳定共识

Agent 分支里的探索、失败尝试和临时推理默认不进入主线。只有通过 team merge review 被接受的内容，才进入主线 thread、main memory 或后续执行任务。

### 2.2 Agent 分支就是工作上下文隔离单元

每个 Agent task 对应一个 branch：

- planner branch：方案和验收标准
- backend branch：后端模型、service、API
- frontend branch：SDK、页面、组件、交互
- test branch：单测、eval、smoke
- reviewer branch：代码审查与风险报告
- verifier branch：验证证据与 merge readiness

### 2.3 协作过程必须可审计

每个 Agent task 需要记录：

- 输入任务与 scope
- branch / thread id
- 状态流转
- 产出 artifact
- changed files
- test evidence
- risk notes
- trajectory refs

### 2.4 先做受控并行，不做无限自治

当前版本支持模型优先的动态任务 DAG、bounded ready-task scheduler、人工可见的最终答案和高级 merge bundle。暂不支持 Agent 无限递归 spawn、自动冲突解决或无人值守提交。

### 2.5 治理与自治先观察后执行

Agent Team Workbench 可以展示 Agent Governance / Autonomy 的建议，但当前版本不把这些建议直接升级成高风险动作：

- skill selection 只输出推荐 skills 和可用 `skills_list` / `skill_view` evidence。
- branch suggestion 只输出 role/run isolation key，作为创建分支或分配 worker 的建议。
- risk-aware workflow policy 只输出 denied tool、review queue、model route rationale 和风险报告。
- workspace write、merge、memory promotion、无人值守提交仍需显式执行入口或人工确认。

## 3. 总体架构

```text
User
  |
  v
Main Thread / Orchestrator
  |
  +-- Agent Team Mission
  |     +-- Dynamic Task DAG
  |     +-- Agent Task Ledger
  |
  +-- Branch: Planner Agent
  |     +-- plan artifact
  |     +-- acceptance criteria
  |
  +-- Branch: Executor / Writer Agent
  |     +-- implementation or user-facing deliverable
  |     +-- changed files / artifacts
  |
  +-- Branch: Test Agent
  |     +-- regression cases
  |     +-- eval cases
  |
  +-- Branch: Reviewer Agent
  |     +-- review findings
  |     +-- risk report
  |
  +-- Branch: Verifier / Integrator Agent
        +-- verification report
        +-- final_answer / merge recommendation
```

复用现有能力：

| 能力 | 当前基础 | Agent Team 用途 |
| --- | --- | --- |
| Branch tree | `BranchService`、branch UI | 每个 Agent 一个工作分支 |
| Branch role | `explore / execute / verify / writeup` | 映射 Agent 工作职责 |
| Merge review | proposal / decision | 汇总 Agent 产物回主线 |
| Memory | branch-local / main memory | 分支发现先本地保存 |
| Task ledger | agent task ledger | 记录协作任务拆分 |
| Trajectory | observability workbench | 审计每个 Agent 执行过程 |
| Artifact | text artifact store | 保存 plan、patch summary、test report |
| Eval | `tests/eval/` | 验证多 Agent 协作质量 |

## 4. 数据模型

### 4.1 AgentTeamSession

```python
class AgentTeamSession:
    session_id: str
    root_thread_id: str
    user_id: str
    title: str
    goal: str
    status: Literal[
        "planning",
        "running",
        "awaiting_review",
        "merging",
        "completed",
        "failed",
        "cancelled",
    ]
    created_at: str
    updated_at: str
    planning_source: Literal["model", "fallback_heuristic", "legacy_template"] | str | None
    planning_rationale: str | None
    planner_model_id: str | None
    plan_generated_at: str | None
    plan_hash: str | None
    planning_error: str | None
```

### 4.2 AgentTeamTask

```python
class AgentTeamTask:
    task_id: str
    session_id: str
    branch_id: str | None
    child_thread_id: str | None
    role: Literal[
        "planner",
        "architect",
        "backend_executor",
        "frontend_executor",
        "test_engineer",
        "reviewer",
        "verifier",
        "writer",
    ]
    title: str | None
    goal: str
    scope: list[str]
    dependencies: list[str]
    acceptance_criteria: list[str]
    planning_rationale: str | None
    task_type: Literal[
        "research",
        "implementation",
        "verification",
        "review",
        "documentation",
        "coordination",
    ] | str | None
    plan_source: str | None
    context_refs: list[dict]
    status: Literal[
        "pending",
        "running",
        "blocked",
        "done",
        "failed",
        "cancelled",
    ]
    output_artifact_ids: list[str]
    changed_files: list[str]
    verification_summary: str | None
    risk_notes: list[str]
    started_at: str | None
    finished_at: str | None
    last_error: str | None
```

### 4.3 AgentTeamTaskOutput / AgentTeamArtifact

AgentTeam task output 是最终答案和高级详情的主要证据来源。每个 output 至少保存 `summary`，并可附带 artifact id、changed files、test evidence、risk notes 和 execution metadata。Artifact 可以复用现有存储，但需要在 task/output 记录里保存 artifact id。建议 artifact kind 包括：

- `plan`
- `patch_summary`
- `test_report`
- `review_report`
- `risk_report`
- `handoff`
- `merge_summary`

### 4.4 AgentTeamMergeBundle

```python
class AgentTeamMergeBundle:
    session_id: str
    summary: str
    final_answer: str | None
    final_answer_status: Literal["ready", "placeholder", "blocked", "error"] | str | None
    final_answer_warnings: list[str]
    source_output_ids: list[str]
    accepted_tasks: list[str]
    rejected_tasks: list[str]
    key_findings: list[str]
    changed_files: list[str]
    test_evidence: list[str]
    open_questions: list[str]
    risk_items: list[str]
    recommended_next_action: Literal[
        "merge",
        "request_changes",
        "split_followup",
        "discard",
    ]
```

### 4.5 OwnershipAuditDashboard

Ownership Audit Dashboard 复用 `OwnershipAuditEvent`，额外通过 report/export helper 汇总审计视图：

```python
class OwnershipAuditDashboard:
    total_events: int
    allow_count: int
    deny_count: int
    deny_rate: float
    deny_reasons: dict[str, int]
    deny_by_resource_type: dict[str, int]
    deny_by_action: dict[str, int]
    deny_by_principal: dict[str, int]
    deny_trend: list[dict[str, str | int | None]]
```

`deny_trend` 按审计事件出现顺序保留 request id 和累计 deny 数，用于 Dashboard 展示最近一段时间的拒绝走势。它只读审计轨迹，不改变 owner 判断。

## 5. Backend 设计

核心模块：

```text
src/focus_agent/core/agent_team.py
src/focus_agent/services/agent_team.py
src/focus_agent/services/agent_team_planning.py
src/focus_agent/services/agent_team_run.py
src/focus_agent/services/agent_team_merge.py
```

`AgentTeamService` 职责：

- 创建 team session
- 读取 Mission goal、来源 thread 和已有任务，生成或刷新动态任务 DAG
- 创建 task 并按需调用 `BranchService.fork_branch()`
- 按依赖运行 ready tasks，支持 fake / inline / background execution mode
- 维护 task 状态
- 汇总 artifact、changed files、risk、verification
- 生成用户态 `final_answer` 和高级 team merge bundle
- 应用 team merge decision
- 汇总 ownership audit report，用于 Dashboard 展示 deny reason 和 deny trend

`AgentTeamPlanningService` 默认走模型结构化规划；模型不可用、校验失败或 repair 失败时使用 2-3 个保守 fallback 任务，并在 session 上记录 `planning_source="fallback_heuristic"` 与 `planning_error`。Legacy `/dispatch` 仍保留，但 Web 主流程使用 `/plan`。

`AgentTeamRunService` 会运行依赖已满足的 ready tasks。fake mode 只用于流程验证；当 merge bundle 检测到 fake output 或 `Fake delegated...` summary 时，`final_answer_status` 必须是 `placeholder`，`recommended_next_action` 必须是 `request_changes`。

当前 API：

```text
POST  /v1/agent-team/sessions
GET   /v1/agent-team/sessions
GET   /v1/agent-team/sessions/{session_id}
GET   /v1/agent-team/sessions/{session_id}/view
POST  /v1/agent-team/sessions/{session_id}/plan
POST  /v1/agent-team/sessions/{session_id}/run
POST  /v1/agent-team/sessions/{session_id}/cancel
POST  /v1/agent-team/sessions/{session_id}/dispatch        # legacy template/fallback入口
POST  /v1/agent-team/sessions/{session_id}/tasks
GET   /v1/agent-team/sessions/{session_id}/tasks
GET   /v1/agent-team/tasks/{task_id}
PATCH /v1/agent-team/tasks/{task_id}
POST  /v1/agent-team/tasks/{task_id}/run
POST  /v1/agent-team/tasks/{task_id}/retry
POST  /v1/agent-team/tasks/{task_id}/cancel
POST  /v1/agent-team/tasks/{task_id}/outputs
POST  /v1/agent-team/sessions/{session_id}/merge-bundle
POST  /v1/agent-team/sessions/{session_id}/merge-decision
```

Compatibility aliases still exist with deprecation headers and are hidden from the OpenAPI schema:

```text
POST  /v1/agent-team/tasks/{task_id}/status                 # use PATCH /tasks/{task_id}
POST  /v1/agent-team/sessions/{session_id}/merge-proposal   # use /merge-bundle
POST  /v1/agent-team/sessions/{session_id}/merge            # use /merge-decision
```

### 5.1 持久化仓储

Agent Team Workbench 已接入 runtime 的主持久化选择：

- 设置 `DATABASE_URI` 时使用 `PostgresAgentTeamRepository`，随 Postgres schema v2 初始化表结构。
- 未设置 `DATABASE_URI` 且直接裸跑 API 时使用 `SQLiteAgentTeamRepository`，作为本地 fallback。
- 通过 `make api`、`make dev`、`make serve`、`make serve-dev`、`make serve-prod` 启动时，如果没有显式 `DATABASE_URI`，启动脚本会托管 repo-local PostgreSQL 并注入 `DATABASE_URI`，因此 Agent Team 也走 Postgres primary persistence。

Postgres 表名固定为：

```text
focus_agent_team_sessions
focus_agent_team_tasks
focus_agent_team_outputs
```

每张表都保留 `data_json JSONB NOT NULL` 作为 Pydantic model 的完整 round-trip 来源；其他列只做查询、排序和索引辅助。schema migration v2 会在已有 v1 数据库上继续创建 Agent Team 表，不依赖全新数据库。

当前不会自动把已有 SQLite fallback 数据迁移到 Postgres。需要跨后端迁移时，应通过显式迁移流程处理。

## 6. Frontend / SDK 设计

SDK typed client 入口：

```text
frontend-sdk/src/types.ts                 public type barrel
frontend-sdk/src/types/agent-team.ts      Agent Team domain types
frontend-sdk/src/client.ts                FocusAgentClient facade
frontend-sdk/src/client/agent-team.ts     Agent Team endpoint mixin
frontend-sdk/src/guards.ts
```

Web 新增：

```text
apps/web/src/features/agent-team/
apps/web/src/pages/agent-team/team-workbench-page.tsx
```

核心组件：

- `AgentTeamWorkbench`
- `CreateSessionPanel`
- `TaskLanesPanel`
- `TaskDetailPanel`
- `PreMergeCheckPanel`
- `MergeBundleCard`
- `useAgentTeamWorkbenchViewModel`

页面布局：

```text
顶部：Mission 标题、用户态状态、一个主 CTA、更多菜单
中部：三步进度（生成方案 / 执行任务 / 查看结果）
左侧：紧凑任务时间线
下方：选中任务的拆解原因、验收标准、结果摘要、关键依据和需要注意
右侧：Agent Team 最终答案、依据、需要注意
高级详情：planning metadata、DAG、branch/thread、output ids、artifact ids、raw evidence
```

默认用户态不展示 branch id、artifact id、raw fake run text、execution metadata 或状态机原文；这些信息只在高级详情中用于调试和审查。Chat 页面侧栏也不再展示 Agent Team / 管理后台入口，这两个入口保留在登录/账号入口页和各自工作区内部导航中。

## 7. Agent 角色映射

| Agent role | BranchRole | 默认职责 |
| --- | --- | --- |
| planner | `deep_dive` | 方案、验收标准、任务拆分 |
| architect | `deep_dive` | 架构边界、接口、风险 |
| backend_executor | `execute` | service/API/repository/schema |
| frontend_executor | `execute` | SDK、页面、组件、交互 |
| test_engineer | `verify` | 单测、eval、smoke |
| reviewer | `verify` | diff review、风险、边界检查 |
| verifier | `verify` | 验证链、证据、merge readiness |
| writer | `writeup` | 文档、release notes、handoff |

## 8. 当前能力与边界

当前支持：

1. 创建 team session。
2. 通过 `/plan` 基于目标生成动态任务 DAG；`replace_existing=true` 可重拆未运行任务。
3. 模型规划不可用时自动降级到保守 fallback，并在 UI 中提示。
4. 通过 `/run` 或 task-level `/run` 按依赖推进 ready tasks。
5. task 可记录 output、artifact、changed files、verification summary、risk notes 和 execution metadata。
6. UI 默认展示紧凑任务进度、选中任务摘要和 Agent Team 最终答案。
7. 生成带 `final_answer`、`final_answer_status`、warnings 和 source output ids 的 merge bundle。
8. 用户记录 accepted / rejected tasks 的 merge decision。
9. Legacy `/dispatch` 继续兼容旧客户端，但不再是 Web 主流程。

当前仍不支持：

- 自动 git worktree 隔离。
- 自动冲突解决。
- 自动提交代码。
- Agent 无限递归 spawn。
- fake mode 生成真实交付内容。fake 只能证明流程走通，最终答案必须标记为 `placeholder`。

## 9. 验收标准

- 后端可以创建 session / task，并为 task 关联 branch。
- `/plan` 能生成动态 DAG，重复调用默认幂等，`replace_existing=true` 可重拆。
- `/run` 只推进依赖满足的 ready tasks，并把 output / artifact / evidence 回写到 session view。
- fake output 会生成 `placeholder` final answer，不能显示为可交付。
- fixture/真实 output 能生成 `ready` final answer，并包含用户目标相关内容。
- SDK 暴露完整 AgentTeam 类型和 client 方法。
- Web 可以展示 Mission header、任务时间线、选中任务摘要、Agent Team 最终答案和高级详情。
- branch tree 能看到 Agent task 分支，且角色标签合理。
- task 输出可汇总成 merge bundle。
- rejected task 不进入主线 memory。
- 至少有后端 service 测试、API shape 测试、SDK 文件测试、eval smoke case。

## 10. 推荐验证链

基础验证：

```bash
make ci
```

`make ci` 当前覆盖 Ruff lint、CI 风格 pytest、API/SDK contract snapshot、frontend SDK check/build/transport validation、Web lint/format-check/check/build，以及 Node stream frontend regression。

Agent Team focused regression：

```bash
.venv/bin/python -m pytest tests/test_agent_team_* -q
pnpm --filter @focus-agent/web-app check
pnpm --filter @focus-agent/web-sdk check
pnpm --filter @focus-agent/web-sdk build
```

新增 eval 后补充：

```bash
uv run python -m tests.eval --suite agent_team --concurrency 1
```

Nightly / Governance Dashboard 可以额外生成质量汇总 report：

```bash
make agent-governance-report

.venv/bin/python scripts/agent_governance_report.py \
  --report-json reports/agent-governance/latest.json \
  --eval-report delegation=reports/release-gate/eval-agent-delegation.json \
  --eval-report governance=reports/release-gate/eval-agent-governance.json \
  --eval-report task-ledger=reports/release-gate/eval-agent-task-ledger.json \
  --eval-report agent-team=reports/release-gate/eval-agent-team.json
```

该 report 保持 `meta` / `commands` / `artifacts` / `summary` 风格，并额外提供 `quality`：

- `delegation`：汇总 delegation、task ledger、agent team 相关 tag 的成功率
- `critic`：汇总 critic、critic gate、reviewer 相关质量信号
- `review`：汇总 review queue、merge review、memory curator 相关质量信号
- `cost`：汇总平均成本、输入输出 token 和工具调用数

Dashboard 侧只需要读取 `summary.status`、`summary.quality_attention` 和 `quality.*.task_success` 即可给出夜间回归状态，不需要重新跑 eval。

## 11. 多 Agent 开发分工

- Backend Agent：`src/focus_agent/core/agent_team.py`、`src/focus_agent/services/agent_team.py`、API contract、后端测试。
- SDK Agent：`frontend-sdk/src/types.ts`、`frontend-sdk/src/types/agent-team.ts`、`frontend-sdk/src/client.ts`、`frontend-sdk/src/client/agent-team.ts`、`guards.ts`、exports、SDK tests。
- Web Agent：`apps/web/src/features/agent-team/`、route、shell navigation。
- Test Agent：pytest、eval dataset、Web/SDK scaffold tests。
- Reviewer / Verifier Agent：审查 diff、跑验证链、整理 merge readiness。

## 12. 风险与缓解

| 风险 | 缓解 |
| --- | --- |
| 多 Agent 写同一文件冲突 | 按 write scope 拆分，leader 最后集成共享文件 |
| branch-local finding 污染主线 | 默认只写 branch-local，merge bundle accepted 后才 promotion |
| UI 复杂度过高 | 保持 task board、detail、artifact/risk/verification 和 merge bundle 的固定信息架构 |
| 自动执行过早复杂化 | 当前只做默认 dispatch 和可视化，递归调度、冲突解决和无人值守提交继续留在显式执行路径之外 |
| 评测不足 | 新增 `agent_team` eval suite 和 branch hygiene cases |
