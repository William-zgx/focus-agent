# GitHub Actions Release Gate

This document is the canonical CI provider binding for the Focus Agent release gate and release evidence pack. It covers GitHub Actions, Buildkite, and generic CI runners; the provider-specific layer is responsible for artifact upload, approval metadata, and retention.

For the human release readiness checklist and blocking criteria, see [../release-checklist.md](../release-checklist.md).

## Required Outputs

Every production release job should retain:

- Deployment-binding validation from `scripts/release_gate.py deployment-binding`
- `latest.json` from `make release-gate`
- `reports/release-gate/<release-id>/manifest.json`, `summary.json`, and `release-health.json` from `make release-evidence`
- Raw deployment signals: `readyz.json`, `trajectory-stats.json`, `replay-comparisons.json`, current eval reports, baseline eval reports, alert report, Postgres migration report, production smoke report, Postgres ops report, OTel smoke report, and Agent governance report

The dry-run job retains the corresponding planning report, deterministic sample
pack, deployment-binding report, and archive under
`reports/release-gate/dry-run/`; it does not manufacture or require live
deployment signals.

The production manifest uses `meta.schema_version: 2`. Production evidence is
fail-closed. It requires approved deployment-platform approval metadata, a
verified retained copy of the pack, readyz, trajectory stats, replay comparison,
current eval, baseline eval, release-health, production smoke, Postgres ops,
OTel smoke, and Agent governance report artifacts. Alert and migration reports
are also release-blocking when supplied by the deployment pipeline.

Every JSON passed to a production `--*-json` option must contain:

- a timezone-aware evidence timestamp accepted through `generated_at`,
  `meta.generated_at`, `checked_at`, `completed_at`, `finished_at`, or
  `timestamp`;
- a complete `release_binding` for `commit_sha`, `deployment_id`,
  `deployment_version`, and `environment`; and
- the same identity as every other input and the requested evidence pack.

The default maximum input age and required-input collection window are both
`21600` seconds. `/readyz` must additionally expose `deployment`,
`app_version`, and `environment`; these must equal the deployment id, deployment
version, and environment in `release_binding`.

The production binding itself must pass all of these checks:

- `RELEASE_COMMIT_SHA` is a hexadecimal SHA that resolves to the checked-out
  repository and resolves to the current `HEAD`;
- `RELEASE_DEPLOYMENT_ID` and `RELEASE_DEPLOYMENT_VERSION` are non-empty; and
- `RELEASE_ENVIRONMENT` is `production` (`prod` canonicalizes to
  `production` in the evidence validator).

Six locally generated report classes attach the timestamp and release binding
from this four-variable environment: `production_smoke.py`, `postgres_ops.py`,
`otel_smoke.py`, `agent_governance_report.py`, eval JSON written by
`tests.eval.reporting`, and `memory_context_eval.py`. A partial tuple fails
before report write. With all four variables absent, ordinary local and generic
CI report generation remains compatible, but those reports cannot pass
production evidence validation.

## Trusted Capture Contract

The evidence builder validates inputs but does not mutate them into trusted
evidence. The checked-in workflow and provider-neutral command catalog call
`scripts/release_evidence_capture.py` after downloading raw JSON. A successful
capture preserves the payload while adding:

```json
{
  "generated_at": "<timezone-aware collection timestamp>",
  "release_binding": {
    "commit_sha": "<RELEASE_COMMIT_SHA>",
    "deployment_id": "<RELEASE_DEPLOYMENT_ID>",
    "deployment_version": "<RELEASE_DEPLOYMENT_VERSION>",
    "environment": "production"
  }
}
```

The binding comes only from the deployment environment. If the input already
declares top-level or `meta.release_binding`, every field must match; partial or
conflicting values fail closed rather than being overwritten. Existing
timestamps must be timezone-aware and are preserved, preventing a stale report
from being made fresh at download time.

Only live snapshots with no producer timestamp may use `--captured-now`. The
workflow enables it for `/readyz` and trajectory stats only. Replay comparison,
alert, Postgres migration, baseline eval, and static stream-event reports must
arrive with their own timestamp. `/readyz` additionally uses `--readyz` to
cross-check `deployment`, `app_version`, and `environment`.

