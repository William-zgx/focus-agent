# Release Checklist

This checklist is intended for maintainers preparing Focus Agent for a public release or a tagged internal milestone. It is the human release-readiness checklist: what to confirm, what blocks release, and what evidence must exist. CI provider binding details live in [docs/ci/github-actions-release-gate.md](ci/github-actions-release-gate.md) from this docs directory.

```mermaid
flowchart LR
    Repo["Repository readiness"] --> Product["Product and API review"]
    Product --> Config["Configuration review"]
    Config --> Quality["Quality checks"]
    Quality --> Security["Security review"]
    Security --> Package["Release packaging"]
    Package --> Followup["Post-release follow-up"]
```

## Repository Readiness

- Confirm `README.md` reflects the current project scope and setup flow
- Confirm `README.zh-CN.md` is still aligned with the English README
- Confirm `CONTRIBUTING.md` reflects the expected contribution workflow
- Confirm `SECURITY.md` has a real private reporting path before public release
- Confirm `.github` issue templates and PR template still match repository conventions
- Remove internal-only references, examples, or wording from docs
- Review tracked files for secrets, tokens, internal hosts, or private organization details

## Licensing and Governance

- Confirm MIT license references still match the root `LICENSE` file
- Ensure README and other docs reference the final license correctly
- Decide whether a `NOTICE`, CLA, or DCO process is required

## Product and API Review

- Confirm the documented API routes still exist and match current behavior
- Confirm SSE event names and payload expectations are still accurate
- Confirm branch lifecycle behavior is still reflected correctly in docs
- Confirm auth behavior, ownership rules, protected-route `return_to`, logout, and account switching are documented accurately
- Confirm Admin Console docs match `/app/admin/config`, `/app/admin/users`, `/app/admin/audit-events`, persisted admin role checks, reasoned admin actions, session revoke, password reset, and last-active-admin protection
- Confirm settings center docs match the current Overview / Connections / Capabilities / Agent Behavior / Security & Runtime / Advanced layout, including Skill management and the MCP reserved connection entry
- Confirm the frontend SDK examples still match the live contract
- Confirm Agent Team docs match dynamic planning, standalone sessions, task contracts, Cockpit UI, retry/cancel, final-answer status, and merge bundle behavior
- Confirm trajectory observability docs match the live API, CLI, and `/app/observability/trajectory` console
- Confirm trajectory failure promotion preview and batch replay workflow still match the API and eval CLI
- Confirm OTel exporter env vars and runtime readiness docs still match the live tracing behavior
- Confirm `docs/api/openapi.json` and `frontend-sdk/src/types/__generated__.ts` were regenerated after any API shape change
- Confirm alert guidance uses the existing `/metrics` endpoint and current metric names
- Confirm Memory v2 and Zvec retrieval docs match the live PostgreSQL canonical store, `retrieval_zvec` readiness, pgvector fallback readiness, memory API authorization, forget tombstone/erasure behavior, and Memory Console fields
- Confirm runtime coordination docs match thread turn lease behavior, durable background job claim heartbeat, and first-turn branch title/metadata refresh after lease release
- Confirm Agent governance expectations still match `docs/agent-role-routing.md`, `/v1/agent/*`, and `/app/agent/governance`
- If Agent governance changed, confirm `/v1/agent/capabilities`, `/v1/agent/tool-router/*`, `/v1/agent/memory/curator/*`, and `/app/agent/governance`
- If Context Engineering changed, confirm `/v1/agent/context/*`, `/app/agent/governance`, and `tests/eval/datasets/agent_context.jsonl`
- If Task Ledger changed, confirm `/v1/agent/task-ledger/*`, `/v1/agent/artifacts`, `/v1/agent/critic/*`, `/app/agent/governance`, and `tests/eval/datasets/agent_task_ledger.jsonl`

## Configuration Review

