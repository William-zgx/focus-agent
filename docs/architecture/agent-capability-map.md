# Agent Capability Map

Updated: 2026-09-28

Current architecture capability map for the platform workbench. Positioning and
product layers: [../project-overview.md](../project-overview.md). This map is a
status view of the code paths, not a claim that every optional provider or
deployment backend is enabled in every environment.

Status meanings:

- `implemented`: the normal code path is wired and has contract/behavior checks.
- `partial`: a useful primitive or persistence surface exists, but the end-to-end
  capability is not wired for the default path or does not survive process loss.
- `flag-gated`: code is available, but the relevant runtime/configuration flag is
  off by default or requires an external dependency.
- `planned`: the current repository deliberately keeps the boundary reserved;
  entries here are not available builtin capabilities.

| Capability | Runtime status | Tool coverage | Prompt coverage | Eval coverage | Notes |
| --- | --- | --- | --- | --- | --- |
| planning | partial / flag-gated | Agent Team planner and delegation planner | registry introduced | smoke/agent_team datasets | Planner and DAG/task records exist; Agent Team v2 execution remains flag-gated (`MULTI_AGENT_V2_ENABLED` default false). |
| execution | implemented core / partial durable | workspace commands and declared Skill entrypoints | registry introduced | sandbox/tool/skill contract checks | `SandboxExecutionService` routes Docker or explicit local fallback. Generic active harness execution is still process-local; durable background worker is conditional. |
| critic | partial / flag-gated | governance/review tools | registry introduced | governance/review checks | Versioned merge-review prompt and governance records exist; automatic critic execution is not the default turn path. |
| memory | implemented canonical / partial semantic index | memory save/search/forget | registry introduced | memory, memory_context, retrieval, and embedding-path tests | PostgreSQL `focus_memories` is canonical. Embedding and Zvec are best-effort/conditional; async embedding defaults on and falls back to FTS/ILIKE when provider or index is unavailable. App schema is v19 (v18 added `embedding_status`; v19 added Agent Team v2 tables). |
| retrieval_rag | implemented fallback / conditional Zvec | memory, artifact, workspace search | retrieval expansion | retrieval expansion and tool tests | Zvec is rebuildable and must hydrate canonical data; its adapter/provider can be unavailable, in which case PostgreSQL/filesystem fallback remains authoritative. |
| skill_scout | partial | Skill registry, search, refresh, install | registry introduced | skill hints in eval schema | Registry and Admin controls are wired; semantic matching is optional and does not imply that a listed Skill's external dependencies are installed. |
| branch_control | implemented / flag-gated | branch proposal, execute, dismiss, merge | N/A (deterministic scorers + optional signals) | branch decision / chat harness tests | Pre-turn recommendations create pending Branch Actions only; no silent fork. Post-turn decisions remain controlled by flags. |
| streaming | implemented protocol / partial recovery | SSE and SDK replay | N/A | streaming + SDK transport tests | Event-ID replay and incomplete-EOF signaling are implemented. Replay/reconnect does not restart a crashed producer. |
| long_running_recovery | partial / flag-gated | Agent Team jobs and background work | N/A | Agent Team/background-worker checks | v19 jobs, claims, leases, and side-effect receipts exist. Generic harness journal can persist/query runs, but `RunManager` is process-local, has no startup hydration/requeue, and durable worker mode requires explicit configuration. |
| followup_wakeup | partial | in-process follow-up/steer queue | N/A | focused runtime tests | Queue, coalescing, and wake primitives exist in memory; the normal factory does not install a handler or start the drain, so this is not a durable public follow-up service. |
| approval_resume | partial / flag-gated | synchronous graph interrupt and v2 approval queue | N/A | approval queue/governance checks | In-memory and Postgres approval records plus an internal resume-job state machine exist. Queue decisions do not automatically replay a returned graph; public executor wiring is not complete. |
| external_connections | partial public web / planned connectors | `web_search` and guarded public `web_fetch` | N/A | web policy/transport checks | Builtin web retrieval is implemented. MCP client/lifecycle, browser/computer control, and account-backed connector sessions remain reserved boundaries; Skill inventory alone does not provide them. |
| result_verification | partial / policy-specific | execution contract and evidence ledger | live-web/Skill policies | execution-contract checks | General implementation tasks do not yet have a common environment verifier; policies other than `live_web_research` and `skill_execution` return `not_required`. |
| task_budget | declared / partial enforcement | AgentBudget and real task runner | task planning fields | runner/round-limit checks | Real Team execution limits global rounds but does not fully enforce declared per-task LLM/tool/cost/deadline budgets. This is separate from context-window limits. |
| context_budget | implemented guard / partial exactness | context preview/compact endpoints and prompt guard | budget metadata in prompt assembly | context-window and context-quality checks | 128k default budget, usage meter, manual/automatic non-destructive compaction are wired. Default `chars_fallback` is an estimate, not provider-exact token accounting. |
| memory_revision | partial | memory audit/forget/evidence refs | memory retrieval plan | memory service/repository checks | Canonical memory merge updates the same record; audit events are append-only and current records retain/union evidence refs, but there is no immutable `MemoryRecord` revision chain. Agent Team v2 revisions are a separate task snapshot mechanism. |
| feedback_loop | partial | governance feedback capture/trend APIs | feedback is evidence, not automatic prompt/model mutation | feedback and retrieval indexing checks | Feedback events and governance-feedback indexing exist. Closing the loop into policy, prompt, model routing, or retrieval weights remains explicit/manual rather than automatic. |