The helper validates every input before writing and uses atomic replacement.
The GitHub workflow downloads into a temporary directory; the provider-neutral
catalog uses `reports/release-gate-raw/`, outside the uploaded release artifact
tree, and removes it after successful capture. Dry-run remains isolated and
does not receive production attestation.

## GitHub Actions

The repository workflow at `.github/workflows/release-gate.yml` uses two
separate jobs rather than one conditionally trusted job:

- `release-gate-dry-run` runs only when `dry_run=true`. It does not bind a
  GitHub Environment, read `FOCUS_AGENT_*` variables or secrets, or require the
  production release identity. It plans the command gate, creates deterministic
  sample evidence under `reports/release-gate/dry-run/`, and uploads only that
  directory.
- `release-gate-production` runs only when `dry_run=false` and hardcodes
  `environment: production`. The workflow dispatch surface contains only
  `release_id`, `dry_run`, and `retention_days`; callers cannot supply an
  environment, approval status, or approval id. GitHub Environment protection
  supplies the reviewer boundary, while the job derives a stable approval id
  and workflow-run URL. Configure deployment identity, live service URLs,
  stream-event evidence, auth token, database backup/restore commands, OTel
  collector/trace URLs, and baseline/evidence URLs as production Environment
  variables or secrets.

The production job sets:

```text
RELEASE_COMMIT_SHA=${{ github.sha }}
RELEASE_DEPLOYMENT_ID=${{ vars.FOCUS_AGENT_DEPLOYMENT_ID }}
RELEASE_DEPLOYMENT_VERSION=${{ vars.FOCUS_AGENT_DEPLOYMENT_VERSION }}
RELEASE_ENVIRONMENT=production
```

Before collecting evidence it validates deployment binding metadata, confirms
the checked-out SHA, requires both deployment fields, and requires the
production environment. Every downloaded JSON then passes through the trusted
capture helper. `/readyz` receives the additional runtime identity
cross-check; static reports without a producer timestamp or with conflicting
identity stop the job before production smoke. The evidence builder then
revalidates complete binding, timestamps, freshness, and cross-artifact
identity while building the schema v2 pack.

Release-blocking eval evidence currently includes smoke, observability,
golden multi-agent, harness stability, and memory/context reports. The nightly
regression workflow runs `model_matrix` and `trajectory_failures` as
non-blocking reports under `reports/nightly/`; upload those artifacts for trend
review, but do not wire them into production release blocking until their cases
are promoted.

Dry-run command used by the workflow:

```bash
export DRY_RUN=true
export DEPLOYMENT_BINDING_JSON=reports/release-gate/dry-run/deployment-binding.json
python scripts/release_gate.py deployment-binding --output "$DEPLOYMENT_BINDING_JSON"
make release-gate RELEASE_GATE_ARGS="--dry-run --report-json reports/release-gate/dry-run/latest.json"
make release-evidence RELEASE_EVIDENCE_ARGS="--dry-run --release-id <release-id> --output-root reports/release-gate/dry-run/evidence --approval-id gha-dry-run-<run-id> --approval-status approved --approval-url <workflow-run-url> --retention-days 90 --storage-dir reports/release-gate/dry-run/archive"
```

Do not export the production `RELEASE_*` tuple or require production report
attestation for this dry run. Its manifest deliberately records a deterministic
sample binding with `required: false`.

Production command shape:

