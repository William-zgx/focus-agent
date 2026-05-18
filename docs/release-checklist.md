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
- Confirm Admin Console docs match `/app/admin/users`, `/app/admin/audit-events`, persisted admin role checks, reasoned admin actions, session revoke, password reset, and last-active-admin protection
- Confirm the frontend SDK examples still match the live contract
- Confirm Agent Team docs match dynamic planning, standalone sessions, task contracts, Cockpit UI, retry/cancel, final-answer status, and merge bundle behavior
- Confirm trajectory observability docs match the live API, CLI, and `/app/observability/trajectory` console
- Confirm trajectory failure promotion preview and batch replay workflow still match the API and eval CLI
- Confirm OTel exporter env vars and runtime readiness docs still match the live tracing behavior
- Confirm alert guidance uses the existing `/metrics` endpoint and current metric names
- Confirm Memory v2 docs match the live PostgreSQL canonical store, pgvector embedding readiness, memory API authorization, forget tombstone/erasure behavior, and Memory Console fields
- Confirm runtime coordination docs match thread turn lease behavior, durable background job claim heartbeat, and first-turn branch title/metadata refresh after lease release
- Confirm Agent governance expectations still match `docs/agent-role-routing.md`, `/v1/agent/*`, and `/app/agent/governance`
- If Agent governance changed, confirm `/v1/agent/capabilities`, `/v1/agent/tool-router/*`, `/v1/agent/memory/curator/*`, and `/app/agent/governance`
- If Context Engineering changed, confirm `/v1/agent/context/*`, `/app/agent/governance`, and `tests/eval/datasets/agent_context.jsonl`
- If Task Ledger changed, confirm `/v1/agent/task-ledger/*`, `/v1/agent/artifacts`, `/v1/agent/critic/*`, `/app/agent/governance`, and `tests/eval/datasets/agent_task_ledger.jsonl`

## Configuration Review

- Review `.env.example` for completeness and safe defaults
- Review local config instructions under `.focus_agent/`
- Decide which settings are development-only versus production-ready
- Confirm non-development startup fails when auth is disabled, `AUTH_JWT_SECRET` is missing/default, demo tokens are enabled, or rate limiting is disabled
- Review persistence-related settings such as `DATABASE_URI`, managed local Postgres runtime files, trajectory settings, and artifact paths
- Review memory embedding and pgvector settings: `AGENT_MEMORY_EMBEDDING_ENABLED`, `AGENT_MEMORY_EMBEDDING_BACKEND`, `AGENT_MEMORY_EMBEDDING_MODEL`, `AGENT_MEMORY_EMBEDDING_DIMENSIONS`, `AGENT_MEMORY_EMBEDDING_BASE_URL`, `AGENT_MEMORY_EMBEDDING_API_KEY_ENV`, `AGENT_MEMORY_EMBEDDING_API_KEY`, `AGENT_MEMORY_EMBEDDING_BATCH_SIZE`, `AGENT_MEMORY_EMBEDDING_TIMEOUT_SECONDS`, `AGENT_MEMORY_VECTOR_SEARCH_MODE`, `AGENT_MEMORY_VECTOR_INDEX_ENABLED`, and `AGENT_MEMORY_PGVECTOR_EXTENSION_MODE`
- Review memory governance settings: `AGENT_MEMORY_POSTGRES_TRIGRAM_ENABLED`, `AGENT_MEMORY_APPROVAL_FOR_SHARED_WRITES`, `AGENT_MEMORY_CURATOR_ENABLED`, and `AGENT_MEMORY_AUTO_PROMOTE_ON_MERGE`
- Review runtime coordination settings: `BACKGROUND_JOB_EXECUTION`, `BACKGROUND_JOB_BACKEND`, `BACKGROUND_JOB_CLAIM_TTL_SECONDS`, `RUNTIME_THREAD_LOCK_TTL_SECONDS`, and `RUNTIME_THREAD_LOCK_HEARTBEAT_SECONDS`

## Quality Checks

Required release gate:

```bash
make release-gate
```

This writes `reports/release-gate/latest.json` with per-command labels, status, duration, exit code, skip reason, and captured stdout/stderr summaries. For local iteration, pass CLI options such as `--dry-run`, `--only`, `--skip`, `--report-json`, and `--keep-going` through `RELEASE_GATE_ARGS`, for example:

```bash
make release-gate RELEASE_GATE_ARGS="--dry-run --only lint"
```

For a fast API/SDK compatibility check before the full gate, run:

```bash
make contract-check
```

The orchestrated command plan mirrors `scripts/release_gate.py`. Full local runs assume the API and Vite app are reachable at the default smoke URLs (`http://127.0.0.1:8000/healthz` and `http://127.0.0.1:5173/app/`); use `RELEASE_GATE_ARGS="--dry-run"` or scoped `--only` checks when those services are not available. `make contract-check` remains a fast preflight outside the full gate.

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
uv run python scripts/memory_context_eval.py --report-json reports/release-gate/memory-context-eval.json
focus-agent-memory-embedding doctor --database-uri "$DATABASE_URI"
uv run python scripts/agent_governance_report.py --report-json reports/agent-governance/latest.json
uv run python scripts/release_health_check.py --mode local --ready-url http://127.0.0.1:8000/readyz --trajectory-stats-url http://127.0.0.1:8000/v1/observability/trajectory/stats --allow-self-check-fallback --eval-report-json reports/release-gate/eval-smoke.json --eval-report-json reports/release-gate/eval-observability.json --eval-report-json reports/release-gate/eval-golden-multi-agent.json --eval-report-json reports/release-gate/memory-context-eval.json --governance-report-json reports/agent-governance/latest.json --report-json reports/release-gate/release-health.json
```

- `scripts/ui_smoke_test.py` covers the main chat, branch, and review routes; keep `make ui-smoke` as the shorthand local target. The smoke waits for assistant text to stabilize after streaming UI has stopped, so an idle disabled send button is not a readiness signal.
- Local Vite smoke URLs should use `http://127.0.0.1:5173/app/` with the trailing slash. Manual browser passes are useful, but personal Chrome profiles can carry stale localStorage, extensions, and auth state; prefer the smoke script's temporary Chrome profile for release evidence and use manual passes as an additional visual check.
- Auth/Admin UI changes also need a manual or in-app-browser pass through protected-route redirect, `Demo 登录`, username/password login after registration or admin password reset, sidebar logout, Bearer Token login, reasoned admin status/role update, session revoke, audit-event filtering, and logout-then-login account switching. Do not treat username/password registration as a release smoke shortcut because it creates persistent local users.
- `scripts/observability_ui_smoke.py --scenario all` seeds and exercises success, failed, zero-step, and missing-detail trajectory cases across overview and trajectory pages. The smoke records fetch request URLs and checks endpoint pathnames, so route/query serialization drift should fail loudly instead of relying on brittle string matches.
- `pnpm --dir apps/web smoke:observability` is a source-level route and wiring check; it complements the real-browser observability smoke and does not replace it.
- `make ui-smoke-agent-team-adoption` is the command name for the Agent Team adoption browser/source smoke. It should cover task selection, diff/test evidence, conflict/apply state, capture to Notes/Tasks, context evidence, and skill feedback once the Web adoption script is present.
- `scripts/memory_context_eval.py` covers the P7 memory/context quality probes: fact fidelity, key fact recall, irrelevant memory pollution, conflict memory marking, compaction answerability, and artifact refs.
- `scripts/feedback_regression.py` summarizes online feedback and adoption/governance signals into `reports/nightly/feedback-regression.json`. It is non-blocking when no production feedback artifact exists, but nightly reports must include its `feedback_pipeline` when events are provided.
- `focus-agent-memory-embedding doctor` is the memory embedding/pgvector release preflight. Include its JSON output as release evidence when PostgreSQL memory embedding is enabled; it should show provider readiness, table dimension compatibility, extension status, and vector index state without exposing API keys or vector values.
- `scripts/release_health_check.py` converts readiness, trajectory stats, replay comparison rows, alert-rule reports, Postgres migration reports, production smoke, Postgres ops, OTel smoke, Agent governance quality, baseline eval reports, and current eval JSON reports into release-blocking health signals. Current release-blocking eval reports include smoke, observability, golden multi-agent, and memory/context. `make release-gate` intentionally runs `--mode local` with `--allow-self-check-fallback` so local dry runs can complete when the API is down. Production release jobs must use `--mode production`, remove the fallback, and pass real `--readyz-json` or `--ready-url`, `--trajectory-stats-json` or `--trajectory-stats-url`, `--replay-comparisons-json`, `--eval-report-json`, `--production-smoke-report-json`, `--postgres-ops-report-json`, `--otel-smoke-report-json`, and `--governance-report-json` inputs. Missing required inputs fail closed with exit code 1; dry-run smoke / ops / OTel reports are rejected in production unless the caller explicitly uses the deterministic evidence-pack escape hatch `--allow-dry-run-reports`.
- `make release-evidence` builds the production evidence pack. Use it for production release review after collecting real deployment signals; the manifest is written to `reports/release-gate/<release-id>/manifest.json` and includes artifact hashes, artifact summary, failure summary, retention metadata, approval metadata, storage verification metadata, release-health summary, and missing-required-artifact checks. Production packs require an explicit `--release-id`, approved deployment-platform `--approval-status approved` with `--approval-id`, plus readyz, trajectory stats, replay comparison, eval report, baseline eval report, production smoke, Postgres ops, OTel smoke, and governance report artifacts. Add `--storage-dir` when the release job should copy the evidence pack to a retained artifact location; the manifest records whether the stored manifest and summary matched local hashes.
- CI provider binding lives in `docs/ci/github-actions-release-gate.md` and `.github/workflows/release-gate.yml`. Keep provider-specific approval metadata, artifact upload, retention, and generic CI command skeletons in that CI document; this checklist only records the release-blocking evidence that must be present before tagging.

