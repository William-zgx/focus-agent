# Agent Capability Map

Updated: 2026-06-25

Current architecture capability map.

| Capability | Tool coverage | Prompt coverage | Eval coverage | Notes |
| --- | --- | --- | --- | --- |
| planning | partial | registry introduced | smoke/agent_team datasets | Agent team planner and delegation planner exist, but prompt migration is incremental. |
| execution | baseline | registry introduced | sandbox/tool/skill contract checks | Tool registry routes workspace commands and declared Skill entrypoints through thread-level sandbox execution with explicit fallback metadata. |
| critic | partial | registry introduced | governance/review checks | Merge review now has a versioned prompt baseline. |
| memory | production baseline | registry introduced | memory, memory_context, retrieval, and embedding-path tests | PostgreSQL canonical memory is the source of truth; Zvec is the default rebuildable retrieval index, with pgvector retained as a compatibility/fallback path when configured. |
| retrieval_rag | shadow-first expansion | registry introduced | retrieval expansion and tool tests | Zvec covers memory, artifact chunks, skills, trajectory, branch context, agent-team plans, failure cases, governance feedback, and workspace chunks; every hit must hydrate canonical data before prompt/context use. |
| skill_scout | partial | registry introduced | skill hints in eval schema | Skill registry is present; eval prompt pinning is now represented in cases. |

Frozen contracts:

- Error envelope: compatible legacy HTTP error body with `stable_code`, `details`, `trace_id`, and `retryable` fields added.
- Prompt registry: `PromptRegistry.get(id, version="latest")`, `render(id, version="latest", **kwargs)`, `list()`, and `diff(id, v1, v2)`.
- Model router: `ModelRouter.pick(kind, user_id=None)`, `decide(...)`, and `fallbacks(kind)`.
- Tool manifest runtime fields: `timeout_seconds`, `max_concurrent_calls`, `max_memory_mb`, `allow_network`, and `allow_filesystem`.
- Shutdown hook: `register_shutdown_hook(async_fn)` plus `trigger_shutdown(timeout=30)`.
