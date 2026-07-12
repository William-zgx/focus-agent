from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

TAIL_LINE_LIMIT = 80
TAIL_CHAR_LIMIT = 12_000
DEFAULT_REPORT_JSON = Path("reports/release-gate/latest.json")
COMMAND_TIMEOUT_ENV = "FOCUS_AGENT_RELEASE_GATE_COMMAND_TIMEOUT_S"

from scripts.release_gate_catalog import (  # noqa: E402,F401
    PRODUCTION_SIGNAL_MAPPINGS,
    RELEASE_GATE_COMMANDS,
    GateCommand,
    production_release_evidence_args,
    production_signal_commands,
)


@dataclass(frozen=True)
class CommandOutcome:
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    timeout_s: float | None = None


Runner = Callable[[GateCommand, Path], CommandOutcome]


def _github_actions_metadata(
    env: Mapping[str, str], *, run_id: str, dry_run: bool
) -> dict[str, Any]:
    return {
        "actor": env.get("GITHUB_ACTOR"),
        "artifact_name": env.get("RELEASE_GATE_ARTIFACT_NAME")
        or (f"release-gate-reports-{run_id}" if run_id else None),
        "environment_name": env.get("ENVIRONMENT_NAME"),
        "event_name": env.get("GITHUB_EVENT_NAME"),
        "is_github_actions": env.get("GITHUB_ACTIONS") == "true",
        "repository": env.get("GITHUB_REPOSITORY"),
        "retention_days": env.get("RETENTION_DAYS"),
        "run_attempt": env.get("GITHUB_RUN_ATTEMPT"),
        "run_id": run_id,
        "run_number": env.get("GITHUB_RUN_NUMBER"),
        "server_url": env.get("GITHUB_SERVER_URL"),
        "sha": env.get("GITHUB_SHA"),
        "workflow": env.get("GITHUB_WORKFLOW"),
        "workflow_ref": env.get("GITHUB_WORKFLOW_REF"),
        "mode": "dry_run" if dry_run else "production",
    }


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
        "github_actions": _github_actions_metadata(env, run_id=run_id, dry_run=dry),
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
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
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
    if (
        fail_on_error
        and payload["meta"]["dry_run"] is False
        and payload["summary"]["status"] != "passed"
    ):
        print(json.dumps(payload["summary"], ensure_ascii=False), file=sys.stderr)
        return 1
    return 0


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
        "timed_out": False,
        "timeout_s": command.timeout_s,
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
        "timed_out": outcome.timed_out,
        "timeout_s": outcome.timeout_s if outcome.timeout_s is not None else command.timeout_s,
    }


def _subprocess_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _effective_command_timeout_s(command: GateCommand) -> float | None:
    override = os.environ.get(COMMAND_TIMEOUT_ENV)
    if override is None or override.strip() == "":
        if command.timeout_s is not None and command.timeout_s <= 0:
            return None
        return command.timeout_s
    try:
        timeout_s = float(override)
    except ValueError:
        return command.timeout_s
    if timeout_s <= 0:
        return None
    return timeout_s


def _subprocess_runner(command: GateCommand, root: Path) -> CommandOutcome:
    timeout_s = _effective_command_timeout_s(command)
    try:
        completed = subprocess.run(
            command.command,
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as exc:
        stderr = _subprocess_text(exc.stderr)
        timeout_note = f"Command timed out after {timeout_s:g}s."
        if stderr:
            stderr = f"{stderr.rstrip()}\n{timeout_note}"
        else:
            stderr = timeout_note
        return CommandOutcome(
            exit_code=124,
            stdout=_subprocess_text(exc.stdout),
            stderr=stderr,
            timed_out=True,
            timeout_s=timeout_s,
        )
    return CommandOutcome(
        exit_code=int(completed.returncode),
        stdout=completed.stdout,
        stderr=completed.stderr,
        timeout_s=timeout_s,
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
        raise ValueError(
            f"Unknown {option_name} label(s): {', '.join(unknown)}. Known labels: {known}"
        )
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
    if not any(record["status"] == "passed" for record in records):
        return "incomplete"
    if any(record["status"] == "skipped" for record in records):
        return "incomplete"
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
    production_selection_options = [
        option_name for option_name, labels in (("--only", only), ("--skip", skip)) if labels
    ]
    production_selection_reason = (
        "production mode requires the full release gate; "
        f"{' and '.join(production_selection_options)} are not allowed"
        if not dry_run and production_selection_options
        else None
    )

    records: list[dict] = []
    failed_label: str | None = None
    for command in RELEASE_GATE_COMMANDS:
        if production_selection_reason is not None:
            records.append(
                _empty_record(
                    command,
                    status="skipped",
                    skip_reason=production_selection_reason,
                )
            )
            continue
        if only and command.label not in only:
            records.append(
                _empty_record(command, status="skipped", skip_reason="not selected by --only")
            )
            continue
        if command.label in skip:
            records.append(
                _empty_record(command, status="skipped", skip_reason="requested by --skip")
            )
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
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and len(argv) > 0 and argv[0] == "deployment-binding":
        parser = argparse.ArgumentParser(
            prog="release_gate.py deployment-binding",
            description="Validate release gate deployment binding metadata.",
        )
        parser.add_argument("deployment_binding_command", nargs="?", default="deployment-binding")
        parser.add_argument(
            "--output",
            default=os.environ.get(
                "DEPLOYMENT_BINDING_JSON", "reports/release-gate/deployment-binding.json"
            ),
            help="Path for deployment binding JSON.",
        )
        parser.add_argument(
            "--dry-run", action="store_true", help="Validate as dry-run regardless of env."
        )
        parser.add_argument(
            "--no-fail",
            action="store_true",
            help="Do not return failure on invalid production binding.",
        )
        return parser.parse_args(argv)

    parser = argparse.ArgumentParser(
        description="Run the Focus Agent release gate and write a structured JSON report."
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Plan commands without executing them."
    )
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
    return 0 if report["status"] in {"passed", "dry-run"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