```bash
make install-openai
make sdk-install
make web-install

export RELEASE_COMMIT_SHA="$(git rev-parse HEAD)"
export RELEASE_DEPLOYMENT_ID="<deployed-id>"
export RELEASE_DEPLOYMENT_VERSION="<deployed-version>"
export RELEASE_ENVIRONMENT="production"
export DRY_RUN=false
export ENVIRONMENT_NAME=production
export DEPLOYMENT_BINDING_JSON=reports/release-gate/deployment-binding.json
export APPROVAL_ID="<approval-id>"
export APPROVAL_STATUS=approved
export APPROVAL_URL="<approval-url>"
export RETENTION_DAYS=90
export ARTIFACT_STORAGE_DIR=reports/release-gate/archive
export BASE_URL="${FOCUS_AGENT_BASE_URL:?}"
export READY_URL="${FOCUS_AGENT_READY_URL:?}"
export TRAJECTORY_STATS_URL="${FOCUS_AGENT_TRAJECTORY_STATS_URL:?}"
export REPLAY_COMPARISONS_URL="${FOCUS_AGENT_REPLAY_COMPARISONS_URL:?}"
export ALERT_REPORT_URL="${FOCUS_AGENT_ALERT_REPORT_URL:?}"
export POSTGRES_MIGRATION_REPORT_URL="${FOCUS_AGENT_POSTGRES_MIGRATION_REPORT_URL:?}"
export BASELINE_EVAL_REPORT_URL="${FOCUS_AGENT_BASELINE_EVAL_REPORT_URL:?}"
export AUTH_TOKEN="${FOCUS_AGENT_SMOKE_AUTH_TOKEN:?}"
export STREAM_EVENTS_REPORT_URL="${FOCUS_AGENT_STREAM_EVENTS_REPORT_URL:?}"
export DATABASE_URI="${FOCUS_AGENT_DATABASE_URI:?}"
export POSTGRES_BACKUP_COMMAND="${FOCUS_AGENT_POSTGRES_BACKUP_COMMAND:?}"
export POSTGRES_RESTORE_COMMAND="${FOCUS_AGENT_POSTGRES_RESTORE_COMMAND:?}"
export POSTGRES_RESTORE_VERIFICATION_QUERY="${FOCUS_AGENT_POSTGRES_RESTORE_VERIFICATION_QUERY:?}"
export POSTGRES_RETENTION_CLEANUP_QUERY="${FOCUS_AGENT_POSTGRES_RETENTION_CLEANUP_QUERY:?}"
export OTEL_ENDPOINT="${FOCUS_AGENT_OTEL_ENDPOINT:?}"
export OTEL_COLLECTOR_HEALTH_URL="${FOCUS_AGENT_OTEL_COLLECTOR_HEALTH_URL:?}"
export OTEL_TRACE_QUERY_URL="${FOCUS_AGENT_OTEL_TRACE_QUERY_URL:?}"
export GOVERNANCE_REPORT_JSON=reports/agent-governance/latest.json

mkdir -p reports/release-gate
python scripts/release_gate.py deployment-binding --output "$DEPLOYMENT_BINDING_JSON"
make release-gate

capture_release_json() {
  local artifact_name="$1" source_url="$2" output_path="$3"
  shift 3
  local raw_dir raw_path
  raw_dir="$(mktemp -d "${TMPDIR:-/tmp}/focus-agent-${artifact_name}.XXXXXX")"
  raw_path="${raw_dir}/${artifact_name}.json"
  curl --fail --show-error --silent --output "$raw_path" -- "$source_url"
  if [ "$artifact_name" = "readyz" ]; then
    uv run python scripts/release_evidence_capture.py \
      "$raw_path" --output "$output_path" --readyz "$raw_path" "$@"
  else
    uv run python scripts/release_evidence_capture.py \
      "$raw_path" --output "$output_path" "$@"
  fi
  rm -rf "$raw_dir"
}

capture_release_json readyz "$READY_URL" \
  reports/release-gate/readyz.json --captured-now
capture_release_json trajectory "$TRAJECTORY_STATS_URL" \
  reports/release-gate/trajectory-stats.json --captured-now
capture_release_json replay "$REPLAY_COMPARISONS_URL" \
  reports/release-gate/replay-comparisons.json
capture_release_json alert "$ALERT_REPORT_URL" \
  reports/release-gate/alert-report.json
capture_release_json migration "$POSTGRES_MIGRATION_REPORT_URL" \
  reports/release-gate/postgres-migration.json
capture_release_json baseline "$BASELINE_EVAL_REPORT_URL" \
  reports/release-gate/baseline-eval-smoke.json
capture_release_json stream "$STREAM_EVENTS_REPORT_URL" \
  reports/release-gate/stream-events.json

make production-smoke PRODUCTION_SMOKE_ARGS="--base-url $BASE_URL --web-base-url $BASE_URL --auth-token $AUTH_TOKEN --stream-events-json reports/release-gate/stream-events.json --report-json reports/release-gate/production-smoke.json"
make postgres-ops POSTGRES_OPS_ARGS="--database-uri $DATABASE_URI --backup-command '$POSTGRES_BACKUP_COMMAND' --restore-command '$POSTGRES_RESTORE_COMMAND' --restore-verification-query '$POSTGRES_RESTORE_VERIFICATION_QUERY' --retention-cleanup-query '$POSTGRES_RETENTION_CLEANUP_QUERY' --report-json reports/release-gate/postgres-ops.json"
make otel-smoke OTEL_SMOKE_ARGS="--endpoint $OTEL_ENDPOINT --collector-health-url $OTEL_COLLECTOR_HEALTH_URL --trace-query-url '$OTEL_TRACE_QUERY_URL' --service-name focus-agent --report-json reports/release-gate/otel-smoke.json"

make release-evidence RELEASE_EVIDENCE_ARGS="--release-id <release-id> --commit-sha ${RELEASE_COMMIT_SHA} --deployment-id ${RELEASE_DEPLOYMENT_ID} --deployment-version ${RELEASE_DEPLOYMENT_VERSION} --environment ${RELEASE_ENVIRONMENT} --max-evidence-age-seconds 21600 --approval-id ${APPROVAL_ID} --approval-status ${APPROVAL_STATUS} --approval-url ${APPROVAL_URL} --retention-days ${RETENTION_DAYS} --storage-dir ${ARTIFACT_STORAGE_DIR} --readyz-json reports/release-gate/readyz.json --trajectory-stats-json reports/release-gate/trajectory-stats.json --replay-comparisons-json reports/release-gate/replay-comparisons.json --alert-report-json reports/release-gate/alert-report.json --postgres-migration-report-json reports/release-gate/postgres-migration.json --production-smoke-report-json reports/release-gate/production-smoke.json --postgres-ops-report-json reports/release-gate/postgres-ops.json --otel-smoke-report-json reports/release-gate/otel-smoke.json --governance-report-json ${GOVERNANCE_REPORT_JSON} --eval-report-json reports/release-gate/eval-smoke.json --eval-report-json reports/release-gate/eval-observability.json --eval-report-json reports/release-gate/eval-golden-multi-agent.json --eval-report-json reports/release-gate/eval-harness-stability.json --eval-report-json reports/release-gate/memory-context-eval.json --baseline-eval-report-json reports/release-gate/baseline-eval-smoke.json"
```

