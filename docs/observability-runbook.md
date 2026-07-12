# Observability Runbook

Updated: 2026-07-12

This runbook is for diagnosing live Focus Agent issues with the built-in runtime endpoints, `/metrics`, trajectory storage, Web observability pages, and the `focus-agent-trajectory` CLI.

Production smoke and release-health reports are release evidence, not a
replacement for real UI smoke. Live stream validation still needs supplied
stream events or a real browser/API flow; dry-run reports should be treated as
setup checks only.

Production evidence packs use manifest schema version 2. Every JSON input in a
production pack must identify the exact release and collection time; passing
content from a different commit or deployment is not reusable evidence.

```mermaid
flowchart TD
    Alert["Alert or user report"] --> Health["Check /healthz"]
    Health --> Ready["Check /readyz"]
    Ready --> Metrics["Read /metrics"]
    Metrics --> Overview["Open observability overview"]
    Overview --> Slice["Choose failing slice"]
    Slice --> Workbench["Inspect trajectory workbench"]
    Workbench --> Pivot["Pivot by request, trace, tool, model"]
    Pivot --> Replay["Replay"]
    Pivot --> Promote["Promote preview"]
    Replay --> Regression["Eval regression case"]
    Promote --> Regression
```

## 1. Confirm Liveness Versus Readiness

Use the runtime endpoints in this order:

- `/healthz` tells you the process is up.
- `/readyz` tells you whether the runtime is actually ready to serve traffic.
- `/metrics` exposes Prometheus text metrics for runtime state, component readiness, and trajectory aggregates.

Examples:

```bash
curl http://127.0.0.1:8000/healthz
curl http://127.0.0.1:8000/readyz
curl http://127.0.0.1:8000/metrics
```

`/readyz` is the primary readiness signal. It returns:

- `status` and `ready`
- `app_version`, `environment`, and `deployment`
- per-component `checks`, including trajectory recorder status when trajectory persistence is expected and `retrieval_zvec` when the embedded retrieval index is enabled

For a production evidence capture, `deployment`, `app_version`, and
`environment` must equal `RELEASE_DEPLOYMENT_ID`,
`RELEASE_DEPLOYMENT_VERSION`, and `RELEASE_ENVIRONMENT`. The evidence pack
builder performs this cross-check in addition to validating the enclosing
`release_binding`; a healthy response from the wrong deployment must fail the
release.

Typical interpretation:

- `/healthz` is `200` but `/readyz` is `503`: the process is alive but one or more runtime checks are degraded.
- `/readyz` is `200` and `trajectory_recorder.ready=false`: runtime is serving, but trajectory persistence is not available.
- `/readyz` includes `retrieval_zvec.ready=false`: online retrieval should fall back to Postgres/legacy scorers, but canonical memory, artifact, and workspace data is not lost.
- `/readyz` includes `background_jobs.ready=false`: local or production job queues have pending, retrying, or dead-lettered work. Treat release and smoke evidence as degraded until the queue drains or the pending jobs are explained.

Alert guidance should use the existing `/metrics` scrape. Start with these signals before adding custom exporters:

- `focus_agent_runtime_ready == 0`: page immediately; traffic readiness is degraded.
- `focus_agent_runtime_component_ready{component="trajectory_recorder"} == 0`: trajectory persistence is unavailable.
- `focus_agent_runtime_component_ready{component="retrieval_zvec"} == 0`: Zvec is unavailable or degraded; verify fallback rate, `AGENT_ZVEC_DATA_DIR`, and the last `focus-agent-retrieval-index doctor` output.
- `focus_agent_trajectory_metrics_available == 0`: the runtime is up but trajectory aggregates cannot be read.
- `focus_agent_trajectory_non_succeeded_count / focus_agent_trajectory_turn_count`: alert on a sustained failure-rate increase, not a single failed turn.
- `focus_agent_trajectory_avg_latency_ms`, `focus_agent_trajectory_max_latency_ms`, and `focus_agent_trajectory_total_fallback_uses`: use warning alerts for sustained latency or fallback growth, then pivot into `/app/observability/overview`.
- `focus_agent.tool_pool.queue`: warn when the isolated tool pool queue grows for multiple scrape windows; pair it with `focus_agent.tool_pool.active`.
- `agent_team_scheduler_lock_wait_ms`: warn when p95 rises above the single-digit millisecond target during multi-session agent-team starts.
- `focus_background_jobs{kind="memory_embedding",status="retrying|dead_lettered"}` or the admin background job summary: investigate embedding provider health or redaction spikes before enabling 100% async embedding.
- `/readyz.active_connections`: track DB pool in-use connections during rollout and compare against `FOCUS_AGENT_DB_POOL_MAX`.