- Review `.env.example` for completeness and safe defaults
- Review local config instructions under `.focus_agent/`
- Decide which settings are development-only versus production-ready
- Confirm non-development startup fails when auth is disabled, `AUTH_JWT_SECRET` is missing/default/shorter than 32 characters, demo tokens are enabled, or rate limiting is disabled
- Review persistence-related settings such as `DATABASE_URI`, Alembic migration execution, managed local Postgres runtime files, trajectory settings, `ARTIFACT_DIR`, and `ARTIFACT_STORE_TYPE`
- Review retrieval, memory embedding, and pgvector fallback settings: `AGENT_RETRIEVAL_BACKEND`, `AGENT_RETRIEVAL_FALLBACK_BACKEND`, `AGENT_ZVEC_ENABLED`, `AGENT_ZVEC_DATA_DIR`, `AGENT_MEMORY_EMBEDDING_ENABLED`, `AGENT_MEMORY_EMBEDDING_BACKEND`, `AGENT_MEMORY_EMBEDDING_MODEL`, `AGENT_MEMORY_EMBEDDING_DIMENSIONS`, `AGENT_MEMORY_EMBEDDING_BASE_URL`, `AGENT_MEMORY_EMBEDDING_API_KEY_ENV`, `AGENT_MEMORY_EMBEDDING_API_KEY`, `AGENT_MEMORY_EMBEDDING_BATCH_SIZE`, `AGENT_MEMORY_EMBEDDING_TIMEOUT_SECONDS`, `AGENT_MEMORY_VECTOR_SEARCH_MODE`, `AGENT_MEMORY_VECTOR_INDEX_ENABLED`, and `AGENT_MEMORY_PGVECTOR_EXTENSION_MODE`
- Review memory governance settings: `AGENT_MEMORY_POSTGRES_TRIGRAM_ENABLED`, `AGENT_MEMORY_APPROVAL_FOR_SHARED_WRITES`, `AGENT_MEMORY_CURATOR_ENABLED`, and `AGENT_MEMORY_AUTO_PROMOTE_ON_MERGE`
- Review runtime coordination settings: `BACKGROUND_JOB_EXECUTION`, `BACKGROUND_JOB_BACKEND`, `BACKGROUND_JOB_CLAIM_TTL_SECONDS`, `RUNTIME_THREAD_LOCK_TTL_SECONDS`, and `RUNTIME_THREAD_LOCK_HEARTBEAT_SECONDS`
- Review Skill settings: `FOCUS_AGENT_SKILLS_ENABLED`, `FOCUS_AGENT_SKILLS_DIRS`, `SKILL_INSTALL_DIRECTORY`, `SKILL_DISABLED_IDS`, `SKILL_SEMANTIC_MATCH_ENABLED`, and `SKILL_SEMANTIC_MATCH_THRESHOLD`

## Quality Checks

Required local/CI command gate:

```bash
make release-gate
```

This writes `reports/release-gate/latest.json` with per-command labels, status, duration, exit code, skip reason, and captured stdout/stderr summaries. For local iteration, pass CLI options such as `--dry-run`, `--only`, `--skip`, `--report-json`, and `--keep-going` through `RELEASE_GATE_ARGS`, for example:

```bash
make release-gate RELEASE_GATE_ARGS="--dry-run --only lint"
```

For broad pre-release validation outside CI, start with
[validation-runbook.md](validation-runbook.md). It defines the expected local
evidence bundle across runtime outcomes, sandbox fallback metadata, Skill
contracts, SDK/OpenAPI drift, Web source smoke, real-browser smoke, Agent Team,
observability, and release-health readiness.

For a fast API/SDK compatibility check before the full gate, run:

```bash
make contract-check
```

The orchestrated subset below follows `scripts/release_gate.py`; the generated
SDK type drift check and retrieval/embedding doctors are additional manual
preflights listed after it. Full local runs assume the API and Vite app are
reachable at the default smoke URLs
(`http://127.0.0.1:8000/healthz` and
`http://127.0.0.1:5173/app/`); use
`RELEASE_GATE_ARGS="--dry-run"` or scoped `--only` checks when those services
are not available. `make contract-check` remains a fast preflight outside the
full gate.

