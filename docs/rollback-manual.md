# Rollback Manual

Updated: 2026-07-12

This runbook covers the perf-p1/perf-p2 flags and their persistence safety
boundaries. Roll back one subsystem at a time when possible, restart the API,
and watch `/readyz`, `/metrics`, API error rate, and the relevant backlog signal
for at least one scrape window.

A deployment rollback creates a new evidence identity. Do not reuse reports
from the deployment being replaced: bind the post-rollback commit, deployment
id, deployment version, and production environment, then capture fresh
evidence for the recovered instance.

| Flag | Default | Rollback command | Effect | Watch |
|------|---------|------------------|--------|-------|
| `FOCUS_AGENT_DB_POOL_ENABLED` | `true` | `FOCUS_AGENT_DB_POOL_ENABLED=false make api` | Postgres repositories stop using the shared pool and return to short-lived connections. | `/readyz.active_connections`, DB connection count, request latency |
| `FOCUS_AGENT_CHECKPOINT_INCREMENTAL` | `true` | `FOCUS_AGENT_CHECKPOINT_INCREMENTAL=false make api` | Explicit pickle saver/store flush after every write; SQLite persists each operation transactionally. | checkpoint write p95, local disk I/O |
| `FOCUS_AGENT_MEMORY_EMBED_ASYNC` | `true` | `FOCUS_AGENT_MEMORY_EMBED_ASYNC=false make api` | Memory writes call embedding synchronously on the write path. | memory write latency, embedding provider errors |
| `FOCUS_AGENT_CHECKPOINT_VERIFY_SIGNATURE` | `true` | Keep `true` in supported runtime rollback paths. | Legacy pickle owner, HMAC, and payload failures stop startup instead of silently discarding or trusting state. | startup errors from `focus_agent.local_persistence`; preserve the rejected files for investigation |
| `FOCUS_AGENT_CHECKPOINT_HMAC_KEY` | unset for SQLite | `export FOCUS_AGENT_CHECKPOINT_HMAC_KEY=<stable-secret>` | Required before startup when explicitly selecting pickle with signature verification enabled. | startup errors, restore success after restart |
| `FOCUS_AGENT_TOOL_POOL_ISOLATED` | `true` | `FOCUS_AGENT_TOOL_POOL_ISOLATED=false make api` | Parallel tool batches return to the shared thread pool. | `focus_agent.tool_pool.queue`, tool latency, shared pool saturation |
| `FOCUS_AGENT_CHECKPOINT_BACKEND` | `sqlite` | `FOCUS_AGENT_CHECKPOINT_BACKEND=pickle FOCUS_AGENT_CHECKPOINT_HMAC_KEY=<stable-secret> make api` | Switches both the local LangGraph checkpoint and store to signed pickle files. Missing key fails before either file is created. | checkpoint/store restore, file growth, rollback behavior |

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
5. Keep the default SQLite backend for local rollback unless a signed,
   owner-matching legacy pickle is the explicit rollback target. With no
   `DATABASE_URI`, app-state repositories and LangGraph checkpoint/store data
   are durable repo-local SQLite, not in-memory fallbacks.
6. Do not switch a shared production deployment from PostgreSQL to repo-local
   SQLite as a database rollback. Each process would get isolated state and
   production trajectory/shared coordination guarantees would be lost.
7. If legacy pickle startup fails because the HMAC key, signature, owner, or
   payload is invalid, stop and preserve the files. Select SQLite for a clean
   local start or perform an audited offline migration; do not weaken the
   running service to make untrusted pickle data load.

## Legacy Pickle Emergency Boundary

`FOCUS_AGENT_CHECKPOINT_VERIFY_SIGNATURE=false make api` remains an executable
compatibility escape hatch in the codebase, but it is not a supported
production rollback or a safe operating state. It may deserialize untrusted
pickle content and must never be the first response to a failed signature.

If recovery of an unsigned historical file is explicitly approved:

1. Copy the artifacts to an isolated, single-user, offline environment.
2. Verify provenance and file ownership outside the application.
3. Run the compatibility command only against the copied artifacts, with no
   production credentials or network access.
4. Export or migrate the recovered records to SQLite or PostgreSQL.
5. Destroy the isolated process and re-enable signature verification before
   any normal runtime starts.

Output produced with verification disabled is untrusted migration material. It
must not be attached as passing release evidence.

## Verification Commands

```bash
curl http://127.0.0.1:8000/readyz
curl http://127.0.0.1:8000/metrics
uv run python scripts/bench_checkpoint.py --backend pickle --turns 500
uv run python scripts/bench_checkpoint.py --backend sqlite --turns 500
uv run python scripts/bench_scheduler_lock.py --sessions 10
uv run python scripts/bench_tool_parallel.py --tools 10
```

For a production rollback, export the identity of the recovered deployment
before generating smoke, Postgres, OTel, governance, or eval reports:

```bash
export RELEASE_COMMIT_SHA="$(git rev-parse HEAD)"
export RELEASE_DEPLOYMENT_ID='<rollback-deployment-id>'
export RELEASE_DEPLOYMENT_VERSION='<rollback-version>'
export RELEASE_ENVIRONMENT='production'
```

Each JSON evidence input must carry a timezone-aware timestamp and this complete
`release_binding`. `/readyz` must report matching `deployment`, `app_version`,
and `environment`. The default evidence freshness window is 21,600 seconds
(6 hours), so recapture rather than reuse stale pre-rollback reports.

Record the flag values, command outputs, operator, timestamp, observed recovery
signal, release identity, and schema-v2 evidence manifest in the release-gate
report directory.
