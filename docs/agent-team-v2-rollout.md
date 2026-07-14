# Agent Team v2 灰度与回滚手册

更新时间：2026-07-14

本文定义 Agent Team v2 的可验证灰度口径。它只描述已在当前代码中
受 feature flag 保护的协调能力；不是“v2 已全量上线”的声明。工作台 UI
可见、Agent Team v1 API 可访问，均不表示 v2 runtime 已启用或真实执行已 ready。

Postgres 应用 schema **v19** 已包含 v2 结构化表（revisions、attempts、jobs、
leases、evidence 等）；**有表不等于执行路径已打开**。

关联文档：

- [Project Overview](project-overview.md)
- [Agent Team Workbench](agent-team-workbench.md)
- [Architecture](architecture.md)
- [Multi-Agent Runtime Runbook](multi_agent_refactor/runbook.md)
- [Agent Governance](agent-role-routing.md)
- [Validation Runbook](validation-runbook.md)
- [Roadmap](roadmap.md)

## 1. 默认状态与隔离

下列设置在 `Settings` 中的默认值均为 `false`：

```dotenv
MULTI_AGENT_V2_ENABLED=false
MULTI_AGENT_DAG_SCHEDULER_ENABLED=false
MULTI_AGENT_RESOURCE_LOCK_ENABLED=false
MULTI_AGENT_MESSAGE_BUS_ENABLED=false
MULTI_AGENT_ASYNC_APPROVAL_ENABLED=false
MULTI_AGENT_FAILURE_HANDLER_ENABLED=false
```

`MULTI_AGENT_V2_ENABLED` 是 v2 的总开关。子开关即使被设置为 `true`，
也不应在总开关关闭时改变 v2 执行路径。普通聊天继续走既有聊天图；
它不会因为用户输入复杂、工作台在导航中可见，或 Agent Team session
存在而自动创建 Team task、worktree、锁或消息。

`VITE_FOCUS_AGENT_ENABLE_AGENT_WORKBENCH` 只控制非 Android Web 构建中的
工作台可见性，不等同于 v2 runtime 总开关。需要临时隐藏入口时，将其设为
`false` 并重新构建 Web；不能把隐藏入口当成执行层 kill switch。

## 2. 灰度前置条件

在改变任何开关前，记录：

```bash
git rev-parse HEAD
git status --short --branch
curl --fail --show-error --silent http://127.0.0.1:8000/readyz
curl --fail --show-error --silent http://127.0.0.1:8000/v2/agent-team/readiness
```

只有 `/readyz` 返回 HTTP 200 且响应中的 `ready=true` 时，才开始灰度。
`/healthz` 只说明进程存活，不能替代 readiness。`/v2/agent-team/readiness`
由 router 调用 `build_agent_team_readiness(settings, runtime=runtime)`，并仅在其
`phase=ready` 且 task-run、evidence、revision 三项 v2 service capability 都可用时
返回 `ready=true`。当配置请求真实执行时，该 assessment 会检查 provider 凭据引用、
Postgres/durable worker/coordination、fencing、locks 和 Docker fail-closed 等前置
条件。该响应不执行任务，也不返回完整 blockers/evidence payload；因此即使
`ready=true`，仍需独立的 provider/Docker 实测和真实 run 证据，不能单独宣称
“真实 run 已成功”或“已上线”。

共享或生产环境的真实执行需要 Postgres repository、Postgres durable job backend/worker
和 Postgres coordination backend。`PostgresAgentTeamRepository` 会将 v2 task run、
checkpoint、tool execution、evidence 和 event 写入 schema v19 的 additive 表；只有
未配置 `DATABASE_URI` 的本地 repository 才使用 per-repository in-memory fallback。
但 approval resume store/task state 仍是 in-memory adapter，公开 runtime 也不会消费
resume job。重启或多进程切换后，不能把审批恢复或 exactly-once 语义说成已验证。

若灰度包含真实写入，先准备以下条件：

1. 受控仓库根目录可由服务进程执行 `git worktree`。
2. 真实执行模式为 `AGENT_DELEGATION_EXECUTION_MODE=inline` 或
   `background`，而不是 `observe` 或 `fake`。
3. 任务拥有明确的 `write_scope`、验收标准和测试命令；不得以空范围的
   workspace 写入作为生产配置。
4. 配置了真实模型 provider、模型和凭据；测试记录中应能看到实际
   `model_id`，不能以 fixture 或 fake executor 代替。
