# Observability Runbook

Updated: 2026-04-22

This runbook is for diagnosing live Focus Agent issues with the built-in runtime endpoints, trajectory storage, Web observability pages, and the `focus-agent-trajectory` CLI.

## 1. Confirm Liveness Versus Readiness

Use the runtime endpoints in this order:

- `/healthz` tells you the process is up.
- `/readyz` tells you whether the runtime is actually ready to serve traffic.
- `/metrics` exposes Prometheus text metrics for runtime state and trajectory aggregates.

Examples:

```bash
curl http://127.0.0.1:8000/healthz
curl http://127.0.0.1:8000/readyz
curl http://127.0.0.1:8000/metrics
```

`/readyz` is the primary readiness signal. It returns:

- `status` and `ready`
- `app_version`, `environment`, and `deployment`
- per-component `checks`, including trajectory recorder status when trajectory persistence is expected

Typical interpretation:

- `/healthz` is `200` but `/readyz` is `503`: the process is alive but one or more runtime checks are degraded.
- `/readyz` is `200` and `trajectory_recorder.ready=false`: runtime is serving, but trajectory persistence is not available.

## 2. Read The Current Slice

Use the aggregated observability surface before drilling into one turn:

- Web: `/app/observability/overview`
- API: `GET /v1/observability/overview`

The overview endpoint returns:

- runtime readiness payload
- trajectory aggregate stats
- optional `trajectory_error` if the runtime is up but the stats query failed

Example:

```bash
curl 'http://127.0.0.1:8000/v1/observability/overview?status=failed&has_error=true&min_latency_ms=500'
```

Useful filters:

- `request_id`
- `trace_id`
- `thread_id`
- `root_thread_id`
- `branch_id`
- `status`
- `scene`
- `tool`
- `model`
- `fallback_used`
- `cache_hit`
- `has_error`
- `started_after`
- `started_before`
- `min_latency_ms`
- `max_latency_ms`

Use the overview page first when you need to answer:

- Is this a broad outage or a narrow slice?
- Which scene, branch role, model, or tool is hot right now?
- Is latency, failure rate, or fallback density moving first?

## 3. Drill Into A Failing Sample

After the overview tells you where to look, move to:

- Web: `/app/observability/trajectory`
- API: `GET /v1/observability/trajectory`
- API detail: `GET /v1/observability/trajectory/{turn_id}`

Examples:

```bash
curl 'http://127.0.0.1:8000/v1/observability/trajectory?status=failed&tool=web_search&limit=20'
curl 'http://127.0.0.1:8000/v1/observability/trajectory/turn-id-here'
```

The trajectory workbench is optimized for this sequence:

1. Narrow the sample list with filters or presets.
2. Select one turn.
3. Inspect the execution timeline and runtime metadata.
4. Pivot into the same request, trace, thread, or model.

## 4. Correlate By Request And Trace

The current observability model carries these correlation fields through persisted trajectory records and runtime metadata:

- `request_id`
- `trace_id`
- `root_span_id`
- `environment`
- `deployment`
- `app_version`

Use them for handoff and root-cause isolation:

- `request_id` is best when you start from a single HTTP request.
- `trace_id` is best when you want to follow the same traced flow across spans and tool runtime payloads.
- `root_span_id` anchors the top-level turn span for a persisted turn.

Examples:

```bash
curl 'http://127.0.0.1:8000/v1/observability/overview?request_id=req-123'
curl 'http://127.0.0.1:8000/v1/observability/trajectory?trace_id=abc123&limit=50'
focus-agent-trajectory list --request-id req-123 --trace-id abc123 --limit 20
```

The Web workbench also supports:

- request and trace deep links
- production pivots from the selected turn
- correlation hooks collected from trajectory runtime metadata

## 5. Use The CLI For Fast Terminal Inspection

`focus-agent-trajectory` reads persisted trajectory data directly from PostgreSQL.

Examples:

```bash
focus-agent-trajectory stats --has-error --fallback-used
focus-agent-trajectory list --request-id req-123 --trace-id abc123 --status failed --limit 20
focus-agent-trajectory show turn-42
focus-agent-trajectory export --scene long_dialog_research --output /tmp/focus-agent-trajectory.jsonl
```

`DATABASE_URI` must point at the same database used by the API. If you are using the managed local PostgreSQL helper, source the runtime file first:

```bash
source .focus_agent/postgres/runtime.env
```

## 6. Replay Or Promote A Known Bad Turn

Once you identify a useful trajectory turn, you can:

- replay it through `POST /v1/observability/trajectory/{turn_id}/replay`
- promote it into an eval-ready dataset payload through `POST /v1/observability/trajectory/{turn_id}/promote`

The Web trajectory page surfaces these actions from the selected turn so you can move from diagnosis into regression capture without leaving the console.

## 7. Recommended Oncall Flow

Use this order when responding to production issues:

1. Check `/readyz` to separate runtime readiness from simple process liveness.
2. Check `/metrics` or `/v1/observability/overview` to see whether the issue is broad or scoped.
3. Open `/app/observability/overview` and identify the hottest scene, tool, branch role, or model slice.
4. Open `/app/observability/trajectory` and pivot into the exact request, trace, thread, or model.
5. Inspect the selected turn's timeline, error text, fallback steps, cache behavior, and runtime metadata.
6. Replay or promote the turn if it should become a regression artifact.

## 8. Local Verification Commands

These are the repo-local checks that currently validate the observability stack:

```bash
make lint
make ci-test
make sdk-check
make sdk-build
make web-check
make web-build
make ui-smoke-observability
pnpm --dir apps/web smoke:observability
```

If your local `.venv` cannot import `psycopg` because `libpq` is missing, use the focused test workaround already documented in [architecture.md](architecture.md).

## 9. Current Boundaries

- Trajectory observability depends on PostgreSQL-backed persistence or another initialized trajectory recorder.
- `/metrics` currently includes trajectory aggregate metrics when they are available; high-frequency scrape behavior should still be reviewed alongside your global API rate-limit settings.
- OpenTelemetry exporter wiring is implemented with standard `OTEL_TRACES_EXPORTER` and `OTEL_EXPORTER_OTLP_*` settings, but collector reachability and desktop-browser automation still depend on the current deployment and execution environment.