```bash
make lint
make ci-test
make sdk-check
make sdk-build
make web-check
make web-build
uv run python scripts/observability_ui_smoke.py --scenario all
pnpm --dir apps/web smoke:observability
uv run python scripts/ui_smoke_test.py
uv run python -m tests.eval --suite smoke --concurrency 1 --report-json reports/release-gate/eval-smoke.json
uv run python -m tests.eval --suite observability --concurrency 1 --report-json reports/release-gate/eval-observability.json
uv run python -m tests.eval --suite golden_multi_agent --concurrency 1 --report-json reports/release-gate/eval-golden-multi-agent.json
uv run python -m tests.eval --suite harness_stability --concurrency 1 --report-json reports/release-gate/eval-harness-stability.json
uv run python scripts/memory_context_eval.py --report-json reports/release-gate/memory-context-eval.json
uv run python scripts/agent_governance_report.py --report-json reports/agent-governance/latest.json
uv run python scripts/release_health_check.py --mode local --ready-url http://127.0.0.1:8000/readyz --trajectory-stats-url http://127.0.0.1:8000/v1/observability/trajectory/stats --allow-self-check-fallback --eval-report-json reports/release-gate/eval-smoke.json --eval-report-json reports/release-gate/eval-observability.json --eval-report-json reports/release-gate/eval-golden-multi-agent.json --eval-report-json reports/release-gate/eval-harness-stability.json --eval-report-json reports/release-gate/memory-context-eval.json --governance-report-json reports/agent-governance/latest.json --report-json reports/release-gate/release-health.json
```

Additional manual preflights:

```bash
make sdk-openapi-types-check
focus-agent-retrieval-index doctor
focus-agent-memory-embedding --database-uri "$DATABASE_URI" doctor
```

- `scripts/ui_smoke_test.py` covers the main chat, branch, and review routes; keep `make ui-smoke` as the shorthand local target. The smoke waits for assistant text to stabilize after streaming UI has stopped, so an idle disabled send button is not a readiness signal.
- Local Vite smoke URLs should use `http://127.0.0.1:5173/app/` with the trailing slash. Manual browser passes are useful, but personal Chrome profiles can carry stale localStorage, extensions, and auth state; prefer the smoke script's temporary Chrome profile for release evidence and use manual passes as an additional visual check.
- On SSH-only release hosts, set `CHROME_PATH` to a headless Chromium wrapper before running browser smoke. The canonical wrapper and readiness follow-up are documented in `docs/validation-runbook.md`.
- Auth/Admin UI changes also need a manual or in-app-browser pass through protected-route redirect, `Demo 登录`, username/password login after registration or admin password reset, settings center Overview/Connections/Capabilities navigation, Skill search and enablement toggles, sidebar logout, Bearer Token login, reasoned admin status/role update, session revoke, audit-event filtering, and logout-then-login account switching. Do not treat username/password registration as a release smoke shortcut because it creates persistent local users.
- `scripts/observability_ui_smoke.py --scenario all` seeds and exercises success, failed, zero-step, and missing-detail trajectory cases across overview and trajectory pages. The smoke records fetch request URLs and checks endpoint pathnames, so route/query serialization drift should fail loudly instead of relying on brittle string matches.
- `pnpm --dir apps/web smoke:observability` is a source-level route and wiring check; it complements the real-browser observability smoke and does not replace it.
- `make ui-smoke-agent-team-adoption` is the command name for the Agent Team adoption source-level smoke. It covers task selection, diff/test evidence, conflict/apply state, capture to Notes/Tasks, context evidence, and skill feedback wiring; pair it with real-browser coverage when changing the visual adoption flow.
- `scripts/memory_context_eval.py` covers the P7 memory/context quality probes: fact fidelity, key fact recall, irrelevant memory pollution, conflict memory marking, compaction answerability, and artifact refs.
- `scripts/feedback_regression.py` summarizes online feedback and adoption/governance signals into `reports/nightly/feedback-regression.json`. It is non-blocking when no production feedback artifact exists, but nightly reports must include its `feedback_pipeline` when events are provided.
- `focus-agent-retrieval-index doctor` is the Zvec release preflight. Include its output as release evidence when Zvec is enabled; it should show backend, data dir, collection/readiness status, and fallback backend without exposing vectors.
- `focus-agent-memory-embedding doctor` is the memory embedding/pgvector fallback preflight. Include its JSON output as release evidence when PostgreSQL memory embedding or pgvector fallback is enabled; it should show provider readiness, table dimension compatibility, extension status, and vector index state without exposing API keys or vector values.
- `scripts/release_health_check.py` converts readiness, trajectory stats, replay comparison rows, alert-rule reports, Postgres migration reports, production smoke, Postgres ops, OTel smoke, Agent governance quality, baseline eval reports, and current eval JSON reports into release-blocking health signals. Current release-blocking eval reports include smoke, observability, golden multi-agent, harness stability, and memory/context. `make release-gate` intentionally runs `--mode local` with `--allow-self-check-fallback` so local dry runs can complete when the API is down. Production release jobs must use `--mode production`, remove the fallback, and pass real production inputs. Missing required inputs fail closed with exit code 1. `--allow-dry-run-reports` is only a deliberate diagnostic escape hatch for direct health-check runs; it is not part of the canonical production evidence workflow.
- Without `--dry-run`, `make release-evidence` builds a production manifest whose `meta.schema_version` is `2`. Run it only after collecting the production deployment signals. The pack is written to `reports/release-gate/<release-id>/` and includes artifact hashes, artifact/failure summaries, release health, approval metadata, retention metadata, release identity validation, freshness validation, and storage verification.
- CI provider binding lives in `docs/ci/github-actions-release-gate.md` and `.github/workflows/release-gate.yml`. Keep provider-specific approval metadata, artifact upload, retention, and generic CI command skeletons in that CI document; this checklist only records the release-blocking evidence that must be present before tagging.

