from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


TAIL_LINE_LIMIT = 80
TAIL_CHAR_LIMIT = 12_000
DEFAULT_REPORT_JSON = Path("reports/release-gate/latest.json")


@dataclass(frozen=True)
class GateCommand:
    label: str
    command: tuple[str, ...]


@dataclass(frozen=True)
class CommandOutcome:
    exit_code: int
    stdout: str = ""
    stderr: str = ""


Runner = Callable[[GateCommand, Path], CommandOutcome]


PRODUCTION_SIGNAL_MAPPINGS: tuple[dict[str, Any], ...] = (
    {
        "key": "base_url",
        "env": "BASE_URL",
        "source": "vars.FOCUS_AGENT_BASE_URL",
        "used_by": "production-smoke --base-url/--web-base-url",
    },
    {
        "key": "readyz",
        "env": "READY_URL",
        "source": "vars.FOCUS_AGENT_READY_URL",
        "artifact_path": "reports/release-gate/readyz.json",
        "used_by": "release-evidence --readyz-json",
    },
    {
        "key": "trajectory_stats",
        "env": "TRAJECTORY_STATS_URL",
        "source": "vars.FOCUS_AGENT_TRAJECTORY_STATS_URL",
        "artifact_path": "reports/release-gate/trajectory-stats.json",
        "used_by": "release-evidence --trajectory-stats-json",
    },
    {
        "key": "replay_comparison",
        "env": "REPLAY_COMPARISONS_URL",
        "source": "vars.FOCUS_AGENT_REPLAY_COMPARISONS_URL",
        "artifact_path": "reports/release-gate/replay-comparisons.json",
        "used_by": "release-evidence --replay-comparisons-json",
    },
    {
        "key": "alert_report",
        "env": "ALERT_REPORT_URL",
        "source": "vars.FOCUS_AGENT_ALERT_REPORT_URL",
        "artifact_path": "reports/release-gate/alert-report.json",
        "used_by": "release-evidence --alert-report-json",
    },
    {
        "key": "baseline_eval",
        "env": "BASELINE_EVAL_REPORT_URL",
        "source": "vars.FOCUS_AGENT_BASELINE_EVAL_REPORT_URL",
        "artifact_path": "reports/release-gate/baseline-eval-smoke.json",
        "used_by": "release-evidence --baseline-eval-report-json",
    },
    {
        "key": "approval_id",
        "env": "APPROVAL_ID",
        "source": "workflow_dispatch.inputs.approval_id",
        "used_by": "release-evidence --approval-id",
    },
    {
        "key": "approval_status",
        "env": "APPROVAL_STATUS",
        "source": "workflow_dispatch.inputs.approval_status",
        "used_by": "release-evidence --approval-status",
    },
    {
        "key": "artifact_storage",
        "env": "ARTIFACT_STORAGE_DIR",
        "source": "job.env.ARTIFACT_STORAGE_DIR",
        "used_by": "release-evidence --storage-dir",
    },
    {
        "key": "artifact_retention",
        "env": "RETENTION_DAYS",
        "source": "workflow_dispatch.inputs.retention_days",
        "used_by": "release-evidence --retention-days and actions/upload-artifact retention-days",
    },
    {
        "key": "smoke_auth_token",
        "env": "AUTH_TOKEN",
        "source": "secrets.FOCUS_AGENT_SMOKE_AUTH_TOKEN or vars.FOCUS_AGENT_SMOKE_AUTH_TOKEN",
        "used_by": "production-smoke --auth-token",
    },
    {
        "key": "stream_events_report_url",
        "env": "STREAM_EVENTS_REPORT_URL",
        "required_in_production": False,
        "source": "vars.FOCUS_AGENT_STREAM_EVENTS_REPORT_URL",
        "used_by": "production-smoke --stream-events-json after curl",
    },
    {
        "key": "stream_events_url",
        "env": "STREAM_EVENTS_URL",
        "required_in_production": False,
        "source": "vars.FOCUS_AGENT_STREAM_EVENTS_URL",
        "used_by": "production-smoke --stream-events-url",
    },
    {
        "key": "database_uri",
        "env": "DATABASE_URI",
        "source": "secrets.FOCUS_AGENT_DATABASE_URI or vars.FOCUS_AGENT_DATABASE_URI",
        "used_by": "postgres-ops --database-uri",
    },
    {
        "key": "postgres_backup_command",
        "env": "POSTGRES_BACKUP_COMMAND",
        "source": "secrets.FOCUS_AGENT_POSTGRES_BACKUP_COMMAND or vars.FOCUS_AGENT_POSTGRES_BACKUP_COMMAND",
        "used_by": "postgres-ops --backup-command",
    },
    {
        "key": "postgres_restore_command",
        "env": "POSTGRES_RESTORE_COMMAND",
        "source": "secrets.FOCUS_AGENT_POSTGRES_RESTORE_COMMAND or vars.FOCUS_AGENT_POSTGRES_RESTORE_COMMAND",
        "used_by": "postgres-ops --restore-command",
    },
    {
        "key": "postgres_restore_verification_query",
        "env": "POSTGRES_RESTORE_VERIFICATION_QUERY",
        "source": "secrets.FOCUS_AGENT_POSTGRES_RESTORE_VERIFICATION_QUERY or vars.FOCUS_AGENT_POSTGRES_RESTORE_VERIFICATION_QUERY",
        "used_by": "postgres-ops --restore-verification-query",
    },
    {
        "key": "postgres_retention_cleanup_query",
        "env": "POSTGRES_RETENTION_CLEANUP_QUERY",
        "source": "secrets.FOCUS_AGENT_POSTGRES_RETENTION_CLEANUP_QUERY or vars.FOCUS_AGENT_POSTGRES_RETENTION_CLEANUP_QUERY",
        "used_by": "postgres-ops --retention-cleanup-query",
    },
    {
        "key": "otel_endpoint",
        "env": "OTEL_ENDPOINT",
        "source": "vars.FOCUS_AGENT_OTEL_ENDPOINT",
        "used_by": "otel-smoke --endpoint",
    },
    {
        "key": "otel_collector_health",
        "env": "OTEL_COLLECTOR_HEALTH_URL",
        "source": "vars.FOCUS_AGENT_OTEL_COLLECTOR_HEALTH_URL",
        "used_by": "otel-smoke --collector-health-url",
    },
    {
        "key": "otel_trace_query",
        "env": "OTEL_TRACE_QUERY_URL",
        "source": "vars.FOCUS_AGENT_OTEL_TRACE_QUERY_URL",
        "used_by": "otel-smoke --trace-query-url",
    },
    {
        "key": "governance_report",
        "env": "GOVERNANCE_REPORT_JSON",
        "source": "job.env.GOVERNANCE_REPORT_JSON",
        "used_by": "release-evidence --governance-report-json",
    },
)


