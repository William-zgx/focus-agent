# Multi-Agent Refactor Tickets

> **Historical refactor record.** These ticket scopes and outputs describe the
> earlier refactor plan; listed outputs/tests are not current acceptance or a
> claim that all flags are enabled. Use the [current overview](../project-overview.md)
> and 2026-09-28 [research](../plans/2026-09-28-agent-capabilities/research.md),
> [design](../plans/2026-09-28-agent-capabilities/design.md), and
> [plan](../plans/2026-09-28-agent-capabilities/plan.md) for current status.

## MAR-DAG-001

- Owner: DEV-A
- Scope: `src/focus_agent/multi_agent/dag_scheduler.py`, `src/focus_agent/services/agent_team_run.py`
- Output: feature-flagged DAG wave selection.
- Tests: DAG validation, diamond graph, resource conflict suppression.

## MAR-COORD-001

- Owner: DEV-B
- Scope: resource locks, message bus, failure handler, coordination backend extension.
- Output: in-memory coordination primitives and additive SQL migration.
- Tests: lock conflict, TTL, message ACK, failure strategy ladder.

## MAR-APPROVAL-001

- Owner: DEV-C
- Scope: approval queue and `graph_tool_executor_node.py`.
- Output: default-off async approval path that does not call `interrupt()`.
- Tests: default-off interrupt regression and async pending behavior.

## MAR-MERGE-001

- Owner: DEV-D
- Scope: planning resource claims and merge conflict detection.
- Output: task resource claims and conflict reports in merge risk notes.
- Tests: overlapping changed files and contradictory summary heuristic.