```bash
make release-evidence RELEASE_EVIDENCE_ARGS="--release-id <release-id> --approval-id <approval-id> --approval-status approved --retention-days 90 --storage-dir reports/release-gate/archive --readyz-json reports/release-gate/readyz.json --trajectory-stats-json reports/release-gate/trajectory-stats.json --replay-comparisons-json reports/release-gate/replay-comparisons.json --alert-report-json reports/release-gate/alert-report.json --postgres-migration-report-json reports/release-gate/postgres-migration.json --production-smoke-report-json reports/release-gate/production-smoke.json --postgres-ops-report-json reports/release-gate/postgres-ops.json --otel-smoke-report-json reports/release-gate/otel-smoke.json --governance-report-json reports/agent-governance/latest.json --eval-report-json reports/release-gate/eval-smoke.json --eval-report-json reports/release-gate/eval-observability.json --eval-report-json reports/release-gate/eval-golden-multi-agent.json --eval-report-json reports/release-gate/memory-context-eval.json --baseline-eval-report-json reports/release-gate/baseline-eval-smoke.json"
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

Schema v14 adoption/governance migration evidence:

- Confirm Postgres ops reports the current schema version as v14 before production promotion.
- Confirm `reports/nightly/latest.json` contains `summary.feedback_pipeline` and `artifacts.feedback_regression`.
- If production feedback exports are available, pass them through `FEEDBACK_REGRESSION_ARGS`, for example `--feedback-events-json`, `--merge-review-json`, `--skill-selection-json`, `--context-evidence-json`, and `--productivity-capture-json`.

Production examples with live evidence:

```bash
make production-smoke PRODUCTION_SMOKE_ARGS="--base-url https://focus-agent.example.com --web-base-url https://focus-agent.example.com --auth-token <token> --stream-events-json reports/release-gate/stream-events.json --rate-limit-min-limit 1 --report-json reports/release-gate/production-smoke.json"
make postgres-ops POSTGRES_OPS_ARGS="--database-uri postgresql://user:pass@host:5432/focus_agent --backup-command 'pg_dump --format=custom --file=/tmp/focus-agent.dump postgresql://user:pass@host:5432/focus_agent' --restore-command 'pg_restore --dbname=postgresql://user:pass@restore-host:5432/focus_agent_verify /tmp/focus-agent.dump' --restore-verification-query 'SELECT 1' --retention-cleanup-query 'SELECT 1' --report-json reports/release-gate/postgres-ops.json"
make otel-smoke OTEL_SMOKE_ARGS="--endpoint http://otel-collector:4318 --collector-health-url http://otel-collector:13133/healthz --trace-query-url 'https://traces.example.com/api/traces/{trace_id}' --report-json reports/release-gate/otel-smoke.json"
make agent-governance-report AGENT_GOVERNANCE_REPORT_ARGS="--report-json reports/agent-governance/latest.json --max-review-queue-backlog 10 --max-avg-cost-usd 0.05"
```

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
