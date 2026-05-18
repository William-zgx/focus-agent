# Multi-Agent Refactor Validation Report

## Acceptance Matrix

| Capability | Evidence |
| --- | --- |
| DAG scheduling | `DAGScheduler` plus Agent Team DAG scheduling tests, including a 5-task diamond DAG where the two middle tasks run in the same scheduling wave. |
| Failure retry/degrade | `FailureHandler` unit tests and Agent Team failure strategy coverage, including retry -> reassign -> degrade without terminating the session. |
| Resource isolation | In-memory/Postgres lock managers, task `resource_claims`, and lock conflict tests that prevent two agents from holding exclusive access to the same file. |
| Async approvals | Approval queue, Agent Team approval REST/Workbench surfacing, and graph async approval tests where one pending tool approval does not block other tool calls. |
| Inter-agent messages | In-memory/Postgres message bus, progress publishing, ACK/TTL tests, and persisted `pg_notify` channel verification. |
| Merge conflict detection | `MergeConflictDetector` and merge bundle blocking tests. |
| Maintenance cleanup | `MultiAgentMaintenanceWorker` and single-tick maintenance tests. |
| Default-off compatibility | Config and integration tests keep the legacy scheduler, approval interrupt, and merge behavior unchanged while `multi_agent_v2_enabled=false`. |

## Test Inventory

- Unit tests for `src/focus_agent/multi_agent`: 130.
- Integration tests for multi-agent acceptance: 15.
- Focused coverage run: 145 tests, 94% line coverage over `src/focus_agent/multi_agent`.
- Full backend regression run: 1326 passed, 13 skipped.

## Verification Commands

- `uv run pytest tests/unit/multi_agent -q`
- `uv run pytest tests/integration/multi_agent/test_acceptance.py -q`
- `uv run coverage erase && uv run coverage run --source=src/focus_agent/multi_agent -m pytest tests/unit/multi_agent tests/integration/multi_agent -q && uv run coverage report --fail-under=80`
- `uv run pytest tests/test_agent_team_api.py::test_agent_team_api_lists_and_decides_pending_tool_approvals tests/test_api_shapes.py::test_public_api_no_longer_exposes_skill_catalog_routes tests/test_graph_builder.py::test_graph_tool_executor_async_approval_records_pending_without_interrupt tests/unit/multi_agent/test_core.py::test_multi_agent_maintenance_runs_optional_cleanup_hooks -q`
- `uv run pytest -q`
- `uv run ruff check src tests`
- `pnpm --filter @focus-agent/web-sdk check`
- `pnpm --filter @focus-agent/web-app check`
- `pnpm --filter @focus-agent/web-app format:check:full`
- `make contract-check`

## Gray Release Configuration

Enable flags from narrowest to broadest so each behavior can be rolled back independently:

| Stage | Flags | Expected signal |
| --- | --- | --- |
| 0: Baseline | all flags false | Legacy scheduling, merge, and synchronous approval path only. |
| 1: Observe | `MULTI_AGENT_V2_ENABLED=true`, `MULTI_AGENT_MESSAGE_BUS_ENABLED=true` | Progress rows appear in `agent_messages`; no scheduling or approval behavior changes. |
| 2: Scheduling | add `MULTI_AGENT_DAG_SCHEDULER_ENABLED=true` | DAG-ready tasks run in bounded waves; dependency order is preserved. |
| 3: Isolation | add `MULTI_AGENT_RESOURCE_LOCK_ENABLED=true` | `agent_resource_claims` contains short-lived claims and conflicting file writes wait. |
| 4: Governance | add `MULTI_AGENT_ASYNC_APPROVAL_ENABLED=true` | Pending approvals are visible in `/view` and approval routes; unrelated tool calls continue. |
| 5: Recovery | add `MULTI_AGENT_FAILURE_HANDLER_ENABLED=true` | Retry/reassign/degrade decisions are recorded without aborting recoverable sessions. |

Recommended TTL defaults remain conservative: lock TTL 120s, message TTL 300s, approval timeout 1800s, deadlock check interval 30s. Production overrides should be set with the corresponding `MULTI_AGENT_*` environment variables.

## Performance Indicators

- Scheduler complexity is bounded by the number of task nodes plus dependency/resource checks; the focused 5-task diamond acceptance test verifies that independent middle tasks are not serialized.
- Resource locking and approval queues use in-memory ports by default and Postgres ports only when the multi-agent feature is enabled with a database-backed coordination backend.
- Focused local validation on 2026-05-16: 145 multi-agent tests completed in 1.72s, and the coverage report completed at 94% line coverage.
- Runtime watchpoints during gray release: average task wait time for `execution_status="waiting_resource_lock"`, pending approval age, unacked message count by session, and expired lock cleanup count.

## Notes

All new runtime behavior is default-off behind `multi_agent_v2_enabled` plus narrower flags. The Agent Team approval surface follows the existing REST plus React Query polling model; there is no pre-existing Agent Team WebSocket channel.
