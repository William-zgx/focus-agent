# Agent Role Routing

Updated: 2026-04-24

This note defines the release gate for Agent role routing and governance without duplicating runtime design details.

## Behavioral Contract

- Default off keeps the existing single-run model path unchanged.
- The v2 route still records `role_route_plan`; `AGENT_DELEGATION_ENABLED=false` keeps legacy execution unchanged.
- `AGENT_DELEGATION_ENABLED=true` builds `agent_delegation_plan`; `AGENT_DELEGATION_ENFORCE=true` marks delegated role runs as enforced governance records for the turn.
- Routed roles use the current role set: `orchestrator`, `planner`, `executor`, `critic`, `memory_curator`, and `skill_scout`.
- Workspace lookup must stay local-first and must not call web tools when the user says not to browse.
- Symbol, definition, usage, or location lookup should start with `search_code` when that tool is available; `.focus_agent/` runtime files are excluded from code search.
- Memory preview is prompt evidence only; uncommitted preview content must not leak into durable memory or final answers.
- Role-specific model settings use `AGENT_ROLE_*_MODEL`. If a role model is unset, `executor` falls back to the main selected model; planning, critique, memory, skill, and orchestration roles fall back to `helper_model`, then the main model.
- Memory Curator is controlled by `AGENT_MEMORY_CURATOR_ENABLED`; auto-promotion only runs after approved branch merge and conflicts stay in `needs_review`.
- Tool Router is controlled by `AGENT_TOOL_ROUTER_ENABLED`; when `AGENT_TOOL_ROUTER_ENFORCE=true`, denied tools are not bound to the model.
- Model Router is controlled by `AGENT_MODEL_ROUTER_ENABLED`; observe mode records `model_route_decision`, enforce mode may replace the effective role model.
- Self-repair and Review Queue are controlled by `AGENT_SELF_REPAIR_ENABLED` and `AGENT_REVIEW_QUEUE_ENABLED`; they record failure candidates and pending human-review items without writing eval datasets automatically.
- Context Engineering v2 is controlled by `AGENT_CONTEXT_ENGINEERING_V2_ENABLED`; long context compression and artifact refs are recorded in `plan_meta` and only materialize long observations when `AGENT_CONTEXT_ARTIFACTIZE_LONG_OBSERVATIONS=true`.
- Agent Task Ledger is controlled by `AGENT_TASK_LEDGER_ENABLED`; artifact synthesis and critic gating are separately controlled by `AGENT_ARTIFACT_SYNTHESIS_ENABLED`, `AGENT_CRITIC_GATE_ENABLED`, and `AGENT_CRITIC_GATE_ENFORCE`.
- Task ledger records convert delegated tasks into traceable task nodes, delegated artifacts, critic verdicts, and optional final synthesis. Critic enforce mode blocks rejected artifacts from synthesis and allows only one local retry task.
- Web operators can inspect role routing, memory curator, tool route, delegation, model route, self-repair, review queue, context engineering, task ledger, delegated artifact, and critic gate records at `/app/agent/governance` (`/app/agent/roles` remains compatible).

## Eval Gate

Run this gate whenever role routing, planning, tool policy, memory preview, or model fallback behavior changes:

```bash
uv run python -m tests.eval --suite agent_arch --concurrency 1
uv run python -m tests.eval --suite agent_governance --concurrency 1
uv run python -m tests.eval --suite agent_delegation --concurrency 1
uv run python -m tests.eval --suite agent_context --concurrency 1
uv run python -m tests.eval --suite agent_task_ledger --concurrency 1
```

For framework-only validation without provider credentials:

```bash
uv run pytest tests/eval/test_agent_arch_suite.py tests/eval/test_agent_governance_suite.py tests/eval/test_agent_delegation_suite.py tests/eval/test_agent_context_suite.py tests/eval/test_agent_task_ledger_suite.py
```

If the Web console or SDK contract changed, pair the gate with:

```bash
make sdk-check
make web-check
```

If the browser chat, branch, review, or observability surfaces changed, add:

```bash
uv run python scripts/ui_smoke_test.py
uv run python scripts/observability_ui_smoke.py --scenario all
pnpm --dir apps/web smoke:observability
```