### Production Evidence Contract

Production evidence is fail-closed and is separate from `--dry-run` planning:

- Bind the pack to the complete `RELEASE_COMMIT_SHA`, `RELEASE_DEPLOYMENT_ID`, `RELEASE_DEPLOYMENT_VERSION`, and `RELEASE_ENVIRONMENT` tuple. The commit must be a hexadecimal SHA that resolves in the checkout and resolves to the current `HEAD`; deployment id and version must be non-empty; the environment must canonicalize to `production`.
- Every JSON supplied through a production `--*-json` evidence input must carry a timezone-aware evidence timestamp and a complete `release_binding` with the same four values. Required evidence timestamps must also fit within one collection window. The default maximum age and collection-window span is `21600` seconds; use `--max-evidence-age-seconds` only to make an intentional, reviewed override.
- `/readyz` must additionally expose `deployment`, `app_version`, and `environment`, matching the bound deployment id, deployment version, and production environment. These checks supplement, rather than replace, its timestamp and complete `release_binding`.
- Trusted capture must process every production JSON input that was not emitted
  by an attesting writer through `scripts/release_evidence_capture.py`. Existing
  top-level or `meta.release_binding` values must already match the environment;
  conflicts and partial bindings fail closed rather than being overwritten.
  Existing evidence timestamps must be timezone-aware and are preserved, so
  capture cannot make stale evidence look fresh. Only live `/readyz` and
  trajectory-stats snapshots may use the explicit `--captured-now` fallback
  when their response has no timestamp. Replay comparison, alert, Postgres
  migration, baseline eval, and static stream-event reports must supply their
  own timestamp.
- Six locally generated report classes attest from the four `RELEASE_*`
  variables: `production_smoke.py`, `postgres_ops.py`, `otel_smoke.py`,
  `agent_governance_report.py`, eval reports written through
  `tests.eval.reporting`, and `memory_context_eval.py`. These writers add a
  timezone-aware `generated_at` and complete `release_binding`; if only part of
  the tuple is set, a non-dry-run writer refuses to write the report. With all
  four variables absent, ordinary local and generic CI reports remain valid but
  are not production evidence.
- Production still requires an explicit path-safe release id, approved deployment-platform `approval_id` and `approval_url`, all required artifacts, and verified retained storage. `--storage-dir` copies the pack to `<storage-dir>/<release-id>`; the manifest records hash verification and the requested retention window.
- Dry-run evidence uses deterministic sample identity and does not require, consume, or pretend to attest the production four-tuple.

The checked-in GitHub production workflow now downloads raw JSON into a
temporary directory, validates and atomically writes the attested copy, and
removes the temporary source. `/readyz` also cross-checks `deployment`,
`app_version`, and `environment`. The provider-neutral command catalog uses the
same `curl -> release_evidence_capture.py` order and keeps raw files outside the
release artifact directory. A capture, timestamp, or identity mismatch stops
the workflow before production smoke or evidence assembly.

After the production reports have been generated under the bound environment, build the pack with explicit identity arguments:

```bash
make release-evidence RELEASE_EVIDENCE_ARGS="--release-id <release-id> --commit-sha ${RELEASE_COMMIT_SHA} --deployment-id ${RELEASE_DEPLOYMENT_ID} --deployment-version ${RELEASE_DEPLOYMENT_VERSION} --environment ${RELEASE_ENVIRONMENT} --max-evidence-age-seconds 21600 --approval-id <approval-id> --approval-status approved --approval-url <approval-url> --retention-days 90 --storage-dir reports/release-gate/archive --readyz-json reports/release-gate/readyz.json --trajectory-stats-json reports/release-gate/trajectory-stats.json --replay-comparisons-json reports/release-gate/replay-comparisons.json --alert-report-json reports/release-gate/alert-report.json --postgres-migration-report-json reports/release-gate/postgres-migration.json --production-smoke-report-json reports/release-gate/production-smoke.json --postgres-ops-report-json reports/release-gate/postgres-ops.json --otel-smoke-report-json reports/release-gate/otel-smoke.json --governance-report-json reports/agent-governance/latest.json --eval-report-json reports/release-gate/eval-smoke.json --eval-report-json reports/release-gate/eval-observability.json --eval-report-json reports/release-gate/eval-golden-multi-agent.json --eval-report-json reports/release-gate/eval-harness-stability.json --eval-report-json reports/release-gate/memory-context-eval.json --baseline-eval-report-json reports/release-gate/baseline-eval-smoke.json"
```

Nightly and production smoke entrypoints:

```bash
make nightly-regression
make feedback-regression
uv run python -m tests.eval --suite model_matrix --concurrency 1 --report-json reports/nightly/eval-model-matrix.json
uv run python -m tests.eval --suite trajectory_failures --concurrency 1 --report-json reports/nightly/eval-trajectory-failures.json
make production-smoke PRODUCTION_SMOKE_ARGS="--dry-run --base-url https://focus-agent.example.com"
make postgres-ops POSTGRES_OPS_ARGS="--dry-run"
make otel-smoke OTEL_SMOKE_ARGS="--dry-run --endpoint http://otel-collector:4318"
make agent-governance-report
```

Schema v17 migration evidence:

- Confirm `uv run alembic -c alembic.ini heads` reports `001_baseline (head)`.
- Confirm container or release workflow runs `alembic upgrade head` against the production `DATABASE_URI`, or captures equivalent migration evidence.
- Confirm Postgres ops reports all expected `focus_schema_migrations` versions through v17 before production promotion, including `focus_branch_decision_events`.
- Confirm `focus_rate_limit_buckets` exists when API rate limiting is enabled on Postgres-backed deployments.
- Confirm `reports/nightly/latest.json` contains `summary.feedback_pipeline` and `artifacts.feedback_regression`.
- If production feedback exports are available, pass them through `FEEDBACK_REGRESSION_ARGS`, for example `--feedback-events-json`, `--merge-review-json`, `--skill-selection-json`, `--context-evidence-json`, and `--productivity-capture-json`.

Production examples with live evidence:

```bash
export RELEASE_COMMIT_SHA="$(git rev-parse HEAD)"
export RELEASE_DEPLOYMENT_ID="<deployed-id>"
export RELEASE_DEPLOYMENT_VERSION="<deployed-version>"
export RELEASE_ENVIRONMENT="production"

make production-smoke PRODUCTION_SMOKE_ARGS="--base-url https://focus-agent.example.com --web-base-url https://focus-agent.example.com --auth-token <token> --stream-events-json reports/release-gate/stream-events.json --rate-limit-min-limit 1 --report-json reports/release-gate/production-smoke.json"
make postgres-ops POSTGRES_OPS_ARGS="--database-uri postgresql://user:pass@host:5432/focus_agent --backup-command 'pg_dump --format=custom --file=/tmp/focus-agent.dump postgresql://user:pass@host:5432/focus_agent' --restore-command 'pg_restore --dbname=postgresql://user:pass@restore-host:5432/focus_agent_verify /tmp/focus-agent.dump' --restore-verification-query 'SELECT 1' --retention-cleanup-query 'SELECT 1' --report-json reports/release-gate/postgres-ops.json"
make otel-smoke OTEL_SMOKE_ARGS="--endpoint http://otel-collector:4318 --collector-health-url http://otel-collector:13133/healthz --trace-query-url 'https://traces.example.com/api/traces/{trace_id}' --report-json reports/release-gate/otel-smoke.json"
make agent-governance-report AGENT_GOVERNANCE_REPORT_ARGS="--report-json reports/agent-governance/latest.json --max-review-queue-backlog 10 --max-avg-cost-usd 0.05"
```