Keep alert labels aligned with `app_version`, `environment`, `deployment`, `component`, and trajectory `status` so release regressions can be separated from general traffic noise.

## 1.1 Perf Rollout Checks

Before moving a perf flag from 10% to 50% or 100%, capture the same small bundle each time:

```bash
curl http://127.0.0.1:8000/readyz > reports/release-gate/readyz.json
curl http://127.0.0.1:8000/metrics > reports/release-gate/metrics.prom
uv run python scripts/bench_checkpoint.py --backend pickle --turns 500 > reports/release-gate/checkpoint-pickle.json
uv run python scripts/bench_scheduler_lock.py --sessions 10 > reports/release-gate/scheduler-lock.json
uv run python scripts/bench_tool_parallel.py --tools 10 > reports/release-gate/tool-parallel.txt
```

Interpretation:

- DB pool: `active_connections` should return to zero when requests drain; sustained growth without matching traffic suggests a leaked connection scope.
- Checkpoint: p95 writes should stay low and size samples should grow in coarse steps under debounce instead of after every write.
- Memory async: pending `memory_embedding` jobs should drain; retrying/dead-letter growth points at provider outage or schema mismatch.
- Retrieval: `retrieval_zvec` should stay ready after startup; a degraded check means search quality may fall back even though canonical stores remain intact.
- Tool pool: queue depth should remain near zero when workers are not saturated.
- Scheduler lock: 10 independent sessions should show p95 lock wait below 5 ms on a quiet local runner.

Executable alert-rule checks should write a small JSON report for release review. The release-health helper accepts it with `--alert-report-json` and fails the release if the report has no executable rule coverage, declares a failed status, or contains firing alerts. A minimal passing report looks like:

```json
{
  "alerts": [],
  "rules": [
    {"name": "runtime-ready", "query": "focus_agent_runtime_ready == 0"},
    {"name": "trajectory-recorder", "query": "focus_agent_runtime_component_ready{component=\"trajectory_recorder\"} == 0"}
  ],
  "status": "passed"
}
```

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

The overview page is intentionally limited to issue discovery. It should tell you which slice deserves a deeper review, not replace the single-turn workbench.

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
3. Read the summary card first so you know whether the sample is failing, slow, zero-step, or detail-degraded.
4. Inspect the evidence panel in the active mode.
5. Read the input/output narrative and runtime context below the evidence block.
6. Use the right rail to pivot into the same request, trace, thread, tool, or model, or run replay/promote.

Evidence modes:

- `timeline`: normal path when step data exists; use it to isolate the exact step, runtime, fallback, cache, or error pivot.
- `zero_step`: compact fallback when the turn has no recorded trajectory steps; the workbench switches to direct evidence instead of leaving an empty timeline shell.
- `missing_detail`: explicit degraded state when the detail payload is unavailable; treat this as an observability gap and verify API/runtime readiness before drawing conclusions.

Outcome review:

- The Outcome panel is the first place to confirm whether the graph classified the final task as `answered`, `degraded_answer`, `blocked`, or `failed`.
- Tool attempts are linked by `tool_call_id`, `attempt_index`, `recovery_of_tool_call_id`, `fallback_used`, and `fallback_group`; use these fields to distinguish a recovered transient failure from an unresolved tool failure.
- Stats include outcome counters such as tool failures, recovered tools, tool fallback uses, degraded answers, and blocked task outcomes. These counters come from graph-authored runtime outcomes, not UI inference.
- If a final answer exposes raw tool metadata such as `run_id`, `command`, or `stdout_truncated` as the main answer, treat it as a runtime outcome regression. See [runtime-outcomes.md](runtime-outcomes.md).

## 4. Correlate By Request And Trace

The current observability model carries these correlation fields through persisted trajectory records and runtime metadata:

- `request_id`
- `trace_id`
- `root_span_id`
- `environment`
- `deployment`
- `app_version`

The fields form a small handoff chain. Start from whichever identifier you already have, then pivot toward the persisted turn record before choosing the next diagnostic surface.

