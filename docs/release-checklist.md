# Release Checklist

This checklist is intended for maintainers preparing Focus Agent for a public release or a tagged internal milestone.

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
- Confirm auth behavior and ownership rules are documented accurately
- Confirm the frontend SDK examples still match the live contract
- Confirm trajectory observability docs match the live API, CLI, and `/app/observability/trajectory` console
- Confirm trajectory failure promotion preview and batch replay workflow still match the API and eval CLI
- Confirm OTel exporter env vars and runtime readiness docs still match the live tracing behavior
- Confirm alert guidance uses the existing `/metrics` endpoint and current metric names
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

The orchestrated command plan is:

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
uv run python scripts/memory_context_eval.py --report-json reports/release-gate/memory-context-eval.json
uv run python scripts/release_health_check.py --mode local --ready-url http://127.0.0.1:8000/readyz --trajectory-stats-url http://127.0.0.1:8000/v1/observability/trajectory/stats --allow-self-check-fallback --eval-report-json reports/release-gate/eval-smoke.json --eval-report-json reports/release-gate/eval-observability.json --eval-report-json reports/release-gate/memory-context-eval.json --report-json reports/release-gate/release-health.json
```

- `scripts/ui_smoke_test.py` covers the main chat, branch, and review routes; keep `make ui-smoke` as the shorthand local target.
- `scripts/memory_context_eval.py` covers the P7 memory/context quality probes: fact fidelity, key fact recall, irrelevant memory pollution, conflict memory marking, compaction answerability, and artifact refs.
- `scripts/release_health_check.py` converts readiness, trajectory stats, replay comparison rows, alert-rule reports, Postgres migration reports, production smoke, Postgres ops, OTel smoke, Agent governance quality, baseline eval reports, and current eval JSON reports into release-blocking health signals. `make release-gate` intentionally runs `--mode local` with `--allow-self-check-fallback` so local dry runs can complete when the API is down. Production release jobs must use `--mode production`, remove the fallback, and pass real `--readyz-json` or `--ready-url`, `--trajectory-stats-json` or `--trajectory-stats-url`, `--replay-comparisons-json`, `--eval-report-json`, `--production-smoke-report-json`, `--postgres-ops-report-json`, `--otel-smoke-report-json`, and `--governance-report-json` inputs. Missing required inputs fail closed with exit code 1; dry-run smoke / ops / OTel reports are rejected in production unless the caller explicitly uses the deterministic evidence-pack escape hatch `--allow-dry-run-reports`.
- `make release-evidence` builds the production evidence pack. Use it for production release review after collecting real deployment signals; the manifest is written to `reports/release-gate/<release-id>/manifest.json` and includes artifact hashes, artifact summary, failure summary, retention metadata, approval metadata, storage verification metadata, release-health summary, and missing-required-artifact checks. Production packs require an explicit `--release-id`, approved deployment-platform `--approval-status approved` with `--approval-id`, plus readyz, trajectory stats, replay comparison, eval report, baseline eval report, production smoke, Postgres ops, OTel smoke, and governance report artifacts. Add `--storage-dir` when the release job should copy the evidence pack to a retained artifact location; the manifest records whether the stored manifest and summary matched local hashes.
- CI provider binding lives in `docs/ci/github-actions-release-gate.md` and `.github/workflows/release-gate.yml`. GitHub Actions dry-runs upload deterministic release evidence; production runs must bind provider approval metadata, upload `reports/release-gate/` as a retained artifact, and pass the same release evidence command. The CI doc also includes Buildkite and generic CI command skeletons.

```bash
make release-evidence RELEASE_EVIDENCE_ARGS="--release-id <release-id> --approval-id <approval-id> --approval-status approved --retention-days 90 --storage-dir reports/release-gate/archive --readyz-json reports/release-gate/readyz.json --trajectory-stats-json reports/release-gate/trajectory-stats.json --replay-comparisons-json reports/release-gate/replay-comparisons.json --alert-report-json reports/release-gate/alert-report.json --postgres-migration-report-json reports/release-gate/postgres-migration.json --production-smoke-report-json reports/release-gate/production-smoke.json --postgres-ops-report-json reports/release-gate/postgres-ops.json --otel-smoke-report-json reports/release-gate/otel-smoke.json --governance-report-json reports/agent-governance/latest.json --eval-report-json reports/release-gate/eval-smoke.json --baseline-eval-report-json reports/release-gate/baseline-eval-smoke.json"
```

Nightly and production smoke entrypoints:

```bash
make nightly-regression
make production-smoke PRODUCTION_SMOKE_ARGS="--dry-run --base-url https://focus-agent.example.com"
make postgres-ops POSTGRES_OPS_ARGS="--dry-run"
make otel-smoke OTEL_SMOKE_ARGS="--dry-run --endpoint http://otel-collector:4318"
make agent-governance-report
```

Production examples with live evidence:

```bash
make production-smoke PRODUCTION_SMOKE_ARGS="--base-url https://focus-agent.example.com --web-base-url https://focus-agent.example.com --auth-token <token> --stream-events-json reports/release-gate/stream-events.json --rate-limit-min-limit 1 --report-json reports/release-gate/production-smoke.json"
make postgres-ops POSTGRES_OPS_ARGS="--database-uri postgresql://user:pass@host:5432/focus_agent --backup-command 'pg_dump --format=custom --file=/tmp/focus-agent.dump postgresql://user:pass@host:5432/focus_agent' --restore-command 'pg_restore --dbname=postgresql://user:pass@restore-host:5432/focus_agent_verify /tmp/focus-agent.dump' --restore-verification-query 'SELECT 1' --retention-cleanup-query 'SELECT 1' --report-json reports/release-gate/postgres-ops.json"
make otel-smoke OTEL_SMOKE_ARGS="--endpoint http://otel-collector:4318 --collector-health-url http://otel-collector:13133/healthz --trace-query-url 'https://traces.example.com/api/traces/{trace_id}' --report-json reports/release-gate/otel-smoke.json"
make agent-governance-report AGENT_GOVERNANCE_REPORT_ARGS="--report-json reports/agent-governance/latest.json --max-review-queue-backlog 10 --max-avg-cost-usd 0.05"
```

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
- 2026-04-26 P0-P3 multi-agent engineering gate completed: security config, API/router split, default tool split, state slice helpers, branch-service facade split, SDK/Web checks, UI smoke, observability smoke, and eval smoke all passed.
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
