from __future__ import annotations

import copy
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "release-gate.yml"
BOOL_TAG = "tag:yaml.org,2002:bool"


class _GitHubWorkflowLoader(yaml.SafeLoader):
    pass


_GitHubWorkflowLoader.yaml_implicit_resolvers = copy.deepcopy(
    yaml.SafeLoader.yaml_implicit_resolvers
)
for initial in ("o", "O"):
    _GitHubWorkflowLoader.yaml_implicit_resolvers[initial] = [
        (tag, pattern)
        for tag, pattern in _GitHubWorkflowLoader.yaml_implicit_resolvers.get(initial, [])
        if tag != BOOL_TAG
    ]


def _load_workflow() -> dict[str, Any]:
    payload = yaml.load(
        WORKFLOW_PATH.read_text(encoding="utf-8"),
        Loader=_GitHubWorkflowLoader,
    )
    assert isinstance(payload, dict)
    return payload


def _production_capture_script() -> str:
    workflow = _load_workflow()
    steps = workflow["jobs"]["release-gate-production"]["steps"]
    step = next(item for item in steps if item["name"] == "Capture production release signals")
    run = step.get("run")
    assert isinstance(run, str)
    return run


def _write_executable(path: Path, source: str) -> None:
    path.write_text(source, encoding="utf-8")
    path.chmod(0o755)


def _capture_environment(tmp_path: Path) -> tuple[dict[str, str], Path]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    call_log = tmp_path / "calls.log"
    governance_report = tmp_path / "governance.json"
    governance_report.write_text("{}\n", encoding="utf-8")
    _write_executable(
        fake_bin / "curl",
        """#!/usr/bin/env bash
set -euo pipefail
output_path=
source_url=
while (($#)); do
  case "$1" in
    --output)
      output_path="$2"
      shift 2
      ;;
    --)
      shift
      source_url="${1:-}"
      shift
      ;;
    *)
      source_url="$1"
      shift
      ;;
  esac
done
printf 'curl:%s\n' "$source_url" >> "$WORKFLOW_CALL_LOG"
if [[ "${FAIL_CURL_URL:-}" == "$source_url" ]]; then
  exit 22
fi
test -n "$output_path"
if [[ "$source_url" == "$READY_URL" || "$source_url" == "$TRAJECTORY_STATS_URL" ]]; then
  printf '{"source_url":"%s"}\n' "$source_url" > "$output_path"
elif [[ -n "${MISSING_TIMESTAMP_URL:-}" && "$source_url" == "$MISSING_TIMESTAMP_URL" ]]; then
  printf '{"source_url":"%s"}\n' "$source_url" > "$output_path"
else
  printf '{"generated_at":"2026-07-12T09:30:45Z","source_url":"%s"}\n' "$source_url" > "$output_path"
fi
""",
    )
    _write_executable(
        fake_bin / "uv",
        """#!/usr/bin/env bash
set -euo pipefail
printf 'uv:%s\n' "$*" >> "$WORKFLOW_CALL_LOG"
if [[ "${1:-}" != "run" || "${2:-}" != "python" || "${3:-}" != "scripts/release_evidence_capture.py" ]]; then
  exit 0
fi
shift 3
input_path="${1:-}"
shift
artifact_name="$(basename "$input_path" .json)"
output_path=
captured_now=false
readyz_path=
while (($#)); do
  case "$1" in
    --output)
      output_path="$2"
      shift 2
      ;;
    --captured-now)
      captured_now=true
      shift
      ;;
    --readyz)
      readyz_path="$2"
      shift 2
      ;;
    *)
      exit 64
      ;;
  esac
done
printf 'capture:%s:%s:%s:%s:%s:%s:%s\n' \
  "$artifact_name" \
  "$captured_now" \
  "$RELEASE_COMMIT_SHA" \
  "$RELEASE_DEPLOYMENT_ID" \
  "$RELEASE_DEPLOYMENT_VERSION" \
  "$RELEASE_ENVIRONMENT" \
  "$input_path" >> "$WORKFLOW_CALL_LOG"
if [[ "${FAIL_CAPTURE_ARTIFACT:-}" == "$artifact_name" ]]; then
  exit 65
fi
if [[ "$artifact_name" == "readyz" && "$readyz_path" != "$input_path" ]]; then
  exit 67
fi
if [[ "$captured_now" == "false" ]] && ! grep -q '"generated_at":"[^"]*[zZ+][^"]*"' "$input_path"; then
  exit 66
fi
mkdir -p "$(dirname "$output_path")"
cp "$input_path" "$output_path"
""",
    )
    environment = {
        **os.environ,
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "WORKFLOW_CALL_LOG": str(call_log),
        "RUNNER_TEMP": str(tmp_path / "runner-temp"),
        "BASE_URL": "https://focus.example",
        "READY_URL": "https://focus.example/readyz",
        "TRAJECTORY_STATS_URL": "https://focus.example/trajectory-stats",
        "REPLAY_COMPARISONS_URL": "https://focus.example/replay-comparisons",
        "ALERT_REPORT_URL": "https://focus.example/alert-report",
        "POSTGRES_MIGRATION_REPORT_URL": "https://focus.example/postgres-migration",
        "BASELINE_EVAL_REPORT_URL": "https://focus.example/baseline-eval",
        "ENVIRONMENT_NAME": "production",
        "GITHUB_SHA": "0123456789abcdef",
        "RELEASE_COMMIT_SHA": "0123456789abcdef",
        "RELEASE_DEPLOYMENT_ID": "focus-agent-production",
        "RELEASE_DEPLOYMENT_VERSION": "2026.07.12.1",
        "RELEASE_ENVIRONMENT": "production",
        "ARTIFACT_STORAGE_DIR": "reports/release-gate/archive",
        "RELEASE_GATE_ARTIFACT_NAME": "release-gate-reports-1-1",
        "RETENTION_DAYS": "90",
        "AUTH_TOKEN": "test-token",
        "DATABASE_URI": "postgresql://focus:test@localhost/focus",
        "POSTGRES_BACKUP_COMMAND": "backup",
        "POSTGRES_RESTORE_COMMAND": "restore",
        "POSTGRES_RESTORE_VERIFICATION_QUERY": "SELECT 1",
        "POSTGRES_RETENTION_CLEANUP_QUERY": "SELECT 1",
        "OTEL_ENDPOINT": "https://otel.example/v1/traces",
        "OTEL_COLLECTOR_HEALTH_URL": "https://otel.example/health",
        "OTEL_TRACE_QUERY_URL": "https://otel.example/traces",
        "STREAM_EVENTS_REPORT_URL": "",
        "STREAM_EVENTS_URL": "https://focus.example/stream",
        "GOVERNANCE_REPORT_JSON": str(governance_report),
    }
    Path(environment["RUNNER_TEMP"]).mkdir()
    return environment, call_log


