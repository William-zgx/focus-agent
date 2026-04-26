from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Sequence


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
            "reports/release-gate/memory-context-eval.json",
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
