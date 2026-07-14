# Validation Runbook

Updated: 2026-07-14

This runbook is the local evidence plan for broad Focus Agent changes across the
self-hosted workbench platform. Use it when changes touch Agent runtime state,
sandbox execution, Skill contracts, streaming, SDK types, Web UI routes, Agent
Team, observability, auth, memory, Android local runtime, or release-health
behavior.

Product layers and fit/non-fit: [project-overview.md](project-overview.md).
Scoped day-to-day commands: [development.md](development.md). Remaining risk
list: [roadmap.md](roadmap.md).

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

For Agent Team v2, `/readyz` only reports process/runtime readiness. Separately,
`GET /v2/agent-team/readiness` calls `build_agent_team_readiness(settings,
runtime=runtime)` and returns `ready=true` only when its `phase=ready` and all
three service capabilities (task-run, evidence, revision) are available. When
real execution is requested, the assessment checks configured provider
credential references, durable jobs/worker, Postgres/coordination, fencing,
locks, and Docker fail-closed. The response does not execute a task or expose
the complete blocker/evidence payload; retain independent provider/Docker
checks and real-run evidence. Do not use either response alone to claim that a
real run succeeded or has been released.

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

### Agent Team v2 Gray Validation

Agent Team v2 is default-off. A visible Agent Team workbench, an available
`/v1/agent-team/*` route, a `ready=true` response from
`/v2/agent-team/readiness`, or a successful fake executor test does not prove
that a real task has executed, produced deliverable evidence, or been released.
Before a v2 gray
change, capture the effective `MULTI_AGENT_*` flags and verify that the
unmodified normal chat path creates no Team session, task, worktree, resource
claim, or message.

Run the focused state-machine and configuration gates:

```bash
uv run pytest \
  tests/test_multi_agent_config.py \
  tests/test_agent_team_multi_agent.py \
  tests/test_agent_team_dynamic_execution.py \
  tests/test_agent_team_merge_review.py \
  tests/integration/multi_agent/test_acceptance.py \
  -q
```

Then validate each enabled gray stage with an explicit Team session:

1. `/readyz` returns HTTP 200 and `ready=true` before and after the flag
   change. Save `/v2/agent-team/readiness` too: it is a configuration/runtime
   prerequisite gate that includes provider/Docker configuration and runtime
   prerequisites, not proof that a real task execution succeeded.
2. The task graph shows dependency ordering, bounded parallelism, and—when
   enabled—resource claims only for declared resources.
3. The session view preserves task/run/output state, progress messages, and
   pending approvals scoped to the selected session.
4. A required approval records a redacted pending request. Its approve/reject
   decision is followed by an explicit, separately recorded task/run retry.
   Current async approval queue decisions do **not** automatically replay a
   graph invocation that already returned. The repository has an internal
   approval resume-job state machine, but no public API/runtime executor
   integration currently consumes its jobs; it is not an end-user automatic
   resume feature.
5. A real writable run has `execution_mode=inline` or `background`, a real
   `model_id`, `agent_run_id`, artifact ids, worktree metadata, `git diff
   --check`, and actual test output. `fake`, `observe`, placeholder output, or
   summary text alone is not real execution evidence.
6. A merge review is previewed and explicitly applied or rejected. Do not
   report it as a commit, push, or merge to `main`.

Before attempting item 5, inspect the full Agent Team readiness assessment. It
must have no blockers and must confirm `AGENT_TEAM_V2_ENABLED=true`, a non-`off`
rollout phase, `AGENT_TEAM_KILL_SWITCH_ENABLED=false`,
`AGENT_TEAM_DURABLE_REQUIRED=true`, Postgres database/repository/coordination,
`BACKGROUND_JOB_BACKEND=postgres`, `BACKGROUND_JOB_EXECUTION=durable`, a started
durable worker, fencing, cross-session locks, resource locks, real
provider/model credentials, and Docker fail-closed. The Postgres Agent Team
repository persists v2 task-run/checkpoint/tool/evidence/event records; the
repository without `DATABASE_URI` remains an in-memory fallback. Approval
resume store/task state are still in-memory, and the public runtime does not
consume resume jobs; retain an explicit rerun instead of claiming recovery
across restart.

`make ui-smoke-agent-team-adoption` is a source-level adoption wiring check; it
does not launch Chrome or invoke a model. `make agent-team-evidence` runs
deterministic Agent Team worktree/chat tests plus a deterministic UI fixture;
its `scripts/agent_team_ui_smoke.py --mode real` deliberately returns
`disabled` until an approved browser/provider adapter exists. Therefore there
is no dedicated canonical real-browser Agent Team v2 smoke command in the
current repository. For a user-facing v2 gray, run a controlled Chrome session
against the target environment and retain screenshots/video plus browser
console/network logs showing: session creation, task evidence, approval
decision, explicit rerun, and merge-review result. Record the Chrome version,
target URL, authenticated principal, exact prompt, start/end time, session id,
task ids, and pass/fail criteria. Do not describe this manual evidence as a CI
browser workflow pass.

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
not Docker-isolation evidence. See
[Agent Team v2 Gray Validation](agent-team-v2-rollout.md) and the
[Multi-Agent Runtime Runbook](multi_agent_refactor/runbook.md) for the
gray/rollback order.

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
