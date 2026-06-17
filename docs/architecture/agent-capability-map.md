# Agent Capability Map

Updated: 2026-05-18

Current architecture capability map.

| Capability | Tool coverage | Prompt coverage | Eval coverage | Notes |
| --- | --- | --- | --- | --- |
| planning | partial | registry introduced | smoke/agent_team datasets | Agent team planner and delegation planner exist, but prompt migration is incremental. |
| execution | baseline | registry introduced | sandbox/tool/skill contract checks | Tool registry routes workspace commands and declared Skill entrypoints through thread-level sandbox execution with explicit fallback metadata. |
| critic | partial | registry introduced | governance/review checks | Merge review now has a versioned prompt baseline. |
| memory | production baseline | registry introduced | memory, memory_context, and embedding-path tests | PostgreSQL canonical memory is the source of truth; pgvector embeddings are a rebuildable semantic index used by hybrid retrieval when configured. |
| skill_scout | partial | registry introduced | skill hints in eval schema | Skill registry is present; eval prompt pinning is now represented in cases. |

Frozen contracts:

- Error envelope: compatible legacy HTTP error body with `stable_code`, `details`, `trace_id`, and `retryable` fields added.
- Prompt registry: `PromptRegistry.get(id, version="latest")`, `render(id, version="latest", **kwargs)`, `list()`, and `diff(id, v1, v2)`.
- Model router: `ModelRouter.pick(kind, user_id=None)`, `decide(...)`, and `fallbacks(kind)`.
- Tool manifest runtime fields: `timeout_seconds`, `max_concurrent_calls`, `max_memory_mb`, `allow_network`, and `allow_filesystem`.
- Shutdown hook: `register_shutdown_hook(async_fn)` plus `trigger_shutdown(timeout=30)`.