def validate_deployment_binding(
    *,
    env: Mapping[str, str] | None = None,
    deployment_binding_json: str | Path | None = None,
    dry_run: bool | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    env = env or os.environ
    dry = (env.get("DRY_RUN") == "true") if dry_run is None else bool(dry_run)
    production = not dry
    run_id = run_id or env.get("GITHUB_RUN_ID", "local")
    records: list[dict[str, Any]] = []
    missing: list[str] = []
    invalid: list[str] = []

    for mapping in PRODUCTION_SIGNAL_MAPPINGS:
        value = env.get(str(mapping["env"]), "")
        if dry and mapping["key"] == "approval_id":
            value = f"gha-dry-run-{run_id}"
        if dry and mapping["key"] == "approval_status":
            value = "approved"
        present = bool(value)
        required = bool(mapping.get("required_in_production", True))
        if production and required and not present:
            missing.append(str(mapping["key"]))
        record = dict(mapping)
        record.update(
            {
                "present": present,
                "required_in_production": required,
                "value": value,
            }
        )
        records.append(record)

    if production and env.get("APPROVAL_STATUS") != "approved":
        invalid.append("approval_status")
    if production and not (env.get("STREAM_EVENTS_REPORT_URL") or env.get("STREAM_EVENTS_URL")):
        missing.append("stream_events")

    status = "passed" if not missing and not invalid else "failed"
    payload = {
        "bindings": records,
        "meta": {
            "ci_provider": "github_actions",
            "dry_run": dry,
            "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "suite": "deployment_binding",
        },
        "summary": {
            "binding_count": len(records),
            "invalid": invalid,
            "missing": missing,
            "mode": "dry_run" if dry else "production",
            "status": status,
        },
    }
    if deployment_binding_json is not None:
        target = Path(deployment_binding_json)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def run_deployment_binding_check(
    *,
    env: Mapping[str, str] | None = None,
    deployment_binding_json: str | Path | None = None,
    dry_run: bool | None = None,
    fail_on_error: bool = True,
) -> int:
    payload = validate_deployment_binding(
        env=env,
        deployment_binding_json=deployment_binding_json,
        dry_run=dry_run,
    )
    if fail_on_error and payload["meta"]["dry_run"] is False and payload["summary"]["status"] != "passed":
        print(json.dumps(payload["summary"], ensure_ascii=False), file=sys.stderr)
        return 1
    return 0


def production_signal_commands() -> list[list[str]]:
    return [
        ["mkdir", "-p", "reports/release-gate"],
        ["python", "scripts/release_gate.py", "deployment-binding", "--output", "${DEPLOYMENT_BINDING_JSON}"],
        ["curl", "--fail", "--show-error", "--silent", "$READY_URL", "--output", "reports/release-gate/readyz.json"],
        ["curl", "--fail", "--show-error", "--silent", "$TRAJECTORY_STATS_URL", "--output", "reports/release-gate/trajectory-stats.json"],
        ["curl", "--fail", "--show-error", "--silent", "$REPLAY_COMPARISONS_URL", "--output", "reports/release-gate/replay-comparisons.json"],
        ["curl", "--fail", "--show-error", "--silent", "$ALERT_REPORT_URL", "--output", "reports/release-gate/alert-report.json"],
        ["curl", "--fail", "--show-error", "--silent", "$POSTGRES_MIGRATION_REPORT_URL", "--output", "reports/release-gate/postgres-migration.json"],
        ["curl", "--fail", "--show-error", "--silent", "$BASELINE_EVAL_REPORT_URL", "--output", "reports/release-gate/baseline-eval-smoke.json"],
        ["uv", "run", "python", "scripts/production_smoke.py", "--report-json", "reports/release-gate/production-smoke.json"],
        ["uv", "run", "python", "scripts/postgres_ops.py", "--report-json", "reports/release-gate/postgres-ops.json"],
        ["uv", "run", "python", "scripts/otel_smoke.py", "--report-json", "reports/release-gate/otel-smoke.json"],
        ["test", "-s", "$GOVERNANCE_REPORT_JSON"],
    ]


def production_release_evidence_args() -> list[str]:
    return [
        "--release-id",
        "${RELEASE_ID}",
        "--approval-id",
        "${APPROVAL_ID}",
        "--approval-status",
        "${APPROVAL_STATUS}",
        "--approval-url",
        "${APPROVAL_URL}",
        "--retention-days",
        "${RETENTION_DAYS}",
        "--storage-dir",
        "${ARTIFACT_STORAGE_DIR}",
        "--readyz-json",
        "reports/release-gate/readyz.json",
        "--trajectory-stats-json",
        "reports/release-gate/trajectory-stats.json",
        "--replay-comparisons-json",
        "reports/release-gate/replay-comparisons.json",
        "--alert-report-json",
        "reports/release-gate/alert-report.json",
        "--postgres-migration-report-json",
        "reports/release-gate/postgres-migration.json",
        "--production-smoke-report-json",
        "reports/release-gate/production-smoke.json",
        "--postgres-ops-report-json",
        "reports/release-gate/postgres-ops.json",
        "--otel-smoke-report-json",
        "reports/release-gate/otel-smoke.json",
        "--governance-report-json",
        "${GOVERNANCE_REPORT_JSON}",
        "--eval-report-json",
        "reports/release-gate/eval-smoke.json",
        "--eval-report-json",
        "reports/release-gate/eval-observability.json",
        "--eval-report-json",
        "reports/release-gate/eval-golden-multi-agent.json",
        "--eval-report-json",
        "reports/release-gate/eval-harness-stability.json",
        "--eval-report-json",
        "reports/release-gate/memory-context-eval.json",
        "--baseline-eval-report-json",
        "reports/release-gate/baseline-eval-smoke.json",
    ]


RELEASE_GATE_COMMANDS: tuple[GateCommand, ...] = (
    GateCommand("lint", ("make", "lint")),
    GateCommand("ci-test", ("make", "ci-test")),
    GateCommand("sdk-check", ("make", "sdk-check")),
    GateCommand("sdk-build", ("make", "sdk-build")),
    GateCommand("web-check", ("make", "web-check")),
    GateCommand("web-build", ("make", "web-build")),
    GateCommand(
        "observability-ui-smoke",
        ("uv", "run", "python", "scripts/observability_ui_smoke.py", "--scenario", "all"),
    ),
    GateCommand("web-observability-smoke", ("pnpm", "--dir", "apps/web", "smoke:observability")),
    GateCommand("ui-smoke", ("uv", "run", "python", "scripts/ui_smoke_test.py")),
    GateCommand(
        "eval-smoke",
        (
            "uv",
            "run",
            "python",
            "-m",
            "tests.eval",
            "--suite",
            "smoke",
            "--concurrency",
            "1",
            "--report-json",
            "reports/release-gate/eval-smoke.json",
        ),
    ),
    GateCommand(
        "eval-observability",
        (
            "uv",
            "run",
            "python",
            "-m",
            "tests.eval",
            "--suite",
            "observability",
            "--concurrency",
            "1",
            "--report-json",
            "reports/release-gate/eval-observability.json",
        ),
    ),
    GateCommand(
        "eval-golden-multi-agent",
        (
            "uv",
            "run",
            "python",
            "-m",
            "tests.eval",
            "--suite",
            "golden_multi_agent",
            "--concurrency",
            "1",
            "--report-json",
            "reports/release-gate/eval-golden-multi-agent.json",
        ),
    ),
    GateCommand(
        "eval-harness-stability",
        (
            "uv",
            "run",
            "python",
            "-m",
            "tests.eval",
            "--suite",
            "harness_stability",
            "--concurrency",
            "1",
            "--report-json",
            "reports/release-gate/eval-harness-stability.json",
        ),
    ),
    GateCommand(
        "memory-context-eval",
        (
            "uv",
            "run",
            "python",
            "scripts/memory_context_eval.py",
            "--report-json",
            "reports/release-gate/memory-context-eval.json",
        ),
    ),
    GateCommand(
        "agent-governance-report",
        (
            "uv",
            "run",
            "python",
            "scripts/agent_governance_report.py",
            "--report-json",
            "reports/agent-governance/latest.json",
        ),
    ),
    GateCommand(
        "release-health",
        (
            "uv",
            "run",
            "python",
            "scripts/release_health_check.py",
            "--mode",
            "local",
            "--ready-url",
            "http://127.0.0.1:8000/readyz",
            "--trajectory-stats-url",
            "http://127.0.0.1:8000/v1/observability/trajectory/stats",
            "--allow-self-check-fallback",
            "--eval-report-json",
            "reports/release-gate/eval-smoke.json",
            "--eval-report-json",
            "reports/release-gate/eval-observability.json",
            "--eval-report-json",
            "reports/release-gate/eval-golden-multi-agent.json",
            "--eval-report-json",
            "reports/release-gate/eval-harness-stability.json",
            "--eval-report-json",
            "reports/release-gate/memory-context-eval.json",
            "--governance-report-json",
            "reports/agent-governance/latest.json",
            "--report-json",
            "reports/release-gate/release-health.json",
        ),
    ),
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _command_text(command: Sequence[str]) -> str:
    return shlex.join(command)


def _tail_output(output: str) -> str:
    if not output:
        return ""

    lines = output.splitlines()
    tail = "\n".join(lines[-TAIL_LINE_LIMIT:])
    if len(tail) > TAIL_CHAR_LIMIT:
        tail = tail[-TAIL_CHAR_LIMIT:]
    return tail


def _stream_summary(output: str) -> dict[str, int | bool]:
    tail = _tail_output(output)
    return {
        "char_count": len(output),
        "line_count": len(output.splitlines()),
        "truncated": tail != output,
    }


def _empty_record(command: GateCommand, *, status: str, skip_reason: str | None) -> dict:
    return {
        "label": command.label,
        "command": _command_text(command.command),
        "status": status,
        "duration_seconds": 0.0,
        "exit_code": None,
        "skip_reason": skip_reason,
        "stdout_tail": "",
        "stderr_tail": "",
        "stdout_summary": _stream_summary(""),
        "stderr_summary": _stream_summary(""),
    }


def _result_record(command: GateCommand, outcome: CommandOutcome, duration_seconds: float) -> dict:
    return {
        "label": command.label,
        "command": _command_text(command.command),
        "status": "passed" if outcome.exit_code == 0 else "failed",
        "duration_seconds": round(duration_seconds, 3),
        "exit_code": outcome.exit_code,
        "skip_reason": None,
        "stdout_tail": _tail_output(outcome.stdout),
        "stderr_tail": _tail_output(outcome.stderr),
        "stdout_summary": _stream_summary(outcome.stdout),
        "stderr_summary": _stream_summary(outcome.stderr),
    }


def _subprocess_runner(command: GateCommand, root: Path) -> CommandOutcome:
    completed = subprocess.run(
        command.command,
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    return CommandOutcome(
        exit_code=int(completed.returncode),
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _split_labels(values: Sequence[str]) -> list[str]:
    labels: list[str] = []
    for value in values:
        labels.extend(label.strip() for label in value.split(",") if label.strip())
    return labels


def _validate_labels(labels: Sequence[str], *, option_name: str) -> set[str]:
    available = {command.label for command in RELEASE_GATE_COMMANDS}
    selected = set(labels)
    unknown = sorted(selected - available)
    if unknown:
        known = ", ".join(sorted(available))
        raise ValueError(f"Unknown {option_name} label(s): {', '.join(unknown)}. Known labels: {known}")
    return selected


def _build_summary(records: Sequence[dict]) -> dict[str, int]:
    statuses = ("passed", "failed", "skipped", "dry-run")
    summary = {status: 0 for status in statuses}
    for record in records:
        status = str(record["status"])
        summary[status] = summary.get(status, 0) + 1
    summary["total"] = len(records)
    return summary


def _report_status(records: Sequence[dict], *, dry_run: bool) -> str:
    if any(record["status"] == "failed" for record in records):
        return "failed"
    if dry_run:
        return "dry-run"
    return "passed"


def _resolve_report_path(report_json: str | Path | None, root: Path) -> Path:
    path = Path(report_json) if report_json is not None else DEFAULT_REPORT_JSON
    if not path.is_absolute():
        path = root / path
    return path


def run_release_gate(
    *,
    dry_run: bool = False,
    only_labels: Sequence[str] | None = None,
    skip_labels: Sequence[str] | None = None,
    report_json: str | Path | None = None,
    root: Path | None = None,
    runner: Runner | None = None,
    keep_going: bool = False,
) -> dict:
    root = root or _repo_root()
    runner = runner or _subprocess_runner
    only = _validate_labels(only_labels or (), option_name="--only")
    skip = _validate_labels(skip_labels or (), option_name="--skip")

    records: list[dict] = []
    failed_label: str | None = None
    for command in RELEASE_GATE_COMMANDS:
        if only and command.label not in only:
            records.append(
                _empty_record(command, status="skipped", skip_reason="not selected by --only")
            )
            continue
        if command.label in skip:
            records.append(_empty_record(command, status="skipped", skip_reason="requested by --skip"))
            continue
        if not keep_going and failed_label is not None:
            records.append(
                _empty_record(
                    command,
                    status="skipped",
                    skip_reason=f"prior failure: {failed_label}",
                )
            )
            continue
        if dry_run:
            records.append(_empty_record(command, status="dry-run", skip_reason="dry-run"))
            continue

        started_at = time.perf_counter()
        outcome = runner(command, root)
        duration_seconds = time.perf_counter() - started_at
        record = _result_record(command, outcome, duration_seconds)
        records.append(record)
        if outcome.exit_code != 0:
            failed_label = command.label

    report = {
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "root": str(root),
        "dry_run": dry_run,
        "keep_going": keep_going,
        "status": _report_status(records, dry_run=dry_run),
        "summary": _build_summary(records),
        "commands": records,
    }

    report_path = _resolve_report_path(report_json, root)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report["report_json"] = str(report_path)
    return report


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    if argv and len(argv) > 0 and argv[0] == "deployment-binding":
        parser = argparse.ArgumentParser(
            prog="release_gate.py deployment-binding",
            description="Validate release gate deployment binding metadata.",
        )
        parser.add_argument("deployment_binding_command", nargs="?", default="deployment-binding")
        parser.add_argument(
            "--output",
            default=os.environ.get("DEPLOYMENT_BINDING_JSON", "reports/release-gate/deployment-binding.json"),
            help="Path for deployment binding JSON.",
        )
        parser.add_argument("--dry-run", action="store_true", help="Validate as dry-run regardless of env.")
        parser.add_argument("--no-fail", action="store_true", help="Do not return failure on invalid production binding.")
        return parser.parse_args(argv)

    parser = argparse.ArgumentParser(
        description="Run the Focus Agent release gate and write a structured JSON report."
    )
    parser.add_argument("--dry-run", action="store_true", help="Plan commands without executing them.")
    parser.add_argument(
        "--only",
        action="append",
        default=[],
        metavar="LABEL",
        help="Run only a label. May be repeated or comma-separated.",
    )
    parser.add_argument(
        "--skip",
        action="append",
        default=[],
        metavar="LABEL",
        help="Skip a label. May be repeated or comma-separated.",
    )
    parser.add_argument(
        "--report-json",
        default=str(DEFAULT_REPORT_JSON),
        help="Path for the release gate JSON report.",
    )
    parser.add_argument(
        "--keep-going",
        action="store_true",
        help="Continue running selected commands after a failure.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if getattr(args, "deployment_binding_command", None) == "deployment-binding":
        explicit_dry_run = True if bool(args.dry_run) else None
        return run_deployment_binding_check(
            deployment_binding_json=args.output,
            dry_run=explicit_dry_run,
            fail_on_error=not bool(args.no_fail),
        )
    try:
        report = run_release_gate(
            dry_run=bool(args.dry_run),
            only_labels=_split_labels(args.only),
            skip_labels=_split_labels(args.skip),
            report_json=str(args.report_json),
            keep_going=bool(args.keep_going),
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(json.dumps({"status": report["status"], "report_json": report["report_json"]}, indent=2))
    return 1 if report["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
