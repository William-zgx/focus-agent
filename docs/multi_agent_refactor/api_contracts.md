# Multi-Agent API Contracts v1.0

## Scope

This document mirrors the runtime contracts in `src/focus_agent/multi_agent/contracts.py`.
All new behavior is guarded by `multi_agent_v2_enabled` and narrower feature flags.

## Contracts

- `DAGTaskNode`: scheduler input with dependencies, resource claims, priority, timeout, and retry budget.
- `ResourceClaim`: resource lock claim for `file:*`, `tool:*`, or `data:*` resources.
- `AgentMessage`: persisted Agent-to-Agent message with optional target and TTL.
- `ApprovalRequest`: asynchronous tool approval request with redacted display handled by tool runtime.
- `ConflictReport`: merge conflict finding emitted before merge bundle finalization.

## Storage

- `agent_resource_claims` stores TTL-scoped resource locks.
- `agent_messages` stores persisted inter-agent messages and backs LISTEN/NOTIFY.
- `tool_approval_requests` stores pending and decided approval requests.

The in-memory ports are used for local/runtime fallback. When a Postgres
database URI is configured and `multi_agent_v2_enabled` is true, coordination
backend construction wires the Postgres implementations for locks, messages,
and approvals.

## Change Log

- v1.0: Initial contracts for DAG scheduling, resource locks, messages, approvals, failure handling, and merge conflict detection.