```mermaid
flowchart LR
    Request["request_id"] --> Trace["trace_id"]
    Trace --> Span["root_span_id"]
    Span --> Turn["Persisted turn"]
    Turn --> Runtime["Runtime metadata"]
    Runtime --> Workbench["Trajectory workbench"]
    Workbench --> CLI["CLI export or show"]
    Workbench --> Eval["Replay or promote"]
```

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
- a persistent right rail for copy/download actions, replay, and eval-sample promotion

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

The Web trajectory page surfaces these actions from the selected turn so you can move from diagnosis into regression capture without leaving the console. The right rail is designed to stay visible while you keep reading the selected sample.

The safest loop is preview-first: diagnose one representative turn, compare replay behavior, then promote only stable evidence into an eval artifact.

```mermaid
flowchart TD
    Turn["Known bad turn"] --> Diagnose["Read timeline or direct evidence"]
    Diagnose --> Replay["Replay compare"]
    Diagnose --> Preview["Promote preview"]
    Replay --> Stable{"Stable regression?"}
    Preview --> Stable
    Stable -->|Yes| Dataset["Eval dataset case"]
    Stable -->|No| Notes["Investigation notes"]
    Dataset --> Gate["Release regression gate"]
```

Use a preview-first workflow:

```bash
curl -X POST 'http://127.0.0.1:8000/v1/observability/trajectory/turn-id-here/promote' \
  -H 'Content-Type: application/json' \
  -d '{"copy_tool_trajectory":true}'
```

The API response is a dataset preview. Review the generated expectations before committing it to a suite.

For batch failure promotion and replay:

```bash
curl -X POST 'http://127.0.0.1:8000/v1/observability/trajectory/batch/promote-preview' \
  -H 'Content-Type: application/json' \
  -d '{"status":["failed"],"has_error":true,"limit":20,"copy_tool_trajectory":true}'

curl -X POST 'http://127.0.0.1:8000/v1/observability/trajectory/batch/replay-compare' \
  -H 'Content-Type: application/json' \
  -d '{"status":["failed"],"has_error":true,"limit":20,"copy_tool_trajectory":true}'

source .focus_agent/postgres/runtime.env
focus-agent-trajectory export --status failed --has-error --output /tmp/focus-agent-failed.jsonl

uv run python -m tests.eval promote \
  --from /tmp/focus-agent-failed.jsonl \
  --failed-only \
  --copy-tool-trajectory \
  --out tests/eval/datasets/promoted-trajectory.jsonl

uv run python -m tests.eval replay \
  --from /tmp/focus-agent-failed.jsonl \
  --trajectory-input \
  --failed-only \
  --copy-tool-trajectory \
  --run \
  --report-json reports/trajectory-replay.json \
  --fail-if-regression
```

Use `--copy-answer-substring` only when the source answer is stable enough to become an assertion. Otherwise keep the promoted case focused on tool path, failure status, and runtime metrics.

## 7. Release Health Gates

The release-health helper turns readiness, trajectory, and replay signals into deterministic gate results that can be used by `make release-gate` or a future CI job:

- `runtime_not_ready`: fails when `/readyz` reports the runtime as not ready.
- `trajectory_recorder_unavailable`: fails when the trajectory recorder readiness check is present and unhealthy.
- `chat_failure_rate`: fails when the non-succeeded turn rate crosses the configured threshold after the minimum sample size.
- `tool_fallback_spike`: fails when fallback usage is high or has grown sharply versus a baseline.
- `eval_replay_regression`: fails when replay comparison rows contain failed replays or replay errors.
- `alert_rules_report`: fails when a provided executable alert report is invalid, has no checked rules, or includes firing alerts.
- `postgres_migration_verification`: fails when a provided Postgres migration verification report is invalid or reports migration errors.
- `production_smoke_report`: fails when a provided production smoke report is invalid, has no checked probes, or reports failed probes.
- `postgres_ops_report`: fails when a provided Postgres ops report is invalid, has no checked operations, or reports failed operations.
- `otel_smoke_report`: fails when a provided OpenTelemetry smoke report is invalid, has no check/span coverage, or reports failed checks.

Memory/context quality probes use the same signal shape for deterministic checks such as required markers, forbidden stale markers, and maximum rendered context size.

Before relying on release-health summaries, keep the browser observability smoke green:

```bash
uv run python scripts/observability_ui_smoke.py --scenario all
pnpm --dir apps/web smoke:observability
```

