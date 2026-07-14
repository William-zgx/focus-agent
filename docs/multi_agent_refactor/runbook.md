# Multi-Agent Runtime Runbook

更新时间：2026-07-13

本手册用于运行已实现、但默认关闭的 Multi-Agent v2 协调能力。它不是全量上线
声明，也不替代 [Agent Team v2 灰度与回滚手册](../agent-team-v2-rollout.md) 的
产品/发布口径。普通聊天不因本手册中的开关或工作台可见而自动进入 Team runtime。

## 1. 开关与默认状态

所有 v2 行为默认关闭：

```dotenv
MULTI_AGENT_V2_ENABLED=false
MULTI_AGENT_DAG_SCHEDULER_ENABLED=false
MULTI_AGENT_RESOURCE_LOCK_ENABLED=false
MULTI_AGENT_MESSAGE_BUS_ENABLED=false
MULTI_AGENT_ASYNC_APPROVAL_ENABLED=false
MULTI_AGENT_FAILURE_HANDLER_ENABLED=false
```

`MULTI_AGENT_V2_ENABLED` 是总开关；只有它和相应子开关均为 `true`，子能力才可
参与 v2 runtime。

| 子开关 | 已实现的作用 | 不应推断的能力 |
| --- | --- | --- |
| `MULTI_AGENT_DAG_SCHEDULER_ENABLED` | 根据依赖和 `resource_claims` 选择有界 task wave | 不会无限扩容或自动修复任意 DAG |
| `MULTI_AGENT_RESOURCE_LOCK_ENABLED` | 执行前为声明的 `resource_claims` 获取独占锁 | 未声明资源不会被自动推断或保护 |
| `MULTI_AGENT_MESSAGE_BUS_ENABLED` | 发布 task start/finish progress message | 消息存在不代表 task 已成功、已验证或已采纳 |
| `MULTI_AGENT_ASYNC_APPROVAL_ENABLED` | 将需审批工具调用记录为 pending queue 项 | 决定后不会自动重放已返回的图执行 |
| `MULTI_AGENT_FAILURE_HANDLER_ENABLED` | 对任务异常选择 retry/reassign/degrade/escalate 策略 | 不会隐去原始错误或自动解决业务问题 |

Web 的 `VITE_FOCUS_AGENT_ENABLE_AGENT_WORKBENCH` 只影响 UI 构建可见性，不能代替
上述 runtime 开关或 kill switch。

## 2. 启用前检查

先记录环境、当前配置和 readiness：

```bash
git rev-parse HEAD
git status --short --branch
curl --fail --show-error --silent http://127.0.0.1:8000/readyz
```

只有 `/readyz` 为 HTTP 200 且 `ready=true` 才开始灰度。`/healthz` 只是 liveness。

共享环境启用 v2 时应使用 PostgreSQL。没有 `DATABASE_URI` 时，Agent Team repository
会使用 in-memory fallback，不能把重启后的状态恢复、审批保留或跨实例协调说成已验证。

真实可写任务还必须满足：

- `AGENT_DELEGATION_EXECUTION_MODE=inline` 或 `background`；`observe` 不自动执行，
  `fake` 只产生测试/流程证据。
- task 有明确 `write_scope`、验收标准、测试命令和风险范围。
- 仓库根目录可执行 `git worktree`，且工作目录/分支命名不与人工任务冲突。
- 模型 provider 凭据可用，并能在 run metadata 中记录真实 `model_id`。
- 涉及命令或 Skill entrypoint 时，Docker sandbox 已准备为 fail-closed，见第 5 节。

## 3. 推荐灰度顺序

按以下顺序逐步启用；每一步失败都回退到前一已验证阶段，不要继续叠加开关：

1. 设置 `MULTI_AGENT_V2_ENABLED=true`，只验证 runtime maintenance worker 启动、`/readyz`
   正常、普通聊天仍未创建 Team task。
2. 加 `MULTI_AGENT_MESSAGE_BUS_ENABLED=true`，验证一个显式 Team task 的 start/finish
   progress message 与 task view 一致。
3. 加 `MULTI_AGENT_DAG_SCHEDULER_ENABLED=true`，验证依赖未完成的 child 保持 pending，
   同资源任务不在同一 wave，且并发不超过 `AGENT_ROLE_MAX_PARALLEL_RUNS`。
4. 加 `MULTI_AGENT_RESOURCE_LOCK_ENABLED=true`，验证锁获取、心跳、释放和过期清理；
   只对已声明的 `resource_claims` 断言。
5. 加 `MULTI_AGENT_FAILURE_HANDLER_ENABLED=true`，注入一个可控失败，保留 attempt、
   原始 error、策略和最终任务状态。
6. 最后加 `MULTI_AGENT_ASYNC_APPROVAL_ENABLED=true`，用实际需审批工具验证 pending、
   人工决定和显式重新运行的完整链路。

不要把 fixture/fake executor 通过称为“模型验证”。它们适合验证状态机和 API shape；
每个要进入更高灰度级别的真实动作，都要用真实 provider/model、真实 worktree 与
实际测试输出重跑。

## 4. 操作与证据

### DAG、锁与消息

对一个明确创建的 session 使用 `/run` 或 task-level `/run`，然后检查：

- `GET /v1/agent-team/sessions/{session_id}/view` 中的 task status、scheduler state、
  run metadata、outputs 和 `pending_tool_approvals`。