Only the two live snapshots use `--captured-now`. The static replay, alert,
migration, baseline, and stream reports must already contain a timezone-aware
timestamp. Generate standard eval, governance, and memory/context reports after
exporting `RELEASE_*` so their writers bind the tuple.

Artifact upload is handled by `actions/upload-artifact@v7`:

```yaml
- name: Upload release gate reports
  if: always()
  uses: actions/upload-artifact@v7
  with:
    name: release-gate-reports-${{ github.run_id }}
    path: reports/release-gate/
    retention-days: 90
    if-no-files-found: ignore
```

The checked-in production job always uses the protected `production` GitHub
Environment. Keep approval id and approval URL tied to that deployment run.
Production validation requires status `approved`, a non-empty approval id and
URL, a configured `--storage-dir`, and successful stored manifest/summary hash
verification. Upload retention must be at least the manifest
`retention.days` value.

## Buildkite

Buildkite should run the same commands and upload the release evidence directory as an artifact:

```yaml
steps:
  - label: ":rocket: release gate"
    command:
      - ": \"${RELEASE_COMMIT_SHA:?must identify the deployed commit}\""
      - ": \"${RELEASE_DEPLOYMENT_ID:?must identify the deployment}\""
      - ": \"${RELEASE_DEPLOYMENT_VERSION:?must identify the deployed version}\""
      - "test \"${RELEASE_ENVIRONMENT:?}\" = production"
      - "test \"$(git rev-parse HEAD)\" = \"$(git rev-parse \"${RELEASE_COMMIT_SHA}^{commit}\")\""
      - "export DRY_RUN=false ENVIRONMENT_NAME=production APPROVAL_ID=$BUILDKITE_BUILD_ID APPROVAL_STATUS=approved APPROVAL_URL=$BUILDKITE_BUILD_URL RETENTION_DAYS=90 ARTIFACT_STORAGE_DIR=reports/release-gate/archive DEPLOYMENT_BINDING_JSON=reports/release-gate/deployment-binding.json"
      - "export BASE_URL=\"${FOCUS_AGENT_BASE_URL:?}\" READY_URL=\"${FOCUS_AGENT_READY_URL:?}\" TRAJECTORY_STATS_URL=\"${FOCUS_AGENT_TRAJECTORY_STATS_URL:?}\" REPLAY_COMPARISONS_URL=\"${FOCUS_AGENT_REPLAY_COMPARISONS_URL:?}\" ALERT_REPORT_URL=\"${FOCUS_AGENT_ALERT_REPORT_URL:?}\" POSTGRES_MIGRATION_REPORT_URL=\"${FOCUS_AGENT_POSTGRES_MIGRATION_REPORT_URL:?}\" BASELINE_EVAL_REPORT_URL=\"${FOCUS_AGENT_BASELINE_EVAL_REPORT_URL:?}\""
      - "export AUTH_TOKEN=\"${FOCUS_AGENT_SMOKE_AUTH_TOKEN:?}\" STREAM_EVENTS_REPORT_URL=\"${FOCUS_AGENT_STREAM_EVENTS_REPORT_URL:?}\" DATABASE_URI=\"${FOCUS_AGENT_DATABASE_URI:?}\" POSTGRES_BACKUP_COMMAND=\"${FOCUS_AGENT_POSTGRES_BACKUP_COMMAND:?}\" POSTGRES_RESTORE_COMMAND=\"${FOCUS_AGENT_POSTGRES_RESTORE_COMMAND:?}\" POSTGRES_RESTORE_VERIFICATION_QUERY=\"${FOCUS_AGENT_POSTGRES_RESTORE_VERIFICATION_QUERY:?}\" POSTGRES_RETENTION_CLEANUP_QUERY=\"${FOCUS_AGENT_POSTGRES_RETENTION_CLEANUP_QUERY:?}\""
      - "export OTEL_ENDPOINT=\"${FOCUS_AGENT_OTEL_ENDPOINT:?}\" OTEL_COLLECTOR_HEALTH_URL=\"${FOCUS_AGENT_OTEL_COLLECTOR_HEALTH_URL:?}\" OTEL_TRACE_QUERY_URL=\"${FOCUS_AGENT_OTEL_TRACE_QUERY_URL:?}\" GOVERNANCE_REPORT_JSON=reports/agent-governance/latest.json"
      - "corepack enable"
      - "make install-openai"
      - "make sdk-install"
      - "make web-install"
      - "python scripts/release_gate.py deployment-binding --output \"$DEPLOYMENT_BINDING_JSON\""
      - "make release-gate"
      - "mkdir -p reports/release-gate-raw reports/release-gate"
      - "curl --fail --show-error --silent --output reports/release-gate-raw/readyz.json -- \"$READY_URL\""
      - "uv run python scripts/release_evidence_capture.py reports/release-gate-raw/readyz.json --output reports/release-gate/readyz.json --readyz reports/release-gate-raw/readyz.json --captured-now"
      - "curl --fail --show-error --silent --output reports/release-gate-raw/trajectory-stats.json -- \"$TRAJECTORY_STATS_URL\""
      - "uv run python scripts/release_evidence_capture.py reports/release-gate-raw/trajectory-stats.json --output reports/release-gate/trajectory-stats.json --captured-now"
      - "curl --fail --show-error --silent --output reports/release-gate-raw/replay-comparisons.json -- \"$REPLAY_COMPARISONS_URL\""
      - "uv run python scripts/release_evidence_capture.py reports/release-gate-raw/replay-comparisons.json --output reports/release-gate/replay-comparisons.json"
      - "curl --fail --show-error --silent --output reports/release-gate-raw/alert-report.json -- \"$ALERT_REPORT_URL\""
      - "uv run python scripts/release_evidence_capture.py reports/release-gate-raw/alert-report.json --output reports/release-gate/alert-report.json"
      - "curl --fail --show-error --silent --output reports/release-gate-raw/postgres-migration.json -- \"$POSTGRES_MIGRATION_REPORT_URL\""
      - "uv run python scripts/release_evidence_capture.py reports/release-gate-raw/postgres-migration.json --output reports/release-gate/postgres-migration.json"
      - "curl --fail --show-error --silent --output reports/release-gate-raw/baseline-eval-smoke.json -- \"$BASELINE_EVAL_REPORT_URL\""
      - "uv run python scripts/release_evidence_capture.py reports/release-gate-raw/baseline-eval-smoke.json --output reports/release-gate/baseline-eval-smoke.json"
      - "curl --fail --show-error --silent --output reports/release-gate-raw/stream-events.json -- \"$STREAM_EVENTS_REPORT_URL\""
      - "uv run python scripts/release_evidence_capture.py reports/release-gate-raw/stream-events.json --output reports/release-gate/stream-events.json"
      - "rm -rf reports/release-gate-raw"
      - "make production-smoke PRODUCTION_SMOKE_ARGS=\"--base-url $BASE_URL --web-base-url $BASE_URL --auth-token $AUTH_TOKEN --stream-events-json reports/release-gate/stream-events.json --report-json reports/release-gate/production-smoke.json\""
      - "make postgres-ops POSTGRES_OPS_ARGS=\"--database-uri $DATABASE_URI --backup-command '$POSTGRES_BACKUP_COMMAND' --restore-command '$POSTGRES_RESTORE_COMMAND' --restore-verification-query '$POSTGRES_RESTORE_VERIFICATION_QUERY' --retention-cleanup-query '$POSTGRES_RETENTION_CLEANUP_QUERY' --report-json reports/release-gate/postgres-ops.json\""
      - "make otel-smoke OTEL_SMOKE_ARGS=\"--endpoint $OTEL_ENDPOINT --collector-health-url $OTEL_COLLECTOR_HEALTH_URL --trace-query-url '$OTEL_TRACE_QUERY_URL' --report-json reports/release-gate/otel-smoke.json\""
      - "make release-evidence RELEASE_EVIDENCE_ARGS=\"--release-id $RELEASE_ID --commit-sha $RELEASE_COMMIT_SHA --deployment-id $RELEASE_DEPLOYMENT_ID --deployment-version $RELEASE_DEPLOYMENT_VERSION --environment $RELEASE_ENVIRONMENT --max-evidence-age-seconds 21600 --approval-id $APPROVAL_ID --approval-status $APPROVAL_STATUS --approval-url $APPROVAL_URL --retention-days $RETENTION_DAYS --storage-dir $ARTIFACT_STORAGE_DIR --readyz-json reports/release-gate/readyz.json --trajectory-stats-json reports/release-gate/trajectory-stats.json --replay-comparisons-json reports/release-gate/replay-comparisons.json --alert-report-json reports/release-gate/alert-report.json --postgres-migration-report-json reports/release-gate/postgres-migration.json --production-smoke-report-json reports/release-gate/production-smoke.json --postgres-ops-report-json reports/release-gate/postgres-ops.json --otel-smoke-report-json reports/release-gate/otel-smoke.json --governance-report-json $GOVERNANCE_REPORT_JSON --eval-report-json reports/release-gate/eval-smoke.json --eval-report-json reports/release-gate/eval-observability.json --eval-report-json reports/release-gate/eval-golden-multi-agent.json --eval-report-json reports/release-gate/eval-harness-stability.json --eval-report-json reports/release-gate/memory-context-eval.json --baseline-eval-report-json reports/release-gate/baseline-eval-smoke.json\""
    artifact_paths:
      - "reports/release-gate/**/*"
```

