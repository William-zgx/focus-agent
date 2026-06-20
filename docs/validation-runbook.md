# Validation Runbook

Updated: 2026-06-20

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

## 6. Completion Rules

Do not report a broad validation pass when any of these are true:

- `/readyz` is degraded,
- browser smoke only loaded the page but did not complete chat/branch/review,
- local sandbox fallback is being described as secure Docker isolation,
- generated SDK or OpenAPI files drift,
- source-level smoke passes but the corresponding real browser flow was never
  attempted for a user-facing change,
- a failed command is excluded without a clear scope reason.

Record skipped checks explicitly in the final verification summary.