5. 配置 `AGENT_TEAM_V2_ENABLED=true`、非 `off` 的
   `AGENT_TEAM_ROLLOUT_PHASE`、`AGENT_TEAM_EXECUTION_MODE`、并解除默认启用的
   `AGENT_TEAM_KILL_SWITCH_ENABLED=true`；同时通过完整的 Agent Team readiness
   assessment 确认没有 blocker。仅打开 `MULTI_AGENT_*` 不会满足这些前置条件。
6. 若任务会调用 workspace command 或 Skill entrypoint，Docker sandbox
   镜像已就绪，且目标环境采用 fail-closed 配置，见第 5 节。

## 3. 推荐灰度顺序

每一步都要完成该步骤的证据检查后再继续；不要求一次开启全部能力。

| 阶段 | 设置 | 要验证的行为 | 允许前进的证据 |
| --- | --- | --- | --- |
| 0 | 所有 v2 开关为 `false` | 普通聊天与既有 Agent Team 流程不变 | 普通聊天、`/readyz`、当前基线均正常 |
| 1 | 仅 `MULTI_AGENT_V2_ENABLED=true` | 维护 worker 启动；未启用子能力 | 启动日志、`/readyz`、一个只读 Team session |
| 2 | 加 `MULTI_AGENT_MESSAGE_BUS_ENABLED=true` | 任务开始/结束产生 progress message | session view、消息存储和任务时间线一致 |
| 3 | 加 `MULTI_AGENT_DAG_SCHEDULER_ENABLED=true` | 依赖完成前子任务保持 pending；同一 wave 有界 | task 状态、wave、并发上限和依赖顺序 |
| 4 | 加 `MULTI_AGENT_RESOURCE_LOCK_ENABLED=true` | 冲突 `resource_claims` 不会同时进入同一执行波次 | 锁记录、等待原因、释放/过期清理结果 |
| 5 | 加 `MULTI_AGENT_FAILURE_HANDLER_ENABLED=true` | 失败策略可见且不会静默掩盖失败 | 原始 error、attempt、最终状态和策略记录 |
| 6 | 加 `MULTI_AGENT_ASYNC_APPROVAL_ENABLED=true` | 高风险工具请求进入 pending queue | 请求、人工决定、后续重新执行的独立证据 |

阶段 6 不是 durable queue 或自动恢复承诺：当前异步审批会把需要审批的工具调用记录为
pending，并让该次图执行继续返回“等待审批”的工具结果。批准或拒绝
`/v1/agent-team/sessions/{session_id}/tool-approvals/{request_id}/decision`
不会自动重放已经结束的图。代码中有内部 approval resume-job 状态机：它会对已批准、
仍可恢复的 task 创建幂等、executor-only job，并将 raw args/checkpoint 与脱敏展示
DTO 分离；但当前公开 API/运行时尚未消费该 job，且默认 store/task state 不持久化，
因此它不是已上线的自动恢复或重启恢复能力。
操作员必须显式重新发起受控的 task/run，并把新 run 的 request id、决定、执行结果
和产物关联起来。

同步 LangGraph interrupt 的 `Command(resume=...)` 是另一条恢复路径；它要求
保留原 thread/checkpoint 和匹配的 `interrupt_id`、`tool_call_id`。不要把
它与异步审批队列 API 混为同一个“自动 resume”能力。

## 4. 真实执行证据链

只有下列信息能够组成“真实执行过”的最小证据链：

```text
session/task id
  -> execution_mode=inline|background
  -> agent_run_id + delegated_task_id + model_id
  -> artifact ids / task output
  -> workspace_id + workspace_path + workspace_branch + base_commit
  -> changed_files + diff_summary + workspace_status
  -> executed test command and result
  -> reviewer/verifier conclusion and explicit merge-review decision
```

检查来源应优先是 `GET /v1/agent-team/sessions/{session_id}/view`、task
output/metadata、worktree 中的 `git diff --check`、测试原始输出及 merge-review
event。最终答案、任务摘要、`changed_files` 字段或单独的“tests passed”文本都
不是充分证据。

以下状态不能被宣称为真实可采纳代码变更：

- `execution_mode=fake`：用于流程、UI 或测试夹具验证；不会创建真实
  task worktree。
- `execution_mode=observe`：没有自动 delegated execution。
- 无 `agent_run_id`、`model_id`、artifact、workspace 元数据或可复现测试输出。
- Docker sandbox payload 标记 `fallback_used=true`、`degraded_reason=local_host_execution`
  或 `sandbox_backend=local_subprocess` / `local_venv`。