The local Python browser smoke launches the Chrome binary supplied through
`CHROME_PATH`; it seeds representative success, failed, zero-step, and
missing-detail turns, opens `/app/observability/overview`, then follows
request/turn deep links into `/app/observability/trajectory`. It records
completed fetch request URLs and verifies endpoint pathnames for overview,
list, and detail calls, which catches route wiring regressions without
depending on fragile query-string text.

The local command is not the same artifact as the GitHub Actions
`.github/workflows/browser-smoke.yml` gate. That workflow installs real Google
Chrome, builds the production Web app, starts PostgreSQL and a deterministic
OpenAI-compatible model fixture, runs both chat/branch/review and observability
interaction smoke, and uploads `reports/browser-smoke/`. The source-level
`pnpm --dir apps/web smoke:observability` command launches neither Chrome nor
the API; use it as a fast wiring check, not as browser evidence.

The release gate runs the helper after the smoke and observability eval suites have written JSON reports:

```bash
uv run python scripts/agent_governance_report.py \
  --report-json reports/agent-governance/latest.json

uv run python scripts/release_health_check.py \
  --mode local \
  --ready-url http://127.0.0.1:8000/readyz \
  --trajectory-stats-url http://127.0.0.1:8000/v1/observability/trajectory/stats \
  --allow-self-check-fallback \
  --eval-report-json reports/release-gate/eval-smoke.json \
  --eval-report-json reports/release-gate/eval-observability.json \
  --eval-report-json reports/release-gate/eval-golden-multi-agent.json \
  --eval-report-json reports/release-gate/memory-context-eval.json \
  --governance-report-json reports/agent-governance/latest.json \
  --report-json reports/release-gate/release-health.json
```

For a live deployment, switch to `--mode live` or `--mode production`, remove `--allow-self-check-fallback`, and pass captured deployment signals. The helper accepts `/readyz` from `--readyz-json` or `--runtime-status-json`, trajectory stats from `--trajectory-stats-json`, optional trajectory baselines from `--baseline-trajectory-stats-json`, replay comparison rows from `--replay-comparisons-json`, alert-rule execution results from `--alert-report-json`, Postgres migration verification from `--postgres-migration-report-json`, production smoke from `--production-smoke-report-json`, Postgres ops from `--postgres-ops-report-json`, OpenTelemetry smoke from `--otel-smoke-report-json`, Agent governance quality from `--governance-report-json`, eval reports from repeated `--eval-report-json` arguments, and optional baseline eval reports from repeated `--baseline-eval-report-json` arguments. In live/production mode, missing readyz, trajectory stats, replay comparison, eval report, production smoke, Postgres ops, OTel smoke, or governance report inputs are release-blocking and return exit code 1. Supplied alert, Postgres, production smoke, Postgres ops, OTel, and governance reports are also release-blocking when they are malformed, failed, contain blocking threshold violations, or are dry-run reports in production.

Production jobs can also probe the live service directly with `--ready-url` and `--trajectory-stats-url`, but those probes are still fail-closed: an unavailable endpoint writes a failed release-health report instead of silently using local self-check samples.

### Production Evidence Identity And Freshness

Before generating any production report, export the complete release identity:

```bash
export RELEASE_COMMIT_SHA="$(git rev-parse HEAD)"
export RELEASE_DEPLOYMENT_ID='<deployment-id>'
export RELEASE_DEPLOYMENT_VERSION='<deployment-version>'
export RELEASE_ENVIRONMENT='production'
```

`RELEASE_COMMIT_SHA` must be a hexadecimal commit that resolves in the checked
out repository and equals its current `HEAD`. The other three values must
identify the deployed production instance. Production smoke, Postgres ops,
OTel smoke, governance, and eval report writers derive their top-level
`release_binding` from these four variables. If only part of the identity is
present, a non-dry-run writer fails before writing the report; caller-supplied
binding fields cannot override the environment-derived identity.

Every JSON input supplied to `release_evidence.py` must contain:

```json
{
  "generated_at": "2026-07-12T12:00:00Z",
  "release_binding": {
    "commit_sha": "<full commit SHA>",
    "deployment_id": "<deployment id>",
    "deployment_version": "<deployment version>",
    "environment": "production"
  }
}
```

The timestamp may use another supported evidence timestamp field, but it must
be ISO-8601 with a timezone. The default maximum age and maximum span across
required inputs are both 21,600 seconds (6 hours); override that only with the
explicit `--max-evidence-age-seconds` release policy. Missing timestamps,
timezone-naive timestamps, stale inputs, mismatched bindings, non-production
environments, and inputs collected too far in the future fail closed.

