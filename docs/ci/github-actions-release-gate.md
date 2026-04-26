# GitHub Actions Release Gate

This document binds the Focus Agent release gate and release evidence pack to CI providers. The same commands work in GitHub Actions, Buildkite, or any generic CI runner; the provider-specific layer is responsible for artifact upload, approval metadata, and retention.

## Required Outputs

Every release job should retain:

- `reports/release-gate/latest.json` from `make release-gate`
- `reports/release-gate/release-health.json` from `scripts/release_health_check.py`
- `reports/release-gate/<release-id>/manifest.json` and `summary.json` from `make release-evidence`
- Raw deployment signals: `readyz.json`, `trajectory-stats.json`, `replay-comparisons.json`, current eval reports, baseline eval reports, alert report, Postgres migration report, production smoke report, Postgres ops report, and OTel smoke report

Production evidence is fail-closed. It requires approved deployment-platform approval metadata plus readyz, trajectory stats, replay comparison, eval, baseline eval, and release-health artifacts. Optional production smoke, Postgres ops, OTel, alert, and migration reports are archived when supplied and become release-blocking if malformed or failed.

## GitHub Actions

The repository workflow at `.github/workflows/release-gate.yml` provides two modes:

- Dry run: `workflow_dispatch` with `dry_run=true`. It plans the release gate and builds deterministic sample evidence, then uploads `reports/release-gate/`.
- Production: `workflow_dispatch` with `dry_run=false`, a path-safe `release_id`, `approval_status=approved`, and an `approval_id` from the GitHub Environment approval or release operator. Configure `FOCUS_AGENT_BASE_URL`, `FOCUS_AGENT_READY_URL`, `FOCUS_AGENT_TRAJECTORY_STATS_URL`, `FOCUS_AGENT_REPLAY_COMPARISONS_URL`, `FOCUS_AGENT_ALERT_REPORT_URL`, `FOCUS_AGENT_POSTGRES_MIGRATION_REPORT_URL`, and `FOCUS_AGENT_BASELINE_EVAL_REPORT_URL` as repository or environment variables. The job binds to a protected GitHub Environment through `environment_name`.

Dry-run command used by the workflow:

```bash
make release-gate RELEASE_GATE_ARGS="--dry-run --report-json reports/release-gate/latest.json"
make release-evidence RELEASE_EVIDENCE_ARGS="--dry-run --release-id <release-id> --approval-id gha-dry-run-<run-id> --approval-status approved --approval-url <workflow-run-url> --retention-days 90 --storage-dir reports/release-gate/archive"
```

Production command shape:

```bash
make install-openai
make sdk-install
make web-install

mkdir -p reports/release-gate
curl --fail --show-error --silent "$FOCUS_AGENT_READY_URL" > reports/release-gate/readyz.json
curl --fail --show-error --silent "$FOCUS_AGENT_TRAJECTORY_STATS_URL" > reports/release-gate/trajectory-stats.json
curl --fail --show-error --silent "$FOCUS_AGENT_REPLAY_COMPARISONS_URL" > reports/release-gate/replay-comparisons.json
curl --fail --show-error --silent "$FOCUS_AGENT_ALERT_REPORT_URL" > reports/release-gate/alert-report.json
curl --fail --show-error --silent "$FOCUS_AGENT_POSTGRES_MIGRATION_REPORT_URL" > reports/release-gate/postgres-migration.json
curl --fail --show-error --silent "$FOCUS_AGENT_BASELINE_EVAL_REPORT_URL" > reports/release-gate/baseline-eval-smoke.json

make release-gate
make production-smoke PRODUCTION_SMOKE_ARGS="--base-url $FOCUS_AGENT_BASE_URL --web-base-url $FOCUS_AGENT_BASE_URL --report-json reports/release-gate/production-smoke.json"
make postgres-ops POSTGRES_OPS_ARGS="--dry-run --report-json reports/release-gate/postgres-ops.json"
make otel-smoke OTEL_SMOKE_ARGS="--dry-run --endpoint ${FOCUS_AGENT_OTEL_ENDPOINT:-http://otel-collector:4318} --service-name focus-agent --report-json reports/release-gate/otel-smoke.json"

make release-evidence RELEASE_EVIDENCE_ARGS="--release-id <release-id> --approval-id <approval-id> --approval-status approved --approval-url <approval-url> --retention-days 90 --storage-dir reports/release-gate/archive --readyz-json reports/release-gate/readyz.json --trajectory-stats-json reports/release-gate/trajectory-stats.json --replay-comparisons-json reports/release-gate/replay-comparisons.json --alert-report-json reports/release-gate/alert-report.json --postgres-migration-report-json reports/release-gate/postgres-migration.json --production-smoke-report-json reports/release-gate/production-smoke.json --postgres-ops-report-json reports/release-gate/postgres-ops.json --otel-smoke-report-json reports/release-gate/otel-smoke.json --eval-report-json reports/release-gate/eval-smoke.json --eval-report-json reports/release-gate/eval-observability.json --eval-report-json reports/release-gate/memory-context-eval.json --baseline-eval-report-json reports/release-gate/baseline-eval-smoke.json"
```

Artifact upload is handled by `actions/upload-artifact@v4`:

```yaml
- name: Upload release gate reports
  if: always()
  uses: actions/upload-artifact@v4
  with:
    name: release-gate-reports-${{ github.run_id }}
    path: reports/release-gate/
    retention-days: 90
    if-no-files-found: ignore
```

Use a protected GitHub Environment for the production job when the repository requires a reviewer click before evidence generation. Record that approval as `--approval-id`; use the workflow run URL or deployment URL as `--approval-url`.

## Buildkite

