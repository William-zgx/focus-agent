# Validation Runbook

Updated: 2026-11-01; source facts corrected, historical validation scope unchanged.
Historical validation baseline: `718be87`

This runbook is the local evidence plan for broad Focus Agent changes across the
self-hosted workbench platform. Use it when changes touch Agent runtime state,
sandbox execution, Skill contracts, streaming, SDK types, Web UI routes, Agent
governance or coordination, observability, auth, memory, Android local runtime,
or release-health behavior.

Product layers and fit/non-fit: [project-overview.md](project-overview.md).
Scoped day-to-day commands: [development.md](development.md). Remaining risk
list: [roadmap.md](roadmap.md).

Latest local execution evidence: [2026-10-03 MR quality report](validation/2026-10-03-mr-quality.md).
It separates real-provider Chrome runs from response fixtures and records failing
baseline gates and unavailable infrastructure. This is not a production release
certificate or an assertion that every gate passed.

The goal is to prove three things before claiming readiness:

- the source tree is internally consistent,
- the runtime can start and report truthful component readiness through `/readyz`,
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
make install-openai
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

`/healthz` only proves the process is alive. `/readyz` is the runtime readiness
gate, not a universal dependency probe. A `200`/`ready=true` response can still
come from local/fallback checks. Retrieval fallback now requires an available
search-capable repository/store, not just a configured name; this capability
check still does not establish a successful database query. Inspect component
details and run explicit DB/provider smoke checks before claiming dependencies
are ready. A common local failure is `background_jobs` reporting old pending work; inspect
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
Uvicorn owns process signals; the application lifespan registers shutdown hooks
without replacing Uvicorn's handlers. The October 3 validation includes actual
isolated API processes exiting normally on `SIGTERM` and a regression test for
handler ownership. This does not establish production in-flight drain behavior
under load; test that separately from local persistence and idle process exit.

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
make sdk-build
node tests/test_thread_stream_frontend_regressions.mjs
```

The standalone Node regression imports `frontend-sdk/dist/index.js`; build the
SDK first so it does not exercise a missing or stale distribution artifact.

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

### Subtask, Approval, And Merge-Review Validation

When bounded `run_subtask` execution, retained multi-agent coordination, async
approvals, or generic merge review changed, run the retained focused checks:

```bash
uv run pytest \
  tests/test_agent_core_v2_subtask.py \
  tests/test_coordination.py \
  tests/test_multi_agent_config.py \
  tests/unit/multi_agent/test_core.py \
  tests/test_merge_review.py \
  -q
```

Before changing flags, capture the effective `MULTI_AGENT_*` settings and the
`run_subtask` tool policy. Confirm that an unmodified normal chat turn does not
create subtask runs, resource claims, or agent-to-agent messages unless the
model invokes `run_subtask` or the corresponding coordination controls
explicitly enable that behavior.

For each enabled coordination stage, retain evidence for these boundaries:

1. `/readyz` returns HTTP 200 and `ready=true` before and after the change.
   This is runtime readiness, not proof of provider health or task execution.
2. Subtask/tool records preserve their ordering, run/output state, progress
   messages, and pending approvals with the expected owner/run scope.
3. A required approval records a redacted pending request. Its approve/reject
   decision changes the queue record but does not automatically replay a graph
   invocation that already returned; perform an explicit, separately recorded
   task/run retry.
4. If real subtask execution is under test, retain its real model id, parent and
   child run ids, artifact ids, actual tool output, and actual test output.
   Fake-model, placeholder output, or summary text alone is not real execution
   evidence.
5. Preview each merge review and explicitly apply or reject it. Do not report
   that review as a commit, push, or merge to `main`.

See [Architecture](architecture.md) for the retained coordination and approval
configuration contract.

Likewise, fixture/fake model tests do not validate a real provider. Real-model
evidence must preserve provider/model identity, redacted request/run metadata,
artifact ids, actual tool or test output, and failure/timeout behavior. Never
log provider keys or unredacted sensitive tool arguments.

For worktree-producing tasks, retain:

```bash
git -C "$WORKSPACE_PATH" status --short
git -C "$WORKSPACE_PATH" diff --check
git -C "$WORKSPACE_PATH" diff --stat
```

For workspace commands and Skill entrypoints in a shared or production-like
validation, verify Docker fail-closed configuration and result metadata:

```dotenv
FOCUS_AGENT_SANDBOX_BACKEND=docker
FOCUS_AGENT_SANDBOX_ALLOW_LOCAL_FALLBACK=0
```

`fallback_used=true`, `degraded_reason=local_host_execution`,
`sandbox_backend=local_subprocess`, or `local_venv` is degraded local evidence,
not Docker-isolation evidence.

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
replay comparisons, eval reports, production smoke, Postgres ops, or OTel smoke
must block production release review.

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
standard eval, and memory/context writers attach that identity from the
environment. Downloaded JSON must pass
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

These identity checks validate the captured runtime binding, not database or
provider health. In production, pair the payload with the required migration,
Postgres ops, provider, and smoke reports; do not use HTTP 200 from a fallback
readiness check as their substitute.

Run the production pack only after those fields, all input bindings, and all
timestamps have been checked:

```bash
make release-evidence RELEASE_EVIDENCE_ARGS="--release-id <release-id> --approval-id <approval-id> --approval-status approved --readyz-json reports/release-gate/readyz.json --trajectory-stats-json reports/release-gate/trajectory-stats.json --replay-comparisons-json reports/release-gate/replay-comparisons.json --production-smoke-report-json reports/release-gate/production-smoke.json --postgres-ops-report-json reports/release-gate/postgres-ops.json --otel-smoke-report-json reports/release-gate/otel-smoke.json --eval-report-json reports/release-gate/eval-smoke.json --baseline-eval-report-json reports/release-gate/baseline-eval-smoke.json"
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
- `/readyz` is `ready=true` only because a local/fallback component check passed,
  without the required external dependency smoke evidence,
- a required evidence input is older than the configured freshness window,
- generated SDK or OpenAPI files drift,
- source-level smoke passes but the corresponding real browser flow was never
  attempted for a user-facing change,
- a failed command is excluded without a clear scope reason.

Record skipped checks explicitly in the final verification summary.