Configure the four `RELEASE_*` values from deployment metadata before this step;
do not derive deployment id or version from the evidence files. If the pipeline
uses a `block` step, pass its stable result or build id as `APPROVAL_ID` and the
build URL as `APPROVAL_URL`. Keep the retained artifact at least as long as
`RETENTION_DAYS`.

## Generic CI

Any CI provider can bind the same three phases:

```bash
set -euo pipefail

make install-openai
make sdk-install
make web-install

: "${RELEASE_COMMIT_SHA:?must identify the deployed commit}"
: "${RELEASE_DEPLOYMENT_ID:?must identify the deployment}"
: "${RELEASE_DEPLOYMENT_VERSION:?must identify the deployed version}"
test "${RELEASE_ENVIRONMENT:?}" = "production"
test "$(git rev-parse HEAD)" = "$(git rev-parse "${RELEASE_COMMIT_SHA}^{commit}")"

export DRY_RUN=false
export ENVIRONMENT_NAME=production
export APPROVAL_ID="${CI_APPROVAL_ID:?}"
export APPROVAL_STATUS=approved
export APPROVAL_URL="${CI_APPROVAL_URL:?}"
export RETENTION_DAYS="${RETENTION_DAYS:-90}"
export ARTIFACT_STORAGE_DIR=reports/release-gate/archive
export DEPLOYMENT_BINDING_JSON=reports/release-gate/deployment-binding.json
export BASE_URL="${FOCUS_AGENT_BASE_URL:?}"
export READY_URL="${FOCUS_AGENT_READY_URL:?}"
export TRAJECTORY_STATS_URL="${FOCUS_AGENT_TRAJECTORY_STATS_URL:?}"
export REPLAY_COMPARISONS_URL="${FOCUS_AGENT_REPLAY_COMPARISONS_URL:?}"
export ALERT_REPORT_URL="${FOCUS_AGENT_ALERT_REPORT_URL:?}"
export POSTGRES_MIGRATION_REPORT_URL="${FOCUS_AGENT_POSTGRES_MIGRATION_REPORT_URL:?}"
export BASELINE_EVAL_REPORT_URL="${FOCUS_AGENT_BASELINE_EVAL_REPORT_URL:?}"
export AUTH_TOKEN="${FOCUS_AGENT_SMOKE_AUTH_TOKEN:?}"
export STREAM_EVENTS_REPORT_URL="${FOCUS_AGENT_STREAM_EVENTS_REPORT_URL:?}"
export DATABASE_URI="${FOCUS_AGENT_DATABASE_URI:?}"
export POSTGRES_BACKUP_COMMAND="${FOCUS_AGENT_POSTGRES_BACKUP_COMMAND:?}"
export POSTGRES_RESTORE_COMMAND="${FOCUS_AGENT_POSTGRES_RESTORE_COMMAND:?}"
export POSTGRES_RESTORE_VERIFICATION_QUERY="${FOCUS_AGENT_POSTGRES_RESTORE_VERIFICATION_QUERY:?}"
export POSTGRES_RETENTION_CLEANUP_QUERY="${FOCUS_AGENT_POSTGRES_RETENTION_CLEANUP_QUERY:?}"
export OTEL_ENDPOINT="${FOCUS_AGENT_OTEL_ENDPOINT:?}"
export OTEL_COLLECTOR_HEALTH_URL="${FOCUS_AGENT_OTEL_COLLECTOR_HEALTH_URL:?}"
export OTEL_TRACE_QUERY_URL="${FOCUS_AGENT_OTEL_TRACE_QUERY_URL:?}"
export GOVERNANCE_REPORT_JSON=reports/agent-governance/latest.json

mkdir -p reports/release-gate
python scripts/release_gate.py deployment-binding --output "$DEPLOYMENT_BINDING_JSON"
make release-gate

mkdir -p reports/release-gate-raw
curl --fail --show-error --silent --output reports/release-gate-raw/readyz.json -- "$READY_URL"
uv run python scripts/release_evidence_capture.py \
  reports/release-gate-raw/readyz.json \
  --output reports/release-gate/readyz.json \
  --readyz reports/release-gate-raw/readyz.json \
  --captured-now
curl --fail --show-error --silent --output reports/release-gate-raw/trajectory-stats.json -- "$TRAJECTORY_STATS_URL"
uv run python scripts/release_evidence_capture.py \
  reports/release-gate-raw/trajectory-stats.json \
  --output reports/release-gate/trajectory-stats.json \
  --captured-now
curl --fail --show-error --silent --output reports/release-gate-raw/replay-comparisons.json -- "$REPLAY_COMPARISONS_URL"
uv run python scripts/release_evidence_capture.py \
  reports/release-gate-raw/replay-comparisons.json \
  --output reports/release-gate/replay-comparisons.json
curl --fail --show-error --silent --output reports/release-gate-raw/alert-report.json -- "$ALERT_REPORT_URL"
uv run python scripts/release_evidence_capture.py \
  reports/release-gate-raw/alert-report.json \
  --output reports/release-gate/alert-report.json
curl --fail --show-error --silent --output reports/release-gate-raw/postgres-migration.json -- "$POSTGRES_MIGRATION_REPORT_URL"
uv run python scripts/release_evidence_capture.py \
  reports/release-gate-raw/postgres-migration.json \
  --output reports/release-gate/postgres-migration.json
curl --fail --show-error --silent --output reports/release-gate-raw/baseline-eval-smoke.json -- "$BASELINE_EVAL_REPORT_URL"
uv run python scripts/release_evidence_capture.py \
  reports/release-gate-raw/baseline-eval-smoke.json \
  --output reports/release-gate/baseline-eval-smoke.json
curl --fail --show-error --silent --output reports/release-gate-raw/stream-events.json -- "$STREAM_EVENTS_REPORT_URL"
uv run python scripts/release_evidence_capture.py \
  reports/release-gate-raw/stream-events.json \
  --output reports/release-gate/stream-events.json
rm -rf reports/release-gate-raw

make production-smoke PRODUCTION_SMOKE_ARGS="--base-url ${BASE_URL} --web-base-url ${BASE_URL} --auth-token ${AUTH_TOKEN} --stream-events-json reports/release-gate/stream-events.json --report-json reports/release-gate/production-smoke.json"
make postgres-ops POSTGRES_OPS_ARGS="--database-uri ${DATABASE_URI} --backup-command '${POSTGRES_BACKUP_COMMAND}' --restore-command '${POSTGRES_RESTORE_COMMAND}' --restore-verification-query '${POSTGRES_RESTORE_VERIFICATION_QUERY}' --retention-cleanup-query '${POSTGRES_RETENTION_CLEANUP_QUERY}' --report-json reports/release-gate/postgres-ops.json"
make otel-smoke OTEL_SMOKE_ARGS="--endpoint ${OTEL_ENDPOINT} --collector-health-url ${OTEL_COLLECTOR_HEALTH_URL} --trace-query-url '${OTEL_TRACE_QUERY_URL}' --report-json reports/release-gate/otel-smoke.json"

make release-evidence RELEASE_EVIDENCE_ARGS="--release-id ${RELEASE_ID} --commit-sha ${RELEASE_COMMIT_SHA} --deployment-id ${RELEASE_DEPLOYMENT_ID} --deployment-version ${RELEASE_DEPLOYMENT_VERSION} --environment ${RELEASE_ENVIRONMENT} --max-evidence-age-seconds 21600 --approval-id ${APPROVAL_ID} --approval-status ${APPROVAL_STATUS} --approval-url ${APPROVAL_URL} --retention-days ${RETENTION_DAYS} --storage-dir ${ARTIFACT_STORAGE_DIR} --readyz-json reports/release-gate/readyz.json --trajectory-stats-json reports/release-gate/trajectory-stats.json --replay-comparisons-json reports/release-gate/replay-comparisons.json --alert-report-json reports/release-gate/alert-report.json --postgres-migration-report-json reports/release-gate/postgres-migration.json --production-smoke-report-json reports/release-gate/production-smoke.json --postgres-ops-report-json reports/release-gate/postgres-ops.json --otel-smoke-report-json reports/release-gate/otel-smoke.json --governance-report-json ${GOVERNANCE_REPORT_JSON} --eval-report-json reports/release-gate/eval-smoke.json --eval-report-json reports/release-gate/eval-observability.json --eval-report-json reports/release-gate/eval-golden-multi-agent.json --eval-report-json reports/release-gate/eval-harness-stability.json --eval-report-json reports/release-gate/memory-context-eval.json --baseline-eval-report-json reports/release-gate/baseline-eval-smoke.json"
```

Set the four release variables before `make release-gate` so locally generated
eval and governance reports attest the same identity as smoke/ops/OTel reports.
Downloaded inputs must pass the trusted capture helper; locally generated eval,
governance, and memory/context reports attest through their writers. The
evidence builder will not add missing identity or timestamps. Upload
`reports/release-gate/**/*` with the provider's artifact feature and keep it for
at least the manifest `retention.days` value. If the provider cannot expose a
structured approval id, use a stable deployment ticket id and include the CI
run URL as `APPROVAL_URL`.
