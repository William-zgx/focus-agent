# Validation Runbook

Updated: 2026-07-12

This runbook is the local evidence plan for broad Focus Agent changes. Use it
when changes touch Agent runtime state, sandbox execution, Skill contracts,
streaming, SDK types, Web UI routes, Agent Team, observability, auth, memory, or
release-health behavior.

The goal is to prove three things before claiming readiness:

- the source tree is internally consistent,
- the runtime can start and report `/readyz` as ready,
- the product-specific Web surfaces and Agent workflows still work in a real
  browser or their canonical smoke checks.

## 1. Preconditions

Start from a clean worktree or record the intentional diff:

```bash
git status --short --branch --untracked-files=all
```

Install local dependencies and config when needed:

```bash
uv venv
uv pip install -e '.[openai,dev]'
make setup-local
pnpm install --registry=https://registry.npmjs.org
```

The browser smoke scripts automatically add headless Chromium flags on Linux
machines without a graphical display. If an older Chromium build still fails to
start, use a temporary wrapper and pass it through `CHROME_PATH`:

```bash
cat > /tmp/focus-agent-chromium-headless <<'SH'
#!/usr/bin/env bash
exec /usr/bin/chromium --headless --no-sandbox "$@"
SH
chmod +x /tmp/focus-agent-chromium-headless
export CHROME_PATH=/tmp/focus-agent-chromium-headless
```

The GitHub Actions `Browser Smoke` workflow is a separate real-Chrome gate. It
installs Google Chrome, builds the production Web app, starts PostgreSQL and a
deterministic model fixture, runs chat/streaming/branch/review plus all
observability scenarios, and uploads `reports/browser-smoke/`. A successful
local command is useful evidence, but must not be reported as a successful
workflow run.

If browser smoke must prove Docker-backed sandbox execution, build the sandbox
image first:

```bash
make sandbox-image
```

Without `focus-agent-sandbox:latest`, dev runs may fall back to
`local_subprocess` or `local_venv`. That is valid degraded evidence for local
development only; it must not be reported as secure Docker isolation.

## 2. Runtime Start And Readiness

Start the full dev stack:

```bash
API_RELOAD=0 make serve-dev
```

Then verify liveness, readiness, and the Vite app:

```bash
curl --fail --show-error --silent http://127.0.0.1:8000/healthz
curl --fail --show-error --silent http://127.0.0.1:8000/readyz
curl --fail --show-error --silent http://127.0.0.1:5173/app/
```

`/healthz` only proves the process is alive. `/readyz` is the readiness gate. A
common local failure is `background_jobs` reporting old pending work; inspect
`/v1/admin/background-jobs/summary`, drain or restart the local dev process, and
recheck `/readyz` before treating the environment as ready.

`make serve-dev` defaults to API hot reload for daily development. Broad browser
validation should set `API_RELOAD=0` because codegen, smoke reports, or script
edits can otherwise trigger a dev reload and leave `/readyz` temporarily
degraded with `shutdown_drain`.

When running the API binary directly without `DATABASE_URI`, local app state and
LangGraph checkpoint/store data default to SQLite under `.focus_agent/`.
Stopping and restarting the process should preserve that state. This local
durability does not substitute for the managed PostgreSQL path used by the
standard `make api` / `make dev` startup commands, and it is not evidence of
shared production persistence.

If legacy pickle checkpoint/store files exist, startup and local-state migration
must fail closed on a missing HMAC key, missing or invalid signature, file-owner
mismatch, corrupt payload, unknown SQLite schema, ambiguous SQLite/pickle
sources, or active SQLite `-wal` / `-shm` files. Stop the runtime and resolve the
source explicitly; do not make verification pass by disabling signature
checking.

## 3. Source And Contract Gates

Run the broad local CI parity gate:

```bash
make ci
```

Run the generated OpenAPI / SDK drift guard separately, because it is not part
of `make ci`:

```bash
make sdk-openapi-types-check
```

For frontend-only broad changes, add the frontend QA bundle:

```bash
make frontend-qa
```

For sandbox or Skill execution changes, include the focused backend contracts:

```bash
.venv/bin/python -m pytest \
  tests/test_sandbox_execution.py \
  tests/test_default_tools.py \
  tests/test_skill_registry.py \
  tests/test_execution_contract.py \
  tests/test_skill_execution_matrix.py \
  -q
```

## 4. Real-Browser And Product-Specific Smoke

Run the main chat / streaming / branch / merge-review browser smoke with a
realistic prompt:

```bash
CHROME_PATH=${CHROME_PATH:-/tmp/focus-agent-chromium-headless} \
.venv/bin/python scripts/ui_smoke_test.py \
  --app-url http://127.0.0.1:5173/app/ \
  --health-url http://127.0.0.1:8000/healthz \
  --message '请用中文解释一次失败的 Python Skill 执行如何经过线程级沙箱、Skill 执行契约和 runtime outcome 形成用户可理解的反馈。'
```

Run the observability browser smoke across success, failed, zero-step, and
missing-detail trajectory evidence states:

```bash
CHROME_PATH=${CHROME_PATH:-/tmp/focus-agent-chromium-headless} \
.venv/bin/python scripts/observability_ui_smoke.py \
  --app-base-url http://127.0.0.1:5173/app \
  --health-url http://127.0.0.1:8000/healthz \
  --scenario all \
  --no-start-api
```

Run source-level product smoke for Web-only wiring that is not fully exercised
by the browser scripts:

```bash
pnpm --dir apps/web smoke:observability
pnpm --dir apps/web smoke:productivity
pnpm --dir apps/web smoke:agent-team-adoption
node tests/test_thread_stream_frontend_regressions.mjs
```