- `agent_resource_claims` 中未释放/未过期的 claim；只有声明资源的 task 应持有锁。
- `agent_messages` 中以 `session_id` 为范围的消息。LISTEN/NOTIFY 是快路径，存储记录
  才是审计来源。
- `MultiAgentMaintenanceWorker.run_once()` 或其运行时日志中的 expired lock/message、
  timed-out approval 和 deadlock 清理计数。

任务完成文本不足以证明真实执行。最小证据链必须包含 `execution_mode`、`agent_run_id`、
`delegated_task_id`、`model_id`、artifact、worktree 元数据、`changed_files`、diff、测试
原始输出及 reviewer/verifier 结论。详见 [Agent Team Workbench](../agent-team-workbench.md)。

### 审批与恢复

列出当前 session 的待处理项：

```bash
curl --fail --show-error --silent \
  "http://127.0.0.1:8000/v1/agent-team/sessions/${SESSION_ID}/tool-approvals"
```

批准或拒绝时使用 `/decision`、`/approve` 或 `/reject`，并记录 request id、决策人、
时间、风险级别和经脱敏的参数。队列决定只改变 approval record；它不会自动恢复已经
返回的 async graph run。代码中有内部 approval resume-job 状态机，可为已批准且未
取消/未 supersede 的 task 创建幂等、executor-only 的 resume job，并且不向展示 DTO
泄露 raw args/checkpoint；目前该 job 尚未被公开 API 或 runtime executor 消费。操作员
仍必须显式重新执行经过审核的 task/run，并将新的 `agent_run_id` 与原 request id 关联。

需要恢复同步 interrupt 时，必须对同一 thread/checkpoint 使用匹配的
`Command(resume=...)`、`interrupt_id` 和 `tool_call_id`。不要用审批队列 API 伪造
该恢复，也不要把旧 pending request 直接标为“已执行”。

## 5. Worktree 与 Docker fail-closed

可写 task 在真实 delegated executor 中可创建：

```text
.focus_agent/worktrees/{session_id}/{task_id}
codex/agent-team/{session-short}/{task-slug}-{task-short}
```

检查 worktree 时保留：

```bash
git -C "$WORKSPACE_PATH" status --short
git -C "$WORKSPACE_PATH" diff --check
git -C "$WORKSPACE_PATH" diff --stat
```

worktree 只隔离 Git 工作目录，不会隔离命令执行、网络或密钥。对 workspace command
和 Skill entrypoint 的安全执行，目标环境必须使用：

```dotenv
FOCUS_AGENT_SANDBOX_BACKEND=docker
FOCUS_AGENT_SANDBOX_ALLOW_LOCAL_FALLBACK=0
```

Docker 不可用或 image 缺失时，该配置应直接失败。开发环境的
`local_subprocess` / `local_venv`、`fallback_used=true` 或
`degraded_reason=local_host_execution` 只能记录为降级开发证据，绝不能写成 Docker
隔离已经通过。

## 6. 事故处理与 Kill Switch

先停止新执行，再保留现场。推荐 kill switch 配置：

```dotenv
MULTI_AGENT_V2_ENABLED=false
MULTI_AGENT_DAG_SCHEDULER_ENABLED=false
MULTI_AGENT_RESOURCE_LOCK_ENABLED=false
MULTI_AGENT_MESSAGE_BUS_ENABLED=false
MULTI_AGENT_ASYNC_APPROVAL_ENABLED=false
MULTI_AGENT_FAILURE_HANDLER_ENABLED=false
AGENT_DELEGATION_EXECUTION_MODE=observe
```

重启 API 后检查 `/readyz`，并确认新普通聊天未产生 Team task/worktree。不要为完成
回滚而删除 worktree、锁、消息或审批记录；先导出 session/task、配置、deployment、
diff 和日志证据。

| 症状 | 先检查 | 处置 |
| --- | --- | --- |
| 任务卡在资源等待 | claim 所有者、TTL/heartbeat、任务依赖 | 让过期锁由维护任务清理；必要时关闭 resource lock 子开关并重新灰度 |
| 进度缺失 | `agent_messages`、session view、message bus flag | 以存储记录为准，不用 UI 空白推断 task 失败 |
| 审批积压/超时 | pending request、超时、决定人 | 决定或拒绝请求，再显式重新运行；超时项不能自动批准 |
| merge conflict | merge bundle `risk_items`、worktree diff、主树 diff | 人工解决重叠；不要自动 apply 或覆盖主树 |
| Docker 不可用 | sandbox payload、镜像、daemon | fail-closed 环境保持失败；不得切到 local fallback 以制造通过结果 |

## 7. 验证与发布限制

至少执行：

```bash
uv run pytest tests/test_multi_agent_config.py \
  tests/test_agent_team_multi_agent.py \
  tests/test_agent_team_approval_resume.py \
  tests/integration/multi_agent/test_acceptance.py -q
make ui-smoke-agent-team-adoption
make agent-team-evidence
```

这些仍不足以证明真实浏览器与真实模型。`make ui-smoke-agent-team-adoption` 是源码接线
smoke。`make agent-team-evidence` 运行 Agent Team worktree/chat 的测试和确定性 UI
fixture；其 `scripts/agent_team_ui_smoke.py --mode real` 当前明确返回 `disabled`，
不会启动浏览器或 provider。真实用户流程必须在 Chrome 中完成 session 创建、证据查看、
审批决定、显式重新运行和 merge review。真实模型验证必须记录 provider/model、请求/
运行 metadata、输出 artifact 和测试结果。完整本地与发布证据链见
[Validation Runbook](../validation-runbook.md)。
