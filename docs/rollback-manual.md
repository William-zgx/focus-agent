# Perf Rollback Manual

Updated: 2026-05-19

This runbook covers the perf-p1/perf-p2 flags. Roll back one subsystem at a
time when possible, restart the API, and watch `/readyz`, `/metrics`, API error
rate, and the relevant backlog signal for at least one scrape window.

| Flag | Default | Rollback command | Effect | Watch |
|------|---------|------------------|--------|-------|
| `FOCUS_AGENT_DB_POOL_ENABLED` | `true` | `FOCUS_AGENT_DB_POOL_ENABLED=false make api` | Postgres repositories stop using the shared pool and return to short-lived connections. | `/readyz.active_connections`, DB connection count, request latency |
| `FOCUS_AGENT_CHECKPOINT_INCREMENTAL` | `true` | `FOCUS_AGENT_CHECKPOINT_INCREMENTAL=false make api` | Local pickle saver/store flush after every write. | checkpoint write p95, local disk I/O |
| `FOCUS_AGENT_MEMORY_EMBED_ASYNC` | `true` | `FOCUS_AGENT_MEMORY_EMBED_ASYNC=false make api` | Memory writes call embedding synchronously on the write path. | memory write latency, embedding provider errors |
| `FOCUS_AGENT_CHECKPOINT_VERIFY_SIGNATURE` | `true` | `FOCUS_AGENT_CHECKPOINT_VERIFY_SIGNATURE=false make api` | Legacy unsigned local pickle files can be loaded for a short migration window. | warnings from `focus_agent.local_persistence`; re-enable after rewrite |
| `FOCUS_AGENT_CHECKPOINT_HMAC_KEY` | unset in example | `export FOCUS_AGENT_CHECKPOINT_HMAC_KEY=<stable-secret>` | Signs and verifies local pickle checkpoint/store files. | missing-key warnings, restore success after restart |
| `FOCUS_AGENT_TOOL_POOL_ISOLATED` | `true` | `FOCUS_AGENT_TOOL_POOL_ISOLATED=false make api` | Parallel tool batches return to the shared thread pool. | `focus_agent.tool_pool.queue`, tool latency, shared pool saturation |
| `FOCUS_AGENT_CHECKPOINT_BACKEND` | `pickle` | `FOCUS_AGENT_CHECKPOINT_BACKEND=pickle make api` | Local LangGraph checkpoint backend uses signed pickle files. | checkpoint restore, file growth, rollback behavior |

## Rollback Order

1. If the service is not ready, check `/readyz` first. A DB pool issue usually
   shows up as rising `active_connections` or connection acquisition errors.
2. If writes are slow but the API is healthy, roll back checkpoint debounce or
   SQLite backend before changing memory embedding.
3. If memory writes are slow or embedding jobs dead-letter, set
   `FOCUS_AGENT_MEMORY_EMBED_ASYNC=false` only if synchronous embedding is
   acceptable for the incident. Otherwise keep async on and disable the
   embedding provider with existing `AGENT_MEMORY_EMBEDDING_*` controls.
4. If tool calls starve unrelated background work, set
   `FOCUS_AGENT_TOOL_POOL_ISOLATED=false` to return to the previous shared pool
   behavior while investigating worker sizing.
5. Use `FOCUS_AGENT_CHECKPOINT_VERIFY_SIGNATURE=false` only for a bounded
   migration window. It lowers local pickle tamper protection.

## Verification Commands

```bash
curl http://127.0.0.1:8000/readyz
curl http://127.0.0.1:8000/metrics
uv run python scripts/bench_checkpoint.py --backend pickle --turns 500
uv run python scripts/bench_checkpoint.py --backend sqlite --turns 500
uv run python scripts/bench_scheduler_lock.py --sessions 10
uv run python scripts/bench_tool_parallel.py --tools 10
```

For a release rollback, record the flag values, command outputs, operator,
timestamp, and observed recovery signal in the release-gate report directory.