These commands do not all provide the same evidence:

- `scripts/ui_smoke_test.py` and `scripts/observability_ui_smoke.py` drive the
  Chrome binary supplied by `CHROME_PATH`.
- `.github/workflows/browser-smoke.yml` is the canonical CI real-Chrome
  interaction gate and retains diagnostics as a workflow artifact.
- `pnpm --dir apps/web smoke:*` and the Node regression tests are source/local
  runtime checks; they do not prove that a real browser rendered and completed
  the interaction.

For Android changes, run the local runtime smoke and the same build/lint/unit
tasks used by the `android` CI job:

```bash
pnpm android:runtime:smoke
pnpm android:sync:debug
(cd android && ./gradlew --no-daemon assembleDebug lintDebug testDebugUnitTest)
```

The CI job does not run `connectedAndroidTest`. When device behavior is in
scope, add a real emulator or attached-device instrumentation run and record
the API level, device image, test count, and result separately from the CI
debug build/lint/unit result.

When Agent Team changed, also exercise the backend API flow:

- create a session,
- create at least one task with `active_skill_ids`,
- record a task output,
- fetch `/view`,
- prepare a merge bundle.

When Skill selection changed, verify all explicit paths:

- plain skill id in user text,
- `.focus_agent/skills/<skill_id>/SKILL.md` path in user text,
- explicit `skill_hints`,
- prefix trigger such as `china-stock-analysis:`.

When sandbox fallback changed, verify the payload includes
`fallback_used=true`, `degraded_reason=local_host_execution`, and a local
backend name when Docker is unavailable.

## 5. Release-Health Evidence

For release candidates, collect or generate the release evidence pack described
in [release-checklist.md](release-checklist.md). A local preflight can use:

```bash
make release-gate
```

Production release-health must be fail-closed and should use real deployment
signals rather than local fallback reports. Missing `/readyz`, trajectory stats,
replay comparisons, eval reports, production smoke, Postgres ops, OTel smoke, or
governance reports must block production release review.

Before collecting production evidence, export one complete identity:

```bash
export RELEASE_COMMIT_SHA="$(git rev-parse HEAD)"
export RELEASE_DEPLOYMENT_ID='<deployment-id>'
export RELEASE_DEPLOYMENT_VERSION='<deployment-version>'
export RELEASE_ENVIRONMENT='production'
```

All four variables are required together for non-dry-run report writers.
`RELEASE_COMMIT_SHA` must resolve and equal the checked-out `HEAD`. Every JSON
input in a production pack must carry a timezone-aware evidence timestamp and a
matching top-level `release_binding` with `commit_sha`, `deployment_id`,
`deployment_version`, and `environment`. Production smoke, Postgres ops, OTel,
governance, standard eval, and memory/context writers attach that identity from
the environment. Downloaded JSON must pass
`scripts/release_evidence_capture.py`.

The capture helper validates existing bindings before replacing their location
with one canonical top-level binding. Existing timestamps are preserved, so a
download cannot make stale evidence fresh. Only `/readyz` and trajectory-stats
live snapshots may use `--captured-now` when no timestamp exists. Replay,
alert, migration, baseline eval, and static stream-event reports must supply an
upstream timestamp. Static stream evidence is checked again inside
`production_smoke.py`; the smoke report records its byte size and SHA-256.

The schema-v2 pack defaults to a 21,600-second (6-hour) maximum evidence age and
collection window. `/readyz` must additionally report:

```text
deployment == RELEASE_DEPLOYMENT_ID
app_version == RELEASE_DEPLOYMENT_VERSION
environment == RELEASE_ENVIRONMENT
```

Run the production pack only after those fields, all input bindings, and all
timestamps have been checked:

```bash
make release-evidence RELEASE_EVIDENCE_ARGS="--release-id <release-id> --approval-id <approval-id> --approval-status approved --readyz-json reports/release-gate/readyz.json --trajectory-stats-json reports/release-gate/trajectory-stats.json --replay-comparisons-json reports/release-gate/replay-comparisons.json --production-smoke-report-json reports/release-gate/production-smoke.json --postgres-ops-report-json reports/release-gate/postgres-ops.json --otel-smoke-report-json reports/release-gate/otel-smoke.json --governance-report-json reports/agent-governance/latest.json --eval-report-json reports/release-gate/eval-smoke.json --baseline-eval-report-json reports/release-gate/baseline-eval-smoke.json"
```

Verify `reports/release-gate/<release-id>/manifest.json` has
`meta.schema_version=2`, `summary.status=passed`,
`release_binding.status=passed`, and `evidence_validation.passed=true`.
`make release-gate` and dry-run packs prove command wiring only; dry-run or
self-check fallback reports are not production evidence.

## 6. Completion Rules

Do not report a broad validation pass when any of these are true:

- `/readyz` is degraded,
- browser smoke only loaded the page but did not complete chat/branch/review,
- a source-level smoke is being described as a real-Chrome workflow pass,
- the Android debug build/lint/unit job is being described as emulator
  instrumentation evidence,
- local sandbox fallback is being described as secure Docker isolation,
- a production evidence input lacks a timezone-aware timestamp or complete,
  matching release binding,
- a static report was given `--captured-now` or an existing timestamp was
  replaced to make evidence appear fresh,
- a static stream-event report is missing/mismatched/stale, even if the outer
  production-smoke report has the current release binding,
- `/readyz` identifies a different deployment, app version, or environment,
- a required evidence input is older than the configured freshness window,
- generated SDK or OpenAPI files drift,
- source-level smoke passes but the corresponding real browser flow was never
  attempted for a user-facing change,
- a failed command is excluded without a clear scope reason.

Record skipped checks explicitly in the final verification summary.