Buildkite should run the same commands and upload the release evidence directory as an artifact:

```yaml
steps:
  - label: ":rocket: release gate"
    command:
      - "corepack enable"
      - "make install-openai"
      - "make sdk-install"
      - "make web-install"
      - "make release-gate"
      - "curl --fail --show-error --silent \"$FOCUS_AGENT_READY_URL\" > reports/release-gate/readyz.json"
      - "curl --fail --show-error --silent \"$FOCUS_AGENT_TRAJECTORY_STATS_URL\" > reports/release-gate/trajectory-stats.json"
      - "curl --fail --show-error --silent \"$FOCUS_AGENT_REPLAY_COMPARISONS_URL\" > reports/release-gate/replay-comparisons.json"
      - "curl --fail --show-error --silent \"$FOCUS_AGENT_ALERT_REPORT_URL\" > reports/release-gate/alert-report.json"
      - "curl --fail --show-error --silent \"$FOCUS_AGENT_POSTGRES_MIGRATION_REPORT_URL\" > reports/release-gate/postgres-migration.json"
      - "curl --fail --show-error --silent \"$FOCUS_AGENT_BASELINE_EVAL_REPORT_URL\" > reports/release-gate/baseline-eval-smoke.json"
      - "make production-smoke PRODUCTION_SMOKE_ARGS=\"--base-url $FOCUS_AGENT_BASE_URL --report-json reports/release-gate/production-smoke.json\""
      - "make postgres-ops POSTGRES_OPS_ARGS=\"--dry-run --report-json reports/release-gate/postgres-ops.json\""
      - "make otel-smoke OTEL_SMOKE_ARGS=\"--dry-run --endpoint ${FOCUS_AGENT_OTEL_ENDPOINT:-http://otel-collector:4318} --report-json reports/release-gate/otel-smoke.json\""
      - "make release-evidence RELEASE_EVIDENCE_ARGS=\"--release-id $RELEASE_ID --approval-id $BUILDKITE_BUILD_ID --approval-status approved --approval-url $BUILDKITE_BUILD_URL --retention-days 90 --storage-dir reports/release-gate/archive --readyz-json reports/release-gate/readyz.json --trajectory-stats-json reports/release-gate/trajectory-stats.json --replay-comparisons-json reports/release-gate/replay-comparisons.json --alert-report-json reports/release-gate/alert-report.json --postgres-migration-report-json reports/release-gate/postgres-migration.json --production-smoke-report-json reports/release-gate/production-smoke.json --postgres-ops-report-json reports/release-gate/postgres-ops.json --otel-smoke-report-json reports/release-gate/otel-smoke.json --eval-report-json reports/release-gate/eval-smoke.json --baseline-eval-report-json reports/release-gate/baseline-eval-smoke.json\""
    artifact_paths:
      - "reports/release-gate/**/*"
```

If the pipeline uses a `block` step, pass the block step result or build id as `--approval-id` and the build URL as `--approval-url`.

## Generic CI

Any CI provider can bind the same three phases:

```bash
set -euo pipefail

make install-openai
make sdk-install
make web-install

mkdir -p reports/release-gate
make release-gate

curl --fail --show-error --silent "$FOCUS_AGENT_READY_URL" > reports/release-gate/readyz.json
curl --fail --show-error --silent "$FOCUS_AGENT_TRAJECTORY_STATS_URL" > reports/release-gate/trajectory-stats.json
curl --fail --show-error --silent "$FOCUS_AGENT_REPLAY_COMPARISONS_URL" > reports/release-gate/replay-comparisons.json
curl --fail --show-error --silent "$FOCUS_AGENT_ALERT_REPORT_URL" > reports/release-gate/alert-report.json
curl --fail --show-error --silent "$FOCUS_AGENT_POSTGRES_MIGRATION_REPORT_URL" > reports/release-gate/postgres-migration.json
curl --fail --show-error --silent "$FOCUS_AGENT_BASELINE_EVAL_REPORT_URL" > reports/release-gate/baseline-eval-smoke.json
make production-smoke PRODUCTION_SMOKE_ARGS="--base-url ${FOCUS_AGENT_BASE_URL} --report-json reports/release-gate/production-smoke.json"
make postgres-ops POSTGRES_OPS_ARGS="--dry-run --report-json reports/release-gate/postgres-ops.json"
make otel-smoke OTEL_SMOKE_ARGS="--dry-run --endpoint ${FOCUS_AGENT_OTEL_ENDPOINT:-http://otel-collector:4318} --report-json reports/release-gate/otel-smoke.json"

make release-evidence RELEASE_EVIDENCE_ARGS="--release-id ${RELEASE_ID} --approval-id ${CI_APPROVAL_ID} --approval-status approved --approval-url ${CI_APPROVAL_URL} --retention-days ${RETENTION_DAYS:-90} --storage-dir reports/release-gate/archive --readyz-json reports/release-gate/readyz.json --trajectory-stats-json reports/release-gate/trajectory-stats.json --replay-comparisons-json reports/release-gate/replay-comparisons.json --alert-report-json reports/release-gate/alert-report.json --postgres-migration-report-json reports/release-gate/postgres-migration.json --production-smoke-report-json reports/release-gate/production-smoke.json --postgres-ops-report-json reports/release-gate/postgres-ops.json --otel-smoke-report-json reports/release-gate/otel-smoke.json --eval-report-json reports/release-gate/eval-smoke.json --baseline-eval-report-json reports/release-gate/baseline-eval-smoke.json"
```

Upload `reports/release-gate/**/*` with the provider's artifact feature and keep it for at least the manifest `retention.days` value. If the provider cannot expose a structured approval id, use a stable deployment ticket id and include the CI run URL as `--approval-url`.