Raw endpoint captures such as `/readyz`, trajectory stats, replay comparisons,
alert reports, and migration reports are not automatically attested by report
writers. Capture them to a temporary path, then run
`scripts/release_evidence_capture.py`. The helper validates any existing
binding before writing the environment-derived top-level binding, preserves
existing timestamps, and writes atomically. For `readyz`, pass `--readyz` to
cross-check `deployment`, `app_version`, and `environment`:

```bash
raw_readyz="$(mktemp)"
curl --fail --show-error --silent --output "$raw_readyz" -- "$READY_URL"
uv run python scripts/release_evidence_capture.py \
  "$raw_readyz" \
  --output reports/release-gate/readyz.json \
  --readyz "$raw_readyz" \
  --captured-now
rm -f "$raw_readyz"
```

`--captured-now` is limited to timestamp-free live snapshots such as `/readyz`
and trajectory stats. It never replaces an existing timestamp. Replay, alert,
migration, baseline eval, and static stream-event reports must carry an
upstream timezone-aware timestamp; missing, naive, stale, or conflicting
evidence fails closed.

Production release review should archive an evidence pack after the live signals are captured:

```bash
make release-evidence RELEASE_EVIDENCE_ARGS="--release-id <release-id> --approval-id <approval-id> --approval-status approved --retention-days 90 --storage-dir reports/release-gate/archive --readyz-json reports/release-gate/readyz.json --trajectory-stats-json reports/release-gate/trajectory-stats.json --replay-comparisons-json reports/release-gate/replay-comparisons.json --alert-report-json reports/release-gate/alert-report.json --postgres-migration-report-json reports/release-gate/postgres-migration.json --production-smoke-report-json reports/release-gate/production-smoke.json --postgres-ops-report-json reports/release-gate/postgres-ops.json --otel-smoke-report-json reports/release-gate/otel-smoke.json --governance-report-json reports/agent-governance/latest.json --eval-report-json reports/release-gate/eval-smoke.json --eval-report-json reports/release-gate/eval-observability.json --eval-report-json reports/release-gate/eval-golden-multi-agent.json --eval-report-json reports/release-gate/eval-harness-stability.json --eval-report-json reports/release-gate/memory-context-eval.json --baseline-eval-report-json reports/release-gate/baseline-eval-smoke.json"
```

The resulting `reports/release-gate/<release-id>/manifest.json` has
`meta.schema_version=2` and records the validated release binding, freshness
records, artifact paths, hashes, artifact summaries, command summaries,
release-health status, approval metadata, retention metadata, storage
verification metadata, and missing required artifacts. Missing readyz,
trajectory stats, replay comparison, eval report, baseline eval report,
production smoke, Postgres ops, OTel smoke, or governance report artifacts
should block production release review. Missing or non-approved
deployment-platform approval should also block production evidence review;
when `--storage-dir` is used, the manifest records whether the retained
manifest and summary match the local pack.

Postgres migration verification can be attached as either a machine-readable migration report or the command evidence that generated it:

```bash
uv run python -m focus_agent.migrate_local_state \
  --database-uri postgresql://user:pass@host:5432/focus_agent \
  --artifact-scan \
  --report-path reports/release-gate/postgres-migration.json
```

Production smoke, Postgres ops, and OTel smoke can be planned before deployment wiring with deterministic dry-run reports:

```bash
uv run python scripts/production_smoke.py \
  --dry-run \
  --base-url https://focus-agent.example.com \
  --web-base-url https://focus-agent.example.com \
  --report-json reports/release-gate/production-smoke.json

uv run python scripts/postgres_ops.py \
  --dry-run \
  --report-json reports/release-gate/postgres-ops.json

uv run python scripts/otel_smoke.py \
  --dry-run \
  --endpoint http://otel-collector:4318 \
  --service-name focus-agent \
  --report-json reports/release-gate/otel-smoke.json
```

Live production examples:

```bash
uv run python scripts/production_smoke.py \
  --base-url https://focus-agent.example.com \
  --web-base-url https://focus-agent.example.com \
  --auth-token <token> \
  --stream-events-json reports/release-gate/stream-events.json \
  --rate-limit-min-limit 1 \
  --report-json reports/release-gate/production-smoke.json

uv run python scripts/postgres_ops.py \
  --database-uri postgresql://user:pass@host:5432/focus_agent \
  --backup-command 'pg_dump --format=custom --file=/tmp/focus-agent.dump postgresql://user:pass@host:5432/focus_agent' \
  --restore-command 'pg_restore --dbname=postgresql://user:pass@restore-host:5432/focus_agent_verify /tmp/focus-agent.dump' \
  --restore-verification-query 'SELECT 1' \
  --retention-cleanup-query 'SELECT 1' \
  --report-json reports/release-gate/postgres-ops.json

uv run python scripts/otel_smoke.py \
  --endpoint http://otel-collector:4318 \
  --collector-health-url http://otel-collector:13133/healthz \
  --trace-query-url 'https://traces.example.com/api/traces/{trace_id}' \
  --report-json reports/release-gate/otel-smoke.json

uv run python scripts/agent_governance_report.py \
  --report-json reports/agent-governance/latest.json \
  --max-review-queue-backlog 10 \
  --max-avg-cost-usd 0.05
```

Attach these reports to release-health with `--production-smoke-report-json`, `--postgres-ops-report-json`, `--otel-smoke-report-json`, and `--governance-report-json`. The reports intentionally fail closed when supplied: empty coverage, malformed JSON, explicit `passed=false`, failed statuses, failed row-level checks, or governance blocking signals block the release-health result.

Ownership allow / deny checks can be exported as trajectory-compatible `ownership.audit` entries. The exported payload includes principal, resource type, resource id, action, decision, reason, and request id, which makes cross-principal denials searchable in the same observability pipeline without adding a new database schema.

## 8. Recommended Oncall Flow

Use this order when responding to production issues:

1. Check `/readyz` to separate runtime readiness from simple process liveness.
2. Check `/metrics` or `/v1/observability/overview` to see whether the issue is broad or scoped.
3. Open `/app/observability/overview` and identify the hottest scene, tool, branch role, or model slice.
4. Open `/app/observability/trajectory` and pivot into the exact request, trace, thread, or model.
5. Read the summary card and note which evidence mode you are in: `timeline`, `zero_step`, or `missing_detail`.
6. Inspect the selected turn's error text, fallback steps, cache behavior, input/output narrative, and runtime metadata.
7. Preview promotion for a representative failed turn.
8. Batch replay or promote the slice if it should become a regression artifact.

## 9. Local Verification Commands

These are the repo-local checks that currently validate the observability stack and release regression gate:

```bash
make lint
make contract-check
make ci-test
make sdk-check
make sdk-build
make web-check
make web-build
uv run python scripts/observability_ui_smoke.py --scenario all
pnpm --dir apps/web smoke:observability
uv run python -m tests.eval --suite smoke --concurrency 1 --fail-if-regression
uv run python -m tests.eval --suite observability --concurrency 1
```

`make ui-smoke-observability` remains the short local target. For release verification, prefer the explicit browser smoke command with `--scenario all` so overview and trajectory evidence states are exercised under one scenario set. The smoke asserts replay/promote controls and exercises promotion for the success seed.

`pnpm --dir apps/web smoke:observability` is a source-level route and wiring check. It complements the real-browser smoke; it does not launch a browser or call the API.

For CI browser evidence, inspect the `Browser Smoke` workflow result and its
`browser-smoke-<run_id>-<run_attempt>` artifact. A local run should be reported
separately with its Chrome version, `CHROME_PATH`, API/base URL, and generated
JSON output; do not describe it as the workflow result.

If your local `.venv` cannot import `psycopg` because `libpq` is missing, use the focused test workaround already documented in [architecture.md](architecture.md).

## 10. Current Boundaries

- Trajectory observability depends on PostgreSQL-backed persistence or another initialized trajectory recorder.
- When `DATABASE_URI` is absent in a raw local process, app state and LangGraph
  checkpoint/store data default to repo-local SQLite. This keeps local state
  durable, but it does not provide production trajectory observability or
  shared multi-process coordination.
- Legacy pickle checkpoint/store files are loaded only when ownership and HMAC
  verification succeed. Missing keys, missing or invalid signatures, owner
  mismatches, and corrupt payloads fail closed; disabling verification is not a
  normal observability recovery step.
- `/metrics` currently includes trajectory aggregate metrics when they are available; high-frequency scrape behavior should still be reviewed alongside your global API rate-limit settings.
- OpenTelemetry exporter wiring is implemented with standard `OTEL_TRACES_EXPORTER` and `OTEL_EXPORTER_OTLP_*` settings, but collector reachability and desktop-browser automation still depend on the current deployment and execution environment.
