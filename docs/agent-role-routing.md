# Agent Role Routing

Updated: 2026-04-24

This note defines the release gate for Agent role routing and governance without duplicating runtime design details.

## Behavioral Contract

- Default off keeps the existing single-run model path unchanged.
- The v2 dry run records `role_route_plan` for observability; it does not change legacy execution.
- Routed roles use the current role set: `orchestrator`, `planner`, `executor`, `critic`, `memory_curator`, and `skill_scout`.
- Workspace lookup must stay local-first and must not call web tools when the user says not to browse.
- Memory preview is prompt evidence only; uncommitted preview content must not leak into durable memory or final answers.
- Role-specific model settings use `AGENT_ROLE_*_MODEL`. If a role model is unset, `executor` falls back to the main selected model; planning, critique, memory, skill, and orchestration roles fall back to `helper_model`, then the main model.
- Memory Curator is controlled by `AGENT_MEMORY_CURATOR_ENABLED`; auto-promotion only runs after approved branch merge and conflicts stay in `needs_review`.
- Tool Router is controlled by `AGENT_TOOL_ROUTER_ENABLED`; when `AGENT_TOOL_ROUTER_ENFORCE=true`, denied tools are not bound to the model.
- Web operators can inspect role routing, memory curator decisions, and tool route plans at `/app/agent/governance` (`/app/agent/roles` remains compatible).

## Eval Gate

Run this gate whenever role routing, planning, tool policy, memory preview, or model fallback behavior changes:

```bash
uv run python -m tests.eval --suite agent_arch --concurrency 1
uv run python -m tests.eval --suite agent_governance --concurrency 1
```

For framework-only validation without provider credentials:

```bash
uv run pytest tests/eval/test_agent_arch_suite.py tests/eval/test_agent_governance_suite.py
```

If the Web console or SDK contract changed, pair the gate with:

```bash
make sdk-check
make web-check
```