Merge review 必须显式预览和 apply；系统不应自动 commit、push 或合并
`main`。fake output 被 merge review 标记为不可采纳，不能通过人工修改文案
绕过该边界。

## 5. Worktree 与 Docker 边界

可写 Team task 仅在真实 delegated executor（`inline` 或 `background`）下尝试
创建 worktree。当前路径是：

```text
.focus_agent/worktrees/{session_id}/{task_id}
```

当前分支名格式是：

```text
codex/agent-team/{session-short}/{task-slug}-{task-short}
```

`base_commit` 来自创建时的 `HEAD`。worktree 是 Git 变更隔离，不是容器隔离；
不要因为存在 worktree 就声称命令、网络或密钥已经被沙箱保护。

Docker fail-closed 适用于 workspace command 与 Skill entrypoint 的 sandbox
执行。目标环境必须设置：

```dotenv
FOCUS_AGENT_SANDBOX_BACKEND=docker
FOCUS_AGENT_SANDBOX_ALLOW_LOCAL_FALLBACK=0
```

`compose.prod.yaml` 已使用这两个值。Docker 不可用或镜像缺失时，执行应失败，
而不是退回 host subprocess。开发环境的 `auto` backend 默认允许本地 fallback，
只能产生带降级元数据的开发证据，不能作为 Docker 隔离或生产安全证据。

## 6. Kill Switch 与事故处理

立即停止 v2 协调行为：

```dotenv
MULTI_AGENT_V2_ENABLED=false
MULTI_AGENT_DAG_SCHEDULER_ENABLED=false
MULTI_AGENT_RESOURCE_LOCK_ENABLED=false
MULTI_AGENT_MESSAGE_BUS_ENABLED=false
MULTI_AGENT_ASYNC_APPROVAL_ENABLED=false
MULTI_AGENT_FAILURE_HANDLER_ENABLED=false
AGENT_TEAM_KILL_SWITCH_ENABLED=true
AGENT_TEAM_EXECUTION_MODE=disabled
AGENT_DELEGATION_EXECUTION_MODE=observe
```

重启 API 后确认 `/readyz`。`AGENT_TEAM_KILL_SWITCH_ENABLED=true` 是执行层的
主要 kill switch；同时关闭协调开关、禁用 Agent Team execution 并把 delegation
退回 `observe` 是为了降低配置歧义。不要删除 worktree、锁、消息或审批记录来
“完成回滚”：先保留现场证据，再按任务级别取消、清理或人工处置。

常见处理顺序：

1. 停止新 run，记录 session/task/request id、部署版本和当前开关。
2. 对卡住任务检查依赖、resource claim、pending approval 和 background job。
3. 对真实 worktree 保存 `git status --short`、`git diff --check` 与 diff；不要
   直接在主工作区覆盖变更。
4. 对审批超时、拒绝或重启后丢失的等待，保留原 request，重新创建受控 run；
   不把旧 pending 直接标为已执行。
5. 修复后从阶段 0 或造成故障的前一阶段重新灰度。

## 7. 验证矩阵

每次 v2 灰度至少保留以下独立证据：

- **配置与 readiness：** 有效开关快照、部署标识、`/readyz` 和
  `/v2/agent-team/readiness` 原始 JSON，以及完整 readiness assessment 的
  blockers/evidence；前两者均不能单独证明真实执行 ready。
- **调度：** DAG、wave、依赖、并发上限、资源锁和任务状态。
- **审批：** redacted approval request、批准/拒绝主体与时间、显式重新运行结果；
  不宣称队列、resume-job 或当前内存记录可跨重启恢复。
- **真实执行：** 真实 provider/model、run metadata、artifact、worktree diff 和测试输出。
- **浏览器：** 真实 Chrome 完成创建、查看证据、审批决定、重新运行和 merge review；
  `pnpm --dir apps/web smoke:agent-team-adoption` 仅检查源码接线，不是浏览器证据；
  `make agent-team-evidence` 的 UI 部分也是确定性 fixture，`--mode real` 当前返回
  `disabled`，同样不能作为浏览器证据。
- **回滚：** kill-switch 后的新普通聊天仍不创建 Team task/worktree，且现有
  session 证据可读。

完整命令和验收禁区见 [Validation Runbook](validation-runbook.md) 与
[Multi-Agent Runtime Runbook](multi_agent_refactor/runbook.md)。