Code anchors for the status above:

- Harness lifecycle and in-process followups: [`runs.py`](../../src/focus_agent/harness/runtime/runs.py) and [`run_followups.py`](../../src/focus_agent/harness/runtime/run_followups.py).
- Approval queue and un-wired resume service: [`approval_queue.py`](../../src/focus_agent/multi_agent/approval_queue.py) and [`agent_team_approval_resume.py`](../../src/focus_agent/services/agent_team_approval_resume.py).
- Canonical memory merge and embedding shadow: [`models.py`](../../src/focus_agent/memory/models.py), [`service.py`](../../src/focus_agent/memory/service.py), and [`postgres_memory_repository.py`](../../src/focus_agent/repositories/postgres_memory_repository.py).
- Context budget and feedback surfaces: [`context_usage.py`](../../src/focus_agent/context_usage.py), [`agent_governance.py`](../../src/focus_agent/api/routers/agent_governance.py), and [`governance_feedback.py`](../../src/focus_agent/retrieval/governance_feedback.py).
- Result verification and task budgets: [`graph_execution_contract.py`](../../src/focus_agent/engine/graph_execution_contract.py), [`delegation_models.py`](../../src/focus_agent/delegation/delegation_models.py), and [`agent_team_real_execution.py`](../../src/focus_agent/services/agent_team_real_execution.py).

Frozen contracts:

- Error envelope: compatible legacy HTTP error body with `stable_code`, `details`, `trace_id`, and `retryable` fields added.
- Prompt registry: `PromptRegistry.get(id, version="latest")`, `render(id, version="latest", **kwargs)`, `list()`, and `diff(id, v1, v2)`.
- Model router: `ModelRouter.pick(kind, user_id=None)`, `decide(...)`, and `fallbacks(kind)`.
- Tool manifest runtime fields: `timeout_seconds`, `max_concurrent_calls`, `max_memory_mb`, `allow_network`, and `allow_filesystem`.
- Shutdown hook: `register_shutdown_hook(async_fn)` plus `trigger_shutdown(timeout=30)`.

The map intentionally distinguishes a persisted schema or an internal service
from an end-to-end default capability. Runtime availability still depends on
feature flags, database/provider configuration, and the deployment backend.

Future work is tracked separately in the [research](../plans/2026-09-28-agent-capabilities/research.md), [design](../plans/2026-09-28-agent-capabilities/design.md), and [plan](../plans/2026-09-28-agent-capabilities/plan.md); those documents do not change the implementation status above.
