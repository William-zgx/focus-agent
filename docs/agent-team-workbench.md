# Agent Team Workbench 技术方案

更新时间：2026-04-25

本文定义 Focus Agent 的 Multi-Agent Development Mode：把一次复杂开发任务拆成多个 Agent 工作分支，让每个 Agent 在隔离上下文中产出计划、代码、测试、审查与验证证据，最后通过受控 merge review 汇总回主线。

## 1. 产品目标

Focus Agent 当前已经具备分支对话、merge review、memory、trajectory observability、artifact 和 eval 基础。Agent Team Workbench 的目标不是另起一套多 Agent 平台，而是复用这些基础，把“分支对话”升级为“多 Agent 协作开发空间”。

核心用户价值：

- 用户输入一个复杂目标后，系统能拆成多个 Agent 子任务。
- 每个 Agent 在自己的 conversation branch 中工作，避免污染主线。
- 每个 Agent 的产出以 artifact、branch-local findings、trajectory 和 task ledger 记录下来。
- 主控 Agent 汇总各分支产物，生成可审查的 team merge bundle。
- 用户只把确认过的结论、补丁摘要和验证证据合并回主线。

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

MVP 阶段先支持固定角色、固定任务列表、人工可见的 merge bundle。暂不支持 Agent 无限递归 spawn、自动冲突解决或无人值守提交。

## 3. 总体架构

```text
User
  |
  v
Main Thread / Orchestrator
  |
  +-- Agent Team Session
  |     +-- Agent Task Ledger
  |
  +-- Branch: Planner Agent
  |     +-- plan artifact
  |     +-- acceptance criteria
  |
  +-- Branch: Backend Agent
  |     +-- backend patch summary
  |     +-- backend tests
  |
  +-- Branch: Frontend Agent
  |     +-- UI / SDK patch summary
  |     +-- interaction notes
  |
  +-- Branch: Test Agent
  |     +-- regression cases
  |     +-- eval cases
  |
  +-- Branch: Reviewer Agent
  |     +-- review findings
  |     +-- risk report
  |
  +-- Branch: Verifier Agent
        +-- verification report
        +-- merge readiness verdict
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
    goal: str
    scope: list[str]
    dependencies: list[str]
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
```

### 4.3 AgentTeamArtifact

AgentTeam 可以复用现有 artifact 存储，但需要在 task 记录里保存 artifact id。建议 artifact kind 包括：

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

## 5. Backend 设计

新增模块：

```text
src/focus_agent/core/agent_team.py
src/focus_agent/services/agent_team.py
```

`AgentTeamService` 职责：

- 创建 team session
- 创建 task 并按需调用 `BranchService.fork_branch()`
- 维护 task 状态
- 汇总 artifact、changed files、risk、verification
- 生成 team merge bundle
- 应用 team merge decision

建议 API：

```text
POST  /v1/agent-team/sessions
GET   /v1/agent-team/sessions
GET   /v1/agent-team/sessions/{session_id}
POST  /v1/agent-team/sessions/{session_id}/tasks
GET   /v1/agent-team/sessions/{session_id}/tasks
GET   /v1/agent-team/tasks/{task_id}
PATCH /v1/agent-team/tasks/{task_id}
POST  /v1/agent-team/tasks/{task_id}/status        # PATCH alias for compatibility
POST  /v1/agent-team/tasks/{task_id}/outputs
POST  /v1/agent-team/sessions/{session_id}/merge-bundle
POST  /v1/agent-team/sessions/{session_id}/merge-proposal # merge-bundle alias
POST  /v1/agent-team/sessions/{session_id}/merge-decision
POST  /v1/agent-team/sessions/{session_id}/merge          # merge-decision alias
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

SDK 新增 typed client：

```text
frontend-sdk/src/types.ts
frontend-sdk/src/client.ts
frontend-sdk/src/guards.ts
```

Web 新增：

```text
apps/web/src/features/agent-team/
apps/web/src/pages/agent-team/team-workbench-page.tsx
```

核心组件：

- `AgentTeamTaskBoard`
- `AgentTeamTaskCard`
- `AgentTeamTaskDetailPanel`
- `AgentTeamArtifactList`
- `AgentTeamMergeBundleCard`

页面布局：

```text
左侧：Agent Task Board
中间：当前选中 Agent branch / task detail
右侧：Artifacts / Findings / Verification
底部：Merge Bundle Review
```

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

## 8. MVP 范围

MVP 支持：

1. 创建 team session。
2. 创建多个 AgentTeamTask。
3. 每个 task 可自动 fork 出 branch。
4. UI 展示 task board。
5. task 可记录 artifact、changed files、verification summary、risk notes。
6. 生成 team merge bundle。
7. 用户选择 accepted / rejected tasks。

暂不支持：

- 真正后台并发执行 Agent。
- 自动 git worktree 隔离。
- 自动冲突解决。
- 自动提交代码。
- Agent 无限递归 spawn。

## 9. 验收标准

- 后端可以创建 session / task，并为 task 关联 branch。
- SDK 暴露完整 AgentTeam 类型和 client 方法。
- Web 可以展示 session、task board、task detail、merge bundle。
- branch tree 能看到 Agent task 分支，且角色标签合理。
- task 输出可汇总成 merge bundle。
- rejected task 不进入主线 memory。
- 至少有后端 service 测试、API shape 测试、SDK 文件测试、eval smoke case。

## 10. 推荐验证链

基础验证：

```bash
make lint
make ci-test
make sdk-check
make sdk-build
make web-check
make web-build
```

新增 eval 后补充：

```bash
uv run python -m tests.eval --suite agent_team --concurrency 1
```

## 11. 多 Agent 开发分工

- Backend Agent：`src/focus_agent/core/agent_team.py`、`src/focus_agent/services/agent_team.py`、API contract、后端测试。
- SDK Agent：`frontend-sdk/src/types.ts`、`client.ts`、`guards.ts`、exports、SDK tests。
- Web Agent：`apps/web/src/features/agent-team/`、route、shell navigation。
- Test Agent：pytest、eval dataset、Web/SDK scaffold tests。
- Reviewer / Verifier Agent：审查 diff、跑验证链、整理 merge readiness。

## 12. 风险与缓解

| 风险 | 缓解 |
| --- | --- |
| 多 Agent 写同一文件冲突 | 按 write scope 拆分，leader 最后集成共享文件 |
| branch-local finding 污染主线 | 默认只写 branch-local，merge bundle accepted 后才 promotion |
| UI 复杂度过高 | MVP 只做 task board + detail + merge bundle |
| 自动执行过早复杂化 | v0 做编排和可视化，v1 再做调度 |
| 评测不足 | 新增 `agent_team` eval suite 和 branch hygiene cases |