Set the tuple before generating any production report, including eval reports.
Attesting writers bind their own output. Downloaded raw evidence must pass through
the trusted capture helper, which preserves and validates the producer timestamp,
rejects conflicting or partial declared bindings, and attaches the deployment
environment's matching `release_binding`; it must never replace an existing
timestamp or declared identity. The checked-out `HEAD` must be the exact commit
represented by the deployment.

`production_smoke.py` is release evidence, not a replacement for `ui_smoke_test.py`. In live mode, provide `--stream-events-json` from a captured successful SSE turn; `--stream-events-url` is only for a GET-compatible event endpoint and should not point directly at the POST-only chat streaming route. For local development, prefer `make ci` plus `uv run python scripts/ui_smoke_test.py` for functional coverage, and use `production-smoke --dry-run` unless the deployment supplies production-like auth, rate-limit, web URL, and stream-event evidence.

Postgres migration verification can be attached as a machine-readable report from the migration command. When moving local state into Postgres, use the migration report path as the release-health/evidence input:

```bash
uv run python -m focus_agent.migrate_local_state \
  --database-uri postgresql://user:pass@host:5432/focus_agent \
  --artifact-scan \
  --report-path reports/release-gate/postgres-migration.json
```

- Real memory/context failures should enter candidate review first, not the golden dataset directly:

```bash
uv run python scripts/memory_context_eval.py \
  --candidate-source-json reports/trajectory-replay.json \
  --candidate-source-type replay \
  --candidate-dataset-out reports/memory-context-candidates.jsonl \
  --candidate-review-sla-days 7

uv run python scripts/memory_context_eval.py \
  --candidate-review-jsonl reports/memory-context-candidates.jsonl \
  --candidate-reviewed-out reports/memory-context-reviewed.jsonl \
  --candidate-promoted-out reports/memory-context-promoted.jsonl \
  --candidate-approve-id <candidate-id> \
  --candidate-reviewer <reviewer>
```

The import / review commands record candidate age, source explanation, duplicate reasons, PII redaction summaries, and promotion SLA metadata. They never update `tests/eval/datasets/memory_context_quality.jsonl` directly. Treat the promoted JSONL as a human-reviewed patch source.

- API/router, tool split, state-slice, and branch-service refactors must keep their focused compatibility tests green before the full gate.
- If deployment or persistence changed, run the targeted Postgres / containerization tests referenced in `docs/architecture.md`
- If production trajectory failures were promoted, replay the exported slice before tagging:

```bash
uv run python -m tests.eval replay \
  --from /tmp/focus-agent-failed.jsonl \
  --trajectory-input \
  --failed-only \
  --copy-tool-trajectory \
  --run \
  --report-json reports/trajectory-replay.json
```

- If a stored eval baseline is available, add `--baseline <baseline.json> --fail-if-regression` to the eval smoke or trajectory replay command

- Review recent changes for accidental breaking API or SDK changes
- Ensure docs were updated for any behavior changes

## Security Review

- Review authentication defaults
- Review token creation and validation behavior
- Review registration policy, password strength rules, and whether self-registration is acceptable for the release environment
- Review bootstrap admin IDs, local implicit-admin behavior, persisted admin roles, and the last-active-admin guard
- Review logout semantics: refresh sessions and cookies are revoked, while stateless copied access tokens remain valid until expiry or key rotation
- Review thread ownership enforcement paths
- Review any filesystem write locations used by tools or examples
- Review dependency versions and known advisories
- Confirm no sensitive values are present in tracked docs or examples

## Release Packaging

- Decide on the release version
- Update version references if needed
- Prepare release notes or changelog entries
- Identify any breaking changes and migration notes
- Tag the release according to repository conventions

## Post-Release Follow-Up

- Monitor issues and security reports after release
- Triage documentation gaps discovered by first external users
- Capture follow-up tasks for onboarding, deployment, and production hardening