def _run_capture_step(
    tmp_path: Path,
    *,
    fail_capture_artifact: str | None = None,
    fail_curl_url: str | None = None,
    static_stream_report: bool = False,
    missing_timestamp_url: str | None = None,
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    environment, call_log = _capture_environment(tmp_path)
    if fail_capture_artifact is not None:
        environment["FAIL_CAPTURE_ARTIFACT"] = fail_capture_artifact
    if fail_curl_url is not None:
        environment["FAIL_CURL_URL"] = fail_curl_url
    if static_stream_report:
        environment["STREAM_EVENTS_REPORT_URL"] = "https://focus.example/stream-events"
        environment["STREAM_EVENTS_URL"] = ""
    if missing_timestamp_url is not None:
        environment["MISSING_TIMESTAMP_URL"] = missing_timestamp_url
    completed = subprocess.run(
        ("bash", "-c", _production_capture_script()),
        cwd=tmp_path,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    calls = call_log.read_text(encoding="utf-8").splitlines()
    return completed, calls


def test_release_workflow_uses_hardcoded_production_environment() -> None:
    workflow = _load_workflow()
    inputs = workflow["on"]["workflow_dispatch"]["inputs"]
    jobs = workflow["jobs"]
    dry_run_job = jobs["release-gate-dry-run"]
    production_job = jobs["release-gate-production"]

    assert set(inputs) == {"release_id", "dry_run", "retention_days"}
    assert dry_run_job["if"] == "${{ inputs.dry_run == true }}"
    assert "environment" not in dry_run_job
    assert production_job["if"] == "${{ inputs.dry_run == false }}"
    assert production_job["environment"] == "production"


def test_release_workflow_does_not_trust_dispatch_approval_fields() -> None:
    workflow = _load_workflow()
    source = WORKFLOW_PATH.read_text(encoding="utf-8")
    production_env = workflow["jobs"]["release-gate-production"]["env"]

    assert "approval_id:" not in source.split("permissions:", maxsplit=1)[0]
    assert "approval_status:" not in source.split("permissions:", maxsplit=1)[0]
    assert "environment_name:" not in source.split("permissions:", maxsplit=1)[0]
    assert "inputs.approval_id" not in source
    assert "inputs.approval_status" not in source
    assert "inputs.environment_name" not in source
    assert production_env["APPROVAL_STATUS"] == "approved"
    assert production_env["APPROVAL_ID"] == (
        "github-environment-production-${{ github.run_id }}-${{ github.run_attempt }}"
    )
    assert production_env["APPROVAL_URL"] == (
        "${{ format('{0}/{1}/actions/runs/{2}', "
        "github.server_url, github.repository, github.run_id) }}"
    )


def test_release_workflow_keeps_dry_run_isolated_from_production() -> None:
    workflow = _load_workflow()
    jobs = workflow["jobs"]
    dry_run_job = jobs["release-gate-dry-run"]
    production_job = jobs["release-gate-production"]
    dry_run_source = yaml.safe_dump(dry_run_job, sort_keys=True)
    production_source = yaml.safe_dump(production_job, sort_keys=True)

    assert dry_run_job["env"]["DRY_RUN"] == "true"
    assert production_job["env"]["DRY_RUN"] == "false"
    assert "secrets." not in dry_run_source
    assert "FOCUS_AGENT_" not in dry_run_source
    assert "--dry-run" in dry_run_source
    assert "reports/release-gate/dry-run/" in dry_run_source
    assert "Capture production release signals" not in dry_run_source
    assert "--dry-run" not in production_source
    assert "Capture production release signals" in production_source


def test_release_workflow_binds_evidence_to_deployed_identity() -> None:
    workflow = _load_workflow()
    production_job = workflow["jobs"]["release-gate-production"]
    production_env = production_job["env"]
    source = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert production_env["RELEASE_COMMIT_SHA"] == "${{ github.sha }}"
    assert production_env["RELEASE_DEPLOYMENT_ID"] == ("${{ vars.FOCUS_AGENT_DEPLOYMENT_ID }}")
    assert production_env["RELEASE_DEPLOYMENT_VERSION"] == (
        "${{ vars.FOCUS_AGENT_DEPLOYMENT_VERSION }}"
    )
    assert production_env["RELEASE_ENVIRONMENT"] == "production"
    assert 'test "$RELEASE_COMMIT_SHA" = "$GITHUB_SHA"' in source
    assert 'test -n "$RELEASE_DEPLOYMENT_ID"' in source
    assert 'test -n "$RELEASE_DEPLOYMENT_VERSION"' in source
    assert 'test "$RELEASE_ENVIRONMENT" = "production"' in source
    assert '"${raw_dir}/${artifact_name}.json"' in source
    assert '--web-base-url "$BASE_URL"' not in source


def test_release_workflow_attests_every_downloaded_production_evidence_input() -> None:
    script = _production_capture_script()
    normalized_script = "\n".join(line.lstrip() for line in script.splitlines())
    expected_captures = (
        (
            "readyz",
            "$READY_URL",
            "reports/release-gate/readyz.json",
            "--captured-now",
        ),
        (
            "trajectory_stats",
            "$TRAJECTORY_STATS_URL",
            "reports/release-gate/trajectory-stats.json",
            "--captured-now",
        ),
        (
            "replay_comparisons",
            "$REPLAY_COMPARISONS_URL",
            "reports/release-gate/replay-comparisons.json",
            "",
        ),
        (
            "alert_report",
            "$ALERT_REPORT_URL",
            "reports/release-gate/alert-report.json",
            "",
        ),
        (
            "postgres_migration_report",
            "$POSTGRES_MIGRATION_REPORT_URL",
            "reports/release-gate/postgres-migration.json",
            "",
        ),
        (
            "baseline_eval_report",
            "$BASELINE_EVAL_REPORT_URL",
            "reports/release-gate/baseline-eval-smoke.json",
            "",
        ),
        (
            "stream_events",
            "$STREAM_EVENTS_REPORT_URL",
            "reports/release-gate/stream-events.json",
            "",
        ),
    )

    assert "set -euo pipefail" in script
    assert 'raw_dir="$(mktemp -d "${RUNNER_TEMP:?}/focus-agent-${artifact_name}.XXXXXX")"' in script
    assert 'raw_path="${raw_dir}/${artifact_name}.json"' in script
    assert "capture_command=(" not in script
    assert '"$raw_path"' in script
    assert '--output "$output_path"' in script
    assert '--readyz "$raw_path"' in script
    assert 'if [ "$artifact_name" = "readyz" ]; then' in script
    assert script.count("scripts/release_evidence_capture.py") == 2
    assert 'rm -rf "$raw_dir"' in script
    assert 'rm -f "$output_path"' in script
    for artifact_name, source_url, output_path, extra_flag in expected_captures:
        invocation = (
            f'capture_release_json \\\n{artifact_name} \\\n"{source_url}" \\\n{output_path}'
        )
        assert invocation in normalized_script
        if extra_flag:
            assert f"{invocation} \\\n{extra_flag}" in normalized_script
        else:
            assert f"{invocation}\n" in normalized_script
        assert f"> {output_path}" not in script

    assert script.index("readyz \\\n") < script.index("trajectory_stats \\\n")
    assert script.count("--captured-now") == 2
    assert 'stream_args+=(--stream-events-url "$STREAM_EVENTS_URL")' in script


def test_release_workflow_capture_uses_complete_environment_binding(
    tmp_path: Path,
) -> None:
    completed, calls = _run_capture_step(tmp_path)

    assert completed.returncode == 0, completed.stderr
    captures = [call for call in calls if call.startswith("capture:")]
    assert [call.split(":", maxsplit=2)[1] for call in captures] == [
        "readyz",
        "trajectory_stats",
        "replay_comparisons",
        "alert_report",
        "postgres_migration_report",
        "baseline_eval_report",
    ]
    assert captures[0].startswith(
        "capture:readyz:true:0123456789abcdef:focus-agent-production:2026.07.12.1:production:"
    )
    assert all(
        ":0123456789abcdef:focus-agent-production:2026.07.12.1:production:" in call
        for call in captures
    )
    assert [":true:" in call for call in captures] == [
        True,
        True,
        False,
        False,
        False,
        False,
    ]


@pytest.mark.parametrize(
    ("failed_artifact", "last_capture", "forbidden_url"),
    (
        ("readyz", "readyz", "https://focus.example/trajectory-stats"),
        (
            "replay_comparisons",
            "replay_comparisons",
            "https://focus.example/alert-report",
        ),
    ),
)
def test_release_workflow_stops_after_capture_mismatch_or_failure(
    tmp_path: Path,
    failed_artifact: str,
    last_capture: str,
    forbidden_url: str,
) -> None:
    completed, calls = _run_capture_step(
        tmp_path,
        fail_capture_artifact=failed_artifact,
    )

    assert completed.returncode != 0
    captures = [call for call in calls if call.startswith("capture:")]
    assert captures[-1].startswith(f"capture:{last_capture}:")
    assert all(forbidden_url not in call for call in calls)
    assert not any("scripts/production_smoke.py" in call for call in calls)


def test_release_workflow_stops_after_raw_download_failure(tmp_path: Path) -> None:
    failed_url = "https://focus.example/trajectory-stats"
    completed, calls = _run_capture_step(tmp_path, fail_curl_url=failed_url)

    assert completed.returncode != 0
    assert any(call == f"curl:{failed_url}" for call in calls)
    assert not any(call.startswith("capture:trajectory_stats:") for call in calls)
    assert not any("https://focus.example/replay-comparisons" in call for call in calls)


def test_release_workflow_attests_static_stream_report_without_captured_now(
    tmp_path: Path,
) -> None:
    completed, calls = _run_capture_step(tmp_path, static_stream_report=True)

    assert completed.returncode == 0, completed.stderr
    stream_capture = next(call for call in calls if call.startswith("capture:stream_events:"))
    assert stream_capture.startswith(
        "capture:stream_events:false:0123456789abcdef:"
        "focus-agent-production:2026.07.12.1:production:"
    )
    assert any(call == "curl:https://focus.example/stream-events" for call in calls)


@pytest.mark.parametrize(
    ("url", "artifact_name"),
    (
        ("https://focus.example/replay-comparisons", "replay_comparisons"),
        ("https://focus.example/alert-report", "alert_report"),
        ("https://focus.example/postgres-migration", "postgres_migration_report"),
        ("https://focus.example/baseline-eval", "baseline_eval_report"),
        ("https://focus.example/stream-events", "stream_events"),
    ),
)
def test_release_workflow_rejects_upstream_report_without_timestamp(
    tmp_path: Path,
    url: str,
    artifact_name: str,
) -> None:
    completed, calls = _run_capture_step(
        tmp_path,
        static_stream_report=artifact_name == "stream_events",
        missing_timestamp_url=url,
    )

    assert completed.returncode != 0
    assert any(call.startswith(f"capture:{artifact_name}:false:") for call in calls)
    assert not any("scripts/production_smoke.py" in call for call in calls)
