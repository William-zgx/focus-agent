# Multi-Agent Runtime Runbook

## Feature Flags

All new behavior is off unless `multi_agent_v2_enabled=true`.

- `multi_agent_dag_scheduler_enabled`: use DAG wave scheduling.
- `multi_agent_resource_lock_enabled`: acquire task `resource_claims` before execution.
- `multi_agent_message_bus_enabled`: publish task progress events.
- `multi_agent_async_approval_enabled`: queue required tool approvals instead of interrupting the graph.
- `multi_agent_failure_handler_enabled`: use retry/reassign/degrade/escalate decisions.

Recommended gray order:

1. Enable `multi_agent_v2_enabled` and `multi_agent_message_bus_enabled`.
2. Add DAG scheduling after progress messages are visible.
3. Add resource locks for teams with known `resource_claims`.
4. Add async approvals after reviewers can see `/tool-approvals`.
5. Add failure handling after retry/reassign/degrade metrics are monitored.

## Operational Checks

- Resource locks: inspect `agent_resource_claims` for unreleased, unexpired rows.
- Messages: inspect `agent_messages` for unacked rows by `session_id` and `target_agent`.
- Approval queue: inspect `tool_approval_requests` where `status='pending'`.
- Runtime maintenance: when `multi_agent_v2_enabled=true`, `MultiAgentMaintenanceWorker` starts with the API runtime and runs cleanup/watchdog hooks for expired locks, expired messages, timed-out approvals, and deadlock checks.
- Agent Team approvals: poll `GET /v1/agent-team/sessions/{session_id}/tool-approvals` or inspect `/view` field `pending_tool_approvals`; decide with `/approve`, `/reject`, or `/decision`.
- Performance watchpoints: average wait time for tasks in `waiting_resource_lock`, pending approval age, unacked message count, and cleanup counts returned by `MultiAgentMaintenanceWorker.run_once()`.

## Incident Response

- Stuck task waiting for a lock: verify the owning claim is still active; release expired claims or disable `multi_agent_resource_lock_enabled` for rollback.
- Missing progress messages: poll `agent_messages`; LISTEN/NOTIFY is only a fast path and the table is authoritative.
- Approval backlog: approve/reject pending requests or temporarily disable `multi_agent_async_approval_enabled`.
- Merge blocked by conflict detection: inspect merge bundle `risk_items` and resolve overlapping files before approving.

## Rollback

Disable `multi_agent_v2_enabled`. The legacy scheduler, synchronous approval interrupt, and merge path remain available.
